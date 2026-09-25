"""Build the offline score table (scoring-v1) from the attribute dictionary, catalog curation and label vectors.

Offline only: no FastAPI app, router or DB. Uses the same maths as the online judge
(backend/app/modules/judging/similarity.py). Output goes to data/artifacts/scoring/<version>/ (not tracked by Git).

    python scripts/scoring/build_score_table.py
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.modules.judging import similarity as sim  # noqa: E402
from app.modules.judging.types import ScoreTable  # noqa: E402

CONFIG = ROOT / "config/scoring/scoring.json"
ATTRIBUTE_MODULES = ("classification", "shape", "function")
TABLE_FILE, MANIFEST_FILE = "score-table.npz", "manifest.json"


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def json_sha256(path: Path) -> str:
    """Hash of the parsed JSON (sorted keys), so CRLF/LF checkouts or reformatting do not change it."""
    canonical = json.dumps(read_json(path), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def content_sha256(ids, arrays: dict[str, np.ndarray]) -> str:
    """Hash of category order + array values; independent of npz/zip timestamps."""
    h = hashlib.sha256(json.dumps(list(ids)).encode())
    for name in sorted(arrays):
        a = np.ascontiguousarray(arrays[name], dtype=np.float64)
        h.update(name.encode()); h.update(np.nan_to_num(a, nan=-1.0).tobytes())
    return h.hexdigest()


def load_attribute_tool():
    spec = importlib.util.spec_from_file_location("attribute_dictionary", ROOT / "scripts/attribute_dictionary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def catalog_labels() -> dict[str, dict]:
    return {c["category_id"]: c for c in read_json(ROOT / "data/quickdraw/metadata/labels.json")["categories"]}


def scoring_ids(curation: dict) -> list[str]:
    cats = curation["categories"]
    return sorted((c for c, v in cats.items() if v["scoring"]), key=lambda c: cats[c]["class_index"])


def label_tokens(cfg: dict, category_id: str, label_en: str) -> list[str]:
    tok = cfg["modules"]["association"]["tokens"]
    if category_id in tok["overrides"]:
        return list(tok["overrides"][category_id])
    return [w for w in label_en.replace("-", " ").split() if w not in set(tok["stopwords"])]


def token_plan(cfg: dict, labels: dict[str, dict]) -> dict[str, list[str]]:
    unknown = set(cfg["modules"]["association"]["tokens"]["overrides"]) - set(labels)
    if unknown:
        raise ValueError(f"token overrides for unknown categories: {sorted(unknown)}")
    return {c: label_tokens(cfg, c, lab["label_en"]) for c, lab in labels.items()}


def load_label_vectors(path: Path) -> tuple[dict[str, np.ndarray], str]:
    data = np.load(path)
    words, vectors = [str(w) for w in data["words"]], data["vectors"]
    digest = hashlib.sha256(json.dumps(words).encode() + np.ascontiguousarray(vectors, np.float32).tobytes()).hexdigest()
    return dict(zip(words, vectors)), digest


def label_vector_matrix(tokens_by_id: dict[str, list[str]], ids: list[str], vectors: dict[str, np.ndarray]) -> np.ndarray:
    rows, missing = [], []
    for c in ids:
        parts = []
        for t in tokens_by_id[c]:
            form = next((f for f in (t, t.lower(), t.capitalize()) if f in vectors), None)
            if form is None:
                missing.append(f"{c}:{t}")
                continue
            v = np.asarray(vectors[form], np.float64)
            parts.append(v / np.linalg.norm(v))
        if not parts:
            missing.append(c)
            rows.append(np.zeros(len(next(iter(vectors.values())))))
            continue
        rows.append(np.mean(parts, 0))
    if missing:
        raise ValueError(f"label vectors missing for: {missing}")
    return np.stack(rows)


def build(cfg: dict, label_vectors: dict[str, np.ndarray] | None = None, label_vectors_sha256: str | None = None):
    """Return (arrays, manifest). `label_vectors` may be injected (tests); otherwise read from cfg inputs."""
    inp = {k: ROOT / v for k, v in cfg["inputs"].items()}
    curation = read_json(inp["catalog_curation"])
    ids = scoring_ids(curation)
    ad = load_attribute_tool()
    ctx = ad.load_context(ROOT / "data/quickdraw/metadata/labels.json", inp["attribute_vocabulary"])
    store = ad.load_store(inp["attribute_dictionary"].parent, ctx)   # validates signatures, class_index, tags
    records = store["records"]
    missing = [c for c in ids if c not in records]
    if missing:
        raise ValueError(f"attribute records missing for score categories: {missing}")

    modules: dict[str, np.ndarray] = {}
    idf_min_df = cfg["tag_weighting"]["min_df"]
    for m in ATTRIBUTE_MODULES:
        spec = cfg["modules"][m]
        tag_lists = [records[c]["attributes"][m]["tags"] if records[c]["attributes"][m]["status"] == "known" else None
                     for c in ids]
        vocab = list(ctx["modules"][m]["tags"])
        weights = sim.idf_weights(tag_lists, idf_min_df)
        fam = sim.family_matrix(vocab, spec["families"], spec["family_partial_credit"]) if spec.get("families") else None
        modules[m] = sim.tag_similarity(tag_lists, vocab, weights, fam)

    assoc = cfg["modules"]["association"]
    if label_vectors is None:
        label_vectors, label_vectors_sha256 = load_label_vectors(inp["label_vectors"])
    plan = token_plan(cfg, catalog_labels())
    cos = sim.cosine_matrix(label_vector_matrix(plan, ids, label_vectors))
    pairs = sim.off_diagonal(cos)
    cal = assoc["calibration"]
    zero_at = float(np.percentile(pairs, cal["zero_at_percentile"]))
    one_at = float(np.percentile(pairs, cal["one_at_percentile"]))
    word = sim.linear_calibration(cos, zero_at, one_at)
    np.fill_diagonal(word, 1.0)
    modules["association"] = word

    weights = {m: float(cfg["modules"][m]["weight"]) for m in modules}
    relation = sim.combine(modules, weights)
    arrays = {"relation": relation, **modules}
    off = relation[~np.eye(len(ids), dtype=bool)]
    manifest = {
        "version": cfg["version"], "status": cfg["status"], "config_sha256": json_sha256(CONFIG),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {k: {"path": cfg["inputs"][k], "sha256": json_sha256(p)} for k, p in inp.items() if k != "label_vectors"}
        | {"label_vectors": {"path": cfg["inputs"]["label_vectors"], "content_sha256": label_vectors_sha256}},
        "catalog_version": curation["version"], "category_count": len(ids), "ids": ids,
        "weights": weights, "missing_axis": cfg["missing_axis"]["policy"],
        "association_calibration": {"zero_at_cosine": zero_at, "one_at_cosine": one_at, **{k: cal[k] for k in
                                    ("method", "zero_at_percentile", "one_at_percentile")}},
        "display": cfg["display"], "ranking": cfg["ranking"],
        "stats": {"zero_share": float(np.mean(off == 0)), "median_display": float(np.median(off) * 100),
                  "p90_display": float(np.percentile(off, 90) * 100)},
        "content_sha256": content_sha256(ids, arrays),
        "license_note": f"association axis derived from {assoc['vector_source']['name']} ({assoc['vector_source']['license']})",
    }
    return arrays, manifest


def write(arrays: dict[str, np.ndarray], manifest: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_dir / TABLE_FILE, ids=np.array(manifest["ids"]),
                        **{k: v.astype(np.float64) for k, v in arrays.items()})
    (out_dir / MANIFEST_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def read(out_dir: Path) -> tuple[dict[str, np.ndarray], dict]:
    manifest = read_json(out_dir / MANIFEST_FILE)
    data = np.load(out_dir / TABLE_FILE)
    if [str(x) for x in data["ids"]] != manifest["ids"]:
        raise ValueError("score table ids do not match manifest")
    return {k: data[k] for k in data.files if k != "ids"}, manifest


def to_score_table(arrays: dict[str, np.ndarray], manifest: dict) -> ScoreTable:
    mods = {m: arrays[m] for m in manifest["weights"]}
    return ScoreTable(manifest["version"], tuple(manifest["ids"]), arrays["relation"], mods, manifest["weights"],
                      manifest["display"]["scale"], manifest["display"]["decimals"], manifest["ranking"]["compare_decimals"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, help="output dir (default: config output_dir)")
    args = ap.parse_args(argv)
    cfg = read_json(CONFIG)
    arrays, manifest = build(cfg)
    out = args.out or ROOT / cfg["output_dir"]
    write(arrays, manifest, out)
    print(json.dumps({"out": str(out), "categories": manifest["category_count"], "stats": manifest["stats"],
                      "association_calibration": manifest["association_calibration"],
                      "content_sha256": manifest["content_sha256"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
