"""Compose dataset versions into one training dataset without copying them (docs/mlops-v1.md §5).

    python -m model.datasets.compose --version qd-10k-64-v1+user-<id> --part qd-10k-64-v1 --part user-<id>:4

Each --part is `<version>[:<trainRepeat>]`; the repeat applies to the train split only (validation and test rows
appear once). Parts must share the class order and preprocessing. The folder holds only the manifests; the parts are
read in place by `sketch_dataset.open_dataset`, so they must not be deleted while a run uses the composite.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = ROOT / "data/datasets"


def compose(version: str, parts: list[tuple[str, int]], out_root: Path = OUT_ROOT) -> dict:
    out = out_root / version
    if out.exists():
        raise SystemExit(f"{out} already exists; dataset versions are never rebuilt in place")
    publics, privates = [], []
    for name, _ in parts:
        folder = out_root / name
        public = json.loads((folder / "manifest.public.json").read_text(encoding="utf-8"))
        if public.get("kind") == "composite":
            raise SystemExit(f"{name} is itself a composite; compose base datasets only")
        publics.append(public)
        privates.append(json.loads((folder / "manifest.json").read_text(encoding="utf-8")))
    first = publics[0]
    for name, public, private in zip((n for n, _ in parts), publics, privates):
        if public["classes"]["sha256"] != first["classes"]["sha256"] or private["classIds"] != privates[0]["classIds"]:
            raise SystemExit(f"{name}: class order differs from {parts[0][0]}")
        if public["preprocessing"] != first["preprocessing"]:
            raise SystemExit(f"{name}: preprocessing differs from {parts[0][0]}")
    splits = {s: sum(p["splits"][s] for p in publics) for s in ("train", "validation", "test")}
    manifest = {
        "datasetVersion": version, "kind": "composite",
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parts": [{"version": name, "trainRepeat": repeat, "samples": p["samples"], "splits": p["splits"],
                   "files": p["files"]} for (name, repeat), p in zip(parts, publics)],
        "preprocessing": first["preprocessing"], "classes": first["classes"],
        "samples": sum(p["samples"] for p in publics), "splits": splits,
        "trainRowsPerEpoch": sum(p["splits"]["train"] * r for (_, r), p in zip(parts, publics)),
        "files": {f"{name}/{f}": sha for (name, _), p in zip(parts, publics) for f, sha in p["files"].items()},
    }
    out.mkdir(parents=True)
    (out / "manifest.public.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                              encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest | {"classIds": privates[0]["classIds"]},
                                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"out": str(out), "splits": splits, "trainRowsPerEpoch": manifest["trainRowsPerEpoch"]}


def parse_part(text: str) -> tuple[str, int]:
    name, _, repeat = text.partition(":")
    return name, int(repeat) if repeat else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True)
    ap.add_argument("--part", action="append", required=True, type=parse_part, help="<version>[:<trainRepeat>]")
    args = ap.parse_args(argv)
    print(json.dumps(compose(args.version, args.part), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
