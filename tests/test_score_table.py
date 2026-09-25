"""Offline score-table build/check contract. Uses synthetic label vectors so no download is needed."""
import copy
import hashlib
import importlib.util
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/scoring/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, str(ROOT / "scripts/scoring"))
    spec.loader.exec_module(mod)
    return mod


bst = load("build_score_table")
check = load("check_score_table")


def synthetic_vectors(cfg):
    plan = bst.token_plan(cfg, bst.catalog_labels())
    words = sorted({t for ts in plan.values() for t in ts})
    vecs = {}
    for w in words:
        seed = int(hashlib.sha256(w.encode()).hexdigest()[:8], 16)
        vecs[w] = np.random.default_rng(seed).normal(size=16).astype(np.float32)
    return vecs


class ScoreTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = bst.read_json(bst.CONFIG)
        cls.vecs = synthetic_vectors(cls.cfg)
        cls.arrays, cls.manifest = bst.build(cls.cfg, cls.vecs, "synthetic")

    def test_covers_exactly_the_score_supported_catalog(self):
        curation = bst.read_json(ROOT / self.cfg["inputs"]["catalog_curation"])
        self.assertEqual(self.manifest["ids"], bst.scoring_ids(curation))
        self.assertNotIn("bird", self.manifest["ids"])
        self.assertNotIn("mug", self.manifest["ids"])   # merged into cup

    def test_integrity_checks_pass_and_catch_tampering(self):
        self.assertEqual(check.integrity_errors(self.arrays, self.manifest, self.cfg, rebuild=False), [])
        bad = {k: v.copy() for k, v in self.arrays.items()}
        bad["relation"][0, 1] += 0.01
        errors = check.integrity_errors(bad, self.manifest, self.cfg, rebuild=False)
        self.assertTrue(any("hash" in e for e in errors))
        self.assertTrue(any("symmetric" in e for e in errors))
        self.assertTrue(any("combination" in e for e in errors))

    def test_build_is_deterministic(self):
        _, again = bst.build(self.cfg, self.vecs, "synthetic")
        self.assertEqual(again["content_sha256"], self.manifest["content_sha256"])

    def test_every_axis_follows_weights_and_missing_policy(self):
        self.assertAlmostEqual(sum(self.manifest["weights"].values()), 1.0)
        fn = self.arrays["function"]
        self.assertTrue(np.isnan(fn).any())                    # not_applicable function axes exist
        self.assertFalse(np.isnan(self.arrays["association"]).any())
        self.assertFalse(np.isnan(self.arrays["relation"]).any())
        self.assertTrue(np.allclose(np.diag(self.arrays["relation"]), 1.0))

    def test_scorer_reads_built_table(self):
        from app.modules.judging import scorer
        table = bst.to_score_table(self.arrays, self.manifest)
        res = scorer.mix_top3(table, "giraffe", [("horse", .5), ("zebra", .2), ("cow", .1)])
        self.assertTrue(0 <= res.mixed <= 1)
        self.assertEqual(len(res.display_text.split(".")[1]), 2)
        self.assertEqual(set(res.candidates[0].modules), set(self.manifest["weights"]))

    def test_config_errors_are_rejected(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["modules"]["shape"]["families"]["rounded"].append("not_a_tag")
        with self.assertRaisesRegex(ValueError, "not in vocabulary"):
            bst.build(cfg, self.vecs, "synthetic")
        cfg = copy.deepcopy(self.cfg)
        cfg["modules"]["association"]["tokens"]["overrides"]["no_such_category"] = ["x"]
        with self.assertRaisesRegex(ValueError, "unknown categories"):
            bst.build(cfg, self.vecs, "synthetic")
        with self.assertRaisesRegex(ValueError, "label vectors missing"):
            bst.build(self.cfg, {k: v for k, v in self.vecs.items() if k != "giraffe"}, "synthetic")


if __name__ == "__main__":
    unittest.main()
