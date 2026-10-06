"""Train a sketch classifier on a built dataset and record the run (docs/model-architecture-v1.md §7.3).

    model/.venv/Scripts/python -m model.training.train                      # config/model/training.json
    model/.venv/Scripts/python -m model.training.train --model small_cnn --epochs 1 --max-steps 200
    model/.venv/Scripts/python -m model.training.train --resume data/artifacts/models/runs/<run_id>
    model/.venv/Scripts/python -m model.training.train --dataset <composite> --init-from <run>/best.pt --epochs 5 --lr 3e-4

--init-from starts from another run's weights (warm start for retraining on new data, docs/mlops-v1.md §6); the
optimizer and schedule start fresh. A composite dataset (model/datasets/compose.py) trains on its parts in place.

Each run writes data/artifacts/models/runs/<run_id>/: run.json (code/config/data/environment/result), classes.json,
history.jsonl (one line per epoch), last.pt (resumable) and best.pt (lowest validation loss). Ctrl+C saves last.pt.
Uses the GPU when available, otherwise the CPU with the same code.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from model.datasets.sketch_dataset import SketchDataset, augment, open_dataset, to_input
from model.networks.sketch_classifier import build

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config/model/training.json"


def canonical_sha256(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def git_state() -> dict:
    def run(*cmd):
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": run("git", "rev-parse", "HEAD"),
            "dirty": bool(run("git", "status", "--porcelain", "--", "model", "config/model"))}


def environment(device: torch.device) -> dict:
    env = {"python": platform.python_version(), "torch": torch.__version__, "platform": platform.platform(),
           "device": str(device)}
    if device.type == "cuda":
        env.update(cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(device),
                   gpuMemoryGb=round(torch.cuda.get_device_properties(device).total_memory / 2**30, 1))
    return env


def write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def lr_at(step: int, total: int, warmup: int, base: float) -> float:
    if step < warmup:
        return base * (step + 1) / warmup
    progress = (step - warmup) / max(1, total - warmup)
    return base * 0.5 * (1 + math.cos(math.pi * min(1.0, progress)))


@torch.no_grad()
def evaluate(model, data: SketchDataset, batch_size: int, device, amp_dtype, max_steps: int | None = None) -> dict:
    model.eval()
    loss_sum, top1, top3, n = 0.0, 0, 0, 0
    for step, (x, y) in enumerate(data.batches(batch_size, shuffle=False)):
        if max_steps is not None and step >= max_steps:
            break
        with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
            logits = model(to_input(x))
        loss_sum += F.cross_entropy(logits.float(), y, reduction="sum").item()
        best3 = logits.topk(3, dim=1).indices
        top1 += (best3[:, 0] == y).sum().item()
        top3 += (best3 == y[:, None]).any(dim=1).sum().item()
        n += len(y)
    model.train()
    return {"loss": loss_sum / max(n, 1), "top1": top1 / max(n, 1), "top3": top3 / max(n, 1), "samples": n}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--resume", type=Path, help="run directory to continue from its last.pt")
    ap.add_argument("--model", help="override model.name")
    ap.add_argument("--dataset", help="override dataset.version")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--batch-size", type=int)
    ap.add_argument("--max-steps", type=int, help="stop after this many optimizer steps (smoke test)")
    ap.add_argument("--eval-steps", type=int, help="limit validation batches (smoke test)")
    ap.add_argument("--run-name", help="suffix for the run id")
    ap.add_argument("--placement", choices=["auto", "gpu", "ram", "mmap"],
                    help="where training images live; not a hyperparameter, so it may change on --resume")
    ap.add_argument("--lr", type=float, help="override train.lr")
    ap.add_argument("--warmup-epochs", type=float, help="override train.warmup_epochs")
    ap.add_argument("--init-from", type=Path, help="checkpoint (.pt) whose weights start this run (warm start)")
    args = ap.parse_args(argv)

    if args.resume:
        run_dir = args.resume
        state = torch.load(run_dir / "last.pt", map_location="cpu", weights_only=False)
        cfg = state["config"]
    else:
        cfg = json.loads(args.config.read_text(encoding="utf-8"))
        cfg = copy.deepcopy(cfg)
        if args.model:
            cfg["model"]["name"] = args.model
        if args.dataset:
            cfg["dataset"]["version"] = args.dataset
        if args.epochs:
            cfg["train"]["epochs"] = args.epochs
        if args.batch_size:
            cfg["train"]["batch_size"] = args.batch_size
        if args.lr:
            cfg["train"]["lr"] = args.lr
        if args.warmup_epochs is not None:
            cfg["train"]["warmup_epochs"] = args.warmup_epochs
        state = None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"{stamp}-{cfg['model']['name']}" + (f"-{args.run_name}" if args.run_name else "")
        run_dir = ROOT / cfg["output_dir"] / run_id
        run_dir.mkdir(parents=True)

    tcfg = cfg["train"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    amp = tcfg.get("amp", "auto")
    if device.type != "cuda" or amp == "off":
        amp_dtype = None
    else:
        amp_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    scaler = torch.amp.GradScaler("cuda", enabled=amp_dtype == torch.float16)
    torch.backends.cudnn.benchmark = True

    dataset_dir = ROOT / cfg["dataset"]["root"] / cfg["dataset"]["version"]
    placement = args.placement or cfg["dataset"].get("placement", "auto")
    train_data = open_dataset(dataset_dir, "train", device, placement, cfg["dataset"].get("recognized_only", False))
    val_data = open_dataset(dataset_dir, "validation", device, placement)
    class_ids = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))["classIds"]

    seed = tcfg["seed"]
    torch.manual_seed(seed)
    model = build(cfg["model"]["name"], **{k: v for k, v in cfg["model"].items() if k != "name"}).to(device)
    init_from = None
    if args.init_from and not state:
        init = torch.load(args.init_from, map_location="cpu", weights_only=False)
        model.load_state_dict(init["model"])  # strict: same architecture and 345 outputs
        init_from = {"path": str(args.init_from), "epoch": init.get("epoch"),
                     "sha256": hashlib.sha256(args.init_from.read_bytes()).hexdigest()}
    model = model.to(memory_format=torch.channels_last)
    optimizer = torch.optim.AdamW(model.parameters(), lr=tcfg["lr"], weight_decay=tcfg["weight_decay"])
    batch = tcfg["batch_size"]
    steps_per_epoch = len(train_data) // batch
    total_steps = steps_per_epoch * tcfg["epochs"]
    warmup = int(steps_per_epoch * tcfg.get("warmup_epochs", 1))
    aug = tcfg.get("augment")

    run = {"runId": run_dir.name, "status": "running", "startedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "code": git_state(), "config": cfg, "configSha256": canonical_sha256(cfg),
           "dataset": {"version": cfg["dataset"]["version"], "files": train_data.manifest["files"],
                       "preprocessing": train_data.manifest["preprocessing"], "train": len(train_data),
                       "validation": len(val_data), "placement": train_data.placement},
           "initFrom": init_from,
           "environment": environment(device), "parameters": sum(p.numel() for p in model.parameters()),
           "amp": str(amp_dtype).replace("torch.", "") if amp_dtype else "off"}
    epoch0, step, best, patience_left, history = 0, 0, None, tcfg.get("early_stop_patience", 5), []
    rng = np.random.default_rng(seed)
    if state:
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scaler.load_state_dict(state["scaler"])
        epoch0, step, best, patience_left, history = (state["epoch"], state["step"], state["best"],
                                                      state["patience_left"], state["history"])
        rng = np.random.default_rng(seed + epoch0)
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8")) | {"status": "running"}
        run.setdefault("resumes", []).append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                              "fromEpoch": epoch0, "placement": train_data.placement})
    write_json(run_dir / "classes.json", {"classIds": class_ids, "sha256": train_data.manifest["classes"]["sha256"]})
    write_json(run_dir / "run.json", run)
    print(f"run {run_dir.name}: {run['parameters']:,} params on {run['environment'].get('gpu', device)} "
          f"({run['amp']}), train {len(train_data):,} / val {len(val_data):,} on {train_data.placement}, "
          f"{steps_per_epoch} steps/epoch",
          flush=True)

    def save(kind: str, epoch: int):
        torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(), "scaler": scaler.state_dict(),
                    "epoch": epoch, "step": step, "best": best, "patience_left": patience_left,
                    "history": history, "config": cfg}, run_dir / f"{kind}.pt")

    status = "finished"
    epoch = epoch0
    try:
        for epoch in range(epoch0, tcfg["epochs"]):
            t0, seen = time.perf_counter(), 0
            loss_sum = torch.zeros((), device=device)  # summed on the device: no GPU sync per step
            for x, y in train_data.batches(batch, shuffle=True, generator=rng, drop_last=True):
                for group in optimizer.param_groups:
                    group["lr"] = lr_at(step, total_steps, warmup, tcfg["lr"])
                inputs = to_input(x).contiguous(memory_format=torch.channels_last)
                if aug:
                    inputs = augment(inputs, aug["degrees"], aug["translate"], tuple(aug["scale"]))
                with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
                    loss = F.cross_entropy(model(inputs), y, label_smoothing=tcfg.get("label_smoothing", 0.0))
                optimizer.zero_grad(set_to_none=True)
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
                step += 1
                seen += len(y)
                loss_sum += loss.detach().float() * len(y)
                if step % 100 == 0:
                    rate = seen / (time.perf_counter() - t0)
                    print(f"epoch {epoch + 1} step {step} loss {loss.item():.3f} {rate:,.0f} img/s", flush=True)
                if args.max_steps and step >= args.max_steps:
                    break
            train_loss = loss_sum.item() / max(seen, 1)
            train_time = time.perf_counter() - t0
            val = evaluate(model, val_data, batch * 2, device, amp_dtype, args.eval_steps)
            improved = best is None or val["loss"] < best["loss"]
            record = {"epoch": epoch + 1, "step": step, "trainLoss": train_loss,
                      "trainImagesPerSec": round(seen / train_time), "epochSeconds": round(train_time, 1),
                      "val": val, "lr": optimizer.param_groups[0]["lr"], "best": improved}
            history.append(record)
            with open(run_dir / "history.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            print(f"epoch {epoch + 1}: train {record['trainLoss']:.3f} | val {val['loss']:.3f} "
                  f"top1 {val['top1']:.3f} top3 {val['top3']:.3f} | {record['trainImagesPerSec']:,} img/s "
                  f"{train_time:.0f}s", flush=True)
            if improved:
                best = {"epoch": epoch + 1, **val}
                patience_left = tcfg.get("early_stop_patience", 5)
                torch.save({"model": model.state_dict(), "config": cfg, "epoch": epoch + 1, "val": val},
                           run_dir / "best.pt")
            else:
                patience_left -= 1
            save("last", epoch + 1)
            if args.max_steps and step >= args.max_steps:
                status = "stopped_max_steps"
                break
            if patience_left <= 0:
                status = "early_stopped"
                break
    except KeyboardInterrupt:
        status = "interrupted"
        save("last", epoch)
        print("interrupted: saved last.pt; continue with --resume", run_dir, flush=True)
    run.update(status=status, finishedAt=datetime.now(timezone.utc).isoformat(timespec="seconds"), best=best,
               epochsRun=len(history), steps=step)
    write_json(run_dir / "run.json", run)
    shown = run_dir.resolve()
    shown = shown.relative_to(ROOT).as_posix() if shown.is_relative_to(ROOT) else str(shown)
    print(json.dumps({"run": shown, "status": status, "best": best}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
