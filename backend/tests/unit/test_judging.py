"""Unit tests for pure judging maths. No API, DB or files.

    python -m unittest discover -s backend/tests/unit
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.modules.judging import scorer, similarity as sim  # noqa: E402
from app.modules.judging.judge import RecognitionRules, judge, score_details  # noqa: E402
from app.modules.judging.types import ScoreTable, UnsupportedCandidateError  # noqa: E402


class SimilarityTests(unittest.TestCase):
    def test_idf_caps_unique_tags_at_min_df(self):
        w = sim.idf_weights([["a", "x"], ["a", "y"], ["a"], None], min_df=2)
        self.assertEqual(w["x"], w["y"])
        self.assertAlmostEqual(w["x"], math.log(5 / 3) + 1)
        self.assertLess(w["a"], w["x"])

    def test_family_matrix_rejects_unknown_or_duplicate_tags(self):
        s = sim.family_matrix(["a", "b", "c"], {"f": ["a", "b"]}, 0.3)
        self.assertEqual(s[0, 1], 0.3)
        self.assertEqual(s[0, 2], 0.0)
        with self.assertRaises(ValueError):
            sim.family_matrix(["a"], {"f": ["a", "z"]}, 0.3)
        with self.assertRaises(ValueError):
            sim.family_matrix(["a", "b"], {"f": ["a"], "g": ["a", "b"]}, 0.3)

    def test_tag_similarity_soft_matching_and_unknown_axis(self):
        vocab = ["a", "b", "c"]
        w = {"a": 1.0, "b": 1.0, "c": 1.0}
        fam = sim.family_matrix(vocab, {"f": ["a", "b"]}, 0.3)
        s = sim.tag_similarity([["a"], ["b"], ["c"], None], vocab, w, fam)
        self.assertAlmostEqual(s[0, 1], 0.3)
        self.assertEqual(s[0, 2], 0.0)
        self.assertTrue(np.isnan(s[0, 3]) and np.isnan(s[3, 3]))
        self.assertTrue(np.allclose(np.diag(s)[:3], 1.0))
        self.assertTrue(np.allclose(s[:3, :3], s[:3, :3].T))

    def test_linear_calibration_is_clipped_and_order_preserving(self):
        x = np.array([-0.2, 0.1, 0.3, 0.5, 0.9])
        y = sim.linear_calibration(x, 0.1, 0.5)
        self.assertTrue(np.allclose(y, [0.0, 0.0, 0.5, 1.0, 1.0]))
        with self.assertRaises(ValueError):
            sim.linear_calibration(x, 0.5, 0.5)

    def test_combine_excludes_missing_axis_and_renormalises(self):
        a = np.array([[1.0, np.nan], [np.nan, 1.0]])
        b = np.array([[1.0, 0.4], [0.4, 1.0]])
        r = sim.combine({"a": a, "b": b}, {"a": 0.5, "b": 0.5})
        self.assertAlmostEqual(r[0, 1], 0.4)
        self.assertEqual(r[0, 0], 1.0)
        with self.assertRaises(ValueError):
            sim.combine({"a": a, "b": b}, {"a": 0.5, "b": 0.6})


def plan_example_table() -> ScoreTable:
    """Worked example of the plan §7.4: answer giraffe; horse .70, giraffe 1.0, deer .80."""
    ids = ("giraffe", "horse", "deer", "zebra", "car")
    r = np.eye(5)
    for (i, j, v) in ((0, 1, .7), (0, 2, .8), (0, 3, .8), (0, 4, 0.0), (1, 2, .6), (1, 3, .9), (2, 3, .5),
                      (1, 4, .1), (2, 4, .1), (3, 4, .1)):
        r[i, j] = r[j, i] = v
    return ScoreTable("test", ids, r, {"axis": r}, {"axis": 1.0})


class ScorerTests(unittest.TestCase):
    def test_top3_mix_matches_plan_example(self):
        res = scorer.mix_top3(plan_example_table(), "giraffe", [("horse", .5), ("giraffe", .3), ("deer", .15)])
        self.assertAlmostEqual(res.mixed, (.5 * .7 + .3 * 1.0 + .15 * .8) / .95)
        self.assertEqual(res.display_text, "81.05")
        self.assertAlmostEqual(sum(c.q for c in res.candidates), 1.0)
        self.assertEqual([c.p for c in res.candidates], [.5, .3, .15])  # original p kept

    def test_display_keeps_fixed_decimals(self):
        self.assertEqual(scorer.display(0.5, 100, 2), (50.0, "50.00"))
        self.assertEqual(scorer.display(0.38721, 100, 2)[1], "38.72")

    def test_relation_rank_answer_first_and_shared_ties(self):
        t = plan_example_table()
        self.assertEqual(scorer.relation_rank(t, "giraffe", "giraffe"), 1)
        self.assertEqual(scorer.relation_rank(t, "giraffe", "deer"), 2)
        self.assertEqual(scorer.relation_rank(t, "giraffe", "zebra"), 2)   # tie with deer
        self.assertEqual(scorer.relation_rank(t, "giraffe", "horse"), 4)
        self.assertEqual(scorer.relation_rank(t, "giraffe", "car"), 5)

    def test_invalid_top3_is_rejected_not_scored(self):
        t = plan_example_table()
        with self.assertRaises(UnsupportedCandidateError):
            scorer.mix_top3(t, "giraffe", [("bird", .5), ("horse", .2), ("deer", .1)])
        with self.assertRaises(ValueError):
            scorer.mix_top3(t, "giraffe", [("horse", 0), ("deer", 0), ("zebra", 0)])
        with self.assertRaises(ValueError):
            scorer.mix_top3(t, "giraffe", [("horse", .5), ("horse", .2), ("deer", .1)])
        with self.assertRaises(ValueError):
            scorer.mix_top3(t, "giraffe", [("horse", float("nan")), ("zebra", .2), ("deer", .1)])


class JudgeTests(unittest.TestCase):
    rules = RecognitionRules(version="test", success_min_p=0.5, min_top1_p=0.2)

    def test_deferral_order(self):
        t = plan_example_table()
        cases = [
            ([("horse", 0.0), ("deer", 0.0), ("zebra", 0.0)], "low_confidence"),      # sum 0 first
            ([("bird", 0.1), ("horse", 0.05), ("deer", 0.01)], "unsupported_candidate"),  # before low p1
            ([("horse", 0.15), ("deer", 0.1), ("zebra", 0.05)], "low_confidence"),
        ]
        for top3, reason in cases:
            res = judge(t, self.rules, "giraffe", top3)
            self.assertEqual((res.status, res.reason, res.mix, res.counted), ("deferred", reason, None, False))

    def test_insufficient_attributes_when_axes_unknown(self):
        t = plan_example_table()
        t.modules["axis"][0, 1] = np.nan
        res = judge(t, self.rules, "giraffe", [("horse", 0.6), ("deer", 0.2), ("zebra", 0.1)])
        self.assertEqual(res.reason, "insufficient_attributes")

    def test_success_needs_top1_answer_and_threshold(self):
        t = plan_example_table()
        self.assertEqual(judge(t, self.rules, "giraffe", [("giraffe", .55), ("horse", .2), ("deer", .1)]).status,
                         "solved")
        self.assertEqual(judge(t, self.rules, "giraffe", [("giraffe", .45), ("horse", .2), ("deer", .1)]).status,
                         "recognized")
        high = judge(t, self.rules, "giraffe", [("zebra", .9), ("giraffe", .05), ("deer", .05)])
        self.assertEqual(high.status, "recognized")  # answer in Top-2 is never success
        margin = RecognitionRules(version="m", success_min_p=0.5, success_min_margin=0.2)
        self.assertEqual(judge(t, margin, "giraffe", [("giraffe", .55), ("horse", .4), ("deer", .05)]).status,
                         "recognized")

    def test_details_record_rules_and_candidates(self):
        t = plan_example_table()
        top3 = [("horse", .5), ("giraffe", .3), ("deer", .15)]
        res = judge(t, self.rules, "giraffe", top3)
        d = score_details(res, self.rules, t, "giraffe", top3)
        self.assertEqual((d["status"], d["recognition"]["min_top1_p"]), ("recognized", 0.2))
        self.assertEqual([c["relationRank"] for c in d["candidates"]], [4, 1, 2])
        deferred = judge(t, self.rules, "giraffe", [("bird", .5), ("horse", .2), ("deer", .1)])
        self.assertIsNone(score_details(deferred, self.rules, t, "giraffe", top3)["candidates"])

    def test_rules_reject_out_of_range_thresholds(self):
        with self.assertRaises(ValueError):
            RecognitionRules.from_config({"version": "x", "success_min_p": 1.5})


if __name__ == "__main__":
    unittest.main()
