"""ENGINE 08: Learning and optimisation.

Everything here is computed from rows in the database: feedback ratings, script versions and
the operations that made them, emotion edits, regenerations, production times, and metrics the
user imports. Each finding carries its sample size; with too little data it says so. Findings are
"observed"; recommendations derived from them are labelled "suggestion". Preferences can be
inspected and reset."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from ..textutil import split_sentences, words
from .db import Store, dumps, loads, new_id, now

MIN_SAMPLES = 3


def _hook_kind(text: str) -> str:
    first = (split_sentences(text) or [""])[0]
    if first.endswith("?"):
        return "question"
    if any(ch.isdigit() for ch in first) or any(w in first.lower().split() for w in ("satu", "dua", "tiga", "lima", "one", "three", "five")):
        return "number"
    if any(w in first.lower().split() for w in ("aku", "saya", "i", "my", "ku")):
        return "personal"
    return "statement"


class Learning:
    def __init__(self, store: Store) -> None:
        self.store = store

    def feedback(self, production_id: str, rating: int, comment: str = "") -> dict:
        if not 1 <= int(rating) <= 5:
            raise ValueError("rating must be 1-5")
        if not self.store.one("SELECT id FROM productions WHERE id=?", (production_id,)):
            raise KeyError(production_id)
        row = {"id": new_id(), "production_id": production_id, "rating": int(rating), "comment": comment[:1000],
               "created_at": now()}
        self.store.insert("feedback", row)
        return row

    def metric(self, production_id: str | None, platform: str, metric: str, value: float, source: str = "user") -> dict:
        row = {"id": new_id(), "production_id": production_id, "platform": platform, "metric": metric,
               "value": float(value), "observed_at": now(), "source": source}
        self.store.insert("performance_metrics", row)
        return row

    def report(self) -> dict:
        prods = self.store.all("SELECT id, request, status, created_at, updated_at, script_version_id FROM productions")
        fb = self.store.all("SELECT f.production_id, f.rating, p.request, p.script_version_id FROM feedback f "
                            "JOIN productions p ON p.id=f.production_id")
        versions = self.store.all("SELECT script_id, source, operation, mode, text FROM script_versions")
        edits = self.store.all("SELECT data FROM emotional_directions WHERE edited=1")
        out = {"observed": {}, "suggestions": [], "samples": {"productions": len(prods), "ratings": len(fb),
                                                               "script_versions": len(versions), "emotion_edits": len(edits)}}
        # production times and reliability
        done = [p for p in prods if p["status"] == "completed"]
        if done:
            secs = [(datetime.fromisoformat(p["updated_at"]) - datetime.fromisoformat(p["created_at"])).total_seconds() for p in done]
            out["observed"]["production_time_s"] = {"median": sorted(secs)[len(secs) // 2], "n": len(secs)}
        if prods:
            out["observed"]["completion_rate"] = {"value": round(len(done) / len(prods), 3), "n": len(prods)}
        # ratings by voice / mode / hook kind
        by = defaultdict(lambda: defaultdict(list))
        for f in fb:
            req = loads(f["request"]) or {}
            by["voice"][req.get("voice") or "default"].append(f["rating"])
            by["mode"][req.get("mode") or "natural"].append(f["rating"])
            if f["script_version_id"]:
                v = self.store.one("SELECT text FROM script_versions WHERE id=?", (f["script_version_id"],))
                if v:
                    by["hook"][_hook_kind(v["text"])].append(f["rating"])
        for dim, groups in by.items():
            out["observed"][f"rating_by_{dim}"] = {k: {"avg": round(sum(v) / len(v), 2), "n": len(v)} for k, v in groups.items()}
            ok = {k: v for k, v in groups.items() if len(v) >= MIN_SAMPLES}
            if len(ok) >= 2:
                best = max(ok, key=lambda k: sum(ok[k]) / len(ok[k]))
                out["suggestions"].append(f"Prefer {dim} '{best}' (highest average rating over {len(ok[best])} ratings).")
        # script operations users apply most (what the first drafts lack)
        ops = Counter(v["operation"] for v in versions if v["source"] != "generated" and v["operation"])
        if ops:
            out["observed"]["edit_operations"] = dict(ops.most_common())
            op, n = ops.most_common(1)[0]
            if n >= MIN_SAMPLES:
                out["suggestions"].append(f"Drafts are often changed with '{op}' ({n} times): apply it during generation.")
        # emotion edits: which labels users replace
        changed = Counter((loads(e["data"]) or {}).get("emotion") for e in edits)
        if changed:
            out["observed"]["emotions_set_by_user"] = dict(changed.most_common())
        # repetitive expressions across scripts
        grams = Counter()
        for v in versions:
            toks = [w.lower() for w in words(v["text"])]
            grams.update({" ".join(toks[i:i + 3]) for i in range(len(toks) - 2)})
        rep = [{"phrase": g, "scripts": c} for g, c in grams.most_common(15) if c >= MIN_SAMPLES]
        if rep:
            out["observed"]["repeated_expressions"] = rep
            out["suggestions"].append(f"Vary '{rep[0]['phrase']}': it appears in {rep[0]['scripts']} scripts.")
        # regenerations: productions per script
        regen = Counter(v["script_id"] for v in versions)
        if regen:
            out["observed"]["versions_per_script"] = {"avg": round(sum(regen.values()) / len(regen), 2), "n": len(regen)}
        metrics = self.store.all("SELECT platform, metric, AVG(value) v, COUNT(*) n FROM performance_metrics GROUP BY platform, metric")
        out["observed"]["performance"] = metrics or "no analytics connected or imported"
        if not out["suggestions"]:
            out["suggestions"].append(f"Not enough data yet: suggestions start after {MIN_SAMPLES} ratings per option.")
        self.store.upsert("user_preferences", {"key": "learning_report", "value": dumps(out), "source": "computed",
                                               "updated_at": now()}, ("key",))
        return out

    def preferences(self) -> list[dict]:
        return [dict(r, value=loads(r["value"])) for r in self.store.all("SELECT * FROM user_preferences")]

    def set_preference(self, key: str, value) -> None:
        self.store.upsert("user_preferences", {"key": key, "value": dumps(value), "source": "user", "updated_at": now()},
                          ("key",))

    def reset(self) -> dict:
        n = self.store.execute("DELETE FROM user_preferences")
        return {"preferences_removed": n, "note": "ratings, history and metrics are kept; delete them separately"}
