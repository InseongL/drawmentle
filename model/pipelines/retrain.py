"""Retraining pipeline: reviewed user drawings -> dataset -> training -> checks -> release (docs/mlops-v1.md §6).

    python -m model.pipelines.retrain --new --until dataset          # export + build datasets, then stop
    python -m model.pipelines.retrain --resume <id> --until compare  # train, calibrate, evaluate, compare
    python -m model.pipelines.retrain --resume <id> --until check_onnx
    python -m model.pipelines.retrain --resume <id> --until release --approve-release
    python -m model.pipelines.retrain --resume <id> --until release --dry-run
    python -m model.pipelines.retrain --list

Every run is a record in data/artifacts/mlops/pipelines/<id>/ (pipeline.json + one log per stage) with a snapshot of
config/mlops/mlops.json. Finished stages are never repeated; a failed stage can be fixed and resumed. Nothing runs
without a person: `--until` is required, training happens only when asked for, a release needs `--approve-release`
and passing gates (or `--override-gates "<reason>"`, recorded), and puzzles are never assigned here - the pipeline
prints the `assign-release` command for a person to run after looking at the reports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MLOPS_CONFIG = ROOT / "config/mlops/mlops.json"
STAGES = ("export", "dataset", "train", "calibrate", "evaluate", "compare", "export_onnx", "check_onnx", "release")


class StageFailed(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_sha256(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Pipeline:
    def __init__(self, record: dict, folder: Path, root: Path = ROOT):
        self.record, self.folder, self.root = record, folder, root
        self.cfg = record["config"]

    # record ----------------------------------------------------------------------------------------------------------
    @classmethod
    def create(cls, cfg: dict, pipelines_dir: Path, root: Path = ROOT) -> "Pipeline":
        pid = datetime.now().strftime("%Y%m%d-%H%M%S")
        folder = pipelines_dir / pid
        folder.mkdir(parents=True, exist_ok=False)
        record = {"id": pid, "createdAt": now(), "config": cfg, "configSha256": canonical_sha256(cfg),
                  "stages": {}, "outputs": {}}
        pipe = cls(record, folder, root)
        pipe.save()
        return pipe

    @classmethod
    def load(cls, folder: Path, root: Path = ROOT) -> "Pipeline":
        return cls(json.loads((folder / "pipeline.json").read_text(encoding="utf-8")), folder, root)

    def save(self) -> None:
        (self.folder / "pipeline.json").write_text(json.dumps(self.record, ensure_ascii=False, indent=1) + "\n",
                                                   encoding="utf-8")

    @property
    def pid(self) -> str:
        return self.record["id"]

    def out(self, key: str, default: str | None = None) -> str:
        return self.record["outputs"].get(key) or default or f"<{key} from an earlier stage>"

    # commands --------------------------------------------------------------------------------------------------------
    def python(self, kind: str) -> str:
        exe = os.environ.get(f"DRAWMENTLE_{kind.upper()}_PYTHON") or self.cfg["runtime"][f"{kind}_python"]
        return str(self.root / exe) if "/" in exe or "\\" in exe else exe

    def commands(self, stage: str) -> list[tuple[list[str], Path]]:
        """(argv, cwd) per step of a stage; later outputs appear as <placeholders> until they exist."""
        c, pid = self.cfg, self.pid
        model, backend = self.python("model"), self.python("backend")
        user = f"user-{pid}"
        composite = f"{c['dataset']['base_version']}+{user}"
        run = self.out("run")
        champion = self.root / c["champion"]["run"]
        if stage == "export":
            return [([backend, "-m", "app.cli", "collection-export"], self.root / "backend")]
        if stage == "dataset":
            return [([model, "-m", "model.datasets.build_user_dataset", "--export", self.out("export_dir"),
                      "--version", user], self.root),
                    ([model, "-m", "model.datasets.compose", "--version", composite,
                      "--part", c["dataset"]["base_version"], "--part", f"{user}:{c['dataset']['train_repeat']}"],
                     self.root)]
        if stage == "train":
            t = c["training"]
            argv = [model, "-u", "-m", "model.training.train", "--config", t["config"], "--dataset", composite,
                    "--epochs", str(t["epochs"]), "--lr", str(t["lr"]), "--warmup-epochs", str(t["warmup_epochs"]),
                    "--placement", t["placement"], "--run-name", f"pipe-{pid}"]
            if t["init"] == "warm_start":
                argv += ["--init-from", str(champion / f"{c['champion']['checkpoint']}.pt")]
            return [(argv, self.root)]
        if stage == "calibrate":
            return [([model, "-m", "model.evaluation.calibrate", "--run", run], self.root)]
        if stage == "evaluate":
            return [([model, "-m", "model.evaluation.evaluate", "--run", run, "--subset", c["gates"]["eval_subset"]],
                     self.root)]
        if stage == "compare":
            return [([model, "-m", "model.evaluation.compare", "--candidate", run, "--champion", str(champion),
                      "--user-dataset", user], self.root)]
        if stage == "export_onnx":
            return [([model, "-m", "model.export.export_onnx", "--run", run], self.root)]
        if stage == "check_onnx":
            return [([backend, "-m", "model.export.check_onnx", "--model-dir", self.out("model_dir")], self.root)]
        if stage == "release":
            return [([backend, "-m", "app.cli", "build-model-release", "--release-id", self.release_id,
                      "--model-dir", str(self.root / self.out("model_dir"))], self.root / "backend")]
        raise ValueError(stage)

    @property
    def release_id(self) -> str:
        return f"{self.cfg['release']['id_prefix']}-{self.pid}"

    # stage results ---------------------------------------------------------------------------------------------------
    def collect(self, stage: str, last_json: dict | None) -> None:
        o = self.record["outputs"]
        if stage == "export":
            if not last_json or not last_json.get("count"):
                raise StageFailed("no accepted, still-consented drawings to export")
            o["export_dir"], o["export_count"] = last_json["out"], last_json["count"]
        elif stage == "dataset":
            o["user_dataset"] = f"user-{self.pid}"
            o["composite_dataset"] = f"{self.cfg['dataset']['base_version']}+user-{self.pid}"
        elif stage == "train":
            runs = sorted((self.root / "data/artifacts/models/runs").glob(f"*-pipe-{self.pid}"))
            if not runs:
                raise StageFailed("training finished but its run folder was not found")
            o["run"] = str(runs[-1].relative_to(self.root))
        elif stage == "compare":
            result = json.loads((self.root / o["run"] / "eval" /
                                 f"compare-{Path(self.cfg['champion']['run']).name}" / "compare.json")
                                .read_text(encoding="utf-8"))
            o["gates_passed"] = result["passed"]
            o["gates"] = {g["gate"]: g["status"] for g in result["gates"]}
        elif stage == "export_onnx":
            o["model_dir"] = last_json["out"]
        elif stage == "check_onnx":
            ok = bool(last_json and last_json.get("passed")) and \
                last_json.get("maxAbsDiff", 1) <= self.cfg["gates"]["max_onnx_diff"]
            o["onnx_check"] = {"passed": ok, "maxAbsDiff": last_json.get("maxAbsDiff") if last_json else None}
            if not ok:
                raise StageFailed(f"ONNX check failed: {last_json}")
        elif stage == "release":
            o["release_id"] = self.release_id

    def run_step(self, argv: list[str], cwd: Path, log) -> dict | None:
        log.write(f"$ {' '.join(argv)}  (cwd {cwd})\n")
        log.flush()
        env = os.environ | {"PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                text=True, encoding="utf-8", errors="replace")
        last = None
        for line in proc.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
            if line.lstrip().startswith("{"):
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    pass
        code = proc.wait()
        if code == 3 and "model.evaluation.compare" in argv:
            return last  # gates failed: recorded by `collect`, decided at release
        if code != 0:
            raise StageFailed(f"exit code {code}: {' '.join(argv)}")
        return last

    # driver ----------------------------------------------------------------------------------------------------------
    def check_release_allowed(self, approve: bool, override: str | None) -> None:
        o = self.record["outputs"]
        if not approve:
            raise StageFailed("a release needs --approve-release (a person looked at the compare report)")
        problems = []
        if not o.get("gates_passed"):
            problems.append(f"compare gates: {o.get('gates')}")
        if not (o.get("onnx_check") or {}).get("passed"):
            problems.append("ONNX check missing or failed")
        if problems and not override:
            raise StageFailed("release blocked: " + "; ".join(problems) + " (--override-gates \"<reason>\" to force)")
        if problems:
            self.record["gateOverride"] = {"reason": override, "problems": problems, "at": now()}

    def run(self, until: str, dry_run: bool = False, approve_release: bool = False,
            override_gates: str | None = None) -> list[str]:
        done = []
        for stage in STAGES[:STAGES.index(until) + 1]:
            state = self.record["stages"].get(stage, {})
            if state.get("status") == "done":
                continue
            if dry_run:
                for argv, cwd in self.commands(stage):
                    print(f"[{stage}] {' '.join(argv)}   (cwd {cwd.relative_to(self.root) if cwd != self.root else '.'})")
                done.append(stage)
                continue
            if stage == "release":
                self.check_release_allowed(approve_release, override_gates)
            self.record["stages"][stage] = {"status": "running", "startedAt": now()}
            self.save()
            try:
                last = None
                with open(self.folder / f"{stage}.log", "a", encoding="utf-8") as log:
                    for argv, cwd in self.commands(stage):
                        last = self.run_step(argv, cwd, log)
                self.collect(stage, last)
            except (StageFailed, OSError) as exc:
                self.record["stages"][stage] = state | {"status": "failed", "error": str(exc), "finishedAt": now()}
                self.save()
                raise StageFailed(f"{stage}: {exc}") from exc
            self.record["stages"][stage] = {"status": "done", "startedAt": self.record["stages"][stage]["startedAt"],
                                            "finishedAt": now()}
            self.save()
            done.append(stage)
        return done

    def next_steps(self) -> list[str]:
        o, c = self.record["outputs"], self.cfg
        if "release_id" not in o:
            return []
        return [f"cd backend && python -m app.cli assign-release --release-id {o['release_id']}",
                f"after the switch: set champion.run={o['run']} and champion.release_id={o['release_id']} in "
                f"config/mlops/mlops.json (previous: {c['champion']['release_id']}, rollback = assign it back)"]


def main(argv=None) -> int:
    cfg = json.loads(MLOPS_CONFIG.read_text(encoding="utf-8"))
    pipelines = ROOT / cfg["runtime"]["pipelines_dir"]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--new", action="store_true", help="start a pipeline with the current config snapshot")
    who.add_argument("--resume", help="pipeline id")
    who.add_argument("--list", action="store_true")
    ap.add_argument("--until", choices=STAGES)
    ap.add_argument("--dry-run", action="store_true", help="print the commands of the remaining stages")
    ap.add_argument("--approve-release", action="store_true")
    ap.add_argument("--override-gates", metavar="REASON")
    args = ap.parse_args(argv)
    if args.list:
        for folder in sorted(pipelines.glob("*/pipeline.json")):
            rec = json.loads(folder.read_text(encoding="utf-8"))
            stages = ", ".join(f"{k}:{v['status']}" for k, v in rec["stages"].items()) or "-"
            print(f"{rec['id']}  {stages}")
        return 0
    if not args.until:
        ap.error("--until is required: say how far this run may go")
    if args.dry_run and args.new:
        pipe = Pipeline({"id": "<new>", "config": cfg, "stages": {}, "outputs": {}}, pipelines / "<new>")
    else:
        pipe = Pipeline.create(cfg, pipelines) if args.new else Pipeline.load(pipelines / args.resume)
    if pipe.record.get("configSha256") not in (None, canonical_sha256(cfg)):
        print("note: config/mlops/mlops.json changed since this pipeline started; it keeps its snapshot",
              file=sys.stderr)
    try:
        done = pipe.run(args.until, args.dry_run, args.approve_release, args.override_gates)
    except StageFailed as exc:
        print(f"pipeline {pipe.pid} stopped: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"pipeline": pipe.pid, "ran" if not args.dry_run else "planned": done,
                      "outputs": pipe.record["outputs"], "next": pipe.next_steps()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
