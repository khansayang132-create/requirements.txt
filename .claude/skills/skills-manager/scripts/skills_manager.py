#!/usr/bin/env python3
"""Skills manager: discover, evaluate, install, verify and remove Claude Code skills.

Usage: python3 skills_manager.py <command> [args]   (run with --help for the full list)

What is real here:
- Discovery reads SKILL.md files from the folders Claude Code actually scans (project `.claude/skills/`,
  user `~/.claude/skills/`, claude.ai-synced skills), other local catalogs (Codex `.agents/skills/`,
  HarnessFlow), and git repos listed in `.claude/skills-manager/config.json` (shallow clones in a cache).
- Install copies a skill folder into a Claude Code skill root. It never runs anything from the skill:
  clones are made with hooks disabled, scripts are scanned statically, and the copy is atomic.
- `verify --live` asks the real `claude` CLI which skills it discovered; `--load` makes it invoke the skill.

Status words follow apex/STATUS.md: PASS, FAIL, BLOCKED, NOT RUN. Nothing is reported as PASS without a check.
Stdlib only, Python 3.8+.
"""
import argparse
import ast
import datetime
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
SCRIPT_EXTS = {".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".ps1"}
TEXT_LIMIT = 2_000_000  # bytes read per file when scanning
SEVERITY = {"none": 0, "info": 1, "low": 2, "medium": 3, "high": 4}

# (severity, id, regex, message, where): where is "code" (scripts), "doc" (markdown) or "any".
SCAN_RULES = [
    ("high", "PIPE_TO_SHELL", r"(?:curl|wget)\b[^\n|;]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b", "downloads and pipes into a shell", "any"),
    ("high", "DESTRUCTIVE_RM", r"\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(?:/|~|\$HOME|/\*)(?:\s|$|[\"'])", "recursive delete of / or home", "any"),
    ("high", "CREDENTIAL_PATH", r"(?:\.ssh/|id_rsa|id_ed25519|\.aws/credentials|\.netrc|\.git-credentials|/etc/shadow|\.config/gh/hosts)", "touches credential files", "any"),
    ("high", "ENCODED_EXEC", r"base64\s+(?:-d|--decode)[^\n]*\|\s*(?:ba)?sh|exec\(\s*(?:base64|codecs)|eval\(\s*atob\(", "decodes and executes hidden code", "any"),
    ("high", "BYPASS_PERMISSIONS", r"dangerously-skip-permissions|bypassPermissions|--no-sandbox-guard", "tries to bypass agent permissions", "any"),
    ("high", "PROMPT_INJECTION", r"ignore (?:all )?(?:previous|prior|above) instructions|(?:do not|don't) (?:tell|inform) the user (?:about|that you|what you)|without (?:telling|asking|informing) the user|(?:hide|conceal|keep) (?:this|it|them) (?:secret )?from the user", "instructs the agent to hide actions or drop its rules", "doc"),
    ("high", "EXFILTRATION", r"exfiltrat|send (?:the )?(?:api keys?|tokens?|secrets?|credentials) to", "asks to send secrets out", "doc"),
    ("medium", "NETWORK", r"\brequests\.(?:get|post|put)|urllib\.request|http\.client|\bfetch\(|\bcurl\s|\bwget\s|\bsocket\.", "network access", "code"),
    ("medium", "SHELL_EXEC", r"\bsubprocess\.|\bos\.system\(|\bos\.popen\(|child_process|\bexecSync\(|\bspawn\(", "runs external commands", "code"),
    ("medium", "DYNAMIC_EVAL", r"(?<![\w.])(?:eval|exec)\(", "evaluates dynamic code", "code"),
    ("medium", "PRIVILEGE", r"\bsudo\s|chmod\s+(?:-R\s+)?777|\bsetuid\b", "asks for elevated privileges", "any"),
    ("medium", "PERSISTENCE", r"\.bashrc|\.zshrc|\.profile\b|crontab\s|systemctl\s+enable|launchctl\s", "changes shell startup or schedules jobs", "any"),
    ("medium", "RUNTIME_INSTALL", r"\bpip3?\s+install\b|\bnpm\s+(?:i|install)\s+-g\b|\bapt(?:-get)?\s+install\b", "installs packages at runtime", "code"),
    ("low", "ENV_READ", r"os\.environ|process\.env|\bgetenv\(", "reads environment variables", "code"),
]
SCAN_RULES = [(s, i, re.compile(rx, re.I), m, w) for s, i, rx, m, w in SCAN_RULES]
URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
# A high match in a sentence that warns against the thing ("Never run `curl | sh`") or in a code comment is
# downgraded to medium, never lower: it still needs a human look and --accept-risk. Adding "never" can't sneak a skill through.
DEFENSIVE_RE = re.compile(r"\b(?:never|must not|mustn't|should not|shouldn't|don't|do not (?!tell|inform)|cannot|can't|not allowed|"
                          r"such as|looks like|for example|refuse|reject|guard|prevent)\b|\be\.g\.", re.I)
COMMENT_RE = re.compile(r"^\s*(?://|#|\*|/\*|--)")
# Env-reading scripts that only talk to these hosts call a vendor API with the user's own key: medium, not exfiltration.
FIRST_PARTY_HOSTS = {"api.anthropic.com", "api.openai.com", "api.github.com", "localhost", "127.0.0.1", "api.elevenlabs.io"}

STOPWORDS = set("a about against all also an and any are as at be best build by can create do first for from get help how i in into "
                "is it make me my need new of on or plus real some something that the them then this to up use using want we "
                "when with write you your".split())
# Small, explicit synonym map so "testing" also finds "playwright"-style skills. Extend in config.json → "synonyms".
SYNONYMS = {
    "test": ["testing", "pytest", "qa"], "browser": ["playwright", "web", "webapp"], "ui": ["frontend", "design", "interface"],
    "design": ["ui", "frontend", "visual"], "git": ["github", "commit", "pr"], "deploy": ["deployment", "release"],
    "security": ["audit", "vulnerability", "secure"], "debug": ["debugging", "bug", "fix"], "api": ["mcp", "integration", "sdk"],
    "doc": ["document", "docx", "word"], "slide": ["pptx", "presentation", "deck"], "spreadsheet": ["xlsx", "excel"],
    "deck": ["pptx", "slide", "presentation"], "powerpoint": ["pptx"], "excel": ["xlsx"], "word": ["docx"],
    "python": ["py", "pytest"], "video": ["ffmpeg", "render"], "plan": ["planning", "spec"],
}


# ---------------------------------------------------------------- paths & config

def project_root(start=None):
    p = Path(start or os.environ.get("SKILLS_MANAGER_PROJECT") or Path.cwd()).resolve()
    for d in [p, *p.parents]:
        if (d / ".claude").is_dir() or (d / ".git").exists():
            return d
    return p


def home():
    return Path(os.environ.get("SKILLS_MANAGER_HOME") or Path.home())


def scope_base(scope, root):
    return (root / ".claude") if scope == "project" else (home() / ".claude")


def state_dir(scope, root):
    return scope_base(scope, root) / "skills-manager"


def cache_dir():
    return Path(os.environ.get("SKILLS_MANAGER_CACHE") or home() / ".cache" / "skills-manager")


DEFAULT_CONFIG = {
    "sources": [],
    "policy": {"block_risk": "high", "confirm_risk": "medium", "max_installs_per_day": 5, "default_scope": "project"},
    "synonyms": {},
}


def load_config(root):
    path = state_dir("project", root) / "config.json"
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path.exists():
        data = json.loads(path.read_text())
        cfg["sources"] = data.get("sources", [])
        cfg["policy"].update(data.get("policy", {}))
        cfg["synonyms"] = data.get("synonyms", {})
    return cfg


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def load_registry(scope, root):
    path = state_dir(scope, root) / "registry.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"schema": 1, "installed": {}, "failed": []}


def save_registry(reg, scope, root):
    d = state_dir(scope, root)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "registry.json.tmp"
    tmp.write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n")
    tmp.replace(d / "registry.json")


def log_history(scope, root, action, name, result, **details):
    d = state_dir(scope, root)
    d.mkdir(parents=True, exist_ok=True)
    entry = {"ts": now(), "action": action, "name": name, "result": result, **details}
    with open(d / "history.jsonl", "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def read_history(scope, root):
    path = state_dir(scope, root) / "history.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------- SKILL.md parsing & validation

def parse_frontmatter(text):
    """Parse the YAML subset SKILL.md files use: scalars, quoted strings, block scalars (| >), nested maps kept raw.
    Returns (dict, errors)."""
    if not text.startswith("---"):
        return {}, ["SKILL.md does not start with a --- frontmatter block"]
    end = re.search(r"^---\s*$", text[3:], re.M)
    if not end:
        return {}, ["frontmatter block is not closed with ---"]
    lines = text[3:3 + end.start()].splitlines()
    meta, errors, i = {}, [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not m:
            errors.append(f"frontmatter line {i + 1} is not 'key: value': {line[:60]!r}")
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        i += 1
        block = []
        while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
            block.append(lines[i].strip())
            i += 1
        if val in ("|", ">", "|-", ">-", ""):
            joiner = "\n" if val.startswith("|") else " "
            val = joiner.join(b for b in block if b) if val else (block and "\n".join(block) or "")
        elif len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        meta[key] = val
    return meta, errors


def validate(meta, dirname):
    """Errors block an install; warnings don't. Rules from the Agent Skills spec (name/description limits)."""
    errors, warnings = [], []
    name, desc = meta.get("name", ""), meta.get("description", "")
    if not name:
        errors.append("missing 'name'")
    elif not NAME_RE.match(name) or len(name) > 64:
        errors.append(f"name {name!r} must be lowercase letters/digits/hyphens, ≤64 chars")
    if not desc:
        errors.append("missing 'description'")
    elif len(desc) > 1024:
        errors.append(f"description is {len(desc)} chars (max 1024)")
    if name and dirname and name != dirname:
        warnings.append(f"name {name!r} differs from folder {dirname!r}; Claude Code uses the name")
    if name and re.search(r"anthropic|claude", name):
        warnings.append("name contains a reserved word (anthropic/claude); the Claude API rejects it on upload")
    return errors, warnings


def read_skill(skill_dir):
    skill_md = skill_dir / "SKILL.md"
    text = skill_md.read_text(errors="replace")
    meta, perrs = parse_frontmatter(text)
    errors, warnings = validate(meta, skill_dir.name)
    return meta, perrs + errors, warnings


# ---------------------------------------------------------------- hashing

def file_hashes(skill_dir):
    out = {}
    for p in sorted(walk(skill_dir)):
        rel = p.relative_to(skill_dir).as_posix()
        if p.is_symlink():
            out[rel] = "symlink:" + os.readlink(p)
        else:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def content_hash(hashes):
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def walk(d):
    for dirpath, dirnames, filenames in os.walk(d, followlinks=False):
        dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
        base = Path(dirpath)
        for n in filenames:
            yield base / n
        for n in dirnames:
            if (base / n).is_symlink():
                yield base / n


# ---------------------------------------------------------------- security scan

def scan(skill_dir):
    """Static scan. Never executes anything. Returns {risk, findings, scripts, hosts, binaries, symlinks}."""
    skill_dir = skill_dir.resolve()
    findings, scripts, hosts, binaries, symlinks = [], [], set(), [], []

    def add(sev, rid, rel, line, msg):
        findings.append({"severity": sev, "rule": rid, "file": rel, "line": line, "message": msg})

    self_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for p in walk(skill_dir):
        rel = p.relative_to(skill_dir).as_posix()
        if p.is_symlink():
            target = (p.parent / os.readlink(p)).resolve()
            symlinks.append(rel)
            if skill_dir not in target.parents and target != skill_dir:
                add("high", "SYMLINK_ESCAPE", rel, 0, f"symlink points outside the skill ({os.readlink(p)})")
            continue
        raw = p.read_bytes()
        size, data = len(raw), raw[:TEXT_LIMIT]
        if b"\0" in data[:8192]:
            binaries.append(rel)
            if os.access(p, os.X_OK):
                add("high", "BINARY_EXECUTABLE", rel, 0, "executable binary; can't be reviewed")
            continue
        if size > 1_000_000:
            add("info", "LARGE_FILE", rel, 0, f"{size // 1024} KB file")
        is_code = p.suffix.lower() in SCRIPT_EXTS or data.startswith(b"#!")
        if is_code:
            scripts.append(rel)
        if hashlib.sha256(raw).hexdigest() == self_hash:
            add("info", "SCANNER_ITSELF", rel, 0, "byte-identical to this scanner; its rule table isn't scanned against itself")
            continue
        is_doc = p.suffix.lower() in {".md", ".mdx", ".txt"}
        text = data.decode("utf-8", "replace")
        for n, line in enumerate(text.splitlines(), 1):
            for host in URL_RE.findall(line):
                hosts.add(host.lower())
            for sev, rid, rx, msg, where in SCAN_RULES:
                if where == "code" and not is_code:
                    continue
                if where == "doc" and not is_doc:
                    continue
                if rx.search(line):
                    if sev == "high" and ((is_doc and DEFENSIVE_RE.search(line)) or (is_code and COMMENT_RE.match(line))):
                        add("medium", rid, rel, n, msg + " (in a warning or comment; check the context)")
                    else:
                        add(sev, rid, rel, n, msg)
        if is_code and re.search(r"os\.environ|process\.env", text) and re.search(r"requests\.post|urllib\.request|fetch\(|curl\s", text):
            file_hosts = {h.lower() for h in URL_RE.findall(text)}
            first_party = file_hosts and file_hosts <= FIRST_PARTY_HOSTS
            add("medium" if first_party else "high", "SECRET_EXFIL", rel, 0,
                "reads environment variables and sends network requests" +
                (f" (only to {', '.join(sorted(file_hosts))})" if first_party else " to unrecognised hosts"))
    # one finding per rule per file is enough to judge; keep the most severe line
    worst = {}
    for f in findings:
        k = (f["rule"], f["file"])
        if k not in worst or SEVERITY[f["severity"]] > SEVERITY[worst[k]["severity"]]:
            worst[k] = f
    uniq = list(worst.values())
    risk = max((f["severity"] for f in uniq), key=SEVERITY.get, default="none")
    if scripts and SEVERITY[risk] < SEVERITY["low"]:
        risk = "low"  # executable content is never "none"
    return {"risk": risk, "findings": uniq, "scripts": sorted(scripts), "hosts": sorted(hosts),
            "binaries": sorted(binaries), "symlinks": sorted(symlinks)}


def dependencies(skill_dir, scripts):
    """Interpreters and Python imports the skill's scripts need, and which are missing here."""
    interp, imports, dep_files = set(), set(), []
    for rel in scripts:
        ext = Path(rel).suffix.lower()
        interp.add({".py": "python3", ".js": "node", ".mjs": "node", ".cjs": "node", ".ts": "node",
                    ".rb": "ruby", ".pl": "perl", ".ps1": "pwsh"}.get(ext, "bash"))
        if ext == ".py":
            try:
                tree = ast.parse((skill_dir / rel).read_text(errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    imports.add(node.module.split(".")[0])
    for f in ("requirements.txt", "package.json", "pyproject.toml"):
        if (skill_dir / f).exists():
            dep_files.append(f)
    local = {Path(s).stem for s in scripts}
    std = getattr(sys, "stdlib_module_names", set())
    third = sorted(m for m in imports if m not in std and m not in local)
    missing = sorted([i for i in interp if not shutil.which(i)] +
                     [m for m in third if importlib.util.find_spec(m) is None])
    return {"interpreters": sorted(interp), "python_imports": third, "dependency_files": dep_files, "missing": missing}


# ---------------------------------------------------------------- discovery

def local_roots(root):
    """(scope, path, discoverable_by) for every local place skills live."""
    h = home() / ".claude" / "skills"
    roots = [("project", root / ".claude" / "skills", "claude-code"), ("user", h, "claude-code")]
    synced = h / "synced"
    if synced.is_dir():
        roots += [("synced", d, "claude-code") for d in sorted(synced.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    roots += [("codex", root / ".agents" / "skills", "codex"),
              ("harnessflow", root / ".github" / "HarnessFlow" / "skills", "harnessflow-workflows")]
    return roots


def skill_record(skill_dir, source, source_type, scope=None, discoverable_by=None, version=None, url=None):
    meta, errors, warnings = read_skill(skill_dir)
    return {
        "name": meta.get("name") or skill_dir.name, "description": meta.get("description", ""),
        "source": source, "source_type": source_type, "url": url, "path": str(skill_dir),
        "scope": scope, "discoverable_by": discoverable_by, "version": version,
        "license": meta.get("license", ""), "allowed_tools": meta.get("allowed-tools", ""),
        "errors": errors, "warnings": warnings,
    }


def discover_local(root):
    out = []
    for scope, base, by in local_roots(root):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if d.name == "synced" and scope == "user":
                continue
            if (d / "SKILL.md").is_file():
                rec = skill_record(d, f"local:{scope}", "local", scope, by)
                if scope == "synced":
                    rec["invoke_as"] = "anthropic-skills:" + rec["name"]
                rec["version"] = content_hash(file_hashes(d))[:12]
                out.append(rec)
    return out


def git(*args, cwd=None, timeout=180):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never", *args],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def source_checkout(src, refresh=False):
    """Shallow clone (or refresh) a configured git source into the cache. Returns (path, commit, error)."""
    dest = cache_dir() / src["id"]
    try:
        if not (dest / ".git").is_dir():
            dest.parent.mkdir(parents=True, exist_ok=True)
            r = git("clone", "-q", "--depth", "1", "--no-recurse-submodules", *(["--branch", src["ref"]] if src.get("ref") else []),
                    src["url"], str(dest))
            if r.returncode:
                shutil.rmtree(dest, ignore_errors=True)
                return None, None, r.stderr.strip()[-300:]
        elif refresh and not src.get("commit"):
            r = git("fetch", "-q", "--depth", "1", "origin", src.get("ref") or "HEAD", cwd=dest)
            if r.returncode:
                return dest, git("rev-parse", "HEAD", cwd=dest).stdout.strip(), "refresh failed: " + r.stderr.strip()[-200:]
            git("reset", "-q", "--hard", "FETCH_HEAD", cwd=dest)
        pin = src.get("commit")
        if pin and git("rev-parse", "HEAD", cwd=dest).stdout.strip() != pin:
            # A pinned source stays on that exact commit, refresh or not; moving it is a config.json change.
            r = git("fetch", "-q", "--depth", "1", "origin", pin, cwd=dest)
            if r.returncode or git("checkout", "-q", "--detach", "FETCH_HEAD", cwd=dest).returncode:
                return None, None, f"pinned commit {pin[:12]} not fetchable: " + r.stderr.strip()[-200:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, None, str(e)
    return dest, git("rev-parse", "HEAD", cwd=dest).stdout.strip(), None


def pin_source(root, source_id, commit=None, clear=False):
    """Pin a source to a commit (default: its current upstream HEAD) in config.json, or clear the pin."""
    path = state_dir("project", root) / "config.json"
    data = json.loads(path.read_text())
    src = next((x for x in data.get("sources", []) if x["id"] == source_id), None)
    if not src:
        raise Refused(f"no source {source_id!r} in config.json")
    if clear:
        src.pop("commit", None)
    else:
        if not commit:
            r = git("ls-remote", src["url"], src.get("ref") or "HEAD", timeout=30)
            if r.returncode or not r.stdout.strip():
                raise Refused(f"can't read {src['url']} HEAD: {r.stderr.strip()[-150:]}")
            commit = r.stdout.split()[0]
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise Refused("--commit must be a full 40-character SHA")
        src["commit"] = commit
    path.write_text(json.dumps(data, indent=2) + "\n")
    log_history("project", root, "pin", source_id, "PASS", commit=src.get("commit"))
    return {"source": source_id, "commit": src.get("commit")}


def discover_remote(cfg, refresh=False, only=None):
    out, problems = [], []
    for src in cfg["sources"]:
        if only and src["id"] != only:
            continue
        dest, commit, err = source_checkout(src, refresh)
        if err:
            problems.append({"source": src["id"], "error": err})
        if not dest:
            continue
        base = dest / src.get("path", "")
        for skill_md in sorted(base.rglob("SKILL.md")):
            rel_parts = skill_md.relative_to(dest).parts
            if any(p in SKIP_DIRS for p in rel_parts) or len(rel_parts) > 6:
                continue
            d = skill_md.parent
            rec = skill_record(d, src["id"], "git", version=commit, url=src["url"])
            rec["repo_path"] = d.relative_to(dest).as_posix()
            rec["trust"] = src.get("trust", "unknown")
            out.append(rec)
    return out, problems


def mcp_servers(root):
    """MCP servers configured for this project (capabilities, not skills). Read-only."""
    out = []
    path = root / ".mcp.json"
    if path.exists():
        try:
            for name, conf in json.loads(path.read_text()).get("mcpServers", {}).items():
                out.append({"name": name, "command": conf.get("command") or conf.get("url", ""), "file": ".mcp.json"})
        except json.JSONDecodeError as e:
            out.append({"name": "?", "error": f".mcp.json is not valid JSON: {e}"})
    return out


# ---------------------------------------------------------------- search & recommend

def stem(w):
    for suf in ("ing", "ers", "ies", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokens(text):
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def expand(query_terms, cfg):
    syn = {**SYNONYMS, **cfg.get("synonyms", {})}
    out = {}
    for t in query_terms:
        out.setdefault(t, {t})
        for s in syn.get(t, []):
            out[t].add(stem(s))
    return out


def score(rec, groups, idf=None):
    """Name hits outweigh description hits; exact terms outweigh synonyms; idf makes common words ("build") count less."""
    name_t, desc_t = set(tokens(rec["name"].replace("-", " "))), set(tokens(rec["description"]))
    s, covered = 0.0, set()
    for term, alts in groups.items():
        w = (idf or {}).get(term, 1.0)
        if alts & name_t:
            s += w * (3 if term in name_t else 2)
            covered.add(term)
        elif alts & desc_t:
            s += w * (1 if term in desc_t else 0.6)
            covered.add(term)
    return s, covered


def idf_weights(records, groups):
    n = max(len(records), 1)
    docs = [set(tokens(r["name"].replace("-", " ") + " " + r["description"])) for r in records]
    return {t: math.log(1 + n / (1 + sum(1 for d in docs if alts & d))) for t, alts in groups.items()}


TRUST_ORDER = {"installed": 0, "official": 1, "catalogued": 2, "community": 3, "unknown": 4}


def rank(records, query, cfg):
    groups = expand(tokens(query), cfg)
    idf = idf_weights(records, groups)
    hits = []
    for r in records:
        s, cov = score(r, groups, idf)
        if s > 0:
            hits.append({**r, "score": round(s, 2), "covers": sorted(cov), "_gain": {t: idf[t] for t in cov}})
    hits.sort(key=lambda h: (-h["score"], TRUST_ORDER.get("installed" if h["source_type"] == "local" else h.get("trust", "unknown"), 9), h["name"]))
    return hits, list(groups)


def recommend(records, task, cfg, limit=3):
    """Smallest useful set: greedy cover of the task's terms, installed skills preferred over remote ones."""
    hits, terms = rank(records, task, cfg)
    installed_names = {h["name"] for h in hits if h["source_type"] == "local" and h["discoverable_by"] == "claude-code"}
    pick, covered = [], set()

    def gain(h):  # idf-weighted value of the task terms this skill adds; name hits count double
        name_t = set(tokens(h["name"].replace("-", " ")))
        return sum(w * (2 if t in name_t else 1) for t, w in h["_gain"].items() if t not in covered)

    for _ in range(limit):
        cands = [h for h in hits if h not in pick and h["discoverable_by"] in (None, "claude-code")
                 and not (h["source_type"] != "local" and h["name"] in installed_names)]
        best = max(cands, key=lambda h: (round(gain(h), 6), h["source_type"] == "local", h["score"]), default=None)
        # stop when the next skill adds little: a set member must carry real weight, not one stray common word
        if not best or gain(best) < 0.5 * max((gain(p) for p in pick[:1]), default=0) or gain(best) <= 0:
            break
        pick.append(best)
        covered |= set(best["covers"])
    return pick, sorted(set(terms) - covered), hits


# ---------------------------------------------------------------- install / remove / rollback

class Refused(Exception):
    pass


def find_candidate(records, name, source=None):
    c = [r for r in records if r["name"] == name and r["source_type"] == "git" and (not source or r["source"] == source)]
    if not c:
        raise Refused(f"no skill named {name!r} in configured sources" + (f" ({source})" if source else "") + "; try `search`")
    if len(c) > 1:
        raise Refused(f"{name!r} exists in several sources ({', '.join(r['source'] for r in c)}); pass --source")
    return c[0]


def backup(path, scope, root, name):
    dest = state_dir(scope, root) / "backups" / name / datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(path, dest, symlinks=True)
    return dest


def installs_today(root):
    today = now()[:10]  # history timestamps are UTC
    return sum(1 for s in ("project", "user") for h in read_history(s, root)
               if h["action"] == "install" and h["result"] == "PASS" and h["ts"].startswith(today))


def install(root, cfg, name, source=None, scope=None, accept_risk=False, force=False, dry_run=False, reason="", refresh=False):
    scope = scope or cfg["policy"]["default_scope"]
    reg = load_registry(scope, root)
    try:
        if not reason:
            raise Refused("--reason is required: say which task needs this skill (it's kept in history)")
        remote, problems = discover_remote(cfg, refresh=refresh, only=source)
        cand = find_candidate(remote, name, source)
        src_dir = Path(cand["path"])
        if cand["errors"]:
            raise Refused("invalid SKILL.md: " + "; ".join(cand["errors"]))
        report = scan(src_dir)
        deps = dependencies(src_dir, report["scripts"])
        pol = cfg["policy"]
        if SEVERITY[report["risk"]] >= SEVERITY[pol["block_risk"]]:
            raise Refused(f"blocked: risk {report['risk']}: " + "; ".join(f"{f['rule']} {f['file']}" for f in report["findings"] if f["severity"] == report["risk"]))
        if SEVERITY[report["risk"]] >= SEVERITY[pol["confirm_risk"]] and not accept_risk:
            raise Refused(f"risk {report['risk']} ({len(report['findings'])} findings, {len(report['scripts'])} scripts). "
                          "Run `inspect` and get the user's OK, then pass --accept-risk")
        target = scope_base(scope, root) / "skills" / name
        dupes = [r for r in discover_local(root) if r["name"] == name and r["discoverable_by"] == "claude-code" and Path(r["path"]) != target]
        if dupes and not force:
            raise Refused(f"duplicate: {name!r} already discoverable at {dupes[0]['path']} ({dupes[0]['scope']}); pass --force to add another copy")
        if target.exists() and not force:
            raise Refused(f"{target} already exists; pass --force to replace it (a backup is kept)")
        if installs_today(root) >= pol["max_installs_per_day"]:
            raise Refused(f"daily install cap reached ({pol['max_installs_per_day']}); raise policy.max_installs_per_day in config.json if the user agrees")
    except Refused as e:
        if not dry_run:
            reg["failed"] = (reg.get("failed", []) + [{"ts": now(), "name": name, "error": str(e)}])[-20:]
            save_registry(reg, scope, root)
            log_history(scope, root, "install", name, "FAIL", error=str(e), reason=reason)
        raise
    plan = {"name": name, "from": f"{cand['url']}:{cand['repo_path']}@{cand['version'][:12]}", "to": str(target),
            "risk": report["risk"], "findings": len(report["findings"]), "missing_dependencies": deps["missing"]}
    if dry_run:
        return {"dry_run": True, **plan}
    backup_path = None
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=target.parent))
    try:
        stage = tmp / name
        shutil.copytree(src_dir, stage, symlinks=True, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        if target.exists():
            backup_path = backup(target, scope, root, name)
            shutil.rmtree(target)
        stage.replace(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    hashes = file_hashes(target)
    entry = {
        "name": name, "description": cand["description"], "source": cand["source"], "url": cand["url"],
        "repo_path": cand["repo_path"], "commit": cand["version"], "trust": cand["trust"], "license": cand["license"],
        "scope": scope, "path": os.path.relpath(target, root) if scope == "project" else str(target),
        "installed_at": now(), "reason": reason, "compatible": ["claude-code"], "dependencies": deps,
        "security": {"risk": report["risk"], "findings": report["findings"], "scripts": report["scripts"],
                     "hosts": report["hosts"], "accepted_risk": bool(accept_risk)},
        "files": hashes, "content_hash": content_hash(hashes), "backup": str(backup_path) if backup_path else None,
        "verification": {"status": "NOT RUN"},
    }
    reg["installed"][name] = entry
    save_registry(reg, scope, root)
    log_history(scope, root, "install", name, "PASS", commit=cand["version"], risk=report["risk"], reason=reason,
                files=sorted(hashes), backup=entry["backup"])
    return {"installed": True, **plan, "files": sorted(hashes), "backup": entry["backup"]}


def installed_path(entry, root):
    p = Path(entry["path"])
    return p if p.is_absolute() else root / p


def check_name(name):
    if not NAME_RE.match(name or ""):
        raise Refused(f"{name!r} is not a valid skill name")


def remove(root, name, scope, yes=False):
    check_name(name)
    reg = load_registry(scope, root)
    entry = reg["installed"].get(name)
    if not entry:
        raise Refused(f"{name!r} is not managed by skills-manager in {scope} scope; it won't remove skills it didn't install")
    path = installed_path(entry, root)
    if not yes:
        raise Refused(f"would delete {path} (backup kept). Get the user's OK, then pass --yes")
    b = backup(path, scope, root, name) if path.exists() else None
    shutil.rmtree(path, ignore_errors=True)
    reg.setdefault("removed", {})[name] = {**entry, "removed_at": now(), "backup": str(b) if b else None}
    del reg["installed"][name]
    save_registry(reg, scope, root)
    log_history(scope, root, "remove", name, "PASS", backup=str(b) if b else None)
    return {"removed": str(path), "backup": str(b) if b else None}


def rollback(root, name, scope):
    """Restore the newest backup of `name` (made by remove, or by install/update --force replacing it)."""
    check_name(name)
    bdir = state_dir(scope, root) / "backups" / name
    snaps = sorted(bdir.iterdir()) if bdir.is_dir() else []
    if not snaps:
        raise Refused(f"no backup for {name!r} in {scope} scope")
    reg = load_registry(scope, root)
    prev = reg.get("removed", {}).get(name) or reg["installed"].get(name)
    target = scope_base(scope, root) / "skills" / name
    if target.exists():
        backup(target, scope, root, name + ".pre-rollback")
        shutil.rmtree(target)
    shutil.copytree(snaps[-1], target, symlinks=True)
    hashes = file_hashes(target)
    if prev:
        prev = {k: v for k, v in prev.items() if k != "removed_at"}
        prev.update(files=hashes, content_hash=content_hash(hashes), restored_from=str(snaps[-1]), restored_at=now(),
                    verification={"status": "NOT RUN"})
        reg["installed"][name] = prev
        reg.get("removed", {}).pop(name, None)
        save_registry(reg, scope, root)
    log_history(scope, root, "rollback", name, "PASS", restored_from=str(snaps[-1]))
    return {"restored": str(target), "from": str(snaps[-1]), "registry_updated": bool(prev)}


def update(root, cfg, name, scope, yes=False, accept_risk=False):
    reg = load_registry(scope, root)
    entry = reg["installed"].get(name)
    if not entry:
        raise Refused(f"{name!r} is not managed in {scope} scope")
    remote, problems = discover_remote(cfg, refresh=True, only=entry["source"])
    if problems:
        raise Refused(f"could not refresh {entry['source']}: {problems[0]['error']}")
    cand = find_candidate(remote, name, entry["source"])
    new = file_hashes(Path(cand["path"]))
    old = entry["files"]
    changed = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    result = {"name": name, "installed_commit": entry["commit"], "latest_commit": cand["version"], "changed_files": changed}
    pinned = next((x.get("commit") for x in cfg["sources"] if x["id"] == entry["source"]), None)
    if pinned:
        result["pinned"] = pinned
    if not changed:
        return {**result, "status": "up to date"}
    if not yes:
        return {**result, "status": "update available; review the change, get the user's OK, then pass --yes"}
    r = install(root, cfg, name, source=entry["source"], scope=scope, accept_risk=accept_risk, force=True,
                reason=f"update from {entry['commit'][:12]}: {entry.get('reason', '')}")
    return {**result, "status": "updated", **r}


def upgrade(root, cfg, scope="project", yes=False):
    """Bring every pinned source to its upstream HEAD and update the skills installed from it, unattended-safe:
    a source moves only if each managed skill it changes is still valid and scans below policy.confirm_risk.
    Anything else is held for a human, with the reason. New skills are never installed here."""
    reg = load_registry(scope, root)
    report = []
    for src in cfg["sources"]:
        row = {"source": src["id"], "pinned": src.get("commit")}
        if not src.get("commit"):
            report.append({**row, "status": "skipped", "detail": "not pinned; use `update <name>`"})
            continue
        r = git("ls-remote", src["url"], src.get("ref") or "HEAD", timeout=30)
        if r.returncode or not r.stdout.strip():
            report.append({**row, "status": "BLOCKED", "detail": r.stderr.strip()[-150:] or "no HEAD"})
            continue
        head = row["upstream"] = r.stdout.split()[0]
        if head == src["commit"]:
            report.append({**row, "status": "up to date"})
            continue
        remote, problems = discover_remote({**cfg, "sources": [{**src, "commit": head}]}, only=src["id"])
        if problems:
            report.append({**row, "status": "BLOCKED", "detail": problems[0]["error"]})
            continue
        changes, held = [], []
        for e in (e for e in reg["installed"].values() if e["source"] == src["id"]):
            cand = next((c for c in remote if c["name"] == e["name"]), None)
            if not cand:
                held.append({"name": e["name"], "reason": "removed upstream"})
                continue
            new = file_hashes(Path(cand["path"]))
            changed = sorted(k for k in set(e["files"]) | set(new) if e["files"].get(k) != new.get(k))
            if not changed:
                continue
            risk = scan(Path(cand["path"]))["risk"]
            if cand["errors"]:
                held.append({"name": e["name"], "reason": "invalid SKILL.md: " + "; ".join(cand["errors"])})
            elif SEVERITY[risk] >= SEVERITY[cfg["policy"]["confirm_risk"]]:
                held.append({"name": e["name"], "reason": f"new version scans {risk}; run `inspect` and review"})
            else:
                changes.append({"name": e["name"], "changed_files": changed, "risk": risk})
        row.update(changes=changes, held=held)
        if held:
            report.append({**row, "status": "held", "detail": "pin not moved; a human must review the held skills"})
        elif not yes:
            report.append({**row, "status": "would upgrade", "detail": "pass --yes to apply"})
        else:
            pin_source(root, src["id"], head)
            moved = load_config(root)
            for c in changes:
                update(root, moved, c["name"], scope, yes=True)
            cfg = moved
            report.append({**row, "status": "upgraded"})
    log_history(scope, root, "upgrade", "*", "PASS", sources={r["source"]: r["status"] for r in report})
    return report


# ---------------------------------------------------------------- verify / audit / doctor

def check(name, status, detail=""):
    return {"check": name, "status": status, "detail": detail}


def claude_init(root, timeout=120):
    """Ask the real Claude Code CLI which skills it discovers in this project. Returns (skills, error)."""
    if not shutil.which("claude"):
        return None, "claude CLI not found"
    try:
        r = subprocess.run(["claude", "-p", "Reply with OK", "--output-format", "stream-json", "--verbose", "--max-turns", "1"],
                           cwd=root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "claude -p timed out"
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            return ev.get("skills") or [], None
    return None, f"no init event (exit {r.returncode}): {r.stderr.strip()[-200:]}"


def claude_load(root, name, timeout=240):
    """Have Claude Code invoke the skill and confirm a Skill tool call for it happened."""
    prompt = f"Invoke the Skill tool with skill \"{name}\" now, then reply with only the first Markdown heading of its instructions."
    try:
        r = subprocess.run(["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--max-turns", "3",
                            "--allowedTools", "Skill"], cwd=root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "claude -p timed out"
    called, result = False, ""
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        for block in (ev.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill" \
                    and (block.get("input") or {}).get("skill") == name:
                called = True
        if ev.get("type") == "result":
            result = (ev.get("result") or "").strip()
    return called, f"Skill tool called={called}; reply: {result[:120]!r}"


def verify(root, cfg, name, scope, live=False, load=False):
    reg = load_registry(scope, root)
    entry = reg["installed"].get(name)
    checks = []
    if not entry:
        checks.append(check("managed by skills-manager", "FAIL", f"not in {scope} registry"))
        return checks
    path = installed_path(entry, root)
    checks.append(check("files installed", "PASS" if (path / "SKILL.md").is_file() else "FAIL", str(path)))
    if (path / "SKILL.md").is_file():
        current = file_hashes(path)
        drift = sorted(k for k in set(entry["files"]) | set(current) if entry["files"].get(k) != current.get(k))
        checks.append(check("files match registry hashes", "FAIL" if drift else "PASS", ", ".join(drift[:5]) or f"{len(entry['files'])} files"))
        meta, errors, warnings = read_skill(path)
        checks.append(check("SKILL.md valid", "FAIL" if errors else "PASS", "; ".join(errors + warnings)))
        checks.append(check("name matches registry", "PASS" if meta.get("name") == name else "FAIL", meta.get("name", "")))
    expected = scope_base(scope, root) / "skills"
    checks.append(check("location is a Claude Code skill root", "PASS" if path.parent.resolve() == expected.resolve() else "FAIL", str(expected)))
    r = git("ls-remote", entry["url"], "HEAD", timeout=30) if shutil.which("git") else None
    if r is None or r.returncode:
        checks.append(check("source exists", "BLOCKED", (r.stderr.strip()[-150:] if r else "git missing") or "unreachable"))
    else:
        checks.append(check("source exists", "PASS", f"{entry['url']} HEAD {r.stdout.split()[0][:12]}"))
    if entry["dependencies"]["missing"]:
        checks.append(check("dependencies available", "FAIL", "missing: " + ", ".join(entry["dependencies"]["missing"])))
    else:
        checks.append(check("dependencies available", "PASS", ", ".join(entry["dependencies"]["interpreters"]) or "none needed"))
    if live:
        skills, err = claude_init(root)
        if err:
            checks.append(check("Claude Code discovers it", "BLOCKED", err))
        else:
            checks.append(check("Claude Code discovers it", "PASS" if name in skills else "FAIL", f"{len(skills)} skills in init event"))
    else:
        checks.append(check("Claude Code discovers it", "NOT RUN", "pass --live"))
    if load:
        ok, detail = claude_load(root, name)
        checks.append(check("Claude Code loads it", "PASS" if ok else "FAIL", detail))
    else:
        checks.append(check("Claude Code loads it", "NOT RUN", "pass --load"))
    worst = "FAIL" if any(c["status"] == "FAIL" for c in checks) else "PASS"
    entry["verification"] = {"status": worst, "at": now(), "checks": checks}
    save_registry(reg, scope, root)
    log_history(scope, root, "verify", name, worst, live=live, load=load)
    return checks


def audit(root, write=True):
    rows = []
    managed = {s: load_registry(s, root)["installed"] for s in ("project", "user")}
    for rec in discover_local(root):
        d = Path(rec["path"])
        rep = scan(d)
        entry = managed.get(rec["scope"], {}).get(rec["name"]) if rec["scope"] in managed else None
        drift = None
        if entry:
            now_h = file_hashes(d)
            drift = sorted(k for k in set(entry["files"]) | set(now_h) if entry["files"].get(k) != now_h.get(k))
        rows.append({"name": rec["name"], "scope": rec["scope"], "path": rec["path"], "managed": bool(entry),
                     "risk": rep["risk"], "findings": rep["findings"], "scripts": rep["scripts"], "hosts": rep["hosts"],
                     "allowed_tools": rec["allowed_tools"], "errors": rec["errors"], "warnings": rec["warnings"],
                     "hash_drift": drift})
    for scope, inst in managed.items():
        for name, e in inst.items():
            if not (installed_path(e, root) / "SKILL.md").is_file():
                rows.append({"name": name, "scope": scope, "path": e["path"], "managed": True, "risk": "unknown",
                             "errors": ["registered but missing on disk"], "findings": [], "hash_drift": None})
    names = {}
    for r in rows:
        if r["scope"] in ("project", "user"):
            names.setdefault(r["name"], []).append(r["scope"])
    report = {"generated_at": now(), "skills": rows,
              "duplicates": {n: s for n, s in names.items() if len(s) > 1},
              "summary": {lvl: sum(1 for r in rows if r["risk"] == lvl) for lvl in ("none", "info", "low", "medium", "high")}}
    if write:
        out = state_dir("project", root) / "reports" / "skills-audit.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        report["written_to"] = str(out)
    return report


def doctor(root, cfg, live=False):
    checks = [check("python ≥ 3.8", "PASS" if sys.version_info >= (3, 8) else "FAIL", sys.version.split()[0]),
              check("git available", "PASS" if shutil.which("git") else "FAIL", shutil.which("git") or "install git")]
    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        probe = cache_dir() / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        checks.append(check("cache writable", "PASS", str(cache_dir())))
    except OSError as e:
        checks.append(check("cache writable", "FAIL", str(e)))
    cfg_path = state_dir("project", root) / "config.json"
    checks.append(check("config.json present", "PASS" if cfg_path.exists() else "FAIL", str(cfg_path)))
    for src in cfg["sources"]:
        r = git("ls-remote", src["url"], "HEAD", timeout=30) if shutil.which("git") else None
        ok = r is not None and r.returncode == 0
        checks.append(check(f"source {src['id']} reachable", "PASS" if ok else "BLOCKED",
                            r.stdout.split()[0][:12] if ok else (r.stderr.strip()[-150:] if r else "git missing")))
    for scope, base, by in local_roots(root):
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if d.is_symlink() and not d.exists():
                checks.append(check(f"symlink {d}", "FAIL", "broken symlink"))
    for rec in discover_local(root):
        if rec["errors"]:
            checks.append(check(f"skill {rec['name']} ({rec['scope']})", "FAIL", "; ".join(rec["errors"])))
    names = {}
    for rec in discover_local(root):
        if rec["scope"] in ("project", "user"):
            names.setdefault(rec["name"], []).append(rec["scope"])
    dupes = {n: s for n, s in names.items() if len(s) > 1}
    checks.append(check("no duplicate skill names", "FAIL" if dupes else "PASS", json.dumps(dupes) if dupes else ""))
    for scope in ("project", "user"):
        for name, e in load_registry(scope, root)["installed"].items():
            ok = (installed_path(e, root) / "SKILL.md").is_file()
            checks.append(check(f"registry entry {name} ({scope}) on disk", "PASS" if ok else "FAIL", e["path"]))
    checks.append(check("claude CLI available", "PASS" if shutil.which("claude") else "BLOCKED", shutil.which("claude") or "not installed"))
    if live:
        skills, err = claude_init(root)
        checks.append(check("claude -p init event lists skills", "BLOCKED" if err else "PASS", err or f"{len(skills)} skills"))
    for s in mcp_servers(root):
        checks.append(check(f"MCP server {s['name']}", "FAIL" if "error" in s else "PASS", s.get("error") or s["command"]))
    return checks


# ---------------------------------------------------------------- CLI

def all_records(root, cfg, refresh=False, remote=True):
    recs = discover_local(root)
    problems = []
    if remote:
        r, problems = discover_remote(cfg, refresh=refresh)
        recs += r
    return recs, problems


def fmt_rec(r):
    where = r["scope"] if r["source_type"] == "local" else f"{r['source']} ({r.get('trust', '?')})"
    tag = "installed" if r["source_type"] == "local" and r["discoverable_by"] == "claude-code" else "available"
    desc = r["description"].replace("\n", " ")
    return f"  {r['name']:<28} [{tag}: {where}] {desc[:110]}{'…' if len(desc) > 110 else ''}"


def print_checks(checks):
    for c in checks:
        print(f"  {c['status']:<8} {c['check']}" + (f": {c['detail']}" if c["detail"] else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skills_manager.py", description=__doc__.split("\n")[0])
    ap.add_argument("--project", help="project root (default: nearest folder with .claude/ or .git)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search", help="natural-language search across local and configured sources")
    p.add_argument("query", nargs="+"); p.add_argument("--refresh", action="store_true"); p.add_argument("--limit", type=int, default=10)
    p = sub.add_parser("list", help="list installed skills (--all adds skills available from sources)")
    p.add_argument("--all", action="store_true"); p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("recommend", help="smallest set of skills for a task, installed ones first")
    p.add_argument("task", nargs="+"); p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("inspect", help="source, metadata, files, dependencies and security findings")
    p.add_argument("name"); p.add_argument("--source")
    p = sub.add_parser("install", help="install from a configured source (never runs the skill's code)")
    p.add_argument("name"); p.add_argument("--source"); p.add_argument("--scope", choices=["project", "user"])
    p.add_argument("--reason", default=""); p.add_argument("--accept-risk", action="store_true")
    p.add_argument("--force", action="store_true"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("verify", help="check files, hashes, source, deps; --live/--load ask the real claude CLI")
    p.add_argument("name"); p.add_argument("--scope", choices=["project", "user"], default="project")
    p.add_argument("--live", action="store_true"); p.add_argument("--load", action="store_true")
    p = sub.add_parser("update", help="compare with the source; apply only with --yes")
    p.add_argument("name"); p.add_argument("--scope", choices=["project", "user"], default="project")
    p.add_argument("--yes", action="store_true"); p.add_argument("--accept-risk", action="store_true")
    p = sub.add_parser("remove", help="remove a skill this tool installed (backup kept; needs --yes)")
    p.add_argument("name"); p.add_argument("--scope", choices=["project", "user"], default="project"); p.add_argument("--yes", action="store_true")
    p = sub.add_parser("rollback", help="restore the newest backup of a skill")
    p.add_argument("name"); p.add_argument("--scope", choices=["project", "user"], default="project")
    sub.add_parser("audit", help="scan every local skill; writes .claude/skills-manager/reports/skills-audit.json")
    p = sub.add_parser("doctor", help="diagnose config, sources, skill folders and the registry")
    p.add_argument("--live", action="store_true")
    p = sub.add_parser("upgrade", help="move pinned sources to upstream HEAD and update installed skills; low-risk only, --yes applies")
    p.add_argument("--scope", choices=["project", "user"], default="project"); p.add_argument("--yes", action="store_true")
    p = sub.add_parser("pin", help="pin a source to a commit in config.json (default: its current HEAD); --clear unpins")
    p.add_argument("source"); p.add_argument("--commit"); p.add_argument("--clear", action="store_true")
    p = sub.add_parser("note", help="record which skill was used for a task and how it helped")
    p.add_argument("name"); p.add_argument("--task", required=True); p.add_argument("--outcome", required=True)
    p.add_argument("--scope", choices=["project", "user"], default="project")
    a = ap.parse_args(argv)

    root = project_root(a.project)
    cfg = load_config(root)
    def out(obj):
        print(json.dumps(obj, indent=2, default=str))
        return 0
    try:
        if a.cmd == "search":
            recs, problems = all_records(root, cfg, a.refresh)
            hits, _ = rank(recs, " ".join(a.query), cfg)
            hits = [{k: v for k, v in h.items() if k != "_gain"} for h in hits[: a.limit]]
            if a.json:
                return out({"results": hits, "source_problems": problems})
            print(f"{len(hits)} result(s) for {' '.join(a.query)!r}:")
            for h in hits:
                print(fmt_rec(h) + f"  (score {h['score']}; source: {h['url'] or h['path']})")
            for pr in problems:
                print(f"  BLOCKED source {pr['source']}: {pr['error']}")
        elif a.cmd == "list":
            recs, problems = all_records(root, cfg, a.refresh, remote=a.all)
            if a.json:
                return out({"skills": recs, "mcp_servers": mcp_servers(root), "source_problems": problems})
            managed = {n for s in ("project", "user") for n in load_registry(s, root)["installed"]}
            for r in recs:
                print(fmt_rec(r) + ("  [managed]" if r["name"] in managed and r["source_type"] == "local" else ""))
            for s in mcp_servers(root):
                print(f"  MCP server: {s['name']} ({s.get('command', s.get('error'))})")
            for pr in problems:
                print(f"  BLOCKED source {pr['source']}: {pr['error']}")
        elif a.cmd == "recommend":
            recs, problems = all_records(root, cfg, a.refresh)
            pick, uncovered, _ = recommend(recs, " ".join(a.task), cfg)
            if a.json:
                return out({"recommended": [{k: v for k, v in h.items() if k != "_gain"} for h in pick],
                            "uncovered_terms": uncovered, "source_problems": problems})
            print("Recommended (smallest set covering the task):" if pick else "No matching skill.")
            for h in pick:
                action = "already installed, just use it" if h["source_type"] == "local" else f"install: skills_manager.py install {h['name']} --source {h['source']} --reason '...'"
                print(fmt_rec(h) + f"\n      covers {', '.join(h['covers'])} → {action}")
            if uncovered:
                print(f"  Not covered by any known skill: {', '.join(uncovered)}")
        elif a.cmd == "inspect":
            recs, _ = all_records(root, cfg)
            c = [r for r in recs if r["name"] == a.name and (not a.source or r["source"] == a.source)]
            if not c:
                raise Refused(f"no skill named {a.name!r}")
            res = []
            for r in c:
                rep = scan(Path(r["path"]))
                res.append({**r, "security": rep, "dependencies": dependencies(Path(r["path"]), rep["scripts"]),
                            "files": sorted(file_hashes(Path(r["path"])))})
            if a.json:
                return out(res)
            for r in res:
                print(f"{r['name']}  [{r['source']}]  version {str(r['version'])[:12]}")
                print(f"  description: {r['description']}")
                print(f"  location: {r['path']}" + (f"\n  url: {r['url']}  path: {r.get('repo_path')}" if r["url"] else ""))
                print(f"  license: {r['license'] or '-'}   allowed-tools: {r['allowed_tools'] or '-'}   trust: {r.get('trust', 'local')}")
                print(f"  files ({len(r['files'])}): {', '.join(r['files'][:12])}{' …' if len(r['files']) > 12 else ''}")
                d = r["dependencies"]
                print(f"  needs: {', '.join(d['interpreters'] + d['python_imports']) or 'nothing'}" + (f"  MISSING: {', '.join(d['missing'])}" if d["missing"] else ""))
                s = r["security"]
                print(f"  risk: {s['risk'].upper()}  ({len(s['findings'])} findings, {len(s['scripts'])} scripts, hosts: {', '.join(s['hosts'][:6]) or '-'})")
                for f in s["findings"]:
                    print(f"    {f['severity']:<6} {f['rule']:<18} {f['file']}:{f['line']}  {f['message']}")
                for e in r["errors"]:
                    print(f"    ERROR  {e}")
                for w in r["warnings"]:
                    print(f"    warn   {w}")
        elif a.cmd == "install":
            res = install(root, cfg, a.name, a.source, a.scope, a.accept_risk, a.force, a.dry_run, a.reason, a.refresh)
            if a.json:
                return out(res)
            print(("Dry run, nothing written: " if res.get("dry_run") else "Installed: ") + f"{res['name']}\n  from {res['from']}\n  to   {res['to']}")
            print(f"  risk {res['risk']} ({res['findings']} findings)" + (f"; MISSING deps: {', '.join(res['missing_dependencies'])}" if res["missing_dependencies"] else ""))
            if not res.get("dry_run"):
                print(f"  next: skills_manager.py verify {res['name']} --live")
        elif a.cmd == "verify":
            checks = verify(root, cfg, a.name, a.scope, a.live, a.load)
            if a.json:
                out(checks)
            else:
                print(f"verify {a.name}:")
                print_checks(checks)
            return 1 if any(c["status"] == "FAIL" for c in checks) else 0
        elif a.cmd == "update":
            res = update(root, cfg, a.name, a.scope, a.yes, a.accept_risk)
            if a.json:
                return out(res)
            print(f"{res['name']}: {res['status']}  ({res['installed_commit'][:12]} → {res['latest_commit'][:12]})")
            for f in res["changed_files"]:
                print(f"  changed: {f}")
        elif a.cmd == "remove":
            res = remove(root, a.name, a.scope, a.yes)
            if a.json:
                return out(res)
            print(f"Removed {res['removed']}\n  backup: {res['backup']}\n  undo:   skills_manager.py rollback {a.name}")
        elif a.cmd == "rollback":
            res = rollback(root, a.name, a.scope)
            if a.json:
                return out(res)
            print(f"Restored {res['restored']} from {res['from']}")
        elif a.cmd == "audit":
            rep = audit(root)
            if a.json:
                return out(rep)
            for r in rep["skills"]:
                flags = [f"{len(r['findings'])} findings"] + (["MANAGED"] if r["managed"] else []) + \
                        ([f"DRIFT {len(r['hash_drift'])} files"] if r.get("hash_drift") else []) + [f"ERROR {e}" for e in r["errors"]]
                print(f"  {r['risk'].upper():<7} {r['name']:<28} {r['scope']:<11} {'; '.join(flags)}")
            print(f"summary: {rep['summary']}  duplicates: {rep['duplicates'] or 'none'}\nwritten: {rep['written_to']}")
        elif a.cmd == "doctor":
            checks = doctor(root, cfg, a.live)
            if a.json:
                out(checks)
            else:
                print_checks(checks)
            return 1 if any(c["status"] == "FAIL" for c in checks) else 0
        elif a.cmd == "upgrade":
            rows = upgrade(root, cfg, a.scope, a.yes)
            if a.json:
                out(rows)
            else:
                for r in rows:
                    print(f"  {r['status']:<14} {r['source']}" + (f": {r['detail']}" if r.get("detail") else ""))
                    for c in r.get("changes", []):
                        print(f"      update {c['name']} ({c['risk']}): {', '.join(c['changed_files'])}")
                    for h in r.get("held", []):
                        print(f"      HELD   {h['name']}: {h['reason']}")
            return 1 if any(r["status"] in ("held", "BLOCKED") for r in rows) else 0
        elif a.cmd == "pin":
            res = pin_source(root, a.source, a.commit, a.clear)
            if a.json:
                return out(res)
            print(f"{res['source']}: " + (f"pinned to {res['commit']}" if res["commit"] else "unpinned (follows HEAD)"))
        elif a.cmd == "note":
            e = log_history(a.scope, root, "usage", a.name, "NOTE", task=a.task, outcome=a.outcome)
            print(json.dumps(e) if a.json else f"Recorded usage of {a.name}.")
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
