"""Dev commands. Run from backend/:  python -m app.cli <command> --help

  build-dev-release   Build a model-less dev release (Top-3 from the dev panel) and register it.
  schedule            Create daily puzzles from the release's daily candidates (random seed, never stored).
  list-puzzles        Dates, IDs and states only (no answers).
  assign-release      Move puzzles that have not opened and have no games to another release.
  set-answer          Change one date's answer (refused once anyone has played it).
  show-answer         Print one date's answer (dev only).
  export-openapi      Write contracts/api/openapi.json from the FastAPI schemas.

Release files go to data/artifacts/releases/<release-id>/ (private files stay untracked).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import secrets
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.core.settings import REPO_ROOT, Settings
from app.db.models import GameSession, Puzzle
from app.db.session import make_engine, make_session_factory
from app.modules.releases import repository as releases_repo
from app.modules.releases.artifact_loader import ArtifactLoader, canonical_sha256
from app.modules.releases.service import register

DEV_RELEASE_ID = "dev-release-v2"  # v2 adds English category names; v1 stays for puzzles already played
SCORE_TABLE_DIR = REPO_ROOT / "data/artifacts/scoring/scoring-v1"
RECOGNITION = REPO_ROOT / "config/scoring/recognition.json"
CURATION = REPO_ROOT / "config/model/catalog-curation-v1.json"
LABELS = REPO_ROOT / "data/quickdraw/metadata/labels.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def dev_manifests(release_id: str) -> tuple[dict, dict]:
    """Public manifest (catalog mapping only) and private manifest (score table ref, rules, answers)."""
    curation = read_json(CURATION)
    cats = curation["categories"]
    labels = sorted(read_json(LABELS)["categories"], key=lambda c: c["class_index"])
    label_en = {c["category_id"]: c["label_en"] for c in labels}
    raw = [{"classIndex": c["class_index"], "categoryId": c["category_id"],
            "candidateId": cats[c["category_id"]]["service_id"]} for c in labels]
    first_index: dict[str, int] = {}
    for r in raw:  # candidate_index = smallest raw class_index merged into the candidate
        first_index.setdefault(r["candidateId"], r["classIndex"])
    candidates = [{"categoryId": c, "candidateIndex": i, "displayNameKo": cats[c]["display_name_ko"],
                   "displayNameEn": label_en[c]}
                  for c, i in sorted(first_index.items(), key=lambda kv: kv[1])]
    public = {
        "manifestVersion": "release-public-v1", "releaseId": release_id, "status": "dev-only",
        "modelVersion": "dev-manual-top3-v0", "preprocessingVersion": "none-v0",
        "catalogVersion": curation["version"], "outputCalibrationVersion": "none-v1",
        "drawingVersions": ["strokes-v1"], "brushVersions": ["pen-v1"], "model": None,
        "inference": {"mode": "dev_manual_top3", "probability": "softmax_full_catalog_then_sum_by_candidate",
                      "outputCalibration": "none",
                      "note": "모델이 없어 개발 패널에서 Top-3와 p를 직접 정한다. 운영 릴리스가 아니다."},
        "rawClasses": raw, "rawClassesSha256": canonical_sha256(raw),
        "candidates": candidates, "candidatesSha256": canonical_sha256(candidates),
    }
    score_manifest = read_json(SCORE_TABLE_DIR / "manifest.json")
    if score_manifest["catalog_version"] != curation["version"]:
        raise SystemExit("score table was built from a different catalog version; rebuild it first")
    private = {
        "manifestVersion": "release-private-v1", "releaseId": release_id,
        "publicManifestSha256": canonical_sha256(public),
        "scoreTable": {"file": "score-table.npz", "manifestFile": "score-manifest.json",
                       "version": score_manifest["version"], "contentSha256": score_manifest["content_sha256"]},
        "recognition": read_json(RECOGNITION),
        "answers": {c: {"displayNameKo": cats[c]["display_name_ko"], "daily": bool(cats[c]["daily_candidate"])}
                    for c in score_manifest["ids"]},
    }
    return public, private


def cmd_build_dev_release(args, settings: Settings, db) -> int:
    release_dir = settings.artifact_root / "data/artifacts/releases" / args.release_id
    private_dir = release_dir / "private"
    public, private = dev_manifests(args.release_id)
    existing = releases_repo.get_bundle(db, args.release_id)
    if existing is not None and existing.public_manifest_sha256 != canonical_sha256(public):
        raise SystemExit(f"{args.release_id} is already registered with different content; use a new --release-id")
    private_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCORE_TABLE_DIR / "score-table.npz", private_dir / "score-table.npz")
    shutil.copyfile(SCORE_TABLE_DIR / "manifest.json", private_dir / "score-manifest.json")
    write_json(private_dir / "private-manifest.json", private)
    write_json(release_dir / "public-manifest.json", public)
    key = (private_dir / "private-manifest.json").relative_to(settings.artifact_root).as_posix()
    bundle = register(db, settings.artifact_root, public, key, dt.datetime.now(dt.timezone.utc))
    db.commit()
    print(f"release {bundle.release_id}: {len(public['candidates'])} candidates, "
          f"{sum(a['daily'] for a in private['answers'].values())} daily answers, "
          f"{bundle.scoring_version} / {bundle.recognition_version}")
    return 0


def _context(settings: Settings, db, release_id: str):
    bundle = releases_repo.get_bundle(db, release_id)
    if bundle is None:
        raise SystemExit(f"release {release_id} is not registered; run build-dev-release first")
    return ArtifactLoader(settings.artifact_root).context(bundle)


def _opens_at(day: dt.date, settings: Settings) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(0), ZoneInfo(settings.service_timezone)).astimezone(dt.timezone.utc)


def cmd_schedule(args, settings: Settings, db) -> int:
    ctx = _context(settings, db, args.release_id)
    daily = sorted(ctx.daily_answers, key=ctx.catalog.candidate_index.__getitem__)
    order = daily[:]
    random.Random(args.seed if args.seed is not None else secrets.randbits(64)).shuffle(order)
    start = args.start or dt.datetime.now(ZoneInfo(settings.service_timezone)).date()
    created = 0
    for offset in range(args.days):
        day = start + dt.timedelta(days=offset)
        if db.execute(select(Puzzle).where(Puzzle.service_date == day)).scalar_one_or_none():
            continue
        answer = order[offset % len(order)]
        db.add(Puzzle(puzzle_id=f"pz-{secrets.token_hex(6)}", service_date=day, release_id=args.release_id,
                      answer_category_id=answer, answer_display_name_ko=ctx.answer_names[answer],
                      opens_at=_opens_at(day, settings), state="published"))
        created += 1
    db.commit()
    print(f"scheduled {created} new puzzle(s) from {start} ({args.days} day window, {len(daily)} daily candidates)")
    return 0


def _puzzle_on(db, day: dt.date) -> Puzzle:
    puzzle = db.execute(select(Puzzle).where(Puzzle.service_date == day)).scalar_one_or_none()
    if puzzle is None:
        raise SystemExit(f"no puzzle on {day}")
    return puzzle


def cmd_list(args, settings: Settings, db) -> int:
    for p in db.execute(select(Puzzle).order_by(Puzzle.service_date)).scalars():
        print(f"{p.service_date}  {p.puzzle_id}  {p.state:<9}  {p.release_id}")
    return 0


def cmd_assign_release(args, settings: Settings, db) -> int:
    """A puzzle keeps its release once it has opened (docs/api-contract-v1.md §3); only unopened, unplayed ones move."""
    ctx = _context(settings, db, args.release_id)
    now = dt.datetime.now(dt.timezone.utc)
    moved, kept = [], []
    for puzzle in db.execute(select(Puzzle).where(Puzzle.opens_at > now).order_by(Puzzle.service_date)).scalars():
        if puzzle.release_id == args.release_id:
            continue
        played = db.execute(select(func.count()).select_from(GameSession)
                            .where(GameSession.puzzle_id == puzzle.puzzle_id)).scalar_one()
        if played or puzzle.answer_category_id not in ctx.answer_names:
            kept.append(puzzle.service_date)
            continue
        puzzle.release_id = args.release_id
        puzzle.answer_display_name_ko = ctx.answer_names[puzzle.answer_category_id]
        moved.append(puzzle.service_date)
    db.commit()
    span = f"{moved[0]}..{moved[-1]}" if moved else "none"
    print(f"moved {len(moved)} unopened puzzle(s) to {args.release_id} ({span}); kept {len(kept)}")
    return 0


def cmd_set_answer(args, settings: Settings, db) -> int:
    puzzle = _puzzle_on(db, args.date)
    ctx = _context(settings, db, puzzle.release_id)
    if args.category not in ctx.answer_names:
        raise SystemExit(f"{args.category} is not a score-supported category of {puzzle.release_id}")
    played = db.execute(select(func.count()).select_from(GameSession)
                        .where(GameSession.puzzle_id == puzzle.puzzle_id)).scalar_one()
    if played:
        raise SystemExit(f"{played} game(s) already started on {args.date}; the answer cannot change")
    puzzle.answer_category_id, puzzle.answer_display_name_ko = args.category, ctx.answer_names[args.category]
    db.commit()
    print(f"{args.date}: answer updated")
    return 0


def cmd_show_answer(args, settings: Settings, db) -> int:
    puzzle = _puzzle_on(db, args.date)
    print(f"{args.date}  {puzzle.answer_category_id}  {puzzle.answer_display_name_ko}")
    return 0


def export_openapi(out: Path) -> int:
    from app.main import create_app  # imported lazily: builds routers only, opens no DB connection
    spec = create_app(Settings()).openapi()
    write_json(out, spec)
    print(f"wrote {out.relative_to(REPO_ROOT).as_posix()} ({len(spec['paths'])} paths)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build-dev-release")
    p.add_argument("--release-id", default=DEV_RELEASE_ID)
    p.set_defaults(fn=cmd_build_dev_release)
    p = sub.add_parser("schedule")
    p.add_argument("--release-id", default=DEV_RELEASE_ID)
    p.add_argument("--start", type=dt.date.fromisoformat, help="first date (default: today in service timezone)")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--seed", type=int, help="shuffle seed; default is random and not stored")
    p.set_defaults(fn=cmd_schedule)
    sub.add_parser("list-puzzles").set_defaults(fn=cmd_list)
    p = sub.add_parser("assign-release")
    p.add_argument("--release-id", default=DEV_RELEASE_ID)
    p.set_defaults(fn=cmd_assign_release)
    p = sub.add_parser("set-answer")
    p.add_argument("date", type=dt.date.fromisoformat)
    p.add_argument("category")
    p.set_defaults(fn=cmd_set_answer, dev_only=True)
    p = sub.add_parser("show-answer")
    p.add_argument("date", type=dt.date.fromisoformat)
    p.set_defaults(fn=cmd_show_answer, dev_only=True)
    p = sub.add_parser("export-openapi")
    p.add_argument("--out", type=Path, default=REPO_ROOT / "contracts/api/openapi.json")
    args = ap.parse_args(argv)
    if args.command == "export-openapi":
        return export_openapi(args.out)

    settings = Settings.from_env()
    if settings.is_production and (getattr(args, "dev_only", False) or args.command == "build-dev-release"):
        raise SystemExit(f"{args.command} is a dev-only command")
    factory = make_session_factory(make_engine(settings.database_url))
    with factory() as db:
        return args.fn(args, settings, db)


if __name__ == "__main__":
    sys.exit(main())
