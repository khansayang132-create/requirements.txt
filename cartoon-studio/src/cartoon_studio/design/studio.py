"""Design Studio: the interface to the multi-style engine (stdlib HTTP, bound to 127.0.0.1).

    cartoon-studio design studio            # http://127.0.0.1:8770

Selectors: style, species, age, body build, body/belly/accent colours (fur and clothing), clothing piece, expression,
animation pose, camera angle, lighting and environment. "Render" draws the character with the real 3D renderer into
the chosen environment; "Compare" draws the same character in five styles. The library tab shows the generated casts
with their QC verdicts. Every input is checked against the engine's option lists; nothing from the request reaches a
shell or a file path unvalidated.
"""
from __future__ import annotations

import io
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import engine as E
from .styles import ACCESSORIES, AGES, ANIMATIONS, BUILDS, CAMERAS, ENVIRONMENTS, EXPRESSIONS, LIGHTING, SPECIES, STYLES

LOCK = threading.Lock()           # one render at a time: the renderer is a single browser process


def render_png(params: dict) -> bytes:
    c, pose = E.custom(params)
    env = params.get("environment", "meadow")
    lighting = params.get("lighting", "style")
    if env not in ENVIRONMENTS or lighting not in LIGHTING:
        raise ValueError("unknown environment or lighting")
    st = STYLES[c.style]
    with LOCK:
        r = E.Renderer([c], st, lighting=lighting)
        try:
            yaw = pose.pop("yaw")
            fig = r.render(c.id, yaw=yaw, scale=1.5, **pose)
        finally:
            r.close()
        E.engine.load()
        from wonderland.render.environments import background
        bg = E.GRADES[st.grade](background(env, 1).convert("RGB").resize((1080, 1920))).crop((0, 520, 1080, 1920))
    fig = E._fit(fig, 900, 1180)
    E._paste_bottom(bg, fig, 540, 1330)
    buf = io.BytesIO()
    bg.save(buf, "PNG")
    return buf.getvalue()


def compare_png(params: dict) -> bytes:
    c, _ = E.custom(params)
    styles = params.get("styles") or ["01-cinematic-3d", "06-anime", "08-clay", "09-storybook", "13-scifi"]
    if not isinstance(styles, list) or not 1 <= len(styles) <= 6 or any(s not in STYLES for s in styles):
        raise ValueError("styles must be 1-6 known style ids")
    import tempfile
    with LOCK, tempfile.TemporaryDirectory() as td:
        p = E.compare(c, styles, Path(td))
        return p.read_bytes()


def _opts(name, values, label, current=None):
    o = "".join(f"<option value='{v}'{' selected' if v == current else ''}>{lbl}</option>" for v, lbl in values)
    return f"<label>{label}<select name='{name}'>{o}</select></label>"


def page(lib: Path) -> bytes:
    styles = [(s.id, s.name) for s in STYLES.values()]
    sel = (_opts("style", styles, "Visual style", "01-cinematic-3d")
           + _opts("species", [(s, s) for s in SPECIES], "Species")
           + _opts("age", [(a, a) for a in AGES], "Age appearance", "child")
           + _opts("build", [(b, b) for b in BUILDS], "Body proportions", "standard")
           + _opts("accessory", sorted({(a, a) for v in ACCESSORIES.values() for a in v}), "Clothing", "scarf")
           + _opts("expression", [(e, e) for e in EXPRESSIONS], "Expression")
           + _opts("animation", [(a, a) for a in ANIMATIONS], "Animation pose")
           + _opts("camera", [(k, k) for k in CAMERAS], "Camera angle", "three-quarter")
           + _opts("lighting", [(k, k) for k in LIGHTING], "Lighting")
           + _opts("environment", [(e, e) for e in ENVIRONMENTS], "Environment"))
    colors = ("<label>Fur / skin<input type=color name=body value='#E8A86B'></label>"
              "<label>Belly / face<input type=color name=belly value='#FFF1DE'></label>"
              "<label>Clothing colour<input type=color name=accent value='#3D7DD8'></label>")
    gallery = []
    lj = lib / "library.json"
    if lj.exists():
        data = json.loads(lj.read_text())
        for sid, s in data.get("styles", {}).items():
            names = ", ".join(c["name"] for c in s["characters"])
            gallery.append(f"<figure><a href='/lib/{sid}/style_lineup.png'><img loading=lazy alt='{s['name']} cast' "
                           f"src='/lib/{sid}/style_lineup.png'></a><figcaption><b>{s['name']}</b> "
                           f"<span class='pill {s['status']}'>{s['status']}</span> {s['accepted']}/{s['wanted']} · {names}"
                           f"</figcaption></figure>")
    html = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Design Studio</title><style>
:root{{--bg:#F6F1E8;--card:#FFFDF8;--ink:#2B2533;--muted:#6A6272;--line:#E2D8C8;--accent:#C2410C;--ok:#1E7A4C;--bad:#B42318;
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--r:12px}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#17141C;--card:#211D27;--ink:#F1ECF5;--muted:#A79FB1;
--line:#352F3D;--accent:#FB923C;--ok:#4ADE80;--bad:#F87171}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
header{{padding:var(--s4) var(--s4) 0;max-width:1280px;margin:0 auto}}h1{{margin:0;font-size:22px}}
header p{{margin:var(--s1) 0 0;color:var(--muted)}}
main{{max-width:1280px;margin:0 auto;padding:var(--s4);display:grid;grid-template-columns:minmax(0,360px) minmax(0,1fr);gap:var(--s4)}}
@media (max-width:860px){{main{{grid-template-columns:minmax(0,1fr)}}}}
section{{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:var(--s4);min-width:0}}
form{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--s3)}}label{{display:flex;flex-direction:column;gap:var(--s1);font-size:13px;color:var(--muted);min-width:0}}
select,input[type=text]{{width:100%;min-width:0;font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;min-height:44px;padding:0 var(--s2)}}
input[type=color]{{width:100%;min-height:44px;border:1px solid var(--line);border-radius:8px;background:var(--bg)}}
.full{{grid-column:1/-1}}.row{{display:flex;gap:var(--s2);grid-column:1/-1}}
button{{font:inherit;font-weight:600;min-height:44px;padding:0 var(--s4);border-radius:8px;border:1px solid var(--ink);background:var(--ink);color:var(--card);cursor:pointer;flex:1}}
button.alt{{background:transparent;color:var(--ink)}}button:focus-visible,select:focus-visible,input:focus-visible,a:focus-visible{{outline:3px solid var(--accent);outline-offset:2px}}
#out{{display:flex;align-items:center;justify-content:center;min-height:420px;background:var(--bg);border-radius:8px}}
#out img{{max-width:100%;max-height:78vh;border-radius:8px}}#status{{color:var(--muted);font-size:13px;margin:var(--s2) 0 0}}
h2{{font-size:16px;margin:0 0 var(--s3)}}.gallery{{grid-column:1/-1}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,380px),1fr));gap:var(--s4)}}
figure{{margin:0}}figure img{{width:100%;border-radius:8px;border:1px solid var(--line)}}figcaption{{font-size:13px;color:var(--muted);margin-top:var(--s1)}}
.pill{{font-size:11px;font-weight:700;padding:1px 6px;border-radius:999px;border:1px solid currentColor}}.PASS{{color:var(--ok)}}.FAIL{{color:var(--bad)}}
</style></head><body><header><h1>Design Studio</h1><p>15 art styles · every preview is a real 3D render · identity stays fixed across styles</p></header>
<main><section><h2>Character</h2><form id=f>
<label class=full>Name<input type=text name=name value="Custom" maxlength=24></label>{sel}{colors}
<div class=row><button type=submit>Render</button><button type=button class=alt id=cmp>Compare 5 styles</button></div></form>
<p id=status role=status>Choose options, then Render.</p></section>
<section><h2>Preview</h2><div id=out><span id=hint>No render yet</span></div></section>
<section class=gallery><h2>Library (generated casts, QC verdicts)</h2><div class=grid>{''.join(gallery) or '<p>No library yet: run <code>cartoon-studio design build</code>.</p>'}</div></section>
</main><script>
const f=document.getElementById('f'),out=document.getElementById('out'),st=document.getElementById('status');
function params(){{const p=Object.fromEntries(new FormData(f));return p}}
async function go(url,body){{st.textContent='Rendering…';const t=performance.now();
 const r=await fetch(url,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
 if(!r.ok){{st.textContent='Error: '+(await r.text());return}}
 const img=new Image();img.alt='Rendered character';img.src=URL.createObjectURL(await r.blob());out.replaceChildren(img);
 st.textContent='Rendered in '+((performance.now()-t)/1000).toFixed(1)+' s'}}
f.addEventListener('submit',e=>{{e.preventDefault();go('/api/render',params())}});
document.getElementById('cmp').addEventListener('click',()=>go('/api/compare',params()));
</script></body></html>"""
    return html.encode()


def serve(lib: Path, port: int = 8770, host: str = "127.0.0.1") -> None:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype="text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                return self._send(200, page(lib))
            m = re.fullmatch(r"/lib/([\w.-]+(?:/[\w.-]+)*\.(?:png|json))", path)
            if m:
                p = (lib / m.group(1)).resolve()
                if p.is_relative_to(lib.resolve()) and p.is_file():
                    return self._send(200, p.read_bytes(), "image/png" if p.suffix == ".png" else "application/json")
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 10_000:
                return self._send(413, b"too large", "text/plain")
            try:
                params = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(params, dict):
                    raise TypeError("expected a JSON object")
                if self.path == "/api/render":
                    return self._send(200, render_png(params), "image/png")
                if self.path == "/api/compare":
                    return self._send(200, compare_png(params), "image/png")
                self._send(404, b"not found", "text/plain")
            except (ValueError, KeyError, TypeError) as e:
                self._send(400, str(e).encode(), "text/plain")

    srv = ThreadingHTTPServer((host, port), H)
    print(f"Design Studio on http://{host}:{port}")
    srv.serve_forever()


