"""Multi-style design engine: original characters per style, real 3D renders, sheets, style comparison, QC.

Every image here comes out of the 3D renderer (wonderland-studio/render3d, Three.js in headless Chromium) with the
style's shading mode and proportions applied to the character rig; nothing is a text description standing in for an
image. Character identity (species, colours, clothing, personality) is fixed in `character.json`; a style changes only
how it is drawn, which is what `compare` relies on.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .. import engine
from .styles import ACCESSORIES, AGES, ANIMATIONS, BUILDS, CAMERAS, EXPRESSIONS, LIGHTING, SPECIES, STYLES, Style

SCALE = 1.9          # figure scale in the 1080x1920 design frame (about 850-1000 px tall references)
VIEWS = (("front", 0.0), ("three-quarter", 35.0), ("side", 90.0), ("back", 180.0))
SYL_A = ("Pi", "Mo", "Ka", "Lu", "Ze", "Ru", "Ta", "Bo", "Fi", "No", "Sa", "Vi", "Jo", "Ke", "Wa", "Dri", "Plo", "Zan")
SYL_B = ("ppa", "ndo", "ri", "lix", "mble", "zzy", "to", "bin", "rra", "vel", "quin", "dle", "mo", "lo", "bie", "fer")
# Generated names are for children's characters: anything containing one of these is rejected and redrawn.
BLOCKED_NAME_PARTS = ("wank", "fuk", "fuc", "sex", "nig", "cum", "tit", "ass", "dik", "dic", "cock", "kok", "shit", "piss",
                      "fag", "nazi", "rape", "anal", "porn", "kill", "die", "dead", "slut", "cunt", "twat", "bitch", "pee", "poo")
QUIRKS = ("hums when nervous", "collects shiny pebbles", "never walks past a puddle", "names every cloud",
          "keeps a pocket notebook", "laughs before the punchline", "always shares the last snack", "sleeps with one ear up")


@dataclass
class Character:
    id: str
    name: str
    style: str
    species: str
    age: str
    build: str
    colors: dict
    clothing: dict
    personality: list[str]
    quirk: str
    seed: int
    proportions: dict = field(default_factory=dict)

    def spec(self, style: Style | None = None) -> dict:
        """Renderer spec. `style` overrides only the rendering, never the identity (comparison engine)."""
        st = style or STYLES[self.style]
        rs = st.render_style()
        age, build = AGES[self.age], BUILDS[self.build]
        rs["head"] = round(min(1.5, rs["head"] * age["head"]), 3)      # caps keep the body visible under the head
        rs["eye"] = round(min(1.45, rs["eye"] * age["eye"]), 3)
        rs["body"] = [round(b * build[i] * age["body"], 3) for i, b in enumerate(rs["body"])]
        return {"id": self.id, "name": self.name, "species": self.species, "colors": self.colors, "clothing": self.clothing,
                "style": rs}


def _rng(*key) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:12], 16))


def _shift(hex_: str, rng: random.Random, amount: int = 14) -> str:
    c = [max(0, min(255, int(hex_[i:i + 2], 16) + rng.randint(-amount, amount))) for i in (1, 3, 5)]
    return "#" + "".join(f"{v:02X}" for v in c)


def generate(style_id: str, n: int = 5, seed: int = 1, taken: set[str] | None = None) -> list[Character]:
    """`n` original characters for a style: different species, palette, clothing and personality each; names unique."""
    st = STYLES[style_id]
    rng = _rng(style_id, seed)
    taken = taken if taken is not None else set()          # shared set: names stay unique across styles
    species = list(st.species)
    rng.shuffle(species)
    out = []
    for i in range(n):
        sp = species[i % len(species)]
        while True:
            name = rng.choice(SYL_A) + rng.choice(SYL_B)
            if name not in taken and not any(b in name.lower() for b in BLOCKED_NAME_PARTS):
                taken.add(name)
                break
        body, belly, accent = st.palettes[i % len(st.palettes)]
        cr = _rng(style_id, seed, i, "c")
        colors = {"body": _shift(body, cr), "belly": belly, "inner_ear": _shift("#FFB3C7", cr, 10), "accent": accent,
                  "nose": _shift("#FF8FAB" if sp != "duck" else "#FFA62B", cr, 10)}
        acc = ACCESSORIES[sp][i % len(ACCESSORIES[sp])]
        age = {"05-cute-baby": "baby", "07-chibi": "child"}.get(style_id, rng.choice(("child", "child", "teen", "adult")))
        build = rng.choice(tuple(BUILDS))
        traits = rng.sample(st.traits, 2) + [rng.choice(("kind", "funny", "shy", "bold", "careful", "playful"))]
        out.append(Character(f"{style_id[:2]}-{name.lower()}", name, style_id, sp, age, build, colors,
                             {"accessory": acc, "color": accent}, traits, rng.choice(QUIRKS), seed,
                             {"age": age, "build": build}))
    return out


# --------------------------------------------------------------------- rendering
class Renderer:
    """One renderer session per style (the cast is built once, then posed and turned)."""

    def __init__(self, chars: list[Character], style: Style | None = None, lighting: str = "style", size=(1080, 1920)):
        engine.load()
        from wonderland.render import three_backend as tb

        self.tb = tb
        self.style = style
        specs = [c.spec(style) for c in chars]
        self.session = tb.Session(specs, *size)
        st = style or STYLES[chars[0].style]
        lights = dict(st.lights)
        if LIGHTING.get(lighting):
            lights |= LIGHTING[lighting]
        self.session.set_lights("design", lights)

    def render(self, cid: str, yaw: float = 0.0, scale: float = SCALE, **pose) -> Image.Image:
        """Transparent RGBA cut-out of one character (straight alpha), cropped to its bounds."""
        from wonderland.render.characters import Pose

        p = Pose(x=540, y=1340, scale=scale, **{k: v for k, v in pose.items() if k != "pitch"})
        rec = self.tb.pose_record(cid, p, -1.0 if yaw < 0 else 1.0, yaw)
        layer = self.session.render([rec], shadow=False)
        self.anchors = layer.anchors.get(cid, {})
        self.box = layer.box                     # crop offset: cut-out pixel (x, y) = design (x + box[0], y + box[1])
        x0, y0, w, h = layer.box
        self.clipped = x0 <= 0 or y0 <= 0 or x0 + w >= 1080 or y0 + h >= 1920
        if layer.rgba is None:
            raise RuntimeError(f"renderer returned an empty frame for {cid}")
        px = layer.rgba.astype(np.float32)
        a = px[..., 3:4] / 255.0
        rgb = np.where(a > 0, px[..., :3] / np.maximum(a, 1e-6), 0)          # premultiplied -> straight alpha
        out = np.concatenate([np.clip(rgb, 0, 255), px[..., 3:4]], axis=2).astype(np.uint8)
        return Image.fromarray(out, "RGBA")

    def close(self):
        self.session.close()


def _font(size: int, bold: bool = False):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _backdrop(st: Style, w: int, h: int) -> Image.Image:
    top, bot = (np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)], np.float32) for c in st.backdrop)
    t = np.linspace(0, 1, h)[:, None, None]
    return Image.fromarray(np.broadcast_to(top * (1 - t) + bot * t, (h, w, 3)).astype(np.uint8), "RGB")


def _ink(st: Style) -> tuple:
    return (235, 235, 245) if st.id == "13-scifi" else (50, 44, 70)


def _fit(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    k = min(box_w / img.width, box_h / img.height)
    return img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)


def _paste_bottom(canvas: Image.Image, img: Image.Image, cx: int, bottom: int):
    canvas.paste(img, (round(cx - img.width / 2), bottom - img.height), img)


# --------------------------------------------------------------------- sheets
def render_character(c: Character, out: Path, r: Renderer) -> dict:
    """All references for one character. Returns the file list."""
    st = STYLES[c.style]
    d = out / c.id
    (d / "views").mkdir(parents=True, exist_ok=True)
    views = {}
    scale = SCALE
    for _ in range(5):                    # one scale for every view: shrink until no view touches the frame edge
        clipped = []
        for name, yaw in VIEWS:
            r.render(c.id, yaw=yaw, scale=scale)
            if r.clipped:
                clipped.append(name)
        if not clipped:
            break
        scale *= 0.85
    else:
        raise RuntimeError(f"{c.id}: views {clipped} still cut off at scale {scale:.2f}")
    for name, yaw in VIEWS:                                        # transparent turnaround PNGs, same scale for all views
        img = r.render(c.id, yaw=yaw, scale=scale)
        img.save(d / "views" / f"{name}.png")
        views[name] = img
        if name == "front":                                         # rig anchors (design px, y down): head top, chin, feet
            a, y0 = r.anchors, r.box[1]
            head_ratio = round((a["chin"][1] - a["head_top"][1]) / max(1e-6, a["feet"][1] - a["head_top"][1]), 3)
    exprs = {}
    for name, pose in EXPRESSIONS.items():
        exprs[name] = r.render(c.id, yaw=12.0, scale=scale, **pose)
    anims = {name: r.render(c.id, yaw=20.0, scale=scale * 0.8, **pose) for name, pose in ANIMATIONS.items()}
    ink, bg = _ink(st), _backdrop

    # turnaround (one row, equal scale, height line)
    H = max(v.height for v in views.values())
    W = sum(v.width for v in views.values()) + 60 * 5
    turn = bg(st, W, H + 170)
    dr = ImageDraw.Draw(turn)
    x = 60
    for name, img in views.items():
        _paste_bottom(turn, img, x + img.width // 2, H + 70)
        dr.text((x + img.width // 2, H + 110), name, fill=ink, font=_font(34, True), anchor="mm")
        x += img.width + 60
    dr.line([(20, 70), (W - 20, 70)], fill=(*ink, ), width=2)
    dr.text((24, 30), f"{c.name} — turnaround ({st.name})", fill=ink, font=_font(34, True))
    turn.save(d / "turnaround.png")

    # expression sheet
    cell = 420
    exs = bg(st, cell * 3, cell * 2 + 80)
    dr = ImageDraw.Draw(exs)
    dr.text((20, 18), f"{c.name} — expressions", fill=ink, font=_font(34, True))
    for i, (name, img) in enumerate(exprs.items()):
        cx, cy = (i % 3) * cell + cell // 2, 80 + (i // 3) * cell
        head = img.crop((0, 0, img.width, round(img.height * 0.62)))       # head and shoulders
        _paste_bottom(exs, _fit(head, cell - 40, cell - 80), cx, cy + cell - 60)
        dr.text((cx, cy + cell - 30), name, fill=ink, font=_font(30), anchor="mm")
    exs.save(d / "expression_sheet.png")

    # proportions (front view; head top, chin and ground lines from the rig's anchors, mapped onto the cut-out)
    front = views["front"]
    top, neck, bottom = (int(a[k][1] - y0) for k in ("head_top", "chin", "feet"))
    prop = bg(st, front.width + 360, front.height + 120)
    dr = ImageDraw.Draw(prop)
    _paste_bottom(prop, front, 140 + front.width // 2, front.height + 60)
    for y, label in ((top, "top of head"), (neck, "chin / neck"), (bottom, "ground")):
        yy = y + 60
        dr.line([(40, yy), (prop.width - 30, yy)], fill=(*ink,), width=2)
        dr.text((prop.width - 30, yy - 6), label, fill=ink, font=_font(24), anchor="rb")
    dr.text((24, 18), f"head : body = {head_ratio:.2f} : {1 - head_ratio:.2f}   ({c.proportions['age']}, {c.proportions['build']})",
            fill=ink, font=_font(28, True))
    prop.save(d / "proportions.png")

    # palette + clothing card
    pal = Image.new("RGB", (1200, 420), "white")
    dr = ImageDraw.Draw(pal)
    for i, (k, v) in enumerate(c.colors.items()):
        dr.rounded_rectangle([30 + i * 230, 30, 230 + i * 230, 230], 22, fill=v, outline=(60, 60, 70), width=2)
        dr.text((130 + i * 230, 260), k, fill=(40, 40, 50), font=_font(26, True), anchor="mm")
        dr.text((130 + i * 230, 296), v, fill=(80, 80, 90), font=_font(24), anchor="mm")
    dr.text((30, 350), f"clothing: {c.clothing['accessory']} in {c.clothing['color']}", fill=(40, 40, 50), font=_font(28))
    pal.save(d / "palette.png")

    # animation poses
    aw = sum(_fit(a, 9999, 700).width for a in anims.values()) + 50 * (len(anims) + 1)
    ani = bg(st, aw, 860)
    dr = ImageDraw.Draw(ani)
    x = 50
    for name, img in anims.items():
        im = _fit(img, 9999, 700)
        _paste_bottom(ani, im, x + im.width // 2, 760)
        dr.text((x + im.width // 2, 805), name, fill=ink, font=_font(30), anchor="mm")
        x += im.width + 50
    ani.save(d / "pose_sheet.png")

    # the production character sheet (high resolution composite)
    sheet = bg(st, 3000, 2200)
    dr = ImageDraw.Draw(sheet)
    dr.text((80, 60), c.name, fill=ink, font=_font(96, True))
    dr.text((80, 180), f"{st.name} · {c.species} · {c.age} · {c.build} build", fill=ink, font=_font(40))
    big = _fit(views["three-quarter"], 900, 1500)
    _paste_bottom(sheet, big, 560, 1850)
    t = _fit(Image.open(d / "turnaround.png").convert("RGBA"), 1900, 700)
    sheet.paste(t, (1030, 300), t)
    e = _fit(Image.open(d / "expression_sheet.png").convert("RGBA"), 1100, 800)
    sheet.paste(e, (1030, 1060), e)
    p = _fit(pal.convert("RGBA"), 760, 270)
    sheet.paste(p, (2170, 1080))
    lines = [f"personality: {', '.join(c.personality)}", f"quirk: {c.quirk}",
             f"clothing: {c.clothing['accessory']} ({c.clothing['color']})", f"head:body {head_ratio:.2f}"]
    for i, ln in enumerate(lines):
        dr.text((2170, 1400 + i * 56), ln, fill=ink, font=_font(34))
    dr.text((80, 2120), f"id {c.id} · seed {c.seed} · rendered in 3D (Three.js / WebGL)", fill=ink, font=_font(28))
    sheet.save(d / "character_sheet.png")

    data = asdict(c) | {"style_name": st.name, "render_spec": c.spec(), "measured": {"head_ratio": head_ratio, "scale": round(scale, 3)}}
    (d / "character.json").write_text(json.dumps(data, indent=2))
    files = ["views/front.png", "views/three-quarter.png", "views/side.png", "views/back.png", "turnaround.png",
             "expression_sheet.png", "proportions.png", "palette.png", "pose_sheet.png", "character_sheet.png", "character.json"]
    return {"dir": str(d), "files": files, "head_ratio": head_ratio}


GRADES = {
    "cinematic": lambda im: ImageOps.autocontrast(im, cutoff=1),
    "punchy": lambda im: _sat(ImageOps.autocontrast(im, cutoff=2), 1.25),
    "dreamy": lambda im: Image.blend(im, im.filter(ImageFilter.GaussianBlur(8)), 0.35),
    "filmic": lambda im: _sat(ImageOps.autocontrast(im, cutoff=1), 0.72),
    "pastel": lambda im: Image.blend(_sat(im, 0.7), Image.new("RGB", im.size, (255, 240, 248)), 0.25),
    "anime": lambda im: _sat(im.filter(ImageFilter.UnsharpMask(3, 120)), 1.35),
    "bright": lambda im: _sat(im, 1.15),
    "clay": lambda im: Image.blend(im.filter(ImageFilter.GaussianBlur(2)).quantize(48).convert("RGB"), Image.new("RGB", im.size, (240, 214, 180)), 0.15),
    "storybook": lambda im: _paper(im.quantize(24).convert("RGB")),
    "tiltshift": lambda im: _tilt(_sat(im, 1.3)),
    "scifi": lambda im: Image.blend(ImageOps.colorize(im.convert("L"), (6, 10, 30), (90, 255, 230)), im, 0.25),
    "fantasy": lambda im: Image.blend(_sat(im, 1.1), Image.new("RGB", im.size, (120, 70, 190)), 0.18),
    "none": lambda im: im,
}


def _sat(im: Image.Image, k: float) -> Image.Image:
    from PIL import ImageEnhance

    return ImageEnhance.Color(im).enhance(k)


def _paper(im: Image.Image) -> Image.Image:
    rng = np.random.default_rng(3)
    grain = (rng.normal(0, 9, (im.height, im.width, 1))).astype(np.float32)
    return Image.fromarray(np.clip(np.asarray(im, np.float32) * 0.96 + grain + 8, 0, 255).astype(np.uint8))


def _tilt(im: Image.Image) -> Image.Image:
    blur = im.filter(ImageFilter.GaussianBlur(14))
    h = im.height
    y = np.abs(np.linspace(-1, 1, h) - 0.25)[:, None]
    m = Image.fromarray((np.clip((y - 0.18) * 3.0, 0, 1) * 255).astype(np.uint8).repeat(im.width, axis=1), "L")
    return Image.composite(blur, im, m)


def environment(st: Style, chars: list[Character], r: Renderer, out: Path) -> Path:
    """Environment concept: the style's painted set, graded in the style, with the cast staged in it."""
    engine.load()
    from wonderland.render.environments import background

    bgimg = background(st.env, 1).convert("RGB").resize((1080, 1920))
    bgimg = GRADES[st.grade](bgimg)
    bgimg = bgimg.crop((0, 560, 1080, 1920)).resize((1620, 2040))
    xs = np.linspace(260, 1360, len(chars))
    for x, c in zip(xs, chars):
        im = _fit(r.render(c.id, yaw=15.0 if x < 810 else -15.0), 300, 760)
        _paste_bottom(bgimg, im, int(x), 1800)
    p = out / "environment_concept.png"
    bgimg.save(p)
    return p


def lineup(st: Style, results: list[dict], out: Path) -> Path:
    imgs = [Image.open(Path(r["dir"]) / "views" / "three-quarter.png") for r in results]
    imgs = [_fit(i, 9999, 900) for i in imgs]
    W = sum(i.width for i in imgs) + 60 * (len(imgs) + 1)
    img = _backdrop(st, max(W, 1600), 1150)
    dr = ImageDraw.Draw(img)
    dr.text((50, 40), f"{st.name} — cast", fill=_ink(st), font=_font(52, True))
    dr.text((50, 110), st.summary, fill=_ink(st), font=_font(26))
    x = 60
    for i, r in zip(imgs, results):
        _paste_bottom(img, i, x + i.width // 2, 1080)
        dr.text((x + i.width // 2, 1115), json.loads((Path(r["dir"]) / "character.json").read_text())["name"],
                fill=_ink(st), font=_font(32, True), anchor="mm")
        x += i.width + 60
    p = out / "style_lineup.png"
    img.save(p)
    return p


def compare(c: Character, style_ids: list[str], out: Path) -> Path:
    """The same character (identity fixed) drawn in several styles, side by side."""
    panels = []
    for sid in style_ids:
        st = STYLES[sid]
        r = Renderer([c], st)
        try:
            scale = SCALE
            for _ in range(5):                  # big-eared species (elephant) need a smaller scale to stay in frame
                im = r.render(c.id, yaw=30.0, scale=scale)
                if not r.clipped:
                    break
                scale *= 0.85
            else:
                raise RuntimeError(f"{c.id} in {sid}: still cut off at scale {scale:.2f}")
            im = _fit(im, 580, 820)
        finally:
            r.close()
        panel = _backdrop(st, 620, 1040)
        _paste_bottom(panel, im, 310, 920)
        dr = ImageDraw.Draw(panel)
        dr.text((310, 975), st.name.split(" (")[0], fill=_ink(st), font=_font(30, True), anchor="mm")
        panels.append(panel)
    img = Image.new("RGB", (620 * len(panels), 1140), "white")
    for i, p in enumerate(panels):
        img.paste(p, (i * 620, 100))
    ImageDraw.Draw(img).text((30, 30), f"{c.name} the {c.species}: same identity, {len(panels)} styles",
                             fill=(40, 40, 50), font=_font(44, True))
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"compare_{c.id}.png"
    img.save(p)
    (out / f"compare_{c.id}.json").write_text(json.dumps({"character": asdict(c), "styles": style_ids}, indent=2))
    return p


def custom(params: dict) -> tuple[Character, dict]:
    """Interface: build one character from selector values (all validated against the known options)."""
    st = STYLES[params.get("style", "01-cinematic-3d")]
    sp = params.get("species", "bunny")
    if sp not in SPECIES:
        raise ValueError("unknown species")
    acc = params.get("accessory", ACCESSORIES[sp][0])
    if acc not in {a for v in ACCESSORIES.values() for a in v}:
        raise ValueError("unknown accessory")
    age, build = params.get("age", "child"), params.get("build", "standard")
    if age not in AGES or build not in BUILDS:
        raise ValueError("unknown age or build")

    def col(k, default):
        v = params.get(k, default)
        if not (isinstance(v, str) and len(v) == 7 and v[0] == "#" and all(ch in "0123456789abcdefABCDEF" for ch in v[1:])):
            raise ValueError(f"{k} must be #RRGGBB")
        return v.upper()
    body, belly, accent = st.palettes[0]
    c = Character("custom", params.get("name", "Custom")[:24] or "Custom", st.id, sp, age, build,
                  {"body": col("body", body), "belly": col("belly", belly), "inner_ear": "#FFB3C7", "accent": col("accent", accent),
                   "nose": "#FF8FAB" if sp != "duck" else "#FFA62B"},
                  {"accessory": acc, "color": col("accent", accent)}, ["custom"], "", 0, {"age": age, "build": build})
    pose = dict(EXPRESSIONS.get(params.get("expression", "happy"), {}))
    pose |= ANIMATIONS.get(params.get("animation", "idle"), {})
    view = {"yaw": CAMERAS.get(params.get("camera", "three-quarter"), 35.0)}
    return c, pose | view
