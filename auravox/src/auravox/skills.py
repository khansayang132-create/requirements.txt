"""Skills installer for Claude Code and Codex: inspect, verify, back up, install, register, test, roll back.

Formats (they are not assumed identical):
  claude  <project>/.claude/skills/<name>/SKILL.md      YAML front matter with `name` and `description` (Agent Skills)
  codex   <project>/.codex/skills/<name>/SKILL.md       same SKILL.md layout as Codex's skills support; plus a pointer
                                                         line in <project>/AGENTS.md, which Codex always reads
A skill is refused when its scripts contain dangerous operations, when its front matter is invalid, or when it would
overwrite an existing skill without --replace (the old one is backed up first and can be restored by rollback).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

DANGEROUS = [
    (r"curl[^|\n]*\|\s*(ba)?sh", "pipes a download straight into a shell"),
    (r"wget[^|\n]*\|\s*(ba)?sh", "pipes a download straight into a shell"),
    (r"rm\s+-rf\s+(/|~|\$HOME)(\s|$)", "deletes the root or home directory"),
    (r"\bsudo\b", "asks for root"),
    (r"chmod\s+(-R\s+)?777", "makes files world-writable"),
    (r"base64\s+(-d|--decode)[^\n]*\|\s*(ba)?sh", "runs an encoded payload"),
    (r"(~|\$HOME)/\.ssh|id_rsa|authorized_keys", "touches SSH keys"),
    (r"\.aws/credentials|\.netrc|\.git-credentials", "reads stored credentials"),
    (r"eval\s*\(\s*(requests|urllib|fetch)", "executes code fetched from the network"),
    (r"exec\(\s*(urllib|requests)", "executes code fetched from the network"),
    (r"pip\s+install\s+(https?://|git\+)", "installs an unpinned package from a URL"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb"),
    (r"(nc|ncat|netcat)\s+-[a-z]*e\s", "opens a reverse shell"),
    (r"crontab\s+-r|>\s*/etc/", "modifies system configuration"),
]
TEXT = {".py", ".sh", ".bash", ".js", ".ts", ".mjs", ".md", ".json", ".toml", ".yaml", ".yml", ".ps1", ".bat", ".txt"}


def tree_sha(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(str(p.relative_to(path)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def front_matter(skill_md: Path) -> dict:
    t = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", t, re.S)
    if not m:
        return {}
    fm, key = {}, None
    for ln in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_-]+):\s*(.*)$", ln)
        if km:
            key = km.group(1)
            fm[key] = km.group(2).strip().strip("'\"") if km.group(2).strip() not in (">", "|", ">-", "|-") else ""
        elif key and ln.startswith(" "):
            fm[key] = (fm[key] + " " + ln.strip()).strip()
    return fm


def provenance(src: Path) -> dict:
    p = {"path": str(src.resolve()), "tree_sha256": tree_sha(src)}
    r = subprocess.run(["git", "-C", str(src), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if r.returncode == 0:
        top = r.stdout.strip()
        p["git_root"] = top
        p["git_commit"] = subprocess.run(["git", "-C", top, "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
        p["git_remote"] = subprocess.run(["git", "-C", top, "remote", "get-url", "origin"], capture_output=True, text=True, check=False).stdout.strip()
        dirty = subprocess.run(["git", "-C", top, "status", "--porcelain", "--", str(src)], capture_output=True, text=True, check=False).stdout.strip()
        p["uncommitted_changes"] = bool(dirty)
    return p


def scan(src: Path) -> dict:
    src = Path(src)
    rep = {"source": str(src), "errors": [], "warnings": [], "findings": [], "files": 0, "dependencies": []}
    sk = src / "SKILL.md"
    if not sk.is_file():
        rep["errors"].append("no SKILL.md")
        return rep | {"ok": False}
    fm = front_matter(sk)
    rep["front_matter"] = fm
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", fm.get("name", "")):
        rep["errors"].append("front matter `name` missing or not lowercase-hyphen (<= 64 chars)")
    if not fm.get("description") or len(fm["description"]) > 1024:
        rep["errors"].append("front matter `description` missing or longer than 1024 characters")
    if len(sk.read_text().splitlines()) > 500:
        rep["warnings"].append("SKILL.md longer than 500 lines (move detail into references/)")
    for p in sorted(src.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        rep["files"] += 1
        if p.suffix.lower() not in TEXT:
            if p.stat().st_mode & 0o111 and p.suffix == "":
                rep["warnings"].append(f"executable binary {p.relative_to(src)} cannot be inspected")
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for pat, why in DANGEROUS:
            for m in re.finditer(pat, text):
                line = text[: m.start()].count("\n") + 1
                rep["findings"].append({"file": str(p.relative_to(src)), "line": line, "match": m.group(0)[:80], "why": why})
        if p.name in ("requirements.txt",):
            rep["dependencies"] += [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    for d in rep["dependencies"]:
        if not re.search(r"==|>=|~=", d):
            rep["warnings"].append(f"unpinned dependency {d}")
    rep["ok"] = not rep["errors"] and not rep["findings"]
    return rep


def _dest(target: str, project: Path, name: str) -> Path:
    return project / (".claude" if target == "claude" else ".codex") / "skills" / name


def install(studio, src: Path, target: str, project: Path, replace: bool = False, test: bool = True) -> dict:
    rep = scan(src)
    name = rep.get("front_matter", {}).get("name") or src.name
    if not rep["ok"]:
        studio.db.insert("skills", {"name": name, "target": target, "path": None, "source": str(src), "provenance": provenance(src) if src.exists() else {},
                                    "status": "REFUSED", "report": rep, "installed_at": time.time()})
        return {"status": "REFUSED", "name": name, "errors": rep["errors"], "findings": rep["findings"]}
    dest = _dest(target, project, name)
    backup = None
    if dest.exists():
        if not replace:
            return {"status": "REFUSED", "name": name, "errors": [f"{dest} already exists (use --replace; it will be backed up)"]}
        backup = studio.home / "skill-backups" / f"{target}-{name}-{int(time.time())}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dest, backup)
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
    pointer = None
    if target == "codex":
        agents = project / "AGENTS.md"
        line = f"- Skill `{name}`: read `.codex/skills/{name}/SKILL.md` when the task matches: {rep['front_matter']['description'][:160]}"
        old = agents.read_text() if agents.exists() else ""
        if f".codex/skills/{name}/SKILL.md" not in old:
            if agents.exists():                                   # keep the previous AGENTS.md
                bdir = studio.home / "skill-backups"
                bdir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(agents, bdir / f"AGENTS.md.{int(time.time())}")
            agents.write_text(old + ("" if old.endswith("\n") or not old else "\n") + ("\n## Skills\n" if "## Skills" not in old else "") + line + "\n")
            pointer = str(agents)
    ok_copy = tree_sha(dest) == tree_sha(src)
    tests = {"files_match_source": ok_copy, "front_matter_valid": True}
    tests.update(test_invocation(target, project, name) if test else {"invocation": "NOT TESTED", "why": "host test skipped"})
    status = "PASS" if ok_copy and tests.get("invocation") in ("PASS", "NOT TESTED") else "FAIL"
    studio.db.insert("skills", {"name": name, "target": target, "path": str(dest), "source": str(src), "provenance": provenance(src), "status": status,
                                "backup": str(backup) if backup else None, "report": rep | {"tests": tests, "agents_md": pointer}, "installed_at": time.time()})
    return {"status": status, "name": name, "path": str(dest), "backup": str(backup) if backup else None, "tests": tests, "warnings": rep["warnings"]}


def test_invocation(target: str, project: Path, name: str) -> dict:
    """Ask the real host whether it can see the skill. Without the host CLI this is NOT TESTED, never PASS."""
    if target == "claude":
        if not shutil.which("claude"):
            return {"invocation": "NOT TESTED", "why": "claude CLI not on PATH"}
        try:
            r = subprocess.run(["claude", "-p", "List the names of the skills available to you in this project, one per line, nothing else."],
                               cwd=project, capture_output=True, text=True, timeout=180, check=False)
        except subprocess.TimeoutExpired:
            return {"invocation": "NOT TESTED", "why": "claude -p timed out"}
        if r.returncode != 0:
            return {"invocation": "NOT TESTED", "why": f"claude -p exit {r.returncode}: {(r.stderr or r.stdout)[:200]}"}
        return {"invocation": "PASS" if name in r.stdout else "FAIL", "host_reply": r.stdout[:600]}
    if not shutil.which("codex"):
        return {"invocation": "NOT TESTED", "why": "codex CLI not on PATH"}
    r = subprocess.run(["codex", "exec", "List the skills you can use in this repository, names only."], cwd=project, capture_output=True,
                       text=True, timeout=180, check=False)
    return {"invocation": "PASS" if name in r.stdout else "FAIL", "host_reply": r.stdout[:600]}


def rollback(studio, name: str, target: str, project: Path) -> dict:
    row = studio.db.one("SELECT * FROM skills WHERE name=? AND target=?", (name, target))
    if not row:
        return {"status": "NOT FOUND"}
    dest = _dest(target, project, name)
    if dest.exists():
        shutil.rmtree(dest)
    restored = None
    if row["backup"] and Path(row["backup"]).exists():
        shutil.copytree(row["backup"], dest)
        restored = row["backup"]
    if target == "codex" and (project / "AGENTS.md").exists():
        t = (project / "AGENTS.md").read_text()
        (project / "AGENTS.md").write_text("\n".join(ln for ln in t.splitlines() if f".codex/skills/{name}/SKILL.md" not in ln) + "\n")
    studio.db.update("skills", "name", name, status="ROLLED_BACK")
    return {"status": "ROLLED_BACK", "restored_backup": restored}


def registry_json(studio) -> str:
    return json.dumps(studio.db.q("SELECT name, target, path, status FROM skills"), indent=2)
