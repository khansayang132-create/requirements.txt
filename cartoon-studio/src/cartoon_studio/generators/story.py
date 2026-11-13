"""Write an original episode for a universe: seven acts, real stage directions, true facts, kind resolution.

Each plot is a small, solvable problem (the world rule: nobody is ever in danger). The script is written in the local
engine's beat format, so the same object drives storyboard, voices, animation and Foley; every line is checked by the
engine's child-safety review (<= 14 words a line, banned topics, honest title).
"""

from __future__ import annotations

import random

from .. import engine
from ..state import EpisodeScript, SceneSpec, UniverseBible
from .originality import check_words
from .universe import engine_universe

ACTS = ["hook", "introduction", "development", "conflict", "climax", "resolution", "ending"]
CAMERA = {"hook": ("wide establishing", "slow push-in"), "introduction": ("medium two-shot", "gentle pan"),
          "development": ("medium", "follow"), "conflict": ("close-up", "slight dolly-in"), "climax": ("low-angle hero", "quick push-in"),
          "resolution": ("medium wide", "slow pull-back"), "ending": ("wide", "crane up")}
MUSIC = {"hook": "bright motif, light", "introduction": "theme, bouncy", "development": "curious pizzicato", "conflict": "soft minor, slower",
         "climax": "build, drums", "resolution": "warm theme returns", "ending": "sting + end theme"}
LIGHT = {"night": "cool moonlight, soft rim", "rainy": "overcast, soft", "bedroom": "warm lamp", "playroom": "warm daylight"}


DESCRIPTOR_WORDS = {"panorama", "view", "vista", "area", "set", "backdrop", "scene"}


def spoken_place(name: str | None, default: str = "the field") -> str:
    """A place label as narration says it: 'Valley panorama' -> 'the valley', 'Root garden' -> 'the root garden'.
    Universe files hold set labels, not proper names, so they are never read out verbatim."""
    if not name:
        return default
    words = [w for w in name.split() if w.lower() not in DESCRIPTOR_WORDS] or name.split()
    return "the " + " ".join(w.lower() for w in words)


def _plot_lost_kite(rng, u, b, c):
    a, f, w = c[0], c[1], c[4]
    p = u.places
    home = next(e for e in ("hilltop", "meadow", "garden") if e in p) if any(e in p for e in ("hilltop", "meadow", "garden")) else "meadow"
    b.go(home).enter(a.character_id)
    b.say("narrator", f"Whoosh! The wind is strong in {spoken_place(p.get(home))} today.", title=f"{a.name} and the Runaway Kite", sfx=["whoosh"])
    b.put("kite", layout="sky", color="red")
    b.say(a.character_id, "My red kite! It is flying away!", act={a.character_id: "look_up"})
    b.enter(f.character_id)
    b.say(f.character_id, f"Hi, {a.name}! I am {f.name}. What is wrong?", act={f.character_id: "wave"})
    b.say(a.character_id, "The wind took my kite. I can't see it now.", act={a.character_id: "sad"})
    b.clear(ground=True)
    b.say("narrator", f"{a.name} feels sad. {f.name} has an idea.", act={f.character_id: "think"})
    b.say(f.character_id, "Let's look for clues together. Kites follow the wind!", act={f.character_id: "point"})
    b.say("narrator", "The leaves are blowing toward the trees. That is a clue!", act={a.character_id: "point", f.character_id: "nod"})
    b.enter(w.character_id).put("tree", layout="ground", x=820, y=1180, size=260).put("kite", layout="ground", x=820, y=1050, color="red", size=120)
    b.say(w.character_id, "Hello! Is that red kite yours? It is in my tree.", act={w.character_id: "wave"})
    b.say(a.character_id, "Yes! But it is so high. How can we get it?", act={a.character_id: "think"})
    b.say(w.character_id, "I am tall. Let me reach it, very gently.", act={w.character_id: "tiptoe"})
    b.drop("kite").hold(w.character_id, "kite", "red", 70)
    b.say("narrator", "Up, up, up, and down. The kite is safe!", act={a.character_id: "cheer", f.character_id: "clap"}, fx="sparkle", sfx=["ding"])
    b.hold(w.character_id, None).hold(a.character_id, "kite", "red", 70)
    b.say(a.character_id, f"Thank you, {w.name}! Thank you, {f.name}!", act={a.character_id: "hop"},
          transfer={"name": "kite", "color": "red", "from": w.character_id, "to": a.character_id})
    b.say("narrator", "When we help each other, big problems get smaller.", act={a.character_id: "hug", f.character_id: "hug"})
    b.say(f.character_id, "What would you do if your kite flew away?", act={f.character_id: "wave"}, end=f"See you next time in {u.title}!")
    return ("friendship", f"{a.name}'s kite blows away; {f.name} and {w.name} help find it.", "Helping each other makes big problems smaller.",
            f"{a.name} and the Runaway Kite")


def _plot_rain_picnic(rng, u, b, c):
    a, f, g = c[1], c[2], c[3]
    b.go("meadow" if "meadow" in u.places else "garden").enter(a.character_id, f.character_id)
    b.put("basket", x=540, y=1260, size=150)
    b.say("narrator", "It is picnic day! Look what is in the basket.", title="The Rainy Picnic")
    b.show("apple", count=2).show("bread")
    b.say(a.character_id, "Two apples and some bread. Yum, yum!", act={a.character_id: "point"}, number=(2, "red"))
    b.say(f.character_id, "Look at the sky. Those clouds are getting dark.", act={f.character_id: "look_up"})
    b.clear().put("cloud", layout="sky", x=540, y=420, size=260)
    b.say("narrator", "Plip, plop. Raindrops start to fall!", act={a.character_id: "wow", f.character_id: "wow"}, sfx=["splash"])
    b.go("rainy", keep_show=False).put("raindrop", layout="fall", count=6)
    b.say(a.character_id, "Oh no! Our picnic will get wet.", act={a.character_id: "sad"})
    b.enter(g.character_id)
    b.say(g.character_id, "Come under my big umbrella, friends!", act={g.character_id: "wave"})
    b.hold(g.character_id, "umbrella", "blue", 110)
    b.say("narrator", "Three friends, one umbrella. Squeeze in close!", act={a.character_id: "hop", f.character_id: "hop"})
    b.say(f.character_id, "We can have our picnic right here, together.", act={f.character_id: "nod"})
    b.go("meadow" if "meadow" in u.places else "garden").put("rainbow", layout="sky", x=540, y=440, size=380)
    b.say("narrator", "The rain stops. The sun comes out. Look, a rainbow!", act={a.character_id: "cheer", f.character_id: "cheer"}, fx="sparkle")
    b.say(a.character_id, "Sunlight and rain made a rainbow!", act={a.character_id: "point"}, word=("RAINBOW", "purple"))
    b.say("narrator", "A rainy day can still be a happy day with friends.", act={g.character_id: "dance"})
    b.say(g.character_id, "What do you like to do on rainy days?", act={g.character_id: "wave"}, end=f"See you next time in {u.title}!")
    b.hold(g.character_id, None)
    return ("educational", "Rain interrupts a picnic; friends share an umbrella and see a rainbow.", "Sunlight shining through raindrops makes a rainbow.",
            "The Rainy Picnic")


def _plot_nervous_drum(rng, u, b, c):
    a, f, t = c[2], c[0], c[4]
    b.go("playroom").enter(f.character_id, t.character_id)
    b.put("drum", x=540, y=1250, size=150).put("xylophone", x=830, y=1260, size=150)
    b.say("narrator", "Boom, boom! Today is music day.", title=f"{a.name} Plays Along", sfx=["pop"])
    b.say(f.character_id, "I play the drum. Boom, boom, boom!", act={f.character_id: "clap"})
    b.say(t.character_id, "I play the xylophone. Ding, ding!", act={t.character_id: "dance"}, sfx=["ding"])
    b.enter(a.character_id)
    b.say(a.character_id, "I want to play too. But I feel nervous.", act={a.character_id: "sad"})
    b.say("narrator", f"Feeling nervous is okay. {a.name} takes a big breath.", act={a.character_id: "stretch"})
    b.say(t.character_id, "Let's try slowly. Clap with me, one, two.", act={t.character_id: "clap", a.character_id: "clap"})
    b.say(a.character_id, "One, two. One, two. I can do it!", act={a.character_id: "clap"}, number=(2, "orange"))
    b.say("narrator", "Clap, boom, ding! Three friends play together.", act={a.character_id: "clap", f.character_id: "dance", t.character_id: "dance"},
          fx="sparkle")
    b.say(f.character_id, f"You did it, {a.name}! That sounded great.", act={f.character_id: "cheer"})
    b.say(a.character_id, "Trying slowly helped me feel brave.", act={a.character_id: "hop"})
    b.say("narrator", "Small steps can help us try new things.", act={a.character_id: "nod"})
    b.say(a.character_id, "What new thing would you like to try?", act={a.character_id: "wave"}, end=f"See you next time in {u.title}!")
    return ("emotional", f"{a.name} is nervous to join music day and learns to try slowly.", "Small steps help us try new things.",
            f"{a.name} Plays Along")


def _plot_seed_glow(rng, u, b, c):
    """The owner's v0.3 story "The Seed That Wouldn't Shine", staged for the engine; their dialogue kept where it fits.

    At most three friends are on stage (the storyboard draws three), two when a prop sits between them, so nobody
    speaks off-screen and the seed is never hidden behind a body."""
    by = {x.character_id: x for x in c}
    pip, bri, mor, til, oak = (by.get(k) or c[i] for i, k in enumerate(("pipkin", "brindle", "morrow", "tilli", "oakley")))
    env = {v: k for k, v in u.places.items()}
    clearing, creek, garden, top = (env.get(n, d) for n, d in (("Fernbridge clearing", "meadow"), ("Mossy creek", "pond"),
                                                               ("Root garden", "garden"), ("Valley panorama", "hilltop")))
    P, B_, M, T, O = (x.character_id for x in (pip, bri, mor, til, oak))
    every = (P, B_, M, T, O)
    b.go(clearing).enter(P, T).put("cloud", layout="sky", x=540, y=420, size=260)
    b.say("narrator", "The storm cloud drifts away. The glow seeds start to shine.", title="The Seed That Wouldn't Shine", sfx=["whoosh"])
    b.put("seed", x=540, y=1330, size=130)
    b.say(P, "The last seed isn't glowing!", act={P: "point", T: "wow"})
    b.say(T, "Maybe it needs a little sunshine.", act={T: "look_up"})
    b.go(creek).leave(*every).enter(B_, P).hold(B_, "leaf", None, 90)
    b.say("narrator", f"{bri.name} builds a shiny leaf to catch the light.", act={B_: "hold_up"})
    b.hold(B_, None).put("boat", x=540, y=1330, size=170)
    b.say(B_, "Oops! My brilliant invention has become a boat.", act={B_: "wow", P: "clap"}, sfx=["splash"])
    b.go(garden).leave(*every).enter(O, M).put("tree", x=540, y=1150, size=330).put("seed", x=540, y=1340, size=120)
    b.say(O, "Look! The seed is stuck under a tangled root.", act={O: "point"})
    b.say(M, "Let's listen before we pull.", act={M: "think"})
    b.say(O, "I can loosen the soil, very gently.", act={O: "tiptoe"})
    b.go(clearing).leave(*every).enter(B_, O).hold(B_, "leaf", None, 90).put("seed", x=540, y=1330, size=130)
    b.put("sun", layout="sky", x=820, y=380, size=200)
    b.say("narrator", f"Light from {bri.name}'s leaf. Soft soil from {oak.name}.", act={B_: "hold_up", O: "nod"})
    b.drop("seed").put("star", x=540, y=1300, size=150, color="yellow")
    b.say("narrator", "The little seed begins to glow!", act={B_: "cheer", O: "cheer"}, fx="sparkle", sfx=["ding"])
    b.hold(B_, None).leave(*every).enter(P, T).put("star", x=540, y=1300, size=150, color="yellow")
    b.say(P, "Together did it!", act={P: "hop", T: "cheer"})
    b.say(T, "And nobody had to be a superhero.", act={T: "dance"})
    b.go(top).leave(*every).enter(M, T).put("sprout", x=540, y=1320, size=170)
    for x, y in ((420, 1050), (540, 990), (660, 1050)):
        b.put("firefly", x=x, y=y, size=60)
    b.say("narrator", "A new sprout opens. Fireflies make a tiny crown.", act={M: "wow", T: "wow"}, fx="sparkle")
    b.say(M, "Every little light belongs.", act={M: "nod", T: "hop"})
    b.say(T, "What small thing could you do to help a friend?", act={T: "wave"}, end=f"See you next time in {u.title}!")
    return ("friendship", "The last glow seed stays dark after a storm; five friends each add a small part and it shines.",
            "A small contribution matters when everyone works together.", "The Seed That Wouldn't Shine")


PLOTS = {"seed-glow": _plot_seed_glow, "runaway-kite": _plot_lost_kite, "rainy-picnic": _plot_rain_picnic, "nervous-drum": _plot_nervous_drum}


MAX_ON_STAGE = 3   # the engine's storyboard draws at most three characters per shot


def staging_issues(beats: list[dict]) -> list[str]:
    """Catch what the renderer would silently drop: a fourth character, or a line spoken by someone not on stage."""
    out = []
    for i, bt in enumerate(beats, 1):
        ids = [a["id"] for a in bt["actors"]]
        if len(ids) > MAX_ON_STAGE:
            out.append(f"beat {i}: {len(ids)} characters on stage; only {MAX_ON_STAGE} are drawn")
        if bt["speaker"] != "narrator" and bt["speaker"] not in ids[:MAX_ON_STAGE]:
            out.append(f"beat {i}: {bt['speaker']} speaks but is not on stage")
    return out


def act_for(i: int, n: int) -> str:
    return ACTS[min(6, int(i * 7 / n))]


def write_episode(u: UniverseBible, plot: str | None = None, seed: str = "1", target_seconds: int = 60) -> EpisodeScript:
    engine.load()
    from wonderland.departments import compliance
    from wonderland.departments.story_formats import B
    from wonderland.render.environments import ENVS
    from wonderland.render.props import PROPS

    rng = random.Random(f"{u.universe_id}|{plot}|{seed}")
    plot = plot or rng.choice(sorted(k for k in PLOTS if k != "seed-glow"))
    uni = engine_universe(u)
    b = B(uni, "meadow")
    theme, logline, moral, title = PLOTS[plot](rng, u, b, u.characters)
    cast = sorted({a["id"] for bt in b.beats for a in bt["actors"]})
    story = {"title": title, "summary": logline, "learning_goal": moral, "beats": b.beats}
    verdict = compliance.review_story(story, set(PROPS), {c.character_id for c in u.characters}, set(ENVS))
    issues = verdict["errors"] + check_words(" ".join(bt["text"] for bt in b.beats) + " " + title) + staging_issues(b.beats)
    if issues:
        raise ValueError("episode failed review: " + "; ".join(issues[:4]))
    names = {c.character_id: c.name for c in u.characters}
    scenes = []
    for i, bt in enumerate(b.beats):
        act = act_for(i, len(b.beats))
        cam = CAMERA[act]
        scenes.append(SceneSpec(number=i + 1, act=act, location=u.places.get(bt["env"], bt["env"]), environment=bt["env"],
                                characters=[names[a["id"]] for a in bt["actors"]], actions={names[a["id"]]: a["action"] for a in bt["actors"]},
                                dialogue={"speaker": names.get(bt["speaker"], "Narrator"), "text": bt["text"]}, camera_angle=cam[0],
                                camera_movement=cam[1], lighting=LIGHT.get(bt["env"], "warm key 45°, cool fill, teal/orange rims"),
                                background=f"painted {bt['env']} set", sound_effects=list(bt.get("sfx") or []), music=MUSIC[act],
                                transition="cross-dissolve" if i and b.beats[i - 1]["env"] != bt["env"] else "cut"))
    return EpisodeScript(episode_id=f"{u.universe_id}-{plot}-{seed}", universe_id=u.universe_id, title=title, theme=theme, logline=logline,
                         moral=moral, target_seconds=target_seconds, scenes=scenes, beats=b.beats,
                         originality={"plot": plot, "issues": [], "review": "engine child-safety review passed", "cast": cast,
                                      "mood": "bright"})
