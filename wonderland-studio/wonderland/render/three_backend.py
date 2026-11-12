"""Bridge to the real-3D character renderer in ``render3d/`` (Three.js in headless Chromium).

Python stays the director: ``Renderer.pose`` decides every joint, this module only ships the
poses to a long-lived Node process (``render3d/driver.mjs``), which renders the characters with
toon shading, rim lights, outlines and a cast shadow on a transparent background and sends back:

  * the RGBA character layer, cropped to the characters' bounding box (premultiplied alpha), and
  * anchors per actor in 1080x1920 design pixels: hand_l, hand_r, head_top, mouth, feet.

The stage pastes that layer where it used to call ``draw_character`` and hangs held props,
transfers, zzz and fx on the anchors. One Node/Chromium process serves one worker for its
whole life; every call has a timeout, and a dead or stuck browser raises ``ThreeError`` instead
of hanging the render.
"""

from __future__ import annotations

import atexit
import base64
import json
import os
import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2] / "render3d"
DRIVER = ROOT / "driver.mjs"
START_TIMEOUT = 60.0
FRAME_TIMEOUT = 30.0


class ThreeError(RuntimeError):
    pass


# --------------------------------------------------------------------- light presets -----
# Directions are world space (x right, y up, z toward the camera). Colours are linear 0..1
# multipliers on the toon base colour (lit / first shade / second shade band).
_DAY = {
    "key_dir": [-0.55, 0.62, 0.56], "lit": [1.0, 0.99, 0.96], "shade1": [0.84, 0.80, 0.90], "shade2": [0.70, 0.66, 0.82],
    "sss": [0.08, 0.03, 0.0], "spec": 0.22, "rim_a": [0.25, 0.85, 0.80], "rim_b": [1.0, 0.62, 0.28],
    "dim": [1.0, 1.0, 1.0], "shadow_opacity": 0.28, "shadow_color": [0.16, 0.20, 0.12],
}
LIGHTS: dict[str, dict] = {
    "day": _DAY,
    "forest": {**_DAY, "lit": [0.98, 1.0, 0.95], "shade1": [0.82, 0.84, 0.86], "shade2": [0.68, 0.72, 0.78], "shadow_opacity": 0.30},
    "rainy": {**_DAY, "key_dir": [-0.3, 0.9, 0.5], "lit": [0.97, 0.98, 1.0], "shade1": [0.87, 0.87, 0.93], "shade2": [0.76, 0.76, 0.86],
              "sss": [0.04, 0.02, 0.0], "spec": 0.18, "rim_a": [0.40, 0.72, 0.80], "rim_b": [0.85, 0.66, 0.50],
              "shadow_opacity": 0.18, "shadow_soft": 16, "shadow_dir": [-0.1, 1.0, 0.2]},
    "indoor": {**_DAY, "lit": [1.0, 0.98, 0.93], "shade1": [0.86, 0.80, 0.86], "shade2": [0.72, 0.65, 0.76],
               "sss": [0.09, 0.035, 0.0], "rim_b": [1.0, 0.70, 0.40], "shadow_opacity": 0.24, "shadow_color": [0.30, 0.20, 0.16]},
    "night": {**_DAY, "key_dir": [0.45, 0.75, 0.5], "lit": [0.86, 0.88, 1.0], "shade1": [0.68, 0.70, 0.88], "shade2": [0.56, 0.57, 0.78],
              "sss": [0.05, 0.02, 0.03], "spec": 0.22, "rim_a": [0.62, 0.72, 1.0], "rim_b": [0.95, 0.72, 0.45],
              "rim_a_dir": [0.75, 0.45, -0.5], "rim_b_dir": [-0.8, 0.2, -0.5],
              "dim": [0.82, 0.84, 0.96], "shadow_opacity": 0.32, "shadow_color": [0.06, 0.06, 0.16], "shadow_dir": [0.3, 1.0, 0.3]},
}
ENV_LIGHT = {"meadow": "day", "garden": "day", "pond": "day", "hilltop": "day", "forest": "forest", "rainy": "rainy",
             "playroom": "indoor", "bathroom": "indoor", "bedroom": "night", "night": "night"}


def light_preset(env: str) -> dict:
    return LIGHTS[ENV_LIGHT.get(env, "day")]


# --------------------------------------------------------------------- availability ------
def _node() -> str | None:
    return shutil.which("node")


def _deps_reason() -> str | None:
    if not _node():
        return "node not found on PATH"
    if not DRIVER.exists():
        return f"{DRIVER} missing"
    probe = ("const {createRequire}=require('module');const p=require('path');let ok={};"
             "for(const m of ['three','playwright']){ok[m]=false;for(const b of [p.join(process.argv[1],'package.json'),'/opt/node-tools/node_modules/',process.env.WONDERLAND_PLAYWRIGHT_DIR]){"
             "if(!b)continue;try{createRequire(b).resolve(m);ok[m]=true;break}catch(e){}}}console.log(JSON.stringify(ok))")
    try:
        p = subprocess.run([_node(), "-e", probe, str(ROOT)], capture_output=True, text=True, timeout=20)
        ok = json.loads(p.stdout.strip() or "{}")
    except (subprocess.SubprocessError, ValueError, OSError) as e:
        return f"node module check failed: {e}"
    missing = [m for m in ("three", "playwright") if not ok.get(m)]
    if missing:
        return f"node modules missing: {', '.join(missing)} (run `npm ci` in render3d/)"
    return None


@lru_cache(maxsize=1)
def available() -> tuple[bool, str]:
    """(True, info) when node + playwright + chromium + three are present AND a one-frame smoke render works."""
    reason = _deps_reason()
    if reason:
        return False, reason
    spec = {"id": "probe", "species": "bunny", "colors": {"body": "#B9A7F2", "belly": "#FFF6E3", "inner_ear": "#FFB3C7",
                                                          "accent": "#FFD95A", "nose": "#FF8FAB"}, "clothing": {"accessory": "scarf"}}
    try:
        with Session([spec], 270, 480, start_timeout=START_TIMEOUT) as s:
            layer = s.render([{"id": "probe", "x": 540, "y": 1340, "scale": 0.9, "side": 1, "yaw": 0}])
        if layer.rgba is None or int(layer.rgba[..., 3].max()) < 250:
            return False, "smoke render produced no opaque pixels"
        return True, f"three.js r{s.info.get('three')} on {s.info.get('renderer', '?')[:60]}"
    except ThreeError as e:
        return False, f"smoke render failed: {e}"


# ------------------------------------------------------------------------- session -------
@dataclass
class Layer:
    rgba: np.ndarray | None        # (h, w, 4) uint8, premultiplied alpha, top-down rows, output pixels
    box: tuple[int, int, int, int]  # x0, y0, w, h in output pixels
    anchors: dict                  # actor id -> {hand_l, hand_r, head_top, mouth, feet: (x, y) design px}


class Session:
    """One Node + Chromium renderer. Not thread-safe; one per worker process."""

    def __init__(self, specs: list[dict], width: int = 1080, height: int = 1920, *, start_timeout: float = START_TIMEOUT,
                 frame_timeout: float = FRAME_TIMEOUT, samples: int = 2):
        node = _node()
        if not node:
            raise ThreeError("node not found on PATH")
        self.width, self.height, self.frame_timeout = width, height, frame_timeout
        self._lines: queue.Queue = queue.Queue()
        self._err: list[str] = []
        self._light_key = None
        self._pending = False
        try:
            self.proc = subprocess.Popen([node, str(DRIVER)], cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, bufsize=1 << 20, start_new_session=True)
        except OSError as e:
            raise ThreeError(f"cannot start node: {e}") from e
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._pump_err, daemon=True).start()
        atexit.register(self.close)
        self.info = self._call({"cmd": "init", "width": width, "height": height, "opts": {"samples": samples, "antialias": samples > 0}},
                               start_timeout)["info"]
        self._call({"cmd": "chars", "specs": [_spec_for_js(s) for s in specs]}, start_timeout)

    def _pump(self) -> None:
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _pump_err(self) -> None:
        for line in self.proc.stderr:
            self._err.append(line.decode(errors="replace").strip())
            del self._err[:-20]

    def _readline(self, timeout: float) -> bytes:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise ThreeError(f"3D renderer timed out after {timeout:.0f}s") from None
        if line is None:
            code = self.proc.poll()
            raise ThreeError(f"3D renderer exited (code {code}): {' | '.join(self._err[-3:])}")
        return line

    def _send(self, msg: dict) -> None:
        if self.proc.poll() is not None:
            raise ThreeError(f"3D renderer is not running (code {self.proc.returncode}): {' | '.join(self._err[-3:])}")
        try:
            self.proc.stdin.write((json.dumps(msg, separators=(",", ":")) + "\n").encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise ThreeError(f"3D renderer pipe closed: {e}; {' | '.join(self._err[-3:])}") from e

    def _reply(self, timeout: float | None = None) -> dict:
        res = json.loads(self._readline(timeout or self.frame_timeout))
        if not res.get("ok"):
            raise ThreeError(res.get("error", "unknown renderer error"))
        return res

    def _call(self, msg: dict, timeout: float | None = None) -> dict:
        if self._pending:
            raise ThreeError("a frame is still in flight; collect() it first")
        self._send(msg)
        return self._reply(timeout)

    def set_lights(self, key: str, preset: dict) -> None:
        if key != self._light_key:
            self._call({"cmd": "lights", "preset": preset})
            self._light_key = key

    def submit(self, actors: list[dict], *, shadow: bool = True, full: bool = False) -> None:
        """Start rendering a frame; ``collect`` returns it. Lets the caller composite the previous
        frame while the browser renders this one."""
        if self._pending:
            raise ThreeError("a frame is already in flight")
        self._send({"cmd": "frame", "actors": actors, "opts": {"shadow": shadow, "full": full}})
        self._pending = True

    def collect(self) -> Layer:
        if not self._pending:
            raise ThreeError("no frame in flight")
        self._pending = False
        res = self._reply()
        data = self._readline(self.frame_timeout).strip()
        x0, y0, w, h = res["box"]
        anchors = {k: {n: tuple(v) for n, v in a.items()} for k, a in res["anchors"].items()}
        if not w or not h or not data:
            return Layer(None, (0, 0, 0, 0), anchors)
        raw = np.frombuffer(base64.b64decode(data), dtype=np.uint32)
        counts, values = raw[0::2], raw[1::2]
        if int(counts.sum()) != w * h:
            raise ThreeError(f"pixel stream size mismatch ({int(counts.sum())} != {w * h})")
        px = np.repeat(values, counts.astype(np.int64)).view(np.uint8).reshape(h, w, 4)[::-1]
        return Layer(np.ascontiguousarray(px), (x0, y0, w, h), anchors)

    def render(self, actors: list[dict], *, shadow: bool = True, full: bool = False) -> Layer:
        self.submit(actors, shadow=shadow, full=full)
        return self.collect()

    def close(self) -> None:
        p = getattr(self, "proc", None)
        if p is None or p.poll() is not None:
            return
        try:
            p.stdin.write(b'{"cmd":"quit"}\n')
            p.stdin.flush()
            p.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        if p.poll() is None:
            try:
                os.killpg(p.pid, 9)
            except OSError:
                p.kill()
            p.wait(timeout=5)

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _spec_for_js(spec: dict) -> dict:
    return {"id": spec["id"], "species": spec["species"], "colors": spec["colors"], "clothing": spec.get("clothing", {})}


# A worker keeps one session for its whole life (shots of one episode share the cast).
_SESSIONS: dict[tuple, Session] = {}


def session_for(universe: dict, width: int, height: int) -> Session:
    key = (id(universe), width, height, os.getpid())
    s = _SESSIONS.get(key)
    if s is None or s.proc.poll() is not None:
        s = Session(universe["characters"], width, height)
        _SESSIONS[key] = s
    return s


def close_all() -> None:
    for s in list(_SESSIONS.values()):
        s.close()
    _SESSIONS.clear()


def pose_record(actor_id: str, p, side: float, yaw: float) -> dict:
    """Pose (characters.Pose) -> the JSON record scene.js understands."""
    return {"id": actor_id, "x": round(p.x, 3), "y": round(p.y, 3), "scale": round(p.scale, 5), "side": round(side, 4),
            "yaw": round(yaw, 3), "lift": round(p.lift, 3), "squash": round(p.squash, 5), "head_tilt": round(p.head_tilt, 3),
            "arm_l": round(p.arm_l, 3), "arm_r": round(p.arm_r, 3), "look": round(p.look, 4), "look_y": round(p.look_y, 4),
            "blink": p.blink, "mouth": round(p.mouth, 4), "mood": p.mood, "ear": round(p.ear, 3), "step": round(p.step, 4),
            "lean": round(p.lean, 3)}

