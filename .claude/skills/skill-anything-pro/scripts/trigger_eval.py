"""Trigger eval for skill-anything (Phase 5/6), fixed for the real Claude Code CLI.

Drop-in replacement for skill-anything's scripts/run_eval.py: same run_eval()
signature and output shape, so run_loop_pro.py can swap it in. Upstream's version
never detects a trigger because:
  - `claude -p --output-format stream-json` exits with an error unless `--verbose` is set;
  - Claude Code invokes skills through a tool named `Skill` ({"skill": "<name>"}),
    not a tool named after the skill;
  - it writes test files into ~/.claude/commands (every project, shared between workers).

Here every query runs in its own temporary project holding only the candidate skill,
with one turn and only the Skill tool allowed. A query whose CLI run fails is
reported as an error, never as "not triggered".
"""
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


def skill_called(stdout: str, skill_name: str) -> tuple[bool, bool]:
    """Return (saw_init, triggered) from `claude -p --output-format stream-json --verbose` output."""
    saw_init = triggered = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            saw_init = True
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill":
                called = str((block.get("input") or {}).get("skill", ""))
                # Plugin and synced skills are reported as "<namespace>:<name>".
                if called == skill_name or called.endswith(":" + skill_name):
                    triggered = True
    return saw_init, triggered


def _run_single_query(query: str, skill_name: str, skill_description: str, should_trigger: bool,
                      model: str | None = None, timeout: int = 120) -> dict[str, Any]:
    project = Path(tempfile.mkdtemp(prefix="sa-trigger-"))
    try:
        skill_dir = project / ".claude" / "skills" / skill_name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: {json.dumps(skill_description)}\n---\n\n"
            "This is a test skill for evaluation.\n"
        )
        cmd = ["claude", "-p", query, "--output-format", "stream-json", "--verbose",
               "--max-turns", "1", "--allowedTools", "Skill"]
        if model:
            cmd += ["--model", model]
        try:
            result = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {"query": query, "should_trigger": should_trigger, "triggered": False,
                    "passed": False, "error": f"claude -p failed: {exc}"}
        saw_init, triggered = skill_called(result.stdout, skill_name)
        if not saw_init:
            return {"query": query, "should_trigger": should_trigger, "triggered": False, "passed": False,
                    "error": f"no init event (exit {result.returncode}): {result.stderr.strip()[-200:]}"}
        return {"query": query, "should_trigger": should_trigger, "triggered": triggered,
                "passed": triggered == should_trigger}
    finally:
        shutil.rmtree(project, ignore_errors=True)


def run_eval(queries: list[dict[str, Any]], skill_name: str, skill_description: str,
             model: str | None = None, max_workers: int = 4) -> dict[str, Any]:
    """Same contract as skill-anything's run_eval. Raises if no query reached Claude Code."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(
            lambda q: _run_single_query(q["query"], skill_name, skill_description, q["should_trigger"], model),
            queries))

    errors = [r for r in results if "error" in r]
    if results and len(errors) == len(results):
        raise RuntimeError(f"every query failed to run; first error: {errors[0]['error']}")

    pos = [r for r in results if r["should_trigger"] and "error" not in r]
    neg = [r for r in results if not r["should_trigger"] and "error" not in r]
    passed = sum(r["passed"] for r in results)
    summary = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "errors": len(errors),
        "pass_rate": passed / len(results) if results else 0,
        "true_positives": sum(r["triggered"] for r in pos),
        "false_negatives": sum(not r["triggered"] for r in pos),
        "true_negatives": sum(not r["triggered"] for r in neg),
        "false_positives": sum(r["triggered"] for r in neg),
    }
    return {"results": results, "summary": summary}


def parse_frontmatter(skill_path: Path) -> tuple[str, str]:
    lines = (skill_path / "SKILL.md").read_text().split("\n")
    if lines[0].strip() != "---" or "---" not in [l.strip() for l in lines[1:]]:
        raise ValueError(f"{skill_path}/SKILL.md has no frontmatter")
    end = [l.strip() for l in lines[1:]].index("---") + 1
    fields, key = {}, None
    for line in lines[1:end]:
        if line[:1] in (" ", "\t") and key:
            fields[key] += " " + line.strip()
        elif ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            fields[key] = value.strip().strip("\"'")
    for k, v in fields.items():
        if v.startswith((">", "|")):
            fields[k] = v[1:].strip()
    return fields.get("name", ""), fields.get("description", "")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Trigger eval for a skill description (fixed run_eval)")
    parser.add_argument("--skill-path", type=Path, required=True)
    parser.add_argument("--eval-file", type=Path, required=True,
                        help='JSON list of {"query": ..., "should_trigger": true|false}')
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    name, description = parse_frontmatter(args.skill_path)
    queries = json.loads(args.eval_file.read_text())
    try:
        output = run_eval(queries, name, description, args.model, args.max_workers)
    except RuntimeError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text)
        print(f"Results written to {args.output}")
    else:
        print(text)
    s = output["summary"]
    print(f"pass {s['passed']}/{s['total']}  FP {s['false_positives']}  FN {s['false_negatives']}  errors {s['errors']}",
          file=sys.stderr)
    return 0 if s["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
