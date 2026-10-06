"""Collection use cases (docs/api-contract-v1.md §8, docs/database-schema-v1.md §5, docs/mlops-v1.md §3).

- Selection is decided once per canonical submission, independent of consent, and stored with the submission.
- Consent changes append a history row and bump the session's revision. Withdrawal moves every sample of the session
  to `delete_pending` at once; files are removed by the reconcile worker.
- `verified` means the server checked the file (format, limits, drawing hash). It is not a label review.
- Uploading or verifying never changes a game's score, attempts or success.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid

from sqlalchemy.orm import Session

from app.core.collection_config import DISABLED_POLICY, CollectionConfig
from app.core.errors import ApiError
from app.core.settings import Settings
from app.db.models import AnonymousSession, CollectionConsent, DrawingSample, DrawingUpload, GameSession, Submission
from app.modules.sessions import repository as sessions_repo
from app.modules.sessions.schemas import CollectionOut, SessionContext
from app.storage.object_store import ObjectExists, ObjectStore

from . import drawing, repository
from .repository import DELETION_STATES
from .schemas import CompleteIn, CompleteOut, ConsentIn, ConsentOut, UploadGrant, UploadIn, UploadOut

UPLOAD_PATH = "/api/collection-uploads/{upload_id}"


# selection ----------------------------------------------------------------------------------------------------------
def select(config: CollectionConfig, submission_id: uuid.UUID, status: str) -> tuple[str, str]:
    """(policy version, selection) recorded on a new submission. Deterministic: same ID, same rule, same answer."""
    if not config.enabled:
        return DISABLED_POLICY, "not_selected"
    s = config.sampling
    rate = {"solved": s.success_rate, "recognized": s.failure_rate, "deferred": s.deferred_rate}[status]
    u = int.from_bytes(hashlib.sha256(f"{s.version}:{submission_id}".encode()).digest()[:8], "big") / 2**64
    if u >= rate:
        return s.version, "not_selected"
    return s.version, "success_sample" if status == "solved" else "failure_sample"


# views --------------------------------------------------------------------------------------------------------------
def policy_view(config: CollectionConfig) -> tuple[str, bool]:
    """(version, enabled) shown with today's puzzle: the notice a consent must name."""
    return (config.notice_version, True) if config.enabled else (DISABLED_POLICY, False)


def submission_view(db: Session, session: AnonymousSession | SessionContext, sub: Submission) -> CollectionOut:
    """Current state for one submission; deletion states win over eligibility (api-contract §8)."""
    sample = repository.get_sample_for_submission(db, sub.submission_id)
    revision = session.consent_revision
    if sample is not None and sample.state in DELETION_STATES:
        state = sample.state
    elif not session.collection_enabled:
        state = "not_consented"
    elif sub.collection_selection == "not_selected":
        state = "not_selected"
    else:
        state = sample.state if sample is not None else "eligible"
    return CollectionOut(state=state, consentRevision=revision)


def _session_out(session: AnonymousSession) -> CollectionOut:
    return CollectionOut(state="eligible" if session.collection_enabled else "not_consented",
                         consentRevision=session.consent_revision)


def _lock_session(db: Session, auth: SessionContext, now: dt.datetime) -> AnonymousSession:
    session = sessions_repo.lock(db, auth.session_id)
    if session is None or session.expires_at <= now:
        raise ApiError(401, "SESSION_EXPIRED", "세션이 만료됐어요. 페이지를 새로고침해주세요.")
    return session


def _owned_submission(db: Session, session_id: uuid.UUID, submission_id: uuid.UUID) -> Submission:
    sub = db.get(Submission, submission_id)
    game = db.get(GameSession, sub.game_session_id) if sub is not None else None
    if game is None or game.session_id != session_id:
        raise ApiError(404, "SUBMISSION_NOT_FOUND", "제출 결과를 찾을 수 없어요.")
    return sub


def _conflict() -> ApiError:
    return ApiError(409, "CONSENT_REVISION_CONFLICT", "수집 선택이 다른 곳에서 바뀌었어요. 다시 확인해주세요.")


# consent ------------------------------------------------------------------------------------------------------------
def change_consent(db: Session, settings: Settings, auth: SessionContext, req: ConsentIn,
                   now: dt.datetime) -> ConsentOut:
    config = settings.collection
    policy = req.policyVersion if req.enabled else None
    if req.enabled:
        if not config.enabled:
            raise ApiError(409, "COLLECTION_DISABLED", "지금은 그림을 수집하지 않아요.")
        if req.policyVersion != config.notice_version:
            raise ApiError(409, "CONSENT_POLICY_OUTDATED", "안내 내용이 바뀌었어요. 새로고침 후 다시 확인해주세요.")
    session = _lock_session(db, auth, now)
    if (session.collection_enabled, session.collection_policy_version) == (req.enabled, policy):
        out = ConsentOut(enabled=req.enabled, policyVersion=policy, collection=_session_out(session))
        db.commit()  # lost-response resend: the value already matches
        return out
    if req.expectedRevision != session.consent_revision:
        raise _conflict()
    repository.ensure_consent_row(db, session.session_id, session.consent_revision, session.collection_enabled,
                                  session.collection_policy_version, session.created_at)
    revision = session.consent_revision + 1
    repository.add_consent(db, CollectionConsent(session_id=session.session_id, revision=revision,
                                                 enabled=req.enabled, policy_version=policy, changed_at=now))
    session.consent_revision, session.collection_enabled, session.collection_policy_version = \
        revision, req.enabled, policy
    if not req.enabled:  # withdrawal: out of training at once, files removed by the reconcile worker
        samples = repository.lock_samples_of_session(
            db, session.session_id, ("pending_upload", "uploaded", "verified", "upload_failed"))
        for upload in repository.open_uploads_of(db, [s.sample_id for s in samples]):
            upload.state, upload.last_error_code, upload.updated_at = "expired", "CONSENT_WITHDRAWN", now
        for sample in samples:
            sample.state, sample.deletion_requested_at, sample.updated_at = "delete_pending", now, now
            sample.last_error_code = "CONSENT_WITHDRAWN"
    db.flush()
    out = ConsentOut(enabled=req.enabled, policyVersion=policy, collection=_session_out(session))
    db.commit()
    return out


# upload grant -------------------------------------------------------------------------------------------------------
def _grant(sample: DrawingSample, upload: DrawingUpload, config: CollectionConfig) -> UploadGrant:
    return UploadGrant(sampleId=sample.sample_id, uploadId=upload.upload_id, method="PUT",
                       url=UPLOAD_PATH.format(upload_id=upload.upload_id), contentType="application/json",
                       maxBytes=config.upload.max_bytes, expiresAt=upload.expires_at.astimezone(dt.timezone.utc))


def request_upload(db: Session, settings: Settings, auth: SessionContext, submission_id: uuid.UUID, req: UploadIn,
                   now: dt.datetime) -> UploadOut:
    config = settings.collection
    session = _lock_session(db, auth, now)
    sub = _owned_submission(db, session.session_id, submission_id)
    sample = repository.lock_sample_for_submission(db, sub.submission_id)

    def no_grant() -> UploadOut:
        out = UploadOut(collection=submission_view(db, session, sub), grant=None)
        db.commit()
        return out

    if not config.enabled or (sample is not None and sample.state in DELETION_STATES):
        return no_grant()
    if not session.collection_enabled or sub.collection_selection == "not_selected":
        return no_grant()
    if req.consentRevision != session.consent_revision:
        raise _conflict()
    if sample is not None and sample.state in ("uploaded", "verified"):
        return no_grant()  # file already here: finish with drawing-complete, never a second original
    if sample is not None and sample.active_upload_id is not None:
        active = repository.lock_upload(db, sample.active_upload_id)
        if active is not None and active.state == "issued" and active.expires_at > now:
            out = UploadOut(collection=submission_view(db, session, sub), grant=_grant(sample, active, config))
            db.commit()  # same attempt asked again while the grant is valid: reuse it
            return out
        if active is not None and active.state == "issued":
            active.state, active.last_error_code, active.updated_at = "expired", "UPLOAD_EXPIRED", now
    if sample is None:
        repository.ensure_consent_row(db, session.session_id, session.consent_revision, session.collection_enabled,
                                      session.collection_policy_version, now)
        sample = DrawingSample(sample_id=uuid.uuid4(), submission_id=sub.submission_id, session_id=session.session_id,
                               consent_revision=session.consent_revision, selection=sub.collection_selection,
                               state="pending_upload", created_at=now, updated_at=now)
        db.add(sample)
        db.flush()
    upload_id = uuid.uuid4()
    upload = DrawingUpload(upload_id=upload_id, sample_id=sample.sample_id, object_key=f"tmp/{upload_id}.json",
                           consent_revision=session.consent_revision,
                           expires_at=now + dt.timedelta(seconds=config.upload.grant_ttl_seconds), state="issued",
                           created_at=now, updated_at=now)
    db.add(upload)
    db.flush()
    sample.active_upload_id, sample.state, sample.updated_at = upload_id, "pending_upload", now
    db.flush()
    out = UploadOut(collection=submission_view(db, session, sub), grant=_grant(sample, upload, config))
    db.commit()
    return out


# receive the file (local store; a remote store would accept the PUT itself) ----------------------------------------
def receive_upload(db: Session, settings: Settings, store: ObjectStore, auth: SessionContext, upload_id: uuid.UUID,
                   body: bytes, now: dt.datetime) -> None:
    config = settings.collection
    if not config.enabled:
        raise ApiError(404, "UPLOAD_NOT_FOUND", "업로드 권한을 찾을 수 없어요.")
    if len(body) > config.upload.max_bytes:
        raise ApiError(413, "INVALID_DRAWING", "그림 파일이 너무 커요.")
    session = _lock_session(db, auth, now)
    upload = db.get(DrawingUpload, upload_id)
    sample = repository.lock_sample(db, upload.sample_id) if upload is not None else None
    if sample is None or sample.session_id != session.session_id:
        raise ApiError(404, "UPLOAD_NOT_FOUND", "업로드 권한을 찾을 수 없어요.")
    upload = repository.lock_upload(db, upload_id)
    usable = (upload.state == "issued" and upload.expires_at > now and sample.active_upload_id == upload.upload_id
              and sample.state == "pending_upload" and session.collection_enabled
              and session.consent_revision == upload.consent_revision)
    if not usable:
        raise ApiError(410, "UPLOAD_EXPIRED", "업로드 권한이 만료됐어요.")
    store.put(upload.object_key, body)
    upload.state, upload.updated_at = "received", now
    sample.state, sample.updated_at = "uploaded", now
    db.commit()


# complete: check the file, then re-check consent under the locks before `verified` ---------------------------------
def complete_upload(db: Session, settings: Settings, store: ObjectStore, auth: SessionContext,
                    submission_id: uuid.UUID, req: CompleteIn, now: dt.datetime) -> CompleteOut:
    config = settings.collection
    sub = _owned_submission(db, auth.session_id, submission_id)
    sample = db.get(DrawingSample, req.sampleId)
    upload = db.get(DrawingUpload, req.uploadId)
    if (sample is None or upload is None or sample.submission_id != sub.submission_id
            or upload.sample_id != sample.sample_id):
        raise ApiError(404, "UPLOAD_NOT_FOUND", "업로드 권한을 찾을 수 없어요.")
    # 1. Read and check outside long locks; copy to an immutable key that a late upload cannot overwrite.
    error, checked, verified_key = None, None, None
    data = store.get(upload.object_key) if config.enabled else None
    if data is None:
        error = "FILE_MISSING"
    else:
        try:
            checked = drawing.check(data, config.upload)
            if checked.sha256 != sub.drawing_hash:
                error = "HASH_MISMATCH"
        except drawing.InvalidDrawing as exc:
            error = f"INVALID_{str(exc).upper()}"
    if error is None:
        verified_key = f"verified/{sample.sample_id}/{checked.sha256}.json"
        try:
            store.put(verified_key, data, create_only=True)
        except ObjectExists:
            pass  # same content: the key contains its hash
    db.rollback()

    # 2. Lock session -> sample -> upload and re-check before committing anything.
    session = _lock_session(db, auth, now)
    sample = repository.lock_sample(db, req.sampleId)
    upload = repository.lock_upload(db, req.uploadId)
    current = (config.enabled and session.collection_enabled and session.consent_revision == upload.consent_revision
               and sample.state not in DELETION_STATES and sample.active_upload_id == upload.upload_id
               and upload.state in ("issued", "received") and sample.state in ("pending_upload", "uploaded"))
    if not current:
        if verified_key is not None and sample.verified_object_key != verified_key:
            store.delete(verified_key)  # e.g. consent withdrawn meanwhile: never resurrect `verified`
        if upload.state in ("issued", "received"):
            upload.state, upload.last_error_code, upload.updated_at = "rejected", "NOT_CURRENT", now
        out = CompleteOut(collection=submission_view(db, session, sub))
        db.commit()
        return out
    if error is not None:
        upload.state, upload.last_error_code, upload.updated_at = "rejected", error, now
        sample.state, sample.last_error_code, sample.updated_at = "upload_failed", error, now
        out = CompleteOut(collection=submission_view(db, session, sub))
        db.commit()
        if error.startswith("INVALID_") or error == "HASH_MISMATCH":
            raise ApiError(422, "INVALID_DRAWING", "그림 파일 형식이 올바르지 않아요.")
        return out
    upload.state, upload.updated_at = "verified", now
    sample.state, sample.verified_object_key, sample.file_sha256 = "verified", verified_key, checked.sha256
    sample.byte_size, sample.stroke_count, sample.point_count = len(data), checked.stroke_count, checked.point_count
    sample.verified_at, sample.last_error_code, sample.updated_at = now, None, now
    out = CompleteOut(collection=submission_view(db, session, sub))
    db.commit()
    store.delete(upload.object_key)  # the temporary copy is no longer needed
    return out
