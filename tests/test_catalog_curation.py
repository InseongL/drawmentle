"""Offline integrity checks for the draft catalog and its probability mapping."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CatalogCurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "config/model/catalog-curation-v1.json").read_text(encoding="utf-8"))
        cls.labels = json.loads((ROOT / "data/quickdraw/metadata/labels.json").read_text(encoding="utf-8"))["categories"]

    def test_source_order_mapping_and_counts_are_consistent(self):
        catalog, labels = self.catalog, self.labels
        encoded = (ROOT / "data/quickdraw/metadata/categories.txt").read_bytes()
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), catalog["source_catalog"]["categories_sha256"])
        categories = catalog["categories"]
        self.assertEqual(set(categories), {c["category_id"] for c in labels})
        for label in labels:
            cid = label["category_id"]
            row = categories[cid]
            self.assertEqual(row["class_index"], label["class_index"])
            self.assertIn(row["service_id"], categories)
            self.assertEqual(categories[row["service_id"]]["service_id"], row["service_id"])
            if cid != row["service_id"]:
                self.assertFalse(row["scoring"])
                self.assertFalse(row["daily_candidate"])
            if row["daily_candidate"]:
                self.assertTrue(row["scoring"])
        candidates = {row["service_id"] for row in categories.values()}
        self.assertEqual(catalog["counts"], {
            "raw_classes": len(labels), "inference_candidates": len(candidates),
            "service_categories": sum(row["scoring"] for row in categories.values()),
            "merged_away": sum(cid != row["service_id"] for cid, row in categories.items()),
            "dropped": 0,
            "unsupported_candidates": sum(not categories[cid]["scoring"] for cid in candidates),
            "daily_candidates": sum(row["daily_candidate"] for row in categories.values()),
            "held_merge_groups": sum(g["decision"] == "hold" for g in catalog["groups"])})

    def test_held_merges_keep_each_concept_independent(self):
        groups = [g for g in self.catalog["groups"] if g["decision"] == "hold"]
        self.assertEqual({g["id"] for g in groups}, {"bowed_string", "small_berry", "pencil", "book", "washer", "whirlwind"})
        for group in groups:
            for cid in group["members"]:
                row = self.catalog["categories"][cid]
                self.assertEqual(row["service_id"], cid)
                self.assertTrue(row["scoring"])

    def test_bird_mass_is_preserved_in_candidate_mapping(self):
        categories = self.catalog["categories"]
        raw = {cid: 0.0 for cid in categories}
        raw.update(bird=0.98, owl=0.018, cup=0.001, mug=0.001)
        mapped = {}
        for cid, probability in raw.items():
            target = categories[cid]["service_id"]
            mapped[target] = mapped.get(target, 0.0) + probability
        self.assertAlmostEqual(sum(mapped.values()), 1.0)
        self.assertEqual(mapped["bird"], 0.98)
        self.assertEqual(mapped["owl"], 0.018)
        self.assertAlmostEqual(mapped["cup"], 0.002)
        self.assertEqual(sorted(mapped, key=mapped.get, reverse=True)[:3], ["bird", "owl", "cup"])
        self.assertFalse(categories["bird"]["scoring"])
        self.assertFalse(categories["bird"]["daily_candidate"])

    def test_user_daily_overrides_are_preserved(self):
        for cid in ("star", "smiley_face"):
            self.assertTrue(self.catalog["categories"][cid]["daily_candidate"])


if __name__ == "__main__":
    unittest.main()
