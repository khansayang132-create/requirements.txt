"""OVERLORD agent registry: every named agent, the department it belongs to, and what really performs its work.

An agent here is a name for a duty. It counts as implemented only when a registered tool does the work (`tool`),
run under a role that is allowed to call it. Duties with no executable tool are listed as NOT IMPLEMENTED, or BLOCKED
with the reason, so the dashboard never shows a description as if it were a working agent. Live state (ACTIVE /
IDLE / FAILED / NEVER RUN) comes from the audit log, not from this file.
"""
from __future__ import annotations

from dataclasses import dataclass

from .roles import ROLES


@dataclass(frozen=True)
class Agent:
    name: str
    department: str
    role: str | None
    tool: str | None
    args: dict | None = None      # narrows which calls count as this agent's work (e.g. one integration)
    note: str = ""


def _a(name, dept, role=None, tool=None, args=None, note=""):
    return Agent(name, dept, role, tool, args, note)


AGENTS: list[Agent] = [
    # Executive
    _a("Chief Executive Agent", "Executive", "executive", None, note="the orchestrator: plans playbooks into tasks"),
    _a("Operations Manager", "Executive", "executive", None, note="the worker loop: resumes approved missions"),
    _a("Task Distribution Agent", "Executive", "executive", None, note="orchestrator assigns each task to its role"),
    _a("Performance Monitoring Agent", "Executive", "performance", "pytest_durations"),
    _a("Recovery Manager", "Executive", "sre", None, note="self-healing engine (agency/healing.py) in every worker pass"),
    # Creative
    _a("Creative Director", "Creative", None, None, note="NOT IMPLEMENTED: creative review needs the LLM provider"),
    _a("Story Writer", "Creative", "ai_engineer", None,
       note="BLOCKED: writing needs the LLM provider (OmniRoute on the owner's phone); Cartoon Studio writes episodes"),
    _a("Character Designer", "Creative", "humanverse", "build_character"),
    _a("Storyboard Artist", "Creative", "video", "cartoon_episode", note="Cartoon Studio storyboard stage"),
    _a("Scene Director", "Creative", "video", "talking_scene"),
    _a("Animation Director", "Creative", "video", "talking_scene"),
    # HUMANVERSE
    _a("Digital Human Creator", "HUMANVERSE", "humanverse", "build_character"),
    _a("3D Character Builder", "HUMANVERSE", "humanverse", "build_character"),
    _a("Human Modeling Agent", "HUMANVERSE", "humanverse", "build_character"),
    _a("Facial Animation Agent", "HUMANVERSE", "video", "talking_scene"),
    _a("Lip Sync Agent", "HUMANVERSE", "video", "talking_scene"),
    _a("Motion Capture Agent", "HUMANVERSE", None, None,
       note="NOT IMPLEMENTED: no capture hardware or mocap data; animation is procedural keyframes"),
    _a("Character Rigging Agent", "HUMANVERSE", "humanverse", "build_character"),
    # Video production
    _a("Video Generation Agent", "Video", "video", "cartoon_episode"),
    _a("Scene Generation Agent", "Video", "video", "talking_scene"),
    _a("Video Editing Agent", "Video", "video", "cartoon_episode", note="Cartoon Studio edit stage"),
    _a("Cinematography Agent", "Video", "video", "talking_scene"),
    _a("Transition Specialist", "Video", "video", "cartoon_episode", note="Cartoon Studio edit stage"),
    _a("Rendering Agent", "Video", "video", "talking_scene"),
    # Audio
    _a("Voice Generation Agent", "Audio", "audio", "voice_dialogue"),
    _a("Voice Cloning Integration Agent", "Audio", None, None,
       note="BLOCKED: needs a licensed cloning service and the speaker's written consent"),
    _a("Sound Effects Agent", "Audio", "audio", "voice_dialogue", note="AURAVOX master adds synthesised effects"),
    _a("Music Composer", "Audio", "audio", "voice_dialogue", note="AURAVOX master synthesises the music bed"),
    _a("Audio Synchronization Agent", "Audio", "audio", "voice_dialogue", note="lip-sync data and validation report"),
    _a("Audio Quality Controller", "Audio", "audio", "voice_dialogue", note="take metrics, defects, retries"),
    # Technical
    _a("Integration Engineer", "Technical", "technical", "integration_probe"),
    _a("API Connection Agent", "Technical", "technical", "integration_probe"),
    _a("Dependency Manager", "Technical", "release", "dependency_inspect"),
    _a("Security Agent", "Technical", "security", "secret_scan"),
    _a("Debugging Agent", "Technical", "sre", None, note="self-healing classifier + `agency show` audit log"),
    _a("Testing Agent", "Technical", "technical", "project_tests"),
    _a("Self-Healing Agent", "Technical", "sre", None, note="agency/healing.py (watchdog, classifier, retries)"),
]


def check() -> list[str]:
    """Registry errors: an agent whose tool its role may not call is a lie, so tests fail on it."""
    errors = []
    for ag in AGENTS:
        if ag.tool and (ag.role not in ROLES or ag.tool not in ROLES[ag.role].tools):
            errors.append(f"{ag.name}: role {ag.role} may not call {ag.tool}")
    return errors


def status(store) -> list[dict]:
    """Each agent with its live state from the audit log."""
    out = []
    running = {(r["role"], r["tool"]) for r in store.db.execute("SELECT role, tool FROM tasks WHERE state='RUNNING'")}
    for ag in AGENTS:
        row = {"agent": ag.name, "department": ag.department, "role": ag.role, "tool": ag.tool, "note": ag.note}
        if not ag.tool:
            row["state"] = ("BLOCKED" if ag.note.startswith("BLOCKED") else
                            "NOT IMPLEMENTED" if ag.note.startswith("NOT IMPLEMENTED") else "BUILT-IN")
        else:
            last = store.db.execute("SELECT status, finished_at, summary FROM tool_calls WHERE role=? AND tool=? "
                                    "ORDER BY id DESC LIMIT 1", (ag.role, ag.tool)).fetchone()
            row["state"] = ("ACTIVE" if (ag.role, ag.tool) in running else "NEVER RUN" if last is None
                            else "FAILED" if last["status"] in ("FAIL", "ERROR") else
                            "BLOCKED" if last["status"] == "BLOCKED" else "IDLE")
            if last is not None:
                row |= {"last": last["status"], "last_at": last["finished_at"], "last_summary": last["summary"]}
        out.append(row)
    return out
