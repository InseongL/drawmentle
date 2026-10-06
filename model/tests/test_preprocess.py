"""qd-strokes-64-v1 rendering rules and sampling. No GPU or dataset needed.

    python -m unittest discover -s model/tests -t .
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from model.datasets.build_manifest import read_records
from model.datasets.preprocess import QD_STROKES_64_V1, normalise, render

# Changing any of these means the preprocessing changed: bump the version instead of updating the hash.
GOLDEN = {
    "square": ([[[0, 100, 100, 0, 0], [0, 0, 100, 100, 0]]],
               "e696cd34646a11671c32670e7aed527bab8a7cb27730d097601c94ff0fa9cade"),
    "wide_line": ([[[0, 255], [120, 120]]], "bd7fb6d6cccc6c69ef366f91a1ce687341eb46044ae1d132dd58cf48afd68b08"),
    "two_strokes_dot": ([[[10, 60], [10, 80]], [[200], [30]]],
                        "da9fdf8606b12f7328becc60bb6416fcdc56577973a49e369b5e87d1e4e094d6"),
    "single_dot": ([[[5], [5]]], "2b13cd5132a0829a49376076586a512d3d27e292265721f85c58a0c7d2852a52"),
}


def ink_box(img):
    ys, xs = np.nonzero(img)
    return xs.min(), xs.max(), ys.min(), ys.max()


class RenderTests(unittest.TestCase):
    def test_golden_outputs_are_frozen(self):
        for name, (drawing, digest) in GOLDEN.items():
            with self.subTest(name):
                self.assertEqual(hashlib.sha256(render(drawing).tobytes()).hexdigest(), digest)

    def test_output_contract(self):
        img = render(GOLDEN["square"][0])
        self.assertEqual((img.shape, img.dtype), ((64, 64), np.uint8))
        self.assertEqual((int(img.min()), int(img.max())), (0, 255))
        self.assertEqual(img[0, 0], 0)  # background is 0, ink is bright

    def test_longest_side_spans_48px_centred_and_keeps_aspect_ratio(self):
        x0, x1, y0, y1 = ink_box(render([[[0, 200], [50, 50]], [[0, 0], [0, 100]]]))  # 200 wide, 100 tall
        self.assertEqual((x0, x1), (6, 57))  # 48 px span + 2 px radius on both sides
        self.assertAlmostEqual((y0 + y1) / 2, 31.5, delta=0.5)
        self.assertLess(y1 - y0, x1 - x0)
        # position and scale of the input do not matter, only the shape
        a = render([[[10, 110, 110], [10, 10, 60]]])
        b = render([[[500, 700, 700], [300, 300, 400]]])
        self.assertTrue((a == b).all())

    def test_single_dot_and_degenerate_drawings(self):
        dot = render([[[5], [5]]])
        self.assertAlmostEqual(np.argwhere(dot == 255).mean(), 31.5)
        self.assertEqual(dot.max(), 255)
        self.assertTrue((render([[[7, 7, 7], [3, 3, 3]]]) == dot).all())  # repeated point = dot
        with self.assertRaises(ValueError):
            render([])
        with self.assertRaises(ValueError):
            render([[[], []]])

    def test_normalise_uses_float_output_pixels(self):
        strokes = normalise([[[0, 10], [0, 20]]], QD_STROKES_64_V1)
        self.assertEqual(strokes[0].dtype, np.float64)
        np.testing.assert_allclose(strokes[0][:, 1], [8.0, 56.0])  # 20 tall -> 48 px, centred at 32


class SharedFixtureTests(unittest.TestCase):
    def test_python_matches_the_cross_language_fixture(self):
        fixture = json.loads((Path(__file__).resolve().parents[2] / "contracts/fixtures/drawing-cases.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(fixture["preprocessing"]["version"], QD_STROKES_64_V1.version)
        for case in fixture["cases"]:
            with self.subTest(case["name"]):
                img = render(case["strokes"])
                self.assertEqual(hashlib.sha256(img.tobytes()).hexdigest(), case["sha256"])
                self.assertEqual((int((img > 0).sum()), int(img.sum(dtype=np.int64))), (case["inkPixels"], case["sum"]))


class SamplingTests(unittest.TestCase):
    def test_per_class_sample_is_reproducible_and_order_independent(self):
        records = [{"key_id": str(1000 + i), "recognized": True, "drawing": [[[i, i + 1], [0, 1]]]} for i in range(50)]
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.ndjson", Path(tmp) / "b.ndjson"
            a.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
            b.write_text("".join(json.dumps(r) + "\n" for r in reversed(records)), encoding="utf-8")
            first = [r["key_id"] for r in read_records(a, 10, seed=7)]
            again = [r["key_id"] for r in read_records(b, 10, seed=7)]
            other = [r["key_id"] for r in read_records(a, 10, seed=8)]
            everything = read_records(a, None, seed=7)
        self.assertEqual(first, again)
        self.assertEqual(len(set(first)), 10)
        self.assertNotEqual(first, other)
        self.assertEqual(len(everything), 50)


if __name__ == "__main__":
    unittest.main()
