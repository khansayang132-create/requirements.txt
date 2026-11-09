#!/usr/bin/env python3
"""Run the complete publishing pipeline from one YAML config.

Steps (each recorded in the job state and the final report):
  1 validate_config      2 verify_auth        3 validate_video     4 generate_metadata
  5 validate_thumbnail   6 process_transcript 7 estimate_quota     8 check_state
  9 upload (needs --confirm)                  10 verify_video_id   11 apply_assets
  12 verify_publication  13 save_state        14 report

Steps 1-8 are local/read-only and always run. Without --dry-run or --confirm the
pipeline stops before step 9 and explains why (exit 2). Re-running the same config is
safe: the job ID comes from the video file hash, finished steps are skipped, an
interrupted upload is resumed through its saved session, and a file that was already
uploaded is never uploaded again.

Examples:
  python skills/youtube-pipeline/scripts/pipeline.py --config examples/sample_pipeline.yaml --dry-run
  python skills/youtube-pipeline/scripts/pipeline.py --config examples/sample_pipeline.yaml --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli, oauth_manager  # noqa: E402
from src.captions import transcribe_with_whisper, format_srt, validate_caption_file, whisper_available  # noqa: E402
from src.config import get, load_yaml_file, upload_defaults  # noqa: E402
from src.exceptions import ConfirmationRequired, QuotaExceededError, ValidationError, YTAOSError  # noqa: E402
from src.logger import get_logger  # noqa: E402
from src.metadata import generate  # noqa: E402
from src.safety import DRY_RUN, decide_mode  # noqa: E402
from src.state import make_job_id, sha256_file  # noqa: E402
from src.uploader import UploadSpec, planned_calls, run_upload, spec_from_mapping, verify_video  # noqa: E402
from src.validators import validate_metadata, validate_thumbnail, validate_video_file  # noqa: E402

STEPS = [
    "validate_config", "verify_auth", "validate_video", "generate_metadata", "validate_thumbnail",
    "process_transcript", "estimate_quota", "check_state", "upload", "verify_video_id",
    "apply_assets", "verify_publication", "save_state", "report",
]
PARTIAL = 12


class Pipeline:
    def __init__(self, config_path: str | Path, rt: cli.Runtime, *, client_factory: Callable[..., Any] | None = None):
        self.config_path = Path(config_path).resolve()
        self.base = self.config_path.parent
        self.rt = rt
        self.client_factory = client_factory or cli.make_client
        self.log = get_logger()
        self.steps: list[dict] = []
        self.warnings: list[str] = []
        self.client = None
        self.job: dict | None = None

    # ------------------------------------------------------------------ util ------
    def record(self, n: int, status: str, detail: Any = None) -> None:
        entry = {"n": n, "name": STEPS[n - 1], "status": status}
        if detail is not None:
            entry["detail"] = detail
        self.steps.append(entry)
        self.log.info(f"pipeline.{STEPS[n - 1]}", status, result=status)
        if self.job is not None:
            self.rt.store.step(self.job, STEPS[n - 1], status, detail=detail if isinstance(detail, (str, int, float, type(None))) else None)

    def path(self, value: Any) -> Path | None:
        if not value:
            return None
        p = Path(str(value)).expanduser()
        return p if p.is_absolute() else (self.base / p).resolve()

    def done(self, step: str) -> bool:
        return bool(self.job and self.job.get("steps", {}).get(step, {}).get("status") in ("ok", "skipped"))

    # ------------------------------------------------------------------ run -------
    def run(self, *, dry_run: bool, confirm: bool, force_reupload: bool = False) -> dict:
        cfg = self.step1_config()
        ops = self.required_ops(cfg)
        self.step2_auth(ops, dry_run=dry_run, confirm=confirm)
        self.step3_video(cfg)
        spec = self.step4_metadata(cfg)
        self.step5_thumbnail(cfg, spec)
        captions_file = self.step6_transcript(cfg, execute=False)
        calls = self.step7_quota(spec, cfg)
        self.step8_state(spec)

        try:
            mode = decide_mode(dry_run=dry_run, confirm=confirm, action="run the publishing pipeline (upload to YouTube)")
        except ConfirmationRequired as exc:
            self.record(9, "refused", str(exc))
            report = self.finish(spec, mode="refused", calls=calls)
            raise ConfirmationRequired(str(exc) + f"\nValidation report: {report['report_file']}") from None
        if mode == DRY_RUN:
            for n in range(9, 13):
                self.record(n, "dry_run", "not executed (dry run)")
            return self.finish(spec, mode="dry_run", calls=calls)

        # ---------------- execute: steps 9-14 ----------------
        assert self.job is not None
        with self.rt.store.lock(self.job["job_id"]):
            self.client = self.client or self.client_factory(self.rt, ops)
            if cfg.get("transcript", {}).get("enabled") and cfg["transcript"].get("source") == "whisper" and not captions_file:
                captions_file = self.step6_transcript(cfg, execute=True)
            self.step9_upload(spec, force_reupload)
            self.step10_verify_id()
            self.step11_assets(spec, cfg, captions_file)
            ok = self.step12_verify(spec)
            self.rt.store.transition(self.job, "COMPLETED" if ok else self.job["status"], "pipeline finished")
            self.record(13, "ok", f"job status {self.job['status']}")
            report = self.finish(spec, mode="execute", calls=calls)
            report["exit_code"] = 0 if ok and all(s["status"] != "failed" for s in self.steps) else PARTIAL
            return report

    # ------------------------------------------------------------------ steps -----
    def step1_config(self) -> dict:
        cfg = load_yaml_file(self.config_path)
        errors = []
        if not isinstance(cfg.get("video"), dict) or not cfg["video"].get("file"):
            errors.append("video.file is required")
        for section in ("metadata", "publish", "thumbnail", "transcript"):
            if section in cfg and cfg[section] is not None and not isinstance(cfg[section], dict):
                errors.append(f"'{section}' must be a mapping")
        if not (cfg.get("metadata") or {}).get("topic_file") and not (cfg.get("metadata") or {}).get("title"):
            errors.append("metadata.topic_file or metadata.title is required")
        if errors:
            self.record(1, "failed", errors)
            raise ValidationError(f"Invalid pipeline config {self.config_path}", errors)
        for section in ("metadata", "publish", "thumbnail", "transcript"):
            cfg[section] = cfg.get(section) or {}
        self.record(1, "ok", str(self.config_path))
        return cfg

    @staticmethod
    def required_ops(cfg: dict) -> list[str]:
        ops = ["videos.insert", "videos.list"]
        if cfg.get("thumbnail", {}).get("file"):
            ops.append("thumbnails.set")
        t = cfg.get("transcript", {})
        if t.get("enabled") and t.get("upload", True):
            ops.append("captions.insert")
        return ops

    def step2_auth(self, ops: list[str], *, dry_run: bool, confirm: bool) -> None:
        if not dry_run and confirm:
            # Real run: load + refresh credentials now so we fail before touching anything.
            self.client = self.client_factory(self.rt, ops)
            self.record(2, "ok", "credentials loaded and scopes checked")
            return
        st = oauth_manager.status()
        missing = oauth_manager.missing_scopes_for(ops, st.get("granted_scopes", []))
        if st["state"] in ("NOT_AUTHENTICATED", "INVALID_NO_REFRESH_TOKEN"):
            msg = f"not authenticated ({st['state']}); run skills/youtube-auth/scripts/authenticate.py --scopes upload,manage" + (",captions" if "captions.insert" in ops else "")
            self.warnings.append("auth: " + msg)
            self.record(2, "warning", msg)
        elif missing:
            self.warnings.append("auth: missing scopes for " + "; ".join(missing))
            self.record(2, "warning", missing)
        else:
            self.record(2, "ok", f"offline check: {st['state']}")

    def step3_video(self, cfg: dict) -> None:
        r = validate_video_file(self.path(cfg["video"]["file"]))
        if not r.ok:
            self.record(3, "failed", r.errors)
            raise ValidationError("Video file is invalid", r.errors)
        self.record(3, "ok", r.info)

    def step4_metadata(self, cfg: dict) -> UploadSpec:
        m = dict(cfg["metadata"])
        generated: dict = {}
        if m.get("topic_file"):
            topic = load_yaml_file(self.path(m["topic_file"]))
            generated = generate(topic, get(self.rt.settings, "metadata", {}) or {}, default_category=upload_defaults(self.rt.settings)["category_id"])
            self.warnings += [f"metadata: {n}" for n in generated["notes"]]
        mapping = {k: generated[k] for k in ("title", "description", "tags", "category_id") if k in generated}
        mapping.update({k: v for k, v in m.items() if k != "topic_file" and v not in (None, "", [])})
        mapping.update({k: v for k, v in cfg["publish"].items() if v is not None})
        mapping["file"] = str(self.path(cfg["video"]["file"]))
        mapping["idempotency_key"] = cfg["video"].get("idempotency_key")
        if cfg["thumbnail"].get("file"):
            mapping["thumbnail"] = str(self.path(cfg["thumbnail"]["file"]))
        spec = spec_from_mapping(mapping, upload_defaults(self.rt.settings))
        r = validate_metadata(spec.metadata())
        self.warnings += [f"metadata: {w}" for w in r.warnings]
        if not r.ok:
            self.record(4, "failed", r.errors)
            raise ValidationError("Metadata is invalid", r.errors)
        self.record(4, "ok", {"title": spec.title, "tags": len(spec.tags), "category_id": spec.category_id, "privacy": spec.privacy, "publish_at": spec.publish_at})
        return spec

    def step5_thumbnail(self, cfg: dict, spec: UploadSpec) -> None:
        if not spec.thumbnail:
            self.record(5, "skipped", "no thumbnail configured")
            return
        strict = bool(cfg["thumbnail"].get("strict", get(self.rt.settings, "thumbnail.strict", False)))
        r = validate_thumbnail(spec.thumbnail, strict=strict)
        self.warnings += r.warnings
        if not r.ok:
            self.record(5, "failed", r.errors)
            raise ValidationError("Thumbnail is invalid", r.errors)
        self.record(5, "ok", {k: r.info.get(k) for k in ("format", "width", "height", "bytes")})

    def step6_transcript(self, cfg: dict, *, execute: bool) -> Path | None:
        t = cfg["transcript"]
        if not t.get("enabled"):
            if not execute:
                self.record(6, "skipped", "transcript disabled")
            return None
        source = t.get("source", "file")
        if source == "file":
            f = self.path(t.get("file"))
            r = validate_caption_file(f) if f else None
            if not r or not r.ok:
                errs = r.errors if r else ["transcript.file is required when source is 'file'"]
                self.record(6, "failed", errs)
                raise ValidationError("Transcript file is invalid", errs)
            self.record(6, "ok", r.info)
            return f
        if source == "whisper":
            if not execute:
                ok, why = whisper_available()
                if not ok:
                    self.record(6, "failed", why)
                    raise ValidationError("Transcript source 'whisper' is not available", [why])
                self.record(6, "ok", "whisper available; will transcribe during the real run")
                return None
            video = self.path(cfg["video"]["file"])
            cues = transcribe_with_whisper(video, model=t.get("model", "base"), language=t.get("language"))
            out = ROOT / "data" / "transcripts" / f"{video.stem}.srt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(format_srt(cues), encoding="utf-8")
            self.log.info("pipeline.process_transcript", f"whisper wrote {len(cues)} cues", file=str(out))
            return out
        self.record(6, "failed", f"unknown transcript.source '{source}'")
        raise ValidationError(f"transcript.source must be 'file' or 'whisper', got '{source}'")

    def step7_quota(self, spec: UploadSpec, cfg: dict) -> list[str]:
        calls = planned_calls(spec, verify=True)
        if cfg["transcript"].get("enabled") and cfg["transcript"].get("upload", True):
            calls.append("captions.insert")
        try:
            warnings = self.rt.quota.check(calls)
        except QuotaExceededError as exc:
            self.record(7, "failed", str(exc))
            raise
        self.warnings += warnings
        self.record(7, "ok", {"calls": calls, "estimate": self.rt.quota.estimate(calls).by_bucket})
        return calls

    def step8_state(self, spec: UploadSpec) -> None:
        sha = sha256_file(spec.file)
        job_id = make_job_id(sha, spec.idempotency_key)
        job = self.rt.store.load(job_id)
        previous = self.rt.store.find_upload(sha)
        if job is None:
            job = self.rt.store.create(job_id, file=str(spec.file), file_sha256=sha, file_bytes=spec.file.stat().st_size,
                                       title=spec.title, config=str(self.config_path))
        job["spec"] = {**spec.metadata(), "file": str(spec.file), "thumbnail": str(spec.thumbnail) if spec.thumbnail else None,
                       "default_language": spec.default_language, "idempotency_key": spec.idempotency_key}
        self.rt.store.save(job)
        self.job = job
        detail = {"job_id": job_id, "status": job["status"], "video_id": job.get("video_id")}
        if previous and previous.get("job_id") != job_id:
            detail["already_uploaded_elsewhere"] = previous
            self.warnings.append(f"state: this file was already uploaded as {previous['video_id']} (job {previous.get('job_id')}); upload will be refused without --force-reupload")
        if job["status"] in ("UPLOAD_UNCERTAIN", "UPLOADING"):
            self.warnings.append("state: a previous upload was interrupted; the real run will resume/verify it before anything else")
        if job["status"] == "NEEDS_MANUAL_CHECK":
            self.warnings.append("state: job NEEDS_MANUAL_CHECK — check YouTube Studio, then use state_manager.py resolve or --force-reupload")
        self.record(8, "ok", detail)

    def step9_upload(self, spec: UploadSpec, force_reupload: bool) -> None:
        assert self.job is not None
        if self.job.get("video_id") and not force_reupload:
            self.record(9, "skipped", f"already uploaded as {self.job['video_id']}")
            return
        chunk = int(get(self.rt.settings, "upload.chunk_size_mb", 8)) * 1024 * 1024

        def progress(done: int, total: int) -> None:
            print(f"  uploaded {done / total:6.1%}", file=sys.stderr)

        try:
            self.job, video = run_upload(self.client, self.rt.store, spec, job=self.job, chunk_size=chunk,
                                         force_reupload=force_reupload, on_progress=progress)
        except YTAOSError as exc:
            self.record(9, "failed", str(exc)[:300])
            raise
        self.record(9, "ok", {"video_id": video["id"]})

    def step10_verify_id(self) -> None:
        vid = self.job.get("video_id") if self.job else None
        if not vid or not isinstance(vid, str):
            self.record(10, "failed", "no video ID")
            raise ValidationError("Upload produced no video ID")
        self.record(10, "ok", vid)

    def step11_assets(self, spec: UploadSpec, cfg: dict, captions_file: Path | None) -> None:
        assert self.job is not None
        vid = self.job["video_id"]
        results: dict = {}
        if spec.thumbnail:
            if self.job.get("thumbnail_set_for") == vid:
                results["thumbnail"] = "skipped (already set)"
            else:
                try:
                    mime = validate_thumbnail(spec.thumbnail).info["mimetype"]
                    self.client.set_thumbnail(vid, spec.thumbnail, mime)
                    self.job["thumbnail_set_for"] = vid
                    self.rt.store.transition(self.job, "THUMBNAIL_SET", "thumbnail applied")
                    results["thumbnail"] = "set"
                except QuotaExceededError:
                    raise
                except YTAOSError as exc:
                    results["thumbnail"] = f"failed: {exc}"[:300]
        t = cfg["transcript"]
        if t.get("enabled") and t.get("upload", True) and captions_file:
            if self.job.get("captions_uploaded_for") == vid:
                results["captions"] = "skipped (already uploaded)"
            else:
                try:
                    track = self.client.insert_caption(vid, t.get("language") or spec.default_language or "id", t.get("name", ""), captions_file, is_draft=bool(t.get("draft", False)))
                    self.job["captions_uploaded_for"] = vid
                    self.rt.store.save(self.job)
                    results["captions"] = f"uploaded track {track.get('id')}"
                except QuotaExceededError:
                    raise
                except YTAOSError as exc:
                    results["captions"] = f"failed: {exc}"[:300]
        failed = any(str(v).startswith("failed") for v in results.values())
        self.record(11, "failed" if failed else ("ok" if results else "skipped"), results or "no assets configured")

    def step12_verify(self, spec: UploadSpec) -> bool:
        report = verify_video(self.client, self.job["video_id"], spec)
        self.job["verification"] = report
        if report["ok"]:
            self.rt.store.transition(self.job, "VERIFIED", "remote settings match")
        self.warnings += [f"verify: {n}" for n in report["notes"]]
        self.record(12, "ok" if report["ok"] else "failed", report)
        return report["ok"]

    def finish(self, spec: UploadSpec, *, mode: str, calls: list[str]) -> dict:
        if mode != "execute":
            self.record(13, "ok" if self.job else "skipped", "local job state saved" if self.job else None)
        report = {
            "mode": mode,
            "config": str(self.config_path),
            "job_id": self.job["job_id"] if self.job else None,
            "job_status": self.job["status"] if self.job else None,
            "video_id": self.job.get("video_id") if self.job else None,
            "url": f"https://youtu.be/{self.job['video_id']}" if self.job and self.job.get("video_id") else None,
            "request_body": spec.body(),
            "planned_calls": calls,
            "quota": self.rt.quota.report(),
            "warnings": self.warnings,
            "steps": self.steps,
            "request_id": self.rt.request_id,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        reports = self.rt.state_dir / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = reports / f"{report['job_id'] or 'pipeline'}-{mode}-{stamp}.json"
        report["report_file"] = str(out)
        self.steps.append({"n": 14, "name": "report", "status": "ok", "detail": str(out)})
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return report


def human(r: dict) -> str:
    lines = [f"Pipeline {r['mode'].upper()}  job={r['job_id']}  status={r['job_status']}"]
    for s in r["steps"]:
        mark = {"ok": "✓", "skipped": "-", "dry_run": "~", "warning": "!", "failed": "✗", "refused": "✗"}.get(s["status"], "?")
        detail = s.get("detail")
        short = detail if isinstance(detail, str) else (json.dumps(detail, ensure_ascii=False, default=str)[:140] if detail is not None else "")
        lines.append(f" {mark} {s['n']:>2} {s['name']:<20} {s['status']:<8} {short}")
    if r.get("url"):
        lines.append(f"Video: {r['url']}")
    for w in r["warnings"]:
        lines.append(f"warning: {w}")
    lines.append(f"Report: {r['report_file']}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", required=True, help="Pipeline YAML (see examples/sample_pipeline.yaml)")
    p.add_argument("--force-reupload", action="store_true", help="Upload even if this file was uploaded before (creates a second video)")
    cli.add_safety_flags(p)
    cli.add_output_flags(p)
    args = p.parse_args()
    rt = cli.runtime()
    report = Pipeline(args.config, rt).run(dry_run=args.dry_run, confirm=args.confirm, force_reupload=args.force_reupload)
    cli.emit(report, args.json, human)
    return report.get("exit_code", 0)


if __name__ == "__main__":
    cli.run(main)
