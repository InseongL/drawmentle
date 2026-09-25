"""Check a built score table and write a review report next to it.

Fails (exit 1) on integrity problems: stale inputs, hash mismatch, coverage, non-finite values, asymmetry,
range, diagonal, recombination and rebuild differences. Also reports ties, zero share, contrast/association
pair ranks and each daily candidate's nearest categories. Passing checks does not mean the scores feel right;
read the nearest lists and play-test.

    python scripts/scoring/check_score_table.py
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_score_table as bst  # noqa: E402
from app.modules.judging import similarity as sim  # noqa: E402


def integrity_errors(arrays: dict[str, np.ndarray], manifest: dict, cfg: dict, rebuild: bool = True) -> list[str]:
    errors = []
    ids = manifest["ids"]
    n = len(ids)
    if bst.content_sha256(ids, arrays) != manifest["content_sha256"]:
        errors.append("content hash does not match manifest")
    if manifest["config_sha256"] != bst.json_sha256(bst.CONFIG):
        errors.append("config/scoring/scoring.json changed after this table was built")
    for k, meta in manifest["inputs"].items():
        if "sha256" in meta and bst.json_sha256(bst.ROOT / meta["path"]) != meta["sha256"]:
            errors.append(f"input changed after build: {meta['path']}")
    curation = bst.read_json(bst.ROOT / cfg["inputs"]["catalog_curation"])
    if bst.scoring_ids(curation) != ids:
        errors.append("score categories differ from the current catalog curation")
    r = arrays["relation"]
    if not np.isfinite(r).all():
        errors.append("relation has non-finite values")
    for name, a in arrays.items():
        if a.shape != (n, n):
            errors.append(f"{name}: shape {a.shape}"); continue
        if not np.array_equal(np.isnan(a), np.isnan(a.T)) or np.nanmax(np.abs(a - a.T)) > 1e-9:
            errors.append(f"{name}: not symmetric")
        if np.nanmin(a) < 0 or np.nanmax(a) > 1 + 1e-12:
            errors.append(f"{name}: values outside [0, 1]")
        d = np.diag(a)
        if not np.allclose(d[~np.isnan(d)], 1.0):
            errors.append(f"{name}: diagonal is not 1")
    mods = {m: arrays[m] for m in manifest["weights"]}
    if not np.allclose(sim.combine(mods, manifest["weights"]), r, atol=1e-12):
        errors.append("relation does not equal the weighted combination of module scores")
    if rebuild:
        fresh, fresh_manifest = bst.build(cfg)
        if fresh_manifest["content_sha256"] != manifest["content_sha256"]:
            errors.append("rebuilding from current inputs gives a different table")
    return errors


def review_metrics(arrays: dict[str, np.ndarray], manifest: dict, cfg: dict) -> dict:
    ids = manifest["ids"]; col = {c: i for i, c in enumerate(ids)}; n = len(ids)
    r = arrays["relation"]
    disp = np.round(r * manifest["display"]["scale"], manifest["display"]["decimals"])
    distinct, zero = [], []
    for i in range(n):
        row = np.delete(disp[i], i)
        distinct.append(len(np.unique(np.sort(row)[::-1][:20])) / 20)
        zero.append(np.mean(row == 0))

    def pair_ranks(pairs):
        out = []
        for a, b in pairs:
            for x, y in ((a, b), (b, a)):
                row = r[col[x]].copy(); row[col[x]] = -1
                out.append(int((row > row[col[y]]).sum()) + 1)
        return np.array(out)

    policy = bst.read_json(bst.ROOT / cfg["inputs"]["attribute_policy"])
    contrast = sorted({tuple(sorted(p)) for g in policy["contrast_groups"] for p in itertools.combinations(g, 2)
                       if p[0] in col and p[1] in col})
    assoc = [tuple(p) for p in cfg["review_sets"]["association_pairs"] if p[0] in col and p[1] in col]
    cr, ar = pair_ranks(contrast), pair_ranks(assoc)
    return {"top20_distinct_ratio": round(float(np.mean(distinct)), 3), "zero_share": round(float(np.mean(zero)), 3),
            "contrast_pairs": len(contrast), "contrast_top10": round(float(np.mean(cr <= 10)), 3),
            "contrast_median_rank": float(np.median(cr)), "association_pairs": len(assoc),
            "association_top10": round(float(np.mean(ar <= 10)), 3), "association_median_rank": float(np.median(ar))}


def write_report(arrays, manifest, cfg, metrics, errors, out_dir: Path) -> Path:
    curation = bst.read_json(bst.ROOT / cfg["inputs"]["catalog_curation"])["categories"]
    ids = manifest["ids"]; r = arrays["relation"]; scale = manifest["display"]["scale"]
    lines = [f"# 점수표 검토 보고서 — {manifest['version']}", "",
             f"- 생성: {manifest['built_at']} · 카테고리 {len(ids)}개 · 내용 해시 `{manifest['content_sha256'][:16]}`",
             f"- 무결성 검사: {'통과' if not errors else '실패 ' + str(len(errors)) + '건'}",
             f"- 상위 20개 중 서로 다른 점수 비율 {metrics['top20_distinct_ratio']} · 0점 비율 {metrics['zero_share']}",
             f"- 혼동 후보 쌍 {metrics['contrast_pairs']}개: 상위 10위 {metrics['contrast_top10']}, 중앙 순위 {metrics['contrast_median_rank']}",
             f"- 연상 쌍 {metrics['association_pairs']}개: 상위 10위 {metrics['association_top10']}, 중앙 순위 {metrics['association_median_rank']}",
             "- 기술 검사 통과가 점수의 납득 가능성이나 재미를 보장하지 않는다. 아래 가까운 후보 목록을 직접 읽는다.", ""]
    if errors:
        lines += ["## 무결성 오류", ""] + [f"- {e}" for e in errors] + [""]
    lines += ["## 데일리 후보별 가까운 카테고리 10개", "", "| 정답 | 가까운 순서 (화면 점수) |", "|---|---|"]
    for i, c in enumerate(ids):
        if not curation[c]["daily_candidate"]:
            continue
        row = r[i].copy(); row[i] = -1
        near = ", ".join(f"{curation[ids[j]]['display_name_ko']} {row[j] * scale:.2f}" for j in np.argsort(-row)[:10])
        lines.append(f"| {curation[c]['display_name_ko']} `{c}` | {near} |")
    path = out_dir / "review-report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, help="table dir (default: config output_dir)")
    ap.add_argument("--no-rebuild", action="store_true", help="skip the rebuild-equality check")
    args = ap.parse_args(argv)
    cfg = bst.read_json(bst.CONFIG)
    out = args.out or bst.ROOT / cfg["output_dir"]
    arrays, manifest = bst.read(out)
    errors = integrity_errors(arrays, manifest, cfg, rebuild=not args.no_rebuild)
    metrics = review_metrics(arrays, manifest, cfg)
    report = write_report(arrays, manifest, cfg, metrics, errors, out)
    print(json.dumps({"errors": errors, "metrics": metrics, "report": str(report)}, ensure_ascii=False, indent=1))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
