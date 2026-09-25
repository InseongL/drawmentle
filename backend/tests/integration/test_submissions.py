"""Submission API on a real PostgreSQL (docs/database-schema-v1.md §6). Skipped when the test DB is unreachable.

    docker compose -f infra/local/docker-compose.yml up -d
    python -m unittest discover -s backend/tests/integration

TEST_DATABASE_URL overrides the default drawmentle_test database on the local compose server.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

import numpy as np

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
REPO = BACKEND.parent
FIXTURE = json.loads((REPO / "contracts/fixtures/submission-cases.json").read_text(encoding="utf-8"))
DEFAULT_URL = "postgresql+psycopg://drawmentle:drawmentle-dev@127.0.0.1:5433/drawmentle_test"
NOW = dt.datetime(2026, 9, 22, 10, 0, tzinfo=dt.timezone.utc)
IDS = ("apple", "pear", "banana")
GAME_TABLES = "submission_score_details, submission_requests, submissions, game_sessions, anonymous_sessions"

try:
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient

    from app.core.settings import Settings
    from app.db.models import Puzzle
    from app.main import create_app
    from app.modules.judging.judge import Judgement
    from app.modules.judging.types import MixResult, content_sha256
    from app.modules.releases.artifact_loader import canonical_sha256
    from app.modules.releases.service import register
    from app.modules.submissions import repository as submissions_repo
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest(f"backend dependencies missing: {exc}")


def prepare_database(url: str) -> sa.Engine:
    target = sa.engine.make_url(url)
    admin = sa.create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            if not conn.execute(sa.text("SELECT 1 FROM pg_database WHERE datname = :d"),
                                {"d": target.database}).scalar():
                conn.execute(sa.text(f'CREATE DATABASE "{target.database}"'))
    except sa.exc.OperationalError as exc:
        raise unittest.SkipTest(f"test database unreachable: {type(exc).__name__}")
    finally:
        admin.dispose()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", target.render_as_string(hide_password=False))
    command.upgrade(cfg, "head")
    return sa.create_engine(target)


def write_release(root: Path, release_id: str, scoring_ids=IDS) -> tuple[dict, str]:
    """Tiny release: model outputs apple/pear/banana; the score table may support fewer."""
    candidates = [{"categoryId": c, "candidateIndex": i, "displayNameKo": n}
                  for i, (c, n) in enumerate(zip(IDS, ("사과", "배", "바나나")))]
    raw = [{"classIndex": i, "categoryId": c, "candidateId": c} for i, c in enumerate(IDS)]
    base = FIXTURE["baseRequest"]
    public = {
        "manifestVersion": "release-public-v1", "releaseId": release_id, "status": "dev-only",
        "modelVersion": base["modelVersion"], "preprocessingVersion": base["preprocessingVersion"],
        "catalogVersion": base["catalogVersion"], "outputCalibrationVersion": base["outputCalibrationVersion"],
        "drawingVersions": [base["drawingVersion"]], "brushVersions": [base["brushVersion"]], "model": None,
        "inference": {"mode": "dev_manual_top3", "probability": "test", "outputCalibration": "none"},
        "rawClasses": raw, "rawClassesSha256": canonical_sha256(raw),
        "candidates": candidates, "candidatesSha256": canonical_sha256(candidates),
    }
    full = np.array([[1.0, 0.6, 0.3], [0.6, 1.0, 0.4], [0.3, 0.4, 1.0]])
    keep = [IDS.index(c) for c in scoring_ids]
    rel = full[np.ix_(keep, keep)]
    arrays = {"relation": rel, "classification": rel, "association": rel}
    score_manifest = {"version": "fixture-scoring-v1", "ids": list(scoring_ids), "catalog_version": "fixture",
                      "weights": {"classification": 0.5, "association": 0.5},
                      "display": {"scale": 100, "decimals": 2}, "ranking": {"compare_decimals": 6},
                      "content_sha256": content_sha256(scoring_ids, arrays)}
    private_dir = root / "releases" / release_id
    private_dir.mkdir(parents=True)
    np.savez_compressed(private_dir / "score-table.npz", ids=np.array(scoring_ids), **arrays)
    (private_dir / "score-manifest.json").write_text(json.dumps(score_manifest), encoding="utf-8")
    private = {
        "manifestVersion": "release-private-v1", "releaseId": release_id,
        "publicManifestSha256": canonical_sha256(public),
        "scoreTable": {"file": "score-table.npz", "manifestFile": "score-manifest.json",
                       "version": "fixture-scoring-v1", "contentSha256": score_manifest["content_sha256"]},
        "recognition": {"version": "fixture-recognition-v1", "min_top1_p": 0.2, "success_min_p": 0.5},
        "answers": {c: {"displayNameKo": dict(zip(IDS, ("사과", "배", "바나나")))[c], "daily": True}
                    for c in scoring_ids},
    }
    (private_dir / "private-manifest.json").write_text(json.dumps(private, ensure_ascii=False), encoding="utf-8")
    return public, f"releases/{release_id}/private-manifest.json"


class StubJudge:
    """Replaces the judge with the fixture's synthetic results; fails if a step should not judge."""

    RESULTS = {
        "recognized": ("recognized", None, 0.3872, "38.72"),
        "solved": ("solved", None, 0.834, "83.40"),
        "deferred": ("deferred", "low_confidence", None, None),
        "unsupported_candidate": ("deferred", "unsupported_candidate", None, None),
    }

    def __init__(self):
        self.next: str | None = None
        self.delay = 0.0
        self.calls = 0

    def __call__(self, table, rules, answer_id, top3):
        if self.next is None:
            raise AssertionError("judge must not run for this step")
        self.calls += 1
        time.sleep(self.delay)
        status, reason, mixed, text = self.RESULTS[self.next]
        mix = MixResult(answer_id, mixed, float(text), text, ()) if mixed is not None else None
        return Judgement(status, reason, mix)


class SubmissionApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = prepare_database(os.environ.get("TEST_DATABASE_URL", DEFAULT_URL))
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.settings = Settings(database_url=cls.engine.url.render_as_string(hide_password=False),
                                artifact_root=cls.root)
        with cls.engine.begin() as conn:
            conn.execute(sa.text(f"TRUNCATE {GAME_TABLES}, puzzles, release_bundles"))
        from sqlalchemy.orm import Session
        with Session(cls.engine) as db:
            for release_id, puzzle_id, day, scoring in (
                    ("fixture-release-v1", "fixture-puzzle-v1", dt.date(2026, 9, 22), IDS),
                    ("fixture-release-partial", "fixture-puzzle-partial", dt.date(2026, 9, 21), ("apple", "pear")),
                    ("fixture-release-future", "fixture-puzzle-future", dt.date(2026, 9, 23), IDS)):
                public, key = write_release(cls.root, release_id, scoring)
                register(db, cls.root, public, key, NOW)
                db.flush()
                opens = dt.datetime.combine(day, dt.time(0), dt.timezone(dt.timedelta(hours=9)))
                db.add(Puzzle(puzzle_id=puzzle_id, service_date=day, release_id=release_id,
                              answer_category_id="apple", answer_display_name_ko="사과", opens_at=opens,
                              state="published"))
            db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.tmp.cleanup()

    def setUp(self):
        with self.engine.begin() as conn:
            conn.execute(sa.text(f"TRUNCATE {GAME_TABLES}"))
        self.judge = StubJudge()
        self.app = create_app(self.settings, engine=self.engine, judge_fn=self.judge, clock=lambda: NOW)
        self.client = self.new_client()

    def new_client(self, cookies=None) -> TestClient:
        client = TestClient(self.app)
        if cookies is None:
            self.assertEqual(client.post("/api/sessions").status_code, 201)
        else:
            client.cookies.update(cookies)
        return client

    # helpers -------------------------------------------------------------------------------------
    def body(self, overrides=None, puzzle_release="fixture-release-v1") -> dict:
        body = copy.deepcopy(FIXTURE["baseRequest"])
        body["releaseId"] = puzzle_release
        body.update(copy.deepcopy(overrides or {}))
        return body

    def submit(self, body, puzzle="fixture-puzzle-v1", client=None):
        return (client or self.client).post(f"/api/puzzles/{puzzle}/submissions", json=body)

    def progress(self, puzzle="fixture-puzzle-v1", client=None, **params):
        res = (client or self.client).get(f"/api/puzzles/{puzzle}/progress", params=params)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def counts(self) -> tuple[int, int]:
        with self.engine.connect() as conn:
            return (conn.execute(sa.text("SELECT count(*) FROM submissions")).scalar(),
                    conn.execute(sa.text("SELECT count(*) FROM submission_requests")).scalar())

    def check(self, res, expect: dict, canon: dict, responses: dict):
        data = res.json()
        if "http" in expect:
            self.assertEqual(res.status_code, expect["http"], res.text)
        if "errorCode" in expect:
            self.assertEqual(data["error"]["code"], expect["errorCode"])
            self.assertIn("requestId", data)
        if "reuse" in expect:
            self.assertEqual(data["reuse"], expect["reuse"])
        if "canonicalSubmissionId" in expect:  # fixture IDs are placeholders: bind on first sight
            bound = canon.setdefault(expect["canonicalSubmissionId"], data["submissionId"])
            self.assertEqual(data["submissionId"], bound)
        result = data.get("result", {})
        for key in ("status", "displayScore", "attemptNumber", "reason", "solved"):
            if key in expect:
                self.assertEqual(result[key], expect[key], key)
        if expect.get("answerAbsent"):
            self.assertNotIn("answer", result)
            self.assertNotIn("answer", data.get("progress", {}))
        if "answerEquals" in expect:
            self.assertEqual(result["answer"], expect["answerEquals"])
        if "resultEquals" in expect:
            self.assertEqual(result, responses[expect["resultEquals"].split(".")[1]]["result"])
        if "collectionState" in expect:
            self.assertEqual(data["collection"], {"state": expect["collectionState"],
                                                  "consentRevision": expect["consentRevision"]})
        if "attemptCount" in expect:
            self.assertEqual(self.progress()["progress"]["attemptCount"], expect["attemptCount"])
        if "storedResults" in expect:
            self.assertEqual(self.counts(), (expect["storedResults"], expect["storedRequests"]))

    def run_case(self, case: dict):
        canon, responses = {}, {k: v for k, v in FIXTURE["responses"].items()}
        for step in case["steps"]:
            if "operation" in step:
                self.skipTest(f"{step['operation']}: collection is disabled (collection-disabled-v0)")
            self.judge.next = step.get("stubResult")
            if step.get("method") == "GET":
                res = self.client.get(step["path"])
            else:
                res = self.submit(self.body(step["overrides"]))
            self.check(res, step["expect"], canon, responses)

    # fixture cases -------------------------------------------------------------------------------
    def test_fixture_cases(self):
        for case in FIXTURE["cases"]:
            if "parallelRequests" in case:
                continue
            with self.subTest(case["name"]):
                self.setUp()
                setup = case.get("setup", {})
                if "consentHistory" in setup:  # current revision 2, disabled
                    with self.engine.begin() as conn:
                        conn.execute(sa.text("UPDATE anonymous_sessions SET consent_revision = 2"))
                self.run_case(case)

    def test_fixture_concurrent_same_drawing(self):
        case = next(c for c in FIXTURE["cases"] if c["name"] == "two_concurrent_ids_same_drawing")
        self.judge.next, self.judge.delay = case["stubResult"], 0.3
        cookies = dict(self.client.cookies)
        results = [None, None]
        barrier = threading.Barrier(2)

        def run(i, req):
            client = self.new_client(cookies)
            barrier.wait()
            results[i] = self.submit(self.body(req["overrides"]), client=client)

        threads = [threading.Thread(target=run, args=(i, r)) for i, r in enumerate(case["parallelRequests"])]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        expect = case["expect"]
        self.assertCountEqual([r.status_code for r in results], expect["httpCodesUnordered"])
        self.assertCountEqual([r.json()["reuse"] for r in results], expect["reusesUnordered"])
        self.assertEqual(len({r.json()["submissionId"] for r in results}), 1)
        self.assertEqual(self.judge.calls, 1)
        self.assertEqual(self.progress()["progress"]["attemptCount"], expect["attemptCount"])
        self.assertEqual(self.counts(), (expect["storedResults"], expect["storedRequests"]))

    # beyond the fixture --------------------------------------------------------------------------
    def test_concurrent_different_drawings_get_distinct_attempts(self):
        self.judge.next, self.judge.delay = "recognized", 0.2
        cookies = dict(self.client.cookies)
        results = []
        barrier = threading.Barrier(2)

        def run(i):
            client = self.new_client(cookies)
            barrier.wait()
            results.append(self.submit(self.body({"submissionId": str(uuid.uuid4()), "drawingHash": f"{i}" * 64}),
                                       client=client))

        threads = [threading.Thread(target=run, args=(i,)) for i in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(sorted(r.json()["result"]["attemptNumber"] for r in results), [1, 2])
        self.assertEqual(self.progress()["progress"]["attemptCount"], 2)

    def test_real_judge_success_and_unsupported(self):
        app = create_app(self.settings, engine=self.engine, clock=lambda: NOW)
        client = TestClient(app)
        client.post("/api/sessions")
        low = self.body({"top3": [{"categoryId": "pear", "p": 0.15}, {"categoryId": "apple", "p": 0.1},
                                  {"categoryId": "banana", "p": 0.05}]})
        res = client.post("/api/puzzles/fixture-puzzle-v1/submissions", json=low)
        self.assertEqual((res.json()["result"]["status"], res.json()["result"]["reason"]),
                         ("deferred", "low_confidence"))
        near = self.body({"submissionId": str(uuid.uuid4()), "drawingHash": "c" * 64,
                          "top3": [{"categoryId": "pear", "p": 0.6}, {"categoryId": "apple", "p": 0.3},
                                   {"categoryId": "banana", "p": 0.1}]})
        result = client.post("/api/puzzles/fixture-puzzle-v1/submissions", json=near).json()["result"]
        # q = .6/.3/.1 -> .6*.6 + .3*1 + .1*.3 = .69
        self.assertEqual((result["status"], result["displayText"], result["attemptNumber"]), ("recognized", "69.00", 1))
        hit = self.body({"submissionId": str(uuid.uuid4()), "drawingHash": "d" * 64})
        data = client.post("/api/puzzles/fixture-puzzle-v1/submissions", json=hit).json()
        self.assertEqual(data["result"]["status"], "solved")
        self.assertEqual(data["result"]["answer"], {"categoryId": "apple", "displayNameKo": "사과"})
        self.assertEqual(data["progress"]["state"], "solved")

        partial = self.body(puzzle_release="fixture-release-partial")
        res = client.post("/api/puzzles/fixture-puzzle-partial/submissions", json=partial)
        self.assertEqual(res.status_code, 201)
        self.assertEqual((res.json()["result"]["status"], res.json()["result"]["reason"]),
                         ("deferred", "unsupported_candidate"))
        with self.engine.connect() as conn:
            details = conn.execute(sa.text("SELECT details FROM submission_score_details d JOIN submissions s "
                                           "USING (submission_id) WHERE s.drawing_hash = :h"), {"h": "c" * 64}).scalar()
        self.assertAlmostEqual(details["mixed"], 0.69)
        self.assertEqual([c["relationRank"] for c in details["candidates"]], [2, 1, 3])

    def test_input_validation(self):
        cases = {
            "unsorted": ({"top3": [{"categoryId": "pear", "p": 0.2}, {"categoryId": "apple", "p": 0.5},
                                   {"categoryId": "banana", "p": 0.1}]}, "INVALID_TOP3"),
            "tie_order": ({"top3": [{"categoryId": "pear", "p": 0.3}, {"categoryId": "apple", "p": 0.3},
                                    {"categoryId": "banana", "p": 0.1}]}, "INVALID_TOP3"),
            "sum_over_one": ({"top3": [{"categoryId": "apple", "p": 0.6}, {"categoryId": "pear", "p": 0.3},
                                       {"categoryId": "banana", "p": 0.2}]}, "INVALID_TOP3"),
            "bool_p": ({"top3": [{"categoryId": "apple", "p": True}, {"categoryId": "pear", "p": 0},
                                 {"categoryId": "banana", "p": 0}]}, "INVALID_TOP3"),
            "duplicate": ({"top3": [{"categoryId": "apple", "p": 0.5}, {"categoryId": "apple", "p": 0.2},
                                    {"categoryId": "banana", "p": 0.1}]}, "INVALID_TOP3"),
            "extra_field": ({"answer": "apple"}, "INVALID_REQUEST"),
            "bad_hash": ({"drawingHash": "A" * 64}, "INVALID_REQUEST"),
        }
        for name, (overrides, code) in cases.items():
            with self.subTest(name):
                res = self.submit(self.body(overrides))
                self.assertEqual((res.status_code, res.json()["error"]["code"]), (422, code))
                self.assertNotIn("apple", json.dumps(res.json()["error"]))  # no body echo
        self.assertEqual(self.counts(), (0, 0))

    def test_versions_session_origin_and_visibility(self):
        res = self.submit(self.body({"modelVersion": "other-model"}))
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (409, "VERSION_MISMATCH"))
        anon = TestClient(self.app)
        res = self.submit(self.body(), client=anon)
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (401, "SESSION_REQUIRED"))
        res = self.client.post("/api/puzzles/fixture-puzzle-v1/submissions", json=self.body(),
                               headers={"Origin": "https://evil.example"})
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (403, "ORIGIN_NOT_ALLOWED"))
        self.assertEqual(self.client.get("/api/puzzles/fixture-puzzle-future").status_code, 404)
        today = self.client.get("/api/puzzles/today").json()
        self.assertEqual((today["puzzleId"], today["serviceDate"]), ("fixture-puzzle-v1", "2026-09-22"))
        self.assertNotIn("apple", {k: v for k, v in today.items() if k != "release"}.__repr__())
        self.assertNotIn("recognition", json.dumps(today))
        self.assertEqual(self.client.post("/api/sessions").status_code, 200)  # valid cookie is reused

    def test_progress_pagination_excludes_deferred(self):
        self.judge.next = "recognized"
        for i in range(12):
            self.submit(self.body({"submissionId": str(uuid.uuid4()), "drawingHash": f"{i:064x}"}))
        self.judge.next = "deferred"
        self.submit(self.body({"submissionId": str(uuid.uuid4()), "drawingHash": "e" * 64}))
        first = self.progress()
        self.assertEqual([i["result"]["attemptNumber"] for i in first["items"]], list(range(12, 2, -1)))
        self.assertEqual(first["nextBeforeAttemptNumber"], 3)
        second = self.progress(beforeAttemptNumber=3)
        self.assertEqual([i["result"]["attemptNumber"] for i in second["items"]], [2, 1])
        self.assertIsNone(second["nextBeforeAttemptNumber"])
        self.assertEqual(first["progress"]["bestSubmissionId"], first["items"][0]["submissionId"])  # tie -> latest
        self.assertEqual(self.client.get("/api/puzzles/fixture-puzzle-v1/progress?limit=51").status_code, 422)

    def test_failure_before_commit_leaves_nothing(self):
        self.judge.next = "recognized"
        client = TestClient(self.app, raise_server_exceptions=False)
        client.cookies.update(dict(self.client.cookies))
        with mock.patch.object(submissions_repo, "add_request", side_effect=RuntimeError("boom")):
            res = self.submit(self.body(), client=client)
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (500, "INTERNAL_ERROR"))
        self.assertEqual(self.counts(), (0, 0))
        self.assertEqual(self.progress()["progress"]["attemptCount"], 0)
        self.assertEqual(self.submit(self.body()).status_code, 201)  # same ID works afterwards

    def test_release_unavailable_only_blocks_new_judgements(self):
        self.judge.next = "recognized"
        self.assertEqual(self.submit(self.body()).status_code, 201)
        table = self.root / "releases/fixture-release-v1/score-table.npz"
        moved = table.with_suffix(".bak")
        table.rename(moved)
        try:
            app = create_app(self.settings, engine=self.engine, judge_fn=self.judge, clock=lambda: NOW)
            client = TestClient(app)
            client.cookies.update(dict(self.client.cookies))
            self.assertEqual(self.submit(self.body(), client=client).json()["reuse"], "request_retry")
            res = self.submit(self.body({"submissionId": str(uuid.uuid4()), "drawingHash": "f" * 64}), client=client)
            self.assertEqual((res.status_code, res.json()["error"]["code"], res.json()["error"]["retryable"]),
                             (503, "RELEASE_UNAVAILABLE", True))
        finally:
            moved.rename(table)


if __name__ == "__main__":
    unittest.main()
