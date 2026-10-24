"""Specialist roles. Each role is data: what it is for, which tools it may call, and who checks its work.

Roles are distinguished by permissions, not by prompts: the orchestrator refuses a plan that gives a role a
tool outside its list, and a task is always verified by a different role than the one that ran it. Every role
may read files and git status; anything that executes code, scans, or leaves the machine is granted per role.

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


def _role(id: str, title: str, mission: str, *extra: str) -> Role:
    return Role(id, title, mission, READ_ONLY | frozenset(extra))


ROLES: dict[str, Role] = {r.id: r for r in [
    _role("executive", "Executive Engineering Agent",
          "Turns a request into a playbook, tracks blockers and writes the evidence-based report."),
    _role("architect", "Principal Software Architect",
          "Module boundaries, interfaces and trade-offs; architecture decision records.", "git_diff"),
    _role("backend", "Senior Backend Engineer",
          "APIs, services, validation, authorization and their integration tests.", "git_diff"),
    _role("frontend", "Senior Frontend Engineer",
          "Responsive, accessible interfaces and their user-journey tests.", "git_diff"),
    _role("fullstack", "Full-Stack Engineer",
          "Features end to end across API contract, data and UI.", "git_diff"),
    _role("ai_engineer", "AI and Agent Engineer",
          "LLM calls with budgets, timeouts and bounded retries; model-assisted review.", "git_diff", "llm_review"),
    _role("ml_engineer", "Machine Learning Engineer",
          "Model integration and reproducible evaluation."),
    _role("devops", "DevOps and Platform Engineer",
          "Reproducible environments, CI, install scripts and smoke checks.", "py_compile", "shellcheck", "git_diff"),
    _role("sre", "SRE and Reliability Engineer",
          "Logging, timeouts, recovery procedures and incident follow-up."),
    _role("security", "Cybersecurity Engineer",
          "Secret detection, dependency vulnerabilities, least privilege.",
          "secret_scan", "pip_audit", "dependency_inspect"),
    _role("qa", "QA and Test Automation Engineer",
          "Runs test suites and independently verifies other roles' evidence.", "run_tests", "py_compile"),
    _role("data", "Database and Data Engineer",
          "Schemas, migrations, backups and integrity checks."),
    _role("cloud", "Cloud and Infrastructure Engineer",
          "Deployment architecture, resource limits and cost."),
    _role("mobile", "Mobile Application Engineer",
          "Android/Termux compatibility and release builds."),
    _role("performance", "Performance Engineer",
          "Measures before optimizing; reproducible benchmarks."),
    _role("code_review", "Code Review and Refactoring Engineer",
          "Lint, diff review and regression risk; verifies QA's evidence.", "ruff", "git_diff"),
    _role("docs", "Documentation Engineer",
          "Setup, architecture and troubleshooting docs kept in sync with the code."),
    _role("release", "Release and Build Engineer",
          "Dependency manifests, versions and release readiness.", "dependency_inspect", "git_diff"),
    _role("integration", "Integration Engineer",
          "External APIs, SDKs and MCP servers, tested against mocks first."),
    _role("research", "Technical Research Engineer",
          "Official documentation, library comparison, licensing."),
]}

# Who checks whose work. QA verifies everyone except itself; code review verifies QA.
VERIFIER = {role: "qa" for role in ROLES} | {"qa": "code_review"}


def playbooks_using(role_id: str, playbooks: dict) -> list[str]:
    return sorted(name for name, pb in playbooks.items() if any(s.role == role_id for s in pb.steps))
