"""Upload + verify logic shared by ``youtube-upload`` and ``youtube-pipeline``.

``run_upload`` is idempotent per video file:
* the job ID comes from the file's SHA-256 (``state.make_job_id``);
* a file already recorded in ``uploads_index.json`` is never uploaded again
  (``DuplicateUploadError``) unless ``force_reupload``;
* an interrupted upload is resumed through its saved session URI;
* if the session is gone, the channel's recent uploads are checked (title + size)
  before anything else happens; an inconclusive check stops with NEEDS_MANUAL_CHECK.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .exceptions import DuplicateUploadError, UploadUncertainError, ValidationError
from .logger import get_logger
from .state import StateStore, make_job_id, sha256_file
from .validators import ValidationResult, parse_publish_at, to_rfc3339_utc, validate_metadata, validate_thumbnail, validate_video_file

UNVERIFIED_PROJECT_NOTE = (
    "Google locks videos uploaded through API projects that have not passed a YouTube API audit "
    "(projects created after 28 July 2020) to 'private'. Request an audit in Google Cloud to publish publicly via the API."
)


@dataclass
class UploadSpec:
    file: Path
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    category_id: str = "22"
    privacy: str = "private"
    made_for_kids: bool | None = False
    publish_at: str | None = None
    default_language: str | None = None
    default_audio_language: str | None = None
    notify_subscribers: bool | None = None
    thumbnail: Path | None = None
    idempotency_key: str | None = None

    def metadata(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "category_id": self.category_id,
            "privacy": self.privacy,
            "made_for_kids": self.made_for_kids,
            "publish_at": self.publish_at,
        }

    def body(self) -> dict:
        snippet: dict[str, Any] = {
            "title": self.title,
            "description": self.description or "",
            "categoryId": str(self.category_id),
        }
        if self.tags:
            snippet["tags"] = list(self.tags)
        if self.default_language:
            snippet["defaultLanguage"] = self.default_language
        if self.default_audio_language:
            snippet["defaultAudioLanguage"] = self.default_audio_language
        status: dict[str, Any] = {"privacyStatus": self.privacy, "selfDeclaredMadeForKids": bool(self.made_for_kids)}
        if self.publish_at:
            status["publishAt"] = to_rfc3339_utc(parse_publish_at(self.publish_at))
        return {"snippet": snippet, "status": status}


def validate_spec(spec: UploadSpec, *, strict_thumbnail: bool = False) -> ValidationResult:
    r = ValidationResult()
    r.merge(validate_video_file(spec.file))
    r.merge(validate_metadata(spec.metadata()))
    if spec.thumbnail:
        r.merge(validate_thumbnail(spec.thumbnail, strict=strict_thumbnail))
    return r


def planned_calls(spec: UploadSpec, *, verify: bool = True) -> list[str]:
    calls = ["videos.insert"]
    if spec.thumbnail:
        calls.append("thumbnails.set")
    if verify:
        calls.append("videos.list")
    return calls


def job_for(store: StateStore, spec: UploadSpec, file_sha: str) -> dict:
    job_id = make_job_id(file_sha, spec.idempotency_key)
    job = store.load(job_id)
    if job is None:
        job = store.create(job_id, file=str(spec.file), file_sha256=file_sha, file_bytes=spec.file.stat().st_size, title=spec.title)
    return job


def run_upload(
    client: Any,
    store: StateStore,
    spec: UploadSpec,
    *,
    job: dict | None = None,
    chunk_size: int,
    force_reupload: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[dict, dict]:
    """Upload ``spec.file`` once. Returns (job, video_resource_or_minimal_dict)."""
    log = get_logger()
    result = validate_spec(spec)
    if not result.ok:
        raise ValidationError("Upload input is invalid", result.errors)
    file_sha = (job or {}).get("file_sha256") or sha256_file(spec.file)
    job = job or job_for(store, spec, file_sha)
    file_bytes = spec.file.stat().st_size

    if job.get("video_id") and job["status"] not in ("FAILED",) and not force_reupload:
        log.info("upload", "job already has a video; skipping upload", video_id=job["video_id"], result="skipped")
        return job, {"id": job["video_id"]}

    previous = store.find_upload(file_sha)
    if previous and not force_reupload:
        raise DuplicateUploadError(
            f"This file (sha256 {file_sha[:12]}…) was already uploaded as video {previous['video_id']} "
            f"on {previous['at']} (job {previous.get('job_id')}). Use --force-reupload only if you really want a second copy."
        )

    def save_session(uri: str) -> None:
        store.transition(job, "UPLOADING", "resumable session created", resumable_uri=uri)

    resume_uri = job.get("resumable_uri") if job["status"] in ("UPLOADING", "UPLOAD_UNCERTAIN") else None
    if resume_uri and not force_reupload:
        store.transition(job, "UPLOAD_UNCERTAIN", "resuming saved session; querying remote byte count first")

    try:
        try:
            response = client.upload_video(
                spec.file,
                spec.body(),
                chunk_size=chunk_size,
                notify_subscribers=spec.notify_subscribers,
                resume_uri=None if force_reupload else resume_uri,
                on_session=save_session,
                on_progress=on_progress,
            )
        except UploadUncertainError:
            if not resume_uri:
                store.transition(job, "UPLOAD_UNCERTAIN", "interrupted; session saved for resume")
                raise
            # The saved session no longer exists. Check the channel before anything else.
            verdict, video = client.find_remote_upload(spec.title, file_bytes)
            if verdict == "found":
                response = video
                log.info("upload", "found the interrupted upload on the channel", video_id=video["id"], result="recovered")
            else:
                store.transition(
                    job,
                    "NEEDS_MANUAL_CHECK",
                    f"saved session gone and remote check was {verdict}",
                    resumable_uri=None,
                )
                raise UploadUncertainError(
                    f"Could not confirm whether the interrupted upload of '{spec.title}' finished (remote check: {verdict}). "
                    "Look at YouTube Studio → Content. If the video is not there, re-run with --force-reupload."
                ) from None
    except UploadUncertainError:
        raise
    except Exception as exc:
        store.transition(job, "FAILED", f"upload failed: {type(exc).__name__}", error=str(exc)[:500])
        raise

    video_id = response.get("id")
    if not video_id:
        store.transition(job, "UPLOAD_UNCERTAIN", "upload returned no video id")
        raise UploadUncertainError("YouTube returned no video ID; check YouTube Studio before retrying.")
    store.record_upload(file_sha, video_id, job["job_id"], spec.title)
    store.transition(job, "UPLOADED", "video id received", video_id=video_id, resumable_uri=None)
    return job, response


def verify_video(client: Any, video_id: str, spec: UploadSpec | None = None) -> dict:
    """Fetch the video from YouTube and compare it with what we asked for."""
    video = client.get_video(video_id, parts="snippet,status,processingDetails")
    if not video:
        return {"video_id": video_id, "exists": False, "ok": False, "checks": [], "notes": ["Video not found (deleted, or not owned by this account)."]}
    snippet, status = video.get("snippet", {}), video.get("status", {})
    checks: list[dict] = []
    notes: list[str] = []

    def check(name: str, expected: Any, actual: Any) -> None:
        checks.append({"name": name, "expected": expected, "actual": actual, "ok": expected == actual})

    upload_status = status.get("uploadStatus")
    checks.append({"name": "uploadStatus", "expected": "uploaded|processed", "actual": upload_status, "ok": upload_status in ("uploaded", "processed")})
    if upload_status in ("rejected", "failed"):
        notes.append(f"YouTube {upload_status} the upload: {status.get('rejectionReason') or status.get('failureReason')}")
    if spec:
        check("title", spec.title, snippet.get("title"))
        check("categoryId", str(spec.category_id), snippet.get("categoryId"))
        check("privacyStatus", spec.privacy, status.get("privacyStatus"))
        if spec.publish_at:
            check("publishAt", to_rfc3339_utc(parse_publish_at(spec.publish_at)), _norm_ts(status.get("publishAt")))
        if spec.made_for_kids is not None and "selfDeclaredMadeForKids" in status:
            check("selfDeclaredMadeForKids", bool(spec.made_for_kids), status.get("selfDeclaredMadeForKids"))
        if spec.privacy != "private" and status.get("privacyStatus") == "private":
            notes.append(UNVERIFIED_PROJECT_NOTE)
    processing = video.get("processingDetails", {}).get("processingStatus")
    if processing:
        notes.append(f"processingStatus: {processing}")
    return {
        "video_id": video_id,
        "exists": True,
        "url": f"https://youtu.be/{video_id}",
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "notes": notes,
    }


def spec_from_mapping(m: dict, defaults: dict, base_dir: Path | None = None) -> UploadSpec:
    """Build an UploadSpec from a config mapping (pipeline YAML / metadata file / CLI dict).

    Relative paths are resolved against ``base_dir`` (the config file's folder).
    """

    def path(v: Any) -> Path | None:
        if not v:
            return None
        p = Path(str(v)).expanduser()
        return p if p.is_absolute() or base_dir is None else (base_dir / p)

    tags = m.get("tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    mfk = m.get("made_for_kids", defaults.get("made_for_kids"))
    return UploadSpec(
        file=path(m.get("file")) or Path(""),
        title=m.get("title") or "",
        description=m.get("description") or "",
        tags=list(tags or []),
        category_id=str(m.get("category_id") or defaults.get("category_id") or "22"),
        privacy=m.get("privacy") or defaults.get("privacy") or "private",
        made_for_kids=mfk if isinstance(mfk, bool) else None,
        publish_at=m.get("publish_at"),
        default_language=m.get("default_language") or defaults.get("default_language"),
        default_audio_language=m.get("default_audio_language"),
        notify_subscribers=m.get("notify_subscribers", defaults.get("notify_subscribers")),
        thumbnail=path(m.get("thumbnail")),
        idempotency_key=m.get("idempotency_key"),
    )


# Fields that videos.update overwrites for a part; anything not sent is cleared/reset.
MUTABLE = {
    "snippet": ["title", "description", "tags", "categoryId", "defaultLanguage"],
    "status": ["privacyStatus", "publishAt", "selfDeclaredMadeForKids", "embeddable", "license", "publicStatsViewable", "containsSyntheticMedia"],
}


def merge_for_update(current: dict, changes: dict[str, dict]) -> tuple[dict, list[dict]]:
    """Build a videos.update body that keeps every current mutable field and applies ``changes``.

    Returns (body, diff). ``changes`` maps part → {field: new_value}; a value of None removes the field.
    """
    body: dict[str, Any] = {"id": current["id"]}
    diff: list[dict] = []
    for part, fields in changes.items():
        cur = current.get(part, {}) or {}
        merged = {k: cur[k] for k in MUTABLE[part] if k in cur}
        for k, v in fields.items():
            old = merged.get(k)
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
            if old != v:
                diff.append({"field": f"{part}.{k}", "old": old, "new": v})
        body[part] = merged
    return body, diff


def _norm_ts(value: str | None) -> str | None:
    if not value:
        return value
    try:
        return to_rfc3339_utc(parse_publish_at(value))
    except ValueError:
        return value
