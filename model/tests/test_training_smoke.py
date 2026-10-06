"""The training loop runs, records the run and resumes, on a tiny synthetic dataset (seconds, CPU or GPU).

    python -m unittest discover -s model/tests -t .      (needs the model venv: torch, torchvision)
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import torch
    from model.training import train
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest(f"torch not installed: {exc}")


def tiny_dataset(root: Path, n: int = 96) -> None:
    rng = np.random.default_rng(0)
    root.mkdir(parents=True)
    np.save(root / "images.npy", rng.integers(0, 256, (n, 64, 64), dtype=np.uint8))
    np.save(root / "labels.npy", (np.arange(n) % 345).astype(np.int16))
    np.save(root / "split.npy", np.array([0] * (n - 32) + [1] * 32, dtype=np.uint8))
    np.save(root / "recognized.npy", np.ones(n, dtype=bool))
    np.save(root / "key_ids.npy", np.arange(n, dtype=np.int64))
    public = {"datasetVersion": "tiny", "files": {}, "classes": {"count": 345, "sha256": "0" * 64},
              "preprocessing": {"version": "qd-strokes-64-v1", "size": 64}}
    (root / "manifest.public.json").write_text(json.dumps(public), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps(public | {"classIds": [f"c{i}" for i in range(345)]}),
                                        encoding="utf-8")


class TrainingSmokeTest(unittest.TestCase):
    def test_runs_records_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            tiny_dataset(tmp / "datasets" / "tiny")
            cfg = json.loads((train.DEFAULT_CONFIG).read_text(encoding="utf-8"))
            cfg["dataset"].update(root=str(tmp / "datasets"), version="tiny")
            cfg["model"] = {"name": "small_cnn"}
            cfg["train"].update(epochs=3, batch_size=16)
            cfg["output_dir"] = str(tmp / "runs")
            (tmp / "cfg.json").write_text(json.dumps(cfg), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                train.main(["--config", str(tmp / "cfg.json"), "--max-steps", "2", "--run-name", "t"])
            run_dir = next((tmp / "runs").iterdir())
            run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual((run["status"], run["steps"]), ("stopped_max_steps", 2))
            for name in ("classes.json", "history.jsonl", "last.pt", "best.pt"):
                self.assertTrue((run_dir / name).exists(), name)
            self.assertEqual(len(json.loads((run_dir / "classes.json").read_text())["classIds"]), 345)
            self.assertIn("commit", run["code"])
            self.assertEqual(run["dataset"]["version"], "tiny")

            with contextlib.redirect_stdout(io.StringIO()):
                train.main(["--resume", str(run_dir)])
            run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertIn(run["status"], ("finished", "early_stopped"))
            self.assertEqual(run["epochsRun"], 3)
            history = [json.loads(line) for line in (run_dir / "history.jsonl").read_text().splitlines()]
            self.assertEqual([h["epoch"] for h in history], [1, 2, 3])
            best = torch.load(run_dir / "best.pt", map_location="cpu", weights_only=False)
            self.assertIn("model", best)


if __name__ == "__main__":
    unittest.main()
