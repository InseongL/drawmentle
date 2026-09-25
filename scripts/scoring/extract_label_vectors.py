"""Extract the label-word vectors used by the association axis from fastText cc.en.300.

Downloads (streams) the public vector file named in config/scoring/scoring.json and keeps only the words in the
label token plan. The full ~1.3 GB file is never written to disk; reading stops once every token is found.
The subset is CC BY-SA 3.0 derived data and stays under data/artifacts (not tracked by Git).

    python scripts/scoring/extract_label_vectors.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_score_table import CONFIG, ROOT, catalog_labels, read_json, token_plan  # noqa: E402


def main() -> int:
    cfg = read_json(CONFIG)
    source = cfg["modules"]["association"]["vector_source"]
    out = ROOT / cfg["inputs"]["label_vectors"]
    plan = token_plan(cfg, catalog_labels())
    wanted = sorted({t for ts in plan.values() for t in ts})
    forms = {f for t in wanted for f in (t, t.lower(), t.capitalize())}
    found: dict[str, np.ndarray] = {}
    start, n = time.time(), 0
    req = urllib.request.Request(source["url"], headers={"User-Agent": "drawmentle-label-vectors"})
    with urllib.request.urlopen(req, timeout=60) as resp, gzip.GzipFile(fileobj=resp) as gz:
        header = gz.readline().decode().strip()
        for n, raw in enumerate(gz, 1):
            word = raw.split(b" ", 1)[0].decode("utf-8", "replace")
            if word in forms and word not in found:
                found[word] = np.array(raw.decode("utf-8", "replace").rstrip().split(" ")[1:], dtype=np.float32)
            if n % 200000 == 0:
                print(f"{n} lines, {time.time() - start:.0f}s, {len(found)} forms", flush=True)
                if all(t in found for t in wanted):
                    break
    missing = [t for t in wanted if not any(f in found for f in (t, t.lower(), t.capitalize()))]
    if missing:
        print(f"Error: tokens not found in {source['url']}: {missing}", file=sys.stderr)
        return 1
    words = sorted(found)
    vectors = np.stack([found[w] for w in words]).astype(np.float32)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, words=np.array(words), vectors=vectors)
    digest = hashlib.sha256(json.dumps(words).encode() + vectors.tobytes()).hexdigest()
    meta = {"source": source, "header": header, "lines_read": n, "words": len(words), "content_sha256": digest,
            "token_plan_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
            "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "words": len(words), "lines_read": n, "content_sha256": digest}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
