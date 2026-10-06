"""Batches from a built dataset (model/datasets/build_manifest.py) to the training device.

The split's uint8 images are placed once, by size:
- "gpu":  the whole split lives on the GPU; a batch is an index into it (fastest, local 1k/class fits in 6 GB).
- "ram":  the split is copied into RAM; a background thread gathers batches into pinned memory.
- "mmap": read from the memory-mapped file through the OS page cache.
Large splits use mmap: on Windows a big private RAM copy was trimmed to the page file mid-training
(2026-10-01, 11 GB train split: ~6k img/s on "ram" vs ~9.5k img/s on "mmap").
Images become float 0..1 and are augmented on the device. No DataLoader worker processes (slow to spawn on Windows).

A composite dataset (model/datasets/compose.py, docs/mlops-v1.md §5) is a folder whose manifest lists other dataset
versions (Quick Draw base + reviewed user drawings). `open_dataset` reads its parts in place, repeating a part in the
train split as configured, so the 14 GB base is never copied.
"""
from __future__ import annotations

import hashlib
import json
import math
import queue
import threading
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

SPLIT_CODES = {"train": 0, "validation": 1, "test": 2}
RAM_LIMIT_BYTES = 4 * 2**30
GPU_SHARE = 0.5  # use at most this share of the currently free GPU memory for data


def choose_placement(nbytes: int, device: torch.device, requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    if device.type == "cuda" and nbytes < torch.cuda.mem_get_info(device)[0] * GPU_SHARE:
        return "gpu"
    return "ram" if nbytes <= RAM_LIMIT_BYTES else "mmap"


class SketchDataset:
    def __init__(self, root: Path, split: str, device: torch.device, placement: str = "auto",
                 recognized_only: bool = False):
        self.root = Path(root)
        self.split = split
        self.device = device
        self.manifest = json.loads((self.root / "manifest.public.json").read_text(encoding="utf-8"))
        images = np.load(self.root / "images.npy", mmap_mode="r")
        mask = np.load(self.root / "split.npy") == SPLIT_CODES[split]
        if recognized_only:  # `recognized` is Google's game outcome, not a reviewed label: an experiment filter only
            mask &= np.load(self.root / "recognized.npy")
        indices = np.flatnonzero(mask)
        labels = np.load(self.root / "labels.npy")[indices].astype(np.int64)
        self.placement = choose_placement(len(indices) * images.shape[1] * images.shape[2], device, placement)
        if self.placement == "mmap":
            self._images, self._rows = images, indices  # rows point into the full file
        else:
            self._images, self._rows = np.ascontiguousarray(images[indices]), np.arange(len(indices))
        if self.placement == "gpu":
            self._gpu_images = torch.from_numpy(self._images).to(device)
            self._gpu_labels = torch.from_numpy(labels).to(device)
            self._images = None  # the CPU copy is no longer needed
        self._labels = labels

    def __len__(self) -> int:
        return len(self._labels)

    def gather(self, pos: np.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
        """Rows by position in this split: uint8 [B, H, W] and int64 [B], on the GPU for "gpu", else on the CPU."""
        if self.placement == "gpu":
            idx = torch.from_numpy(pos).to(self.device)
            return self._gpu_images[idx], self._gpu_labels[idx]
        return torch.from_numpy(self._images[self._rows[pos]]), torch.from_numpy(self._labels[pos])

    def batches(self, batch_size: int, shuffle: bool, generator: np.random.Generator | None = None,
                drop_last: bool = False):
        """Yields (uint8 [B, H, W], int64 [B]) on the device."""
        order = np.arange(len(self))
        if shuffle:
            generator.shuffle(order)
        n = len(order) // batch_size * batch_size if drop_last else len(order)
        if self.placement == "gpu":
            order_gpu = torch.from_numpy(order[:n]).to(self.device)
            for start in range(0, n, batch_size):
                idx = order_gpu[start:start + batch_size]
                yield self._gpu_images[idx], self._gpu_labels[idx]
            return

        pinned = self.device.type == "cuda"

        def load(start):
            x, y = self.gather(np.sort(order[start:start + batch_size]))  # sorted reads suit the memory map
            return (x.pin_memory(), y.pin_memory()) if pinned else (x, y)

        q: queue.Queue = queue.Queue(maxsize=4)

        def producer():
            for start in range(0, n, batch_size):
                q.put(load(start))
            q.put(None)

        threading.Thread(target=producer, daemon=True).start()
        while (item := q.get()) is not None:
            x, y = item
            yield x.to(self.device, non_blocking=True), y.to(self.device, non_blocking=True)


class CompositeDataset:
    """Several dataset versions read as one split. `trainRepeat` repeats a part in the train split only."""

    def __init__(self, root: Path, manifest: dict, split: str, device: torch.device, placement: str = "auto",
                 recognized_only: bool = False):
        self.root, self.split, self.device, self.manifest = Path(root), split, device, manifest
        self.parts = [SketchDataset(self.root.parent / part["version"], split, device, placement, recognized_only)
                      for part in manifest["parts"]]
        repeats = [int(part.get("trainRepeat", 1)) if split == "train" else 1 for part in manifest["parts"]]
        self._part = np.concatenate([np.full(len(d) * r, i, dtype=np.int64)
                                     for i, (d, r) in enumerate(zip(self.parts, repeats))])
        self._row = np.concatenate([np.tile(np.arange(len(d), dtype=np.int64), r)
                                    for d, r in zip(self.parts, repeats)])
        self.placement = "+".join(d.placement for d in self.parts)

    def __len__(self) -> int:
        return len(self._part)

    def batches(self, batch_size: int, shuffle: bool, generator: np.random.Generator | None = None,
                drop_last: bool = False):
        order = np.arange(len(self))
        if shuffle:
            generator.shuffle(order)
        n = len(order) // batch_size * batch_size if drop_last else len(order)
        pinned = self.device.type == "cuda"

        def load(start):
            pos = order[start:start + batch_size]
            out = []
            for i, part in enumerate(self.parts):
                rows = np.sort(self._row[pos[self._part[pos] == i]])
                if len(rows):
                    x, y = part.gather(rows)
                    out.append((x.pin_memory(), y.pin_memory()) if pinned and x.device.type == "cpu" else (x, y))
            return out

        q: queue.Queue = queue.Queue(maxsize=4)

        def producer():
            for start in range(0, n, batch_size):
                q.put(load(start))
            q.put(None)

        threading.Thread(target=producer, daemon=True).start()
        while (item := q.get()) is not None:
            xs = [x.to(self.device, non_blocking=True) for x, _ in item]
            ys = [y.to(self.device, non_blocking=True) for _, y in item]
            yield torch.cat(xs), torch.cat(ys)


def open_dataset(root: Path, split: str, device: torch.device, placement: str = "auto",
                 recognized_only: bool = False):
    manifest = json.loads((Path(root) / "manifest.public.json").read_text(encoding="utf-8"))
    if manifest.get("kind") == "composite":
        return CompositeDataset(root, manifest, split, device, placement, recognized_only)
    return SketchDataset(root, split, device, placement, recognized_only)


def split_meta(root: Path, split: str) -> dict[str, np.ndarray]:
    """Per row of `split` (validation/test order, no repeats): Google's recognized flag, the image-hash parity used to
    split validation into select/calibrate halves, and which dataset part (source) the row came from."""
    root = Path(root)
    manifest = json.loads((root / "manifest.public.json").read_text(encoding="utf-8"))
    parts = [root.parent / p["version"] for p in manifest["parts"]] if manifest.get("kind") == "composite" else [root]
    out = {"recognized": [], "odd": [], "source": []}
    for i, part in enumerate(parts):
        mask = np.load(part / "split.npy") == SPLIT_CODES[split]
        images = np.load(part / "images.npy", mmap_mode="r")
        rows = np.flatnonzero(mask)
        out["recognized"].append(np.load(part / "recognized.npy")[mask])
        out["odd"].append(np.fromiter((hashlib.sha256(images[r].tobytes()).digest()[0] & 1 for r in rows),
                                      dtype=np.uint8, count=len(rows)))
        out["source"].append(np.full(len(rows), i, dtype=np.uint8))
    return {k: np.concatenate(v) for k, v in out.items()}


def to_input(x_uint8: torch.Tensor) -> torch.Tensor:
    """uint8 [B, H, W] -> float [B, 1, H, W] in 0..1, matching the browser input (no mean/std)."""
    return x_uint8.unsqueeze(1).float().div_(255.0)


def augment(x: torch.Tensor, degrees: float, translate: float, scale: tuple[float, float]) -> torch.Tensor:
    """Small random rotation / shift / scale per image (docs §7.3: no crops, no flips)."""
    b, dev = x.shape[0], x.device
    angle = (torch.rand(b, device=dev) * 2 - 1) * math.radians(degrees)
    s = torch.empty(b, device=dev).uniform_(scale[0], scale[1])
    t = (torch.rand(b, 2, device=dev) * 2 - 1) * translate * 2  # affine_grid coordinates span 2
    cos, sin = torch.cos(angle) / s, torch.sin(angle) / s
    theta = torch.stack([torch.stack([cos, -sin, t[:, 0]], 1), torch.stack([sin, cos, t[:, 1]], 1)], 1)
    grid = F.affine_grid(theta, list(x.shape), align_corners=False)
    return F.grid_sample(x, grid, mode="bilinear", padding_mode="zeros", align_corners=False)
