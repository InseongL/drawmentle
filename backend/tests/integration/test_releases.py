"""Model releases: manifests built from an exported model, registration, and refusal of mismatching inputs.

    python -m unittest discover -s backend/tests/integration

Needs the local score table (data/artifacts/scoring/scoring-v1) and the test database; skipped otherwise.
The model file is a stand-in: the server never parses ONNX, it only checks hashes and publishes the file.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import cli  # noqa: E402
from app.core.settings import Settings  # noqa: E402
from app.modules.releases.artifact_loader import ArtifactLoader, canonical_sha256  # noqa: E402
from app.modules.releases.service import ReleaseService  # noqa: E402

RELEASE_ID = "test-model-release"
RECOGNITION = {"version": "test-recognition-v1", "status": "draft", "min_top1_p": 0.15, "min_top3_sum": None,
               "min_known_axes": 1, "success_min_p": 0.9, "success_min_margin": None}


def fake_model(folder: Path, class_ids: list[str], temperature: float = 1.25) -> Path:
    folder.mkdir(parents=True)
    onnx = folder / "model.onnx"
    onnx.write_bytes(b"stand-in for an ONNX file")
    manifest = {
        "modelVersion": "test-model-e1", "format": "onnx", "opset": 17, "file": "model.onnx",
        "bytes": onnx.stat().st_size, "sha256": hashlib.sha256(onnx.read_bytes()).hexdigest(),
        "input": {"name": "image", "shape": [1, 1, 64, 64]}, "output": {"name": "logits", "shape": [1, 345]},
        "preprocessing": {"version": "qd-strokes-64-v1", "size": 64, "span": 48.0, "radius": 2.0, "supersample": 4},
        "classes": {"count": len(class_ids), "sha256": hashlib.sha256(json.dumps(class_ids).encode()).hexdigest()},
        "outputCalibration": {"method": "temperature", "temperature": temperature},
        "source": {"runId": "test-run", "checkpoint": "best", "epoch": 1},
    }
    (folder / "model-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


@unittest.skipUnless((cli.SCORE_TABLE_DIR / "score-table.npz").exists(), "local score table not built")
class ModelReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_submissions import DEFAULT_URL, prepare_database
        cls.engine = prepare_database(os.environ.get("TEST_DATABASE_URL", DEFAULT_URL))
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.class_ids = [r["categoryId"] for r in cli.dev_manifests("x")[0]["rawClasses"]]

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.tmp.cleanup()

    def setUp(self):
        import sqlalchemy as sa
        with self.engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM release_bundles WHERE release_id = :r"), {"r": RELEASE_ID})

    def test_builds_registers_and_serves_the_model_release(self):
        from sqlalchemy.orm import Session
        model_dir = fake_model(self.root / "models" / "ok", self.class_ids)
        public, private, model = cli.model_manifests(RELEASE_ID, model_dir, RECOGNITION)
        self.assertEqual(public["inference"]["mode"], "browser_onnx")
        self.assertEqual((public["modelVersion"], public["preprocessingVersion"], public["outputCalibrationVersion"]),
                         ("test-model-e1", "qd-strokes-64-v1", "temperature-1.25"))
        self.assertEqual(public["model"]["url"], "/models/test-model-e1/model.onnx")
        self.assertEqual((public["model"]["sha256"], public["model"]["temperature"]), (model["sha256"], 1.25))
        self.assertEqual(private["publicManifestSha256"], canonical_sha256(public))
        self.assertNotIn("answers", json.dumps(public))

        settings = Settings(database_url=self.engine.url.render_as_string(hide_password=False), artifact_root=self.root)
        with Session(self.engine) as db:
            cli.write_and_register(settings, db, RELEASE_ID, public, private, model_dir / "model.onnx")
            service = ReleaseService(ArtifactLoader(self.root))
            context = service.context(db, RELEASE_ID)
            self.assertEqual((context.rules.version, context.rules.success_min_p, context.rules.min_top1_p),
                             ("test-recognition-v1", 0.9, 0.15))
            self.assertEqual(context.catalog.manifest.model["temperature"], 1.25)
            self.assertEqual(len(context.catalog.candidate_index), 335)
        published = self.root / "frontend/public/models/test-model-e1/model.onnx"
        self.assertEqual(published.read_bytes(), (model_dir / "model.onnx").read_bytes())

    def test_refuses_changed_model_wrong_class_order_and_missing_thresholds(self):
        tampered = fake_model(self.root / "models" / "tampered", self.class_ids)
        (tampered / "model.onnx").write_bytes(b"changed after export")
        with self.assertRaisesRegex(SystemExit, "hash"):
            cli.model_manifests(RELEASE_ID, tampered, RECOGNITION)
        reordered = fake_model(self.root / "models" / "reordered", list(reversed(self.class_ids)))
        with self.assertRaisesRegex(SystemExit, "class order"):
            cli.model_manifests(RELEASE_ID, reordered, RECOGNITION)
        ok = fake_model(self.root / "models" / "no-thresholds", self.class_ids)
        with self.assertRaisesRegex(SystemExit, "success_min_p"):
            cli.model_manifests(RELEASE_ID, ok, RECOGNITION | {"success_min_p": None})


if __name__ == "__main__":
    unittest.main()
