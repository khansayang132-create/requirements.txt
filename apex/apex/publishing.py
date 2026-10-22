"""Publishing state machine and adapters.

No platform adapter is implemented yet: TikTok, YouTube, Instagram and Facebook each need
an approved developer app and OAuth credentials. The DryRunAdapter prepares the exact
upload package and records it, but never contacts a platform, so a post can never be
marked PUBLISHED without a real provider confirmation.
"""
from __future__ import annotations

import json
import shutil
import time
from enum import Enum
from pathlib import Path
from typing import Protocol


class PostState(str, Enum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    SUBMISSION_IN_PROGRESS = "SUBMISSION_IN_PROGRESS"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REQUIRES_AUTHORIZATION = "REQUIRES_AUTHORIZATION"
    STATUS_UNKNOWN = "PUBLICATION_STATUS_UNKNOWN"


POST_TRANSITIONS = {
    PostState.DRAFT: {PostState.READY_FOR_REVIEW, PostState.CANCELLED},
    PostState.READY_FOR_REVIEW: {PostState.APPROVED, PostState.CANCELLED},
    PostState.APPROVED: {PostState.SCHEDULED, PostState.SUBMISSION_IN_PROGRESS, PostState.REQUIRES_AUTHORIZATION,
                         PostState.CANCELLED},
    PostState.SCHEDULED: {PostState.SUBMISSION_IN_PROGRESS, PostState.CANCELLED},
    PostState.SUBMISSION_IN_PROGRESS: {PostState.PUBLISHED, PostState.FAILED, PostState.STATUS_UNKNOWN},
    PostState.REQUIRES_AUTHORIZATION: {PostState.APPROVED, PostState.CANCELLED},
    PostState.STATUS_UNKNOWN: {PostState.PUBLISHED, PostState.FAILED},
    PostState.PUBLISHED: set(), PostState.FAILED: set(), PostState.CANCELLED: set(),
}


class PublishResult(dict):
    """{'confirmed': bool, 'post_id': str|None, 'url': str|None, 'provider_response': dict}"""


class PublishAdapter(Protocol):
    platform: str

    def publish(self, video: Path, metadata: dict) -> PublishResult: ...


class Post:
    def __init__(self, video: Path, metadata: dict, platform: str):
        self.video, self.metadata, self.platform = video, metadata, platform
        self.state, self.history, self.result = PostState.DRAFT, [], None
        self._log(PostState.DRAFT, "created")

    def _log(self, state, detail):
        self.history.append({"state": state.value, "at": time.time(), "detail": detail})

    def move(self, to: PostState, detail: str = "") -> None:
        if to not in POST_TRANSITIONS[self.state]:
            raise ValueError(f"post: {self.state.value} -> {to.value} is not allowed")
        self.state = to
        self._log(to, detail)

    def submit(self, adapter: PublishAdapter) -> None:
        """Only an adapter's explicit confirmation can make a post PUBLISHED."""
        self.move(PostState.SUBMISSION_IN_PROGRESS, f"via {adapter.platform}")
        try:
            res = adapter.publish(self.video, self.metadata)
        except PermissionError as e:
            self.state = PostState.APPROVED
            self.move(PostState.REQUIRES_AUTHORIZATION, str(e))
            return
        except Exception as e:  # noqa: BLE001
            self.move(PostState.FAILED, str(e)[:300])
            return
        self.result = res
        if res.get("confirmed") and res.get("post_id"):
            self.move(PostState.PUBLISHED, f"post_id={res['post_id']}")
        else:
            self.move(PostState.STATUS_UNKNOWN, "provider gave no confirmation")


class DryRunAdapter:
    """Writes the upload package to disk. Never posts anything, never reports a post as published."""

    def __init__(self, out_dir: Path, platform: str = "tiktok"):
        self.out_dir, self.platform = Path(out_dir), f"dry-run:{platform}"

    def publish(self, video: Path, metadata: dict) -> PublishResult:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video, self.out_dir / video.name)
        (self.out_dir / "post.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
        return PublishResult(confirmed=False, post_id=None, url=None,
                             provider_response={"dry_run": True, "package": str(self.out_dir)})
