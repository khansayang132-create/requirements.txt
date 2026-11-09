"""Thin, policy-enforcing wrapper over the official Google API client.

Every remote call goes through ``YouTubeClient.call`` which:
1. checks the quota estimate before the call (refuses if a bucket is exhausted);
2. records each attempt in the quota ledger (Google charges failed calls too);
3. retries with bounded exponential backoff + jitter (``retry.RetryPolicy``);
4. on 403 quotaExceeded marks the bucket exhausted and raises — never loops;
5. logs operation, endpoint, HTTP status, error class, retry count, request ID.

Only official endpoints are used: ``youtube`` v3 and ``youtubeAnalytics`` v2 via
``googleapiclient.discovery.build`` with the discovery documents bundled in the
library (``static_discovery=True``), so building a client needs no network.

Resumable uploads: the session URI is handed to ``on_session`` as soon as Google
issues it, so the pipeline can persist it. If the process dies mid-upload, passing
that URI back as ``resume_uri`` makes the library ask Google how many bytes it has
(``PUT`` with ``Content-Range: bytes */size``) before sending anything — so a timeout
never causes a blind second upload.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .exceptions import APIError, QuotaExceededError, UploadUncertainError
from .logger import current_request_id, get_logger
from .quota_manager import QuotaManager
from .retry import HINTS, RETRYABLE, ErrorClass, RetryPolicy, classify, is_http_error, is_network_error, parse_http_error

DEFAULT_CHUNK = 8 * 1024 * 1024  # must be a multiple of 256 KiB for real uploads


def build_services(credentials: Any = None, *, http: Any = None) -> tuple[Any, Any]:
    from googleapiclient.discovery import build

    kwargs: dict[str, Any] = {"cache_discovery": False, "static_discovery": True}
    if http is not None:
        kwargs["http"] = http
    else:
        kwargs["credentials"] = credentials
    youtube = build("youtube", "v3", **kwargs)
    analytics = build("youtubeAnalytics", "v2", **kwargs)
    return youtube, analytics


class YouTubeClient:
    def __init__(
        self,
        youtube: Any,
        analytics: Any = None,
        *,
        quota: QuotaManager | None = None,
        policy: RetryPolicy | None = None,
        credentials: Any = None,
        refresh: Callable[[Any], Any] | None = None,
    ):
        self.youtube = youtube
        self.analytics = analytics
        self.quota = quota
        self.policy = policy or RetryPolicy()
        self.credentials = credentials
        self._refresh = refresh
        self.log = get_logger()

    @classmethod
    def from_credentials(cls, credentials: Any, *, quota: QuotaManager | None, policy: RetryPolicy | None = None) -> YouTubeClient:
        from .oauth_manager import refresh_credentials

        youtube, analytics = build_services(credentials)
        return cls(youtube, analytics, quota=quota, policy=policy, credentials=credentials, refresh=refresh_credentials)

    # ------------------------------------------------------------------ core ------
    def _try_refresh(self) -> bool:
        if self.credentials is None or self._refresh is None or not getattr(self.credentials, "refresh_token", None):
            return False
        try:
            self._refresh(self.credentials)
            return True
        except Exception:  # noqa: BLE001 - surfaced as the original 401
            return False

    def call(self, op: str, make_request: Callable[[], Any], *, endpoint: str = "", idempotent: bool = True) -> Any:
        """Execute ``make_request().execute()`` under quota + retry + logging policy."""
        if self.quota:
            for w in self.quota.check([op]):
                self.log.warning(op, w, endpoint=endpoint)

        def attempt_hook(n: int, exc: Exception | None) -> None:
            if not self.quota:
                return
            status = None
            if exc is not None and is_http_error(exc):
                status = parse_http_error(exc)[0]
            self.quota.record(op, http_status=status or (200 if exc is None else None), success=exc is None, request_id=current_request_id())

        def mark() -> None:
            if self.quota:
                self.quota.mark_exhausted(op)

        result = self.policy.run(
            lambda: make_request().execute(),
            operation=op,
            endpoint=endpoint or op,
            idempotent=idempotent,
            on_auth_error=self._try_refresh,
            on_quota_error=mark,
            on_attempt=attempt_hook,
        )
        self.log.info(op, "ok", endpoint=endpoint or op, http_status=200, result="success")
        return result

    # ---------------------------------------------------------------- videos ------
    def upload_video(
        self,
        path: str | Path,
        body: dict,
        *,
        chunk_size: int = DEFAULT_CHUNK,
        notify_subscribers: bool | None = None,
        resume_uri: str | None = None,
        on_session: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict:
        """Resumable upload via ``videos.insert``. Returns the created video resource.

        Raises UploadUncertainError if bytes were sent but completion could not be
        confirmed after bounded retries; the session URI was already passed to
        ``on_session`` so a later run can resume or verify.
        """
        from googleapiclient.http import MediaFileUpload

        op = "videos.insert"
        if self.quota and not resume_uri:
            for w in self.quota.check([op]):
                self.log.warning(op, w)
        mimetype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        media = MediaFileUpload(str(path), mimetype=mimetype, chunksize=chunk_size, resumable=True)
        kwargs: dict[str, Any] = {"part": ",".join(sorted(body.keys())), "body": body, "media_body": media}
        if notify_subscribers is not None:
            kwargs["notifySubscribers"] = notify_subscribers
        request = self.youtube.videos().insert(**kwargs)
        initiated = False
        if resume_uri:
            request.resumable_uri = resume_uri
            request._in_error_state = True  # forces a status query before sending bytes (see module doc)
            initiated = True
            self.log.info(op, "resuming existing upload session", endpoint="videos.insert(resumable)")

        def note_session() -> bool:
            # The session is created inside the first next_chunk() call, which may then fail
            # while sending bytes; capture the URI on both the success and the error path.
            if request.resumable_uri:
                if self.quota:
                    self.quota.record(op, http_status=200, success=True, request_id=current_request_id())
                if on_session:
                    on_session(request.resumable_uri)
                return True
            return False

        attempts = 0
        response = None
        while response is None:
            try:
                status, response = request.next_chunk()
                if not initiated:
                    initiated = note_session()
                if status is not None and on_progress:
                    on_progress(status.resumable_progress, status.total_size)
                attempts = 0
            except Exception as exc:  # noqa: BLE001 - classified below
                if not initiated:
                    initiated = note_session()
                if is_http_error(exc):
                    code, reason, message = parse_http_error(exc)
                    cls = classify(code, reason)
                elif is_network_error(exc):
                    code, reason, message, cls = None, type(exc).__name__, str(exc), ErrorClass.NETWORK
                else:
                    raise
                if not initiated and self.quota:
                    self.quota.record(op, http_status=code, success=False, request_id=current_request_id())
                self.log.warning(op, message[:300], endpoint="videos.insert(resumable)", http_status=code, error_class=cls.value, retry_count=attempts)
                if cls is ErrorClass.QUOTA:
                    if self.quota:
                        self.quota.mark_exhausted(op)
                    raise QuotaExceededError(f"{HINTS[cls]} (HTTP {code}, reason={reason})") from exc
                if cls is ErrorClass.AUTH and attempts == 0 and self._try_refresh():
                    attempts += 1
                    continue
                if code == 404 and resume_uri and initiated:
                    raise UploadUncertainError(
                        "The saved resumable upload session no longer exists (expired or completed). "
                        "Check the channel for the video before uploading again."
                    ) from exc
                if cls in RETRYABLE and attempts + 1 < self.policy.max_attempts:
                    self.policy.sleep(self.policy.backoff(attempts))
                    attempts += 1
                    continue  # next_chunk queries the server's byte count first (error state)
                if initiated and cls in RETRYABLE:
                    raise UploadUncertainError(
                        f"Upload interrupted after retries ({cls.value}: {message[:200]}). Bytes may have reached "
                        "YouTube; the session URI is saved — re-run to resume, do not start a new upload."
                    ) from exc
                raise APIError(
                    f"videos.insert failed: {message} — {HINTS[cls]}",
                    status=code,
                    reason=reason,
                    classification=cls.value,
                    retryable=cls in RETRYABLE,
                    attempts=attempts + 1,
                ) from exc
        video_id = response.get("id") if isinstance(response, dict) else None
        self.log.info(op, "upload complete", endpoint="videos.insert(resumable)", http_status=200, result="success", video_id=video_id)
        return response

    def set_thumbnail(self, video_id: str, path: str | Path, mimetype: str) -> dict:
        from googleapiclient.http import MediaFileUpload

        def make():
            media = MediaFileUpload(str(path), mimetype=mimetype, resumable=False)
            return self.youtube.thumbnails().set(videoId=video_id, media_body=media)

        return self.call("thumbnails.set", make, endpoint="thumbnails.set")

    def get_videos(self, video_ids: list[str], parts: str = "snippet,status,contentDetails") -> list[dict]:
        if not video_ids:
            return []
        resp = self.call("videos.list", lambda: self.youtube.videos().list(part=parts, id=",".join(video_ids), maxResults=50), endpoint="videos.list")
        return resp.get("items", [])

    def get_video(self, video_id: str, parts: str = "snippet,status,contentDetails") -> dict | None:
        items = self.get_videos([video_id], parts)
        return items[0] if items else None

    def update_video(self, body: dict, parts: str) -> dict:
        return self.call("videos.update", lambda: self.youtube.videos().update(part=parts, body=body), endpoint="videos.update")

    def delete_video(self, video_id: str) -> None:
        self.call("videos.delete", lambda: self.youtube.videos().delete(id=video_id), endpoint="videos.delete")

    # --------------------------------------------------------------- channel ------
    def my_channel(self) -> dict | None:
        resp = self.call("channels.list", lambda: self.youtube.channels().list(part="snippet,contentDetails", mine=True), endpoint="channels.list")
        items = resp.get("items", [])
        return items[0] if items else None

    def recent_uploads(self, max_results: int = 25) -> list[dict]:
        """Most recent videos on the authenticated channel, with snippet/status/fileDetails.

        Uses the channel's uploads playlist (1 unit each call) instead of search.list.
        """
        channel = self.my_channel()
        if not channel:
            return []
        uploads = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not uploads:
            return []
        resp = self.call(
            "playlistItems.list",
            lambda: self.youtube.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=min(max_results, 50)),
            endpoint="playlistItems.list",
        )
        ids = [i["contentDetails"]["videoId"] for i in resp.get("items", []) if i.get("contentDetails", {}).get("videoId")]
        return self.get_videos(ids, parts="snippet,status,fileDetails")

    def find_remote_upload(self, title: str, file_size: int | None, max_results: int = 25) -> tuple[str, dict | None]:
        """Look for a just-uploaded video by exact title (+ file size when YouTube reports it).

        Returns ("found", video) | ("ambiguous", None) | ("not_found", None).
        """
        candidates = [v for v in self.recent_uploads(max_results) if v.get("snippet", {}).get("title") == title]
        if file_size is not None:
            sized = []
            for v in candidates:
                reported = v.get("fileDetails", {}).get("fileSize")
                if reported is None or int(reported) == int(file_size):
                    sized.append(v)
            candidates = sized
        if len(candidates) == 1:
            return "found", candidates[0]
        if len(candidates) > 1:
            return "ambiguous", None
        return "not_found", None

    # -------------------------------------------------------------- captions ------
    def list_captions(self, video_id: str) -> list[dict]:
        resp = self.call("captions.list", lambda: self.youtube.captions().list(part="snippet", videoId=video_id), endpoint="captions.list")
        return resp.get("items", [])

    def download_caption(self, caption_id: str, fmt: str | None = None, language: str | None = None) -> bytes:
        def make():
            kwargs: dict[str, Any] = {"id": caption_id}
            if fmt:
                kwargs["tfmt"] = fmt
            if language:
                kwargs["tlang"] = language
            return self.youtube.captions().download_media(**kwargs)

        data = self.call("captions.download", make, endpoint="captions.download")
        return data if isinstance(data, bytes) else str(data).encode("utf-8")

    def insert_caption(self, video_id: str, language: str, name: str, path: str | Path, is_draft: bool = False) -> dict:
        from googleapiclient.http import MediaFileUpload

        def make():
            media = MediaFileUpload(str(path), mimetype="application/octet-stream", resumable=False)
            body = {"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": is_draft}}
            return self.youtube.captions().insert(part="snippet", body=body, media_body=media)

        return self.call("captions.insert", make, endpoint="captions.insert", idempotent=False)

    def update_caption(self, caption_id: str, path: str | Path | None = None, is_draft: bool | None = None) -> dict:
        from googleapiclient.http import MediaFileUpload

        def make():
            body: dict[str, Any] = {"id": caption_id}
            if is_draft is not None:
                body["snippet"] = {"isDraft": is_draft}
            kwargs: dict[str, Any] = {"part": "snippet" if is_draft is not None else "id", "body": body}
            if path:
                kwargs["media_body"] = MediaFileUpload(str(path), mimetype="application/octet-stream", resumable=False)
            return self.youtube.captions().update(**kwargs)

        return self.call("captions.update", make, endpoint="captions.update")

    # ------------------------------------------------------------- analytics ------
    def analytics_query(self, **params: Any) -> dict:
        if self.analytics is None:
            raise APIError("YouTube Analytics service is not configured", classification="client")
        params = {k: v for k, v in params.items() if v not in (None, "")}
        return self.call("analytics.reports.query", lambda: self.analytics.reports().query(**params), endpoint="youtubeAnalytics.reports.query")
