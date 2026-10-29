"""Specialist roles. Each role is data: what it is for, which tools it may call, and who checks its work.

Roles are distinguished by permissions, not by prompts: the orchestrator refuses a plan that gives a role a
tool outside its list, and a task is always verified by a different role than the one that ran it. Every role
may read files and git status; anything that executes code, scans, or leaves the machine is granted per role.

`owns` is file ownership for code changes: `apply_patch` refuses a diff that touches a path outside the
calling role's globs (fnmatch, `*` crosses directories), so two roles can't change the same files by accident.

A role that no playbook uses yet is registered but idle. `playbooks_using()` reports that honestly instead of
showing it as active.
"""
from __future__ import annotations

from dataclasses import dataclass

READ_ONLY = frozenset({"read_file", "git_status"})


@dataclass(frozen=True)
class Role:
    id: str
    title: str
    mission: str
    tools: frozenset[str]
    owns: tuple[str, ...] = ()


def _role(id: str, title: str, mission: str, *extra: str, owns: tuple[str, ...] = ()) -> Role:
    return Role(id, title, mission, READ_ONLY | frozenset(extra), owns)


CHANGE = ("apply_patch",)


ROLES: dict[str, Role] = {r.id: r for r in [
    _role("executive", "Executive Engineering Agent",
          "Turns a request into a playbook, tracks blockers and writes the evidence-based report."),
    _role("architect", "Principal Software Architect",
          "Module boundaries, interfaces and trade-offs; architecture decision records.", "git_diff"),
    _role("backend", "Senior Backend Engineer",
          "APIs, services, validation, authorization and their integration tests.", "git_diff", *CHANGE,
          owns=("bot.py", "apex/apex/*", "apex/tests/*", "tests/test_bot.py")),
    _role("frontend", "Senior Frontend Engineer",
          "Responsive, accessible interfaces and their user-journey tests.", "git_diff", *CHANGE,
          owns=("agency/dashboard.py", "apex/apex/dashboard.py")),
    _role("fullstack", "Full-Stack Engineer",
          "Features end to end across API contract, data and UI.", "git_diff", "propose_patch", "run_tests", *CHANGE,
          owns=("bot.py", "apex/*", "agency/*", "tests/*", "scripts/*", "README.md")),
    _role("ai_engineer", "AI and Agent Engineer",
          "LLM calls with budgets, timeouts and bounded retries; model-assisted review and patches.",
          "git_diff", "llm_review", "propose_patch", *CHANGE,
          owns=("agency/providers.py", "agency/planner.py", "apex/apex/script_engine.py", "apex/apex/ideas.py",
                "apex/apex/vision.py")),
    _role("ml_engineer", "Machine Learning Engineer",
          "Model integration and reproducible evaluation (runs the APEX evaluation suites).", "run_tests"),
    _role("devops", "DevOps and Platform Engineer",
          "Reproducible environments, CI, install scripts and smoke checks.", "py_compile", "shellcheck", "git_diff",
          "http_health", *CHANGE, owns=("service/*", "scripts/*", "apex/Dockerfile")),
    _role("sre", "SRE and Reliability Engineer",
          "Logging, timeouts, recovery procedures and incident follow-up; health endpoints.", "http_health"),
    _role("security", "Cybersecurity Engineer",
          "Secret detection, dependency vulnerabilities, least privilege.",
          "secret_scan", "pip_audit", "dependency_inspect", "bandit"),
    _role("qa", "QA and Test Automation Engineer",
          "Runs test suites and independently verifies other roles' evidence.", "run_tests", "py_compile", *CHANGE,
          owns=("tests/*", "apex/tests/*")),
    _role("data", "Database and Data Engineer",
          "Schemas, migrations, backups and integrity checks.", *CHANGE,
          owns=("agency/store.py", "apex/apex/jobs.py", "apex/apex/backup.py")),
    _role("cloud", "Cloud and Infrastructure Engineer",
          "Deployment architecture, resource limits and cost.", "http_health"),
    _role("mobile", "Mobile Application Engineer",
          "Android/Termux compatibility and release builds.", "shellcheck", *CHANGE, owns=("termux/*",)),
    _role("performance", "Performance Engineer",
          "Measures before optimizing; reproducible benchmarks.", "pytest_durations"),
    _role("code_review", "Code Review and Refactoring Engineer",
          "Lint, diff review and regression risk; verifies QA's evidence.", "ruff", "git_diff"),
    _role("docs", "Documentation Engineer",
          "Setup, architecture and troubleshooting docs kept in sync with the code.", *CHANGE,
          owns=("*.md",)),
    _role("release", "Release and Build Engineer",
          "Dependency manifests, versions and release readiness; pushes reviewed branches.",
          "dependency_inspect", "git_diff", "git_push", "pypi_info", *CHANGE, owns=("requirements.txt", "apex/requirements.txt")),
    _role("integration", "Integration Engineer",
          "External APIs, SDKs and MCP servers, tested against mocks first.", "mcp_list_tools", "mcp_call"),
    _role("research", "Technical Research Engineer",
          "Official documentation, library comparison, licensing.", "pypi_info"),
]}

# Who checks whose work. QA verifies everyone except itself; code review verifies QA.
VERIFIER = {role: "qa" for role in ROLES} | {"qa": "code_review"}


def playbooks_using(role_id: str, playbooks: dict) -> list[str]:
    return sorted(name for name, pb in playbooks.items() if any(s.role == role_id for s in pb.steps))
