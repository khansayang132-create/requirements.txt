"""A prop handed from one character to another is on screen exactly once in every frame of the hand-off.

Found in ep004/ep006 (Oakley gives Pipkin the kite): the receiver already held the kite in the story data while the
transfer also drew it flying, so two kites showed for about a second."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wonderland import config  # noqa: E402
from wonderland.render import stage  # noqa: E402
from wonderland.render.stage import Actor, Renderer, Shot  # noqa: E402

UNI = config.load_universe()


def test_handed_prop_is_drawn_once_per_frame(monkeypatch):
    ids = [c["id"] for c in UNI["characters"]][:2]
    kite = {"name": "kite", "color": "red", "side": 1, "size": 70}
    shot = Shot(env=next(iter(UNI.get("environments", {"garden": 0}))) if UNI.get("environments") else "garden",
                actors=[Actor(ids[0], 765, action="give", facing=-1), Actor(ids[1], 315, action="hop", hold=kite)],
                duration=2.5, transfer={"name": "kite", "color": "red", "from": ids[0], "to": ids[1], "start": 0.5, "end": 1.6})
    real, drawn = stage.draw_prop, []

    def spy(c, name, *a, **k):
        if name == "kite":
            drawn.append(name)
        return real(c, name, *a, **k)
    monkeypatch.setattr(stage, "draw_prop", spy)
    r = Renderer(UNI)
    r.three = None
    for t in (0.1, 0.5, 1.0, 1.59, 1.6, 2.2):
        drawn.clear()
        r.frame(shot, t, t + 3.0)
        assert len(drawn) == 1, f"t={t}: kite drawn {len(drawn)} times"
