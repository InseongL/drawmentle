"""MLOps pieces on synthetic data: user dataset build, composite datasets, promotion gates, the pipeline record,
and warm-start training on a composite (seconds, CPU or GPU).

    python -m unittest discover -s model/tests -t .      (needs the model venv)
"""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import torch
    from model.datasets import build_user_dataset, compose
    from model.datasets.preprocess import QD_STROKES_64_V1, render
    from model.datasets.sketch_dataset import open_dataset, split_meta
    from model.evaluation.compare import evaluate_gates, passed
    from model.pipelines import retrain
    from model.training import train
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest(f"torch not installed: {exc}")

from model.tests.test_training_smoke import tiny_dataset

CFG = json.loads(retrain.MLOPS_CONFIG.read_text(encoding="utf-8"))


def fake_export(folder: Path, n: int = 40) -> None:
    folder.mkdir(parents=True)
    lines = []
    for i in range(n):
        strokes = [[[10 + i, 10], [500, 40 + 7 * i], [900, 900 - i]], [[300, 300 + i]]]
        lines.append({"sampleId": f"00000000-0000-4000-8000-{i:012d}", "group": f"g{i % 10}",
                      "label": ("apple", "banana")[i % 2], "strokes": strokes, "coordinateMax": 1024})
    body = "".join(json.dumps(line) + "\n" for line in lines)
    (folder / "samples.jsonl").write_text(body, encoding="utf-8", newline="\n")
    manifest = {"exportId": "user-test", "samplesSha256": hashlib.sha256(body.encode()).hexdigest(), "count": n}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class UserDatasetTests(unittest.TestCase):
    def test_build_renders_like_quickdraw_and_splits_by_person(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake_export(tmp / "export")
            out = build_user_dataset.build(tmp / "export", "user-t", tmp / "datasets", CFG["dataset"])
            root = Path(out["out"])
            images, labels, split = (np.load(root / f"{n}.npy") for n in ("images", "labels", "split"))
            self.assertEqual(images.shape, (40, 64, 64))
            first = json.loads((tmp / "export" / "samples.jsonl").read_text(encoding="utf-8").splitlines()[0])
            expected = render(build_user_dataset.to_quickdraw(first["strokes"]), QD_STROKES_64_V1)
            np.testing.assert_array_equal(images[0], expected)
            classes = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["classIds"]
            self.assertEqual({classes[i] for i in labels}, {"apple", "banana"})
            groups = [s["group"] for s in json.loads((root / "samples.json").read_text(encoding="utf-8"))]
            for g in set(groups):  # one person's drawings never span two splits
                self.assertEqual(len({int(split[i]) for i, x in enumerate(groups) if x == g}), 1)
            with self.assertRaises(SystemExit):  # versions are never rebuilt in place
                build_user_dataset.build(tmp / "export", "user-t", tmp / "datasets", CFG["dataset"])

    def test_composite_reads_parts_in_place_with_train_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            datasets = Path(tmp) / "datasets"
            tiny_dataset(datasets / "base", n=64)
            tiny_dataset(datasets / "extra", n=48)
            for name in ("base", "extra"):  # tiny_dataset leaves splits out of the public manifest
                public = json.loads((datasets / name / "manifest.public.json").read_text(encoding="utf-8"))
                split = np.load(datasets / name / "split.npy")
                public.update(samples=len(split), splits={s: int((split == i).sum())
                                                          for i, s in enumerate(("train", "validation", "test"))})
                (datasets / name / "manifest.public.json").write_text(json.dumps(public), encoding="utf-8")
            compose.compose("base+extra", [("base", 1), ("extra", 3)], datasets)
            device = torch.device("cpu")
            train_data = open_dataset(datasets / "base+extra", "train", device)
            self.assertEqual(len(train_data), 32 + 3 * 16)
            seen = sum(len(y) for _, y in train_data.batches(10, shuffle=True, generator=np.random.default_rng(0)))
            self.assertEqual(seen, len(train_data))
            val = open_dataset(datasets / "base+extra", "validation", device)
            meta = split_meta(datasets / "base+extra", "validation")
            self.assertEqual((len(val), len(meta["odd"]), int(meta["source"].sum())), (64, 64, 32))


class GateTests(unittest.TestCase):
    def metrics(self, top1, false, daily, user_n=0, user_top1=0.0):
        return {"base": {"top1": top1, "falseSuccess": false, "daily": daily}, "user": {"n": user_n, "top1": user_top1}}

    def test_pass_fail_and_pending(self):
        g = CFG["gates"]
        champ = self.metrics(0.70, 0.047, {"a": 0.4, "b": 0.3})
        good = self.metrics(0.71, 0.046, {"a": 0.42, "b": 0.31})
        gates = evaluate_gates(champ, good, g)
        self.assertTrue(passed(gates))
        self.assertEqual({x["gate"]: x["status"] for x in gates}["user_top1"], "pending")  # no real drawings yet
        worse = self.metrics(0.69, 0.06, {"a": 0.2, "b": 0.01}, user_n=500, user_top1=0.5)
        statuses = {x["gate"]: x["status"] for x in evaluate_gates(self.metrics(0.70, 0.047, {"a": 0.4, "b": 0.3},
                                                                                 500, 0.6), worse, g)}
        self.assertEqual(statuses, {"top1": "fail", "false_success": "fail", "daily_floor": "fail",
                                    "answer_regression": "fail", "user_top1": "fail"})


class PipelineTests(unittest.TestCase):
    def test_record_dry_run_and_release_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipe = retrain.Pipeline.create(CFG, Path(tmp))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                planned = pipe.run("release", dry_run=True)
            self.assertEqual(planned, list(retrain.STAGES))
            self.assertIn("--init-from", out.getvalue())  # warm start from the champion
            self.assertEqual(pipe.record["stages"], {})  # a dry run changes nothing
            with self.assertRaisesRegex(retrain.StageFailed, "approve"):
                pipe.check_release_allowed(False, None)
            pipe.record["outputs"].update(gates_passed=False, gates={"top1": "fail"})
            with self.assertRaisesRegex(retrain.StageFailed, "blocked"):
                pipe.check_release_allowed(True, None)
            pipe.check_release_allowed(True, "checked by hand")
            self.assertEqual(pipe.record["gateOverride"]["reason"], "checked by hand")
            again = retrain.Pipeline.load(Path(tmp) / pipe.pid)
            self.assertEqual(again.record["configSha256"], retrain.canonical_sha256(CFG))


class WarmStartTests(unittest.TestCase):
    def test_trains_on_a_composite_from_another_runs_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            datasets = tmp / "datasets"
            tiny_dataset(datasets / "base", n=64)
            fake_export(tmp / "export")
            build_user_dataset.build(tmp / "export", "user-t", datasets, CFG["dataset"])
            public = json.loads((datasets / "base" / "manifest.public.json").read_text(encoding="utf-8"))
            user = json.loads((datasets / "user-t" / "manifest.public.json").read_text(encoding="utf-8"))
            public.update(classes=user["classes"], preprocessing=user["preprocessing"], samples=64,
                          splits={"train": 32, "validation": 32, "test": 0})
            (datasets / "base" / "manifest.public.json").write_text(json.dumps(public), encoding="utf-8")
            private = json.loads((datasets / "user-t" / "manifest.json").read_text(encoding="utf-8"))
            (datasets / "base" / "manifest.json").write_text(json.dumps(public | {"classIds": private["classIds"]}),
                                                            encoding="utf-8")
            compose.compose("base+user-t", [("base", 1), ("user-t", 2)], datasets)
            cfg = json.loads(train.DEFAULT_CONFIG.read_text(encoding="utf-8"))
            cfg["dataset"].update(root=str(datasets), version="base")
            cfg["model"] = {"name": "small_cnn"}
            cfg["train"].update(epochs=1, batch_size=16)
            cfg["output_dir"] = str(tmp / "runs")
            (tmp / "cfg.json").write_text(json.dumps(cfg), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                train.main(["--config", str(tmp / "cfg.json"), "--max-steps", "1", "--run-name", "first"])
                first = next((tmp / "runs").iterdir())
                train.main(["--config", str(tmp / "cfg.json"), "--dataset", "base+user-t", "--max-steps", "2",
                            "--lr", "0.0003", "--warmup-epochs", "0", "--init-from", str(first / "best.pt"),
                            "--run-name", "second"])
            second = next(p for p in (tmp / "runs").iterdir() if p.name.endswith("second"))
            run = json.loads((second / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run["dataset"]["version"], "base+user-t")
            self.assertEqual(run["initFrom"]["epoch"], 1)
            self.assertEqual((run["config"]["train"]["lr"], run["config"]["train"]["warmup_epochs"]), (0.0003, 0))
            self.assertIn("user-t/images.npy", run["dataset"]["files"])


if __name__ == "__main__":
    unittest.main()
