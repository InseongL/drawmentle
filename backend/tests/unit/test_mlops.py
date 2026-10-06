"""Unit tests for collection settings, sampling and monitoring thresholds. No API, DB or files beyond config.

    python -m unittest discover -s backend/tests/unit
"""
import dataclasses
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import cli  # noqa: E402
from app.core.collection_config import DISABLED_POLICY, CollectionConfig, Sampling  # noqa: E402
from app.core.settings import COLLECTION_CONFIG, REPO_ROOT  # noqa: E402
from app.modules.collections.service import policy_view, select  # noqa: E402
from app.storage.object_store import LocalObjectStore, ObjectExists  # noqa: E402

BASE = CollectionConfig.load(COLLECTION_CONFIG)


class CollectionConfigTests(unittest.TestCase):
    def test_repo_config_loads_and_starts_disabled(self):
        self.assertFalse(BASE.enabled)
        self.assertEqual(BASE.selection_policy, DISABLED_POLICY)
        self.assertEqual(policy_view(BASE), (DISABLED_POLICY, False))
        on = dataclasses.replace(BASE, enabled=True)
        self.assertEqual((on.selection_policy, policy_view(on)), (on.sampling.version, (on.notice_version, True)))

    def test_bad_values_are_rejected(self):
        raw = json.loads(COLLECTION_CONFIG.read_text(encoding="utf-8"))
        for path, value in ((("sampling", "failure_rate"), 1.5), (("upload", "max_bytes"), 0),
                            (("retention", "temp_hours"), 0), (("storage", "backend"), "s3")):
            with self.subTest(path):
                bad = json.loads(json.dumps(raw))
                bad[path[0]][path[1]] = value
                with self.assertRaises(ValueError):
                    CollectionConfig.from_dict(bad)


class SamplingTests(unittest.TestCase):
    def test_disabled_never_selects(self):
        self.assertEqual(select(BASE, uuid.uuid4(), "solved"), (DISABLED_POLICY, "not_selected"))

    def test_rates_and_determinism(self):
        cfg = dataclasses.replace(BASE, enabled=True, sampling=Sampling("s-test", 1.0, 0.25, 0.0))
        ids = [uuid.UUID(int=i) for i in range(2000)]
        self.assertTrue(all(select(cfg, i, "solved") == ("s-test", "success_sample") for i in ids))
        self.assertTrue(all(select(cfg, i, "deferred")[1] == "not_selected" for i in ids))
        failures = [select(cfg, i, "recognized")[1] for i in ids]
        self.assertAlmostEqual(failures.count("failure_sample") / len(ids), 0.25, delta=0.03)
        self.assertEqual(failures, [select(cfg, i, "recognized")[1] for i in ids])  # same ID, same answer


class ObjectStoreTests(unittest.TestCase):
    def test_create_only_and_key_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalObjectStore(Path(tmp))
            store.put("verified/a/b.json", b"1", create_only=True)
            with self.assertRaises(ObjectExists):
                store.put("verified/a/b.json", b"2", create_only=True)
            self.assertEqual(store.get("verified/a/b.json"), b"1")
            with self.assertRaises(ValueError):
                store.put("../outside.json", b"x")
            self.assertEqual(store.list("verified"), ["verified/a/b.json"])


class MonitoringTests(unittest.TestCase):
    CFG = json.loads((REPO_ROOT / "config/mlops/mlops.json").read_text(encoding="utf-8"))["monitoring"]

    def row(self, **kw):
        base = {"date": "2026-10-07", "release": "r", "games": 100, "deferralRate": 0.03, "solveRate": 0.6,
                "nearMissShare": 0.2, "nearMissMedianP1": 0.6, "top1Concentration": 0.05}
        return base | kw

    def test_quiet_day_and_small_days_have_no_alerts(self):
        self.assertEqual(cli.monitoring_alerts([self.row()], self.CFG), [])
        self.assertEqual(cli.monitoring_alerts([self.row(games=3, deferralRate=0.9)], self.CFG), [])

    def test_each_threshold_alerts(self):
        alerts = cli.monitoring_alerts([self.row(deferralRate=0.2, solveRate=0.1, nearMissShare=0.7,
                                                 nearMissMedianP1=0.8, top1Concentration=0.5)], self.CFG)
        self.assertEqual(len(alerts), 4)
        # many near misses far below the threshold are a model problem, not a too strict threshold
        self.assertEqual(cli.monitoring_alerts([self.row(nearMissShare=0.7, nearMissMedianP1=0.3)], self.CFG), [])


if __name__ == "__main__":
    unittest.main()
