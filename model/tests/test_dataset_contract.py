"""A built dataset matches its manifest and the class catalogue. Skipped when the dataset is not built locally.

    DATASET_VERSION=qd-local1k-64-v1 python -m unittest discover -s model/tests -t .
"""
import hashlib
import json
import os
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
VERSION = os.environ.get("DATASET_VERSION", "qd-local1k-64-v1")
DATASET = ROOT / "data/datasets" / VERSION


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


@unittest.skipUnless((DATASET / "manifest.json").exists(), f"dataset {VERSION} not built")
class DatasetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
        cls.public = json.loads((DATASET / "manifest.public.json").read_text(encoding="utf-8"))
        cls.images = np.load(DATASET / "images.npy", mmap_mode="r")
        cls.labels = np.load(DATASET / "labels.npy")
        cls.split = np.load(DATASET / "split.npy")
        cls.keys = np.load(DATASET / "key_ids.npy")

    def test_files_match_manifest_hashes(self):
        for name, digest in self.public["files"].items():
            with self.subTest(name):
                self.assertEqual(sha256_file(DATASET / name), digest)

    def test_shapes_types_and_counts(self):
        n = self.public["samples"]
        size = self.public["preprocessing"]["size"]
        self.assertEqual(self.images.shape, (n, size, size))
        self.assertEqual(self.images.dtype, np.uint8)
        self.assertEqual((len(self.labels), len(self.split), len(self.keys)), (n, n, n))
        self.assertEqual(set(np.unique(self.split).tolist()) - {0, 1, 2}, set())
        counts = {name: int((self.split == i).sum()) for i, name in enumerate(("train", "validation", "test"))}
        self.assertEqual(counts, self.public["splits"])

    def test_labels_are_the_345_raw_classes_in_catalogue_order(self):
        catalogue = json.loads((ROOT / "data/quickdraw/metadata/labels.json").read_text(encoding="utf-8"))
        ids = [c["category_id"] for c in sorted(catalogue["categories"], key=lambda c: c["class_index"])]
        self.assertEqual(self.manifest["classIds"], ids)
        self.assertEqual(self.public["classes"]["sha256"], hashlib.sha256(json.dumps(ids).encode()).hexdigest())
        self.assertEqual((int(self.labels.min()), int(self.labels.max())), (0, len(ids) - 1))

    def test_identical_images_never_cross_splits_and_key_ids_are_unique_per_class(self):
        seen: dict[bytes, int] = {}
        for i in range(0, len(self.images), 50000):
            block = np.asarray(self.images[i:i + 50000])
            for img, s in zip(block, self.split[i:i + 50000]):
                d = hashlib.sha256(img.tobytes()).digest()
                self.assertEqual(seen.setdefault(d, int(s)), int(s))
        pairs = set(zip(self.labels.tolist(), self.keys.tolist()))
        self.assertEqual(len(pairs), len(self.keys))


if __name__ == "__main__":
    unittest.main()
