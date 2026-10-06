"""Collection, review and export on a real PostgreSQL (docs/database-schema-v1.md §5-6, docs/mlops-v1.md).

Consent revisions, sampling, upload grant -> file -> verification, withdrawal and deletion, the reconcile worker,
review batches and the training export. Skipped when the test DB is unreachable (see test_submissions.py).
"""
from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_submissions import (DEFAULT_URL, FIXTURE, GAME_TABLES, NOW, StubJudge,  # noqa: E402
                              prepare_database, write_release)

import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import cli  # noqa: E402
from app.core.collection_config import Sampling  # noqa: E402
from app.core.settings import Settings  # noqa: E402
from app.db.models import Puzzle  # noqa: E402
from app.db.session import make_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.collections import drawing, export, review  # noqa: E402
from app.modules.releases.service import register  # noqa: E402
from app.storage.object_store import open_store  # noqa: E402
from app.workers import collection_reconcile  # noqa: E402

STROKES = [[[10, 10], [100, 120], [300, 90]], [[500, 500]]]


class Clock:
    def __init__(self, now: dt.datetime):
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now


class CollectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = prepare_database(os.environ.get("TEST_DATABASE_URL", DEFAULT_URL))
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        base = Settings(database_url=cls.engine.url.render_as_string(hide_password=False), artifact_root=cls.root)
        cls.settings = dataclasses.replace(base, collection=dataclasses.replace(
            base.collection, enabled=True, sampling=Sampling("sampling-test", 1.0, 0.0, 0.0)))
        cls.notice = cls.settings.collection.notice_version
        with cls.engine.begin() as conn:
            conn.execute(sa.text(f"TRUNCATE {GAME_TABLES}, puzzles, release_bundles"))
        with Session(cls.engine) as db:
            public, key = write_release(cls.root, "fixture-release-v1")
            register(db, cls.root, public, key, NOW)
            db.flush()
            db.add(Puzzle(puzzle_id="fixture-puzzle-v1", service_date=dt.date(2026, 9, 22),
                          release_id="fixture-release-v1", answer_category_id="apple", answer_display_name_ko="사과",
                          opens_at=dt.datetime(2026, 9, 22, tzinfo=dt.timezone(dt.timedelta(hours=9))),
                          state="published"))
            db.commit()
        cls.factory = make_session_factory(cls.engine)
        cls.store = open_store(cls.root, "local", cls.settings.collection.storage_root)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.tmp.cleanup()

    def setUp(self):
        with self.engine.begin() as conn:
            conn.execute(sa.text(f"TRUNCATE {GAME_TABLES}"))
        self.judge = StubJudge()
        self.clock = Clock(NOW)
        self.app = create_app(self.settings, engine=self.engine, judge_fn=self.judge, clock=self.clock)
        self.client = self.client_for_new_session()

    def client_for_new_session(self) -> TestClient:
        client = TestClient(self.app)
        self.assertEqual(client.post("/api/sessions").status_code, 201)
        return client

    # helpers ---------------------------------------------------------------------------------------------------------
    def consent(self, enabled: bool, expected: int, client=None, policy=None):
        body = {"expectedRevision": expected, "enabled": enabled}
        if enabled:
            body["policyVersion"] = policy or self.notice
        return (client or self.client).put("/api/collection-consent", json=body)

    def file_bytes(self, strokes=STROKES) -> bytes:
        return drawing.serialise(strokes, 1024)

    def submit(self, status="solved", data: bytes | None = None, client=None, revision=1) -> dict:
        self.judge.next = status
        body = json.loads(json.dumps(FIXTURE["baseRequest"]))
        body.update(submissionId=str(uuid.uuid4()), collectionConsentRevision=revision,
                    drawingHash=hashlib.sha256(data if data is not None else self.file_bytes()).hexdigest())
        res = (client or self.client).post("/api/puzzles/fixture-puzzle-v1/submissions", json=body)
        self.assertIn(res.status_code, (200, 201), res.text)
        return res.json()

    def grant(self, submission_id: str, revision=1, client=None) -> dict:
        res = (client or self.client).post(f"/api/submissions/{submission_id}/drawing-upload",
                                           json={"consentRevision": revision})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def complete(self, submission_id: str, grant: dict, revision=1):
        return self.client.post(f"/api/submissions/{submission_id}/drawing-complete",
                                json={"sampleId": grant["sampleId"], "uploadId": grant["uploadId"],
                                      "consentRevision": revision})

    def upload_and_verify(self, data: bytes | None = None) -> tuple[str, dict]:
        self.assertEqual(self.consent(True, 0).status_code, 200)
        data = data if data is not None else self.file_bytes()
        sub = self.submit(data=data)
        grant = self.grant(sub["submissionId"])["grant"]
        self.assertEqual(self.client.put(grant["url"], content=data).status_code, 204)
        res = self.complete(sub["submissionId"], grant)
        self.assertEqual((res.status_code, res.json()["collection"]["state"]), (200, "verified"), res.text)
        return sub["submissionId"], grant

    def sample(self) -> dict:
        with self.engine.connect() as conn:
            return dict(conn.execute(sa.text("SELECT * FROM drawing_samples")).mappings().one())

    # consent ---------------------------------------------------------------------------------------------------------
    def test_consent_revisions_resend_and_conflict(self):
        res = self.consent(True, 0)
        self.assertEqual(res.json(), {"enabled": True, "policyVersion": self.notice,
                                      "collection": {"state": "eligible", "consentRevision": 1}})
        self.assertEqual(self.consent(True, 0).json()["collection"]["consentRevision"], 1)  # lost-response resend
        res = self.consent(False, 0)  # stale revision, different value
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (409, "CONSENT_REVISION_CONFLICT"))
        res = self.consent(True, 1, policy="collection-notice-old")
        self.assertEqual(res.json()["error"]["code"], "CONSENT_POLICY_OUTDATED")
        self.assertEqual(self.consent(False, 1).json()["collection"], {"state": "not_consented", "consentRevision": 2})
        with self.engine.connect() as conn:
            history = conn.execute(sa.text("SELECT revision, enabled FROM collection_consents ORDER BY revision")).all()
        self.assertEqual([tuple(r) for r in history], [(0, False), (1, True), (2, False)])
        self.assertEqual(self.client.post("/api/sessions").json()["collection"],
                         {"state": "not_consented", "consentRevision": 2})

    def test_consent_is_refused_while_collection_is_off(self):
        off = dataclasses.replace(self.settings, collection=dataclasses.replace(self.settings.collection,
                                                                                enabled=False))
        client = TestClient(create_app(off, engine=self.engine, judge_fn=self.judge, clock=self.clock))
        client.post("/api/sessions")
        res = client.put("/api/collection-consent", json={"expectedRevision": 0, "enabled": True,
                                                          "policyVersion": self.notice})
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (409, "COLLECTION_DISABLED"))
        today = client.get("/api/puzzles/today").json()["collectionPolicy"]
        self.assertEqual(today, {"version": "collection-disabled-v0", "enabled": False})

    # selection -------------------------------------------------------------------------------------------------------
    def test_selection_is_recorded_once_and_independent_of_consent(self):
        solved = self.submit("solved", revision=0)  # not consented, still selected
        self.assertEqual(solved["collection"]["state"], "not_consented")
        with self.engine.connect() as conn:
            rows = conn.execute(sa.text("SELECT status, collection_policy_version, collection_selection "
                                        "FROM submissions")).all()
        self.assertEqual([tuple(r) for r in rows], [("solved", "sampling-test", "success_sample")])
        self.consent(True, 0)
        self.assertEqual(self.client.get(f"/api/puzzles/fixture-puzzle-v1/submissions/by-request/"
                                         f"{solved['requestSubmissionId']}").json()["collection"]["state"], "eligible")

    def test_unselected_drawing_gets_no_grant(self):
        self.consent(True, 0)
        sub = self.submit("recognized")  # failure_rate 0 in this config
        out = self.grant(sub["submissionId"])
        self.assertEqual((out["grant"], out["collection"]["state"]), (None, "not_selected"))

    # upload ----------------------------------------------------------------------------------------------------------
    def test_upload_verifies_the_exact_drawing_and_never_touches_the_game(self):
        submission_id, grant = self.upload_and_verify()
        s = self.sample()
        self.assertEqual((s["state"], s["stroke_count"], s["point_count"]), ("verified", 2, 4))
        self.assertEqual(self.store.get(s["verified_object_key"]), self.file_bytes())
        self.assertEqual(self.store.list("tmp"), [])  # temporary copy removed
        progress = self.client.get("/api/puzzles/fixture-puzzle-v1/progress").json()["progress"]
        self.assertEqual((progress["state"], progress["attemptCount"]), ("solved", 1))
        again = self.grant(submission_id)  # already verified: no second original
        self.assertEqual((again["grant"], again["collection"]["state"]), (None, "verified"))

    def test_wrong_file_is_rejected_and_can_be_retried(self):
        self.consent(True, 0)
        good = self.file_bytes()
        sub = self.submit(data=good)
        grant = self.grant(sub["submissionId"])["grant"]
        other = self.file_bytes([[[1, 1], [2, 2]]])
        self.assertEqual(self.client.put(grant["url"], content=other).status_code, 204)
        res = self.complete(sub["submissionId"], grant)
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (422, "INVALID_DRAWING"))
        self.assertEqual((self.sample()["state"], self.sample()["last_error_code"]), ("upload_failed", "HASH_MISMATCH"))
        retry = self.grant(sub["submissionId"])["grant"]
        self.assertNotEqual(retry["uploadId"], grant["uploadId"])
        self.assertEqual(self.client.put(grant["url"], content=good).status_code, 410)  # old grant is dead
        self.assertEqual(self.client.put(retry["url"], content=good).status_code, 204)
        self.assertEqual(self.complete(sub["submissionId"], retry).json()["collection"]["state"], "verified")

    def test_grant_is_reused_while_valid_and_renewed_after_expiry(self):
        self.consent(True, 0)
        sub = self.submit()
        first = self.grant(sub["submissionId"])["grant"]
        self.assertEqual(self.grant(sub["submissionId"])["grant"]["uploadId"], first["uploadId"])
        self.clock.now = NOW + dt.timedelta(seconds=self.settings.collection.upload.grant_ttl_seconds + 1)
        self.assertEqual(self.client.put(first["url"], content=self.file_bytes()).status_code, 410)
        second = self.grant(sub["submissionId"])["grant"]
        self.assertNotEqual(second["uploadId"], first["uploadId"])

    def test_other_sessions_cannot_use_my_submission(self):
        self.consent(True, 0)
        sub = self.submit()
        grant = self.grant(sub["submissionId"])["grant"]
        other = self.client_for_new_session()
        self.consent(True, 0, client=other)
        res = other.post(f"/api/submissions/{sub['submissionId']}/drawing-upload", json={"consentRevision": 1})
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (404, "SUBMISSION_NOT_FOUND"))
        self.assertEqual(other.put(grant["url"], content=self.file_bytes()).status_code, 404)

    def test_drawing_limits(self):
        limits = self.settings.collection.upload
        for bad, code in ((b"{}", "wrong_fields"), (b"not json", "not_json"),
                          (self.file_bytes([[[0, 2000]]]), "point"),
                          (self.file_bytes([[[1, 1]]] * (limits.max_strokes + 1)), "stroke_count"),
                          (json.dumps({"drawingVersion": "strokes-v1", "coordinateMax": 1024,
                                       "brushVersion": "pen-v1", "strokes": [[[1, 1]]]}).encode(), "not_canonical")):
            with self.subTest(code):
                with self.assertRaises(drawing.InvalidDrawing) as ctx:
                    drawing.check(bad, limits)
                self.assertEqual(str(ctx.exception), code)

    # withdrawal and clean-up ---------------------------------------------------------------------------------------
    def test_withdrawal_deletes_files_and_reconsent_never_restores(self):
        submission_id, _ = self.upload_and_verify()
        key = self.sample()["verified_object_key"]
        self.assertEqual(self.consent(False, 1).status_code, 200)
        self.assertEqual(self.sample()["state"], "delete_pending")
        counts = collection_reconcile.run(self.factory, self.settings, self.store, NOW)
        self.assertEqual(counts.get("samples_deleted"), 1)
        self.assertIsNone(self.store.get(key))
        self.assertEqual(self.sample()["state"], "deleted")
        self.assertEqual(self.consent(True, 2).status_code, 200)
        out = self.grant(submission_id, revision=3)
        self.assertEqual((out["grant"], out["collection"]["state"]), (None, "deleted"))

    def test_withdrawal_removes_derived_copies_and_reports_datasets(self):
        self.upload_and_verify()
        sample_id = str(self.sample()["sample_id"])
        batch = self.root / cli.COLLECTED / "review" / "batch-derived"
        review.export_batch(self.factory, self.settings, self.store, batch, 10, False, NOW)
        dataset = self.root / "data/datasets/user-derived"
        dataset.mkdir(parents=True)
        (dataset / "samples.json").write_text(json.dumps([{"sampleId": sample_id, "group": "g"}]), encoding="utf-8")
        self.consent(False, 1)
        counts = collection_reconcile.run(self.factory, self.settings, self.store, NOW)
        self.assertFalse(batch.exists())
        self.assertEqual((counts.get("review_batches_removed"), counts.get("datasets_with_deleted_drawings")),
                         (1, ["user-derived"]))
        self.assertTrue(dataset.exists())  # "report": a person decides, the run that used it stays reproducible
        delete = dataclasses.replace(self.settings, collection=dataclasses.replace(self.settings.collection,
                                                                                   derived_datasets="delete"))
        counts = collection_reconcile.run(self.factory, delete, self.store, NOW)
        self.assertEqual(counts.get("datasets_removed"), 1)
        self.assertFalse(dataset.exists())

    def test_reconcile_expires_grants_and_removes_orphans(self):
        self.consent(True, 0)
        sub = self.submit()
        self.grant(sub["submissionId"])
        self.store.put("tmp/not-an-upload.json", b"x")
        self.store.put(f"verified/{uuid.uuid4()}/stray.json", b"x")
        later = NOW + dt.timedelta(hours=1)
        counts = collection_reconcile.run(self.factory, self.settings, self.store, later)
        self.assertEqual((counts.get("uploads_expired"), counts.get("orphan_tmp_removed"),
                          counts.get("orphan_verified_removed")), (1, 1, 1))
        self.assertEqual((self.sample()["state"], self.sample()["last_error_code"]), ("upload_failed", "UPLOAD_EXPIRED"))

    def test_retention_moves_old_verified_samples_to_deletion(self):
        self.upload_and_verify()
        days = self.settings.collection.verified_days
        counts = collection_reconcile.run(self.factory, self.settings, self.store, NOW + dt.timedelta(days=days + 1))
        self.assertEqual((counts.get("retention_expired"), counts.get("samples_deleted")), (1, 1))
        self.assertEqual(self.sample()["state"], "deleted")

    # review and export ---------------------------------------------------------------------------------------------
    def test_review_batch_import_and_training_export(self):
        self.upload_and_verify()
        batch = self.root / "review" / f"batch-{uuid.uuid4().hex[:8]}"
        out = review.export_batch(self.factory, self.settings, self.store, batch, 10, False, NOW)
        self.assertEqual(out["count"], 1)
        self.assertIn("<svg", (batch / "index.html").read_text(encoding="utf-8"))
        with open(batch / "items.csv", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual((rows[0]["decision"], rows[0]["category_id"]), ("", ""))  # nothing pre-filled

        bad = batch / "bad.csv"
        with open(bad, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=review.FIELDS)
            w.writeheader()
            w.writerow(rows[0] | {"decision": "accepted", "category_id": "not-a-category"})
        with self.assertRaises(SystemExit):
            review.import_batch(self.factory, bad, "tester", NOW)

        with open(batch / "items.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=review.FIELDS)
            w.writeheader()
            w.writerow(rows[0] | {"decision": "accepted", "category_id": "apple"})
        self.assertEqual(review.import_batch(self.factory, batch / "items.csv", "tester", NOW)["accepted"], 1)
        self.assertEqual(review.export_batch(self.factory, self.settings, self.store, batch.with_name("next"), 10,
                                             False, NOW)["count"], 0)  # reviewed: not offered again

        exports = self.root / cli.COLLECTED / "exports"  # where mlops-status looks
        result = export.export_training(self.factory, self.settings, self.store, exports, NOW)
        self.assertEqual(result["count"], 1)
        line = json.loads((Path(result["out"]) / "samples.jsonl").read_text(encoding="utf-8"))
        self.assertEqual((line["label"], line["strokes"]), ("apple", STROKES))
        self.assertNotIn(str(self.sample()["session_id"]), json.dumps(line))  # only a salted group hash
        manifest = json.loads((Path(result["out"]) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sampleIds"], [line["sampleId"]])

        with self.factory() as db:
            status = cli.mlops_status(db, self.settings, NOW)
        self.assertEqual((status["exportable"], status["newAcceptedSinceLastExport"]), (1, 0))

        self.consent(False, 1)  # withdrawn after review: never exported again
        later = export.export_training(self.factory, self.settings, self.store, exports, NOW + dt.timedelta(seconds=1))
        self.assertEqual(later["count"], 0)


if __name__ == "__main__":
    unittest.main()
