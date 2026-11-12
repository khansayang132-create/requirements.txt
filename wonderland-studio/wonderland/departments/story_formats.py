"""The story formats: original Wonder Meadow stories for categories A-H.

A format is a function ``(rng, uni) -> Story``. It picks its own cast, setting and
content from the seeded ``rng`` and writes the beats with the ``B`` builder. Every beat
is one short spoken line plus what the stage shows while it is said.

Writing rules these formats follow (and ``compliance`` re-checks on every story):
* one small idea per video; sentences of 12 words or fewer;
* facts must be true and stated plainly (no "light things float" style shortcuts);
* nobody is in danger, nobody is mean, problems are preschool-sized;
* no pronouns for the characters (so no character is mis-gendered by a template);
* the only question to the viewer is a gentle, optional one at the end — never a
  request to like, subscribe, buy or share anything about themselves.

All text is original to this project. US spelling ("color") is used throughout.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..render.props import LETTERS, TINTABLE, spoken_name

NUM = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
INTERJ = ["Ooh!", "Look!", "Wow!", "Oh my!", "I see it!"]
PLACES = {"meadow": "the sunny meadow", "garden": "the flower garden", "pond": "the little pond", "hilltop": "the breezy hilltop",
          "forest": "the friendly woods", "rainy": "the rainy meadow", "playroom": "the playroom", "bathroom": "the washroom",
          "bedroom": "the cozy bedroom", "night": "the starry meadow"}
COLOR_LIKE = {"red": "Red like a ripe strawberry.", "yellow": "Yellow like the warm sun.", "blue": "Blue like the big sky.",
              "green": "Green like the meadow grass.", "orange": "Orange like a juicy orange.", "purple": "Purple like sweet grapes.",
              "pink": "Pink like cherry blossoms.", "brown": "Brown like a teddy bear."}
SPECIES_WORD = {"bunny": "bunny", "cat": "kitten", "elephant": "elephant", "duck": "duckling", "bear": "bear"}


def an(word: str) -> str:
    return ("an " if word[0].lower() in "aeiou" else "a ") + word


def join_words(words: list[str]) -> str:
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


@dataclass
class Story:
    category: str
    format: str
    series: str
    title: str
    summary: str
    learning_goal: str
    mood: str
    cast: list[str]
    beats: list[dict]
    topics: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    song: bool = False

    def script(self) -> str:
        return " ".join(b["text"] for b in self.beats)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("category", "format", "series", "title", "summary", "learning_goal", "mood",
                                              "cast", "beats", "topics", "params", "song")}


# Technical QA rejects any stretch of 3 s without visible motion (ffmpeg freezedetect, n=0.002).
# Measured on the flat renderer: these actions, effects, props and scenes always move enough;
# a still pose (idle, pointing, looking up, even talking) or a gently bobbing prop does not.
MOVING_ACTIONS = {"nod", "clap", "cheer", "dance", "hop", "stretch"}
MOVING_FX = {"hearts", "notes"}
MOVING_PROPS = {"sun", "butterfly", "snowflake"}
MOVING_ENVS = {"night"}
CALM_SWAP = ("idle", "look_up", "wow", "think", "tiptoe", "point")   # poses a gentle nod can replace


def keep_moving(acts: dict, speaker: str, fx, env: str, items: list[dict]) -> dict:
    """Give a beat that would otherwise look frozen one gentle nod (a listener first)."""
    if (env in MOVING_ENVS or fx in MOVING_FX or any(a in MOVING_ACTIONS for a in acts.values())
            or any(it["name"] in MOVING_PROPS or it.get("layout") in ("fly", "fall") for it in items)):
        return acts
    order = sorted(acts, key=lambda c: (c == speaker, CALM_SWAP.index(acts[c]) if acts[c] in CALM_SWAP else 99))
    for cid in order:
        if acts[cid] in CALM_SWAP:
            return {**acts, cid: "nod"}
    return acts


class B:
    """Beat builder with a persistent stage (cast, showcase, ground items)."""

    def __init__(self, uni: dict, env: str):
        self.uni = uni
        self.names = {c["id"]: c["name"] for c in uni["characters"]}
        self.env = env
        self.cast: list[str] = []
        self.state: dict[str, dict] = {}
        self.show_items: list[dict] = []
        self.ground: list[dict] = []
        self.beats: list[dict] = []

    def n(self, cid: str) -> str:
        return self.names[cid]

    def enter(self, *ids: str) -> "B":
        for i in ids:
            if i not in self.cast:
                self.cast.append(i)
                self.state[i] = {}
        return self

    def leave(self, *ids: str) -> "B":
        for i in ids:
            if i in self.cast:
                self.cast.remove(i)
        return self

    def go(self, env: str, keep_show: bool = False) -> "B":
        self.env = env
        self.ground = []
        if not keep_show:
            self.show_items = []
        return self

    def show(self, name: str, color: str | None = None, count: int = 1, **kw) -> "B":
        self.show_items.append({"name": name, "color": color, "count": count, "layout": "show", "new": True, **kw})
        return self

    def put(self, name: str, layout: str = "ground", **kw) -> "B":
        self.ground.append({"name": name, "layout": layout, "new": True, **kw})
        return self

    def clear(self, ground: bool = False) -> "B":
        self.show_items = []
        if ground:
            self.ground = []
        return self

    def drop(self, name: str) -> "B":
        self.ground = [g for g in self.ground if g["name"] != name]
        self.show_items = [g for g in self.show_items if g["name"] != name]
        return self

    def hold(self, cid: str, name: str | None, color: str | None = None, size: int = 60, side: int = 1) -> "B":
        self.state[cid]["hold"] = {"name": name, "color": color, "size": size, "side": side} if name else None
        return self

    def say(self, who: str, text: str, act: dict | None = None, word=None, number=None, letter=None, title=None, end=None,
            fx=None, transfer=None, sfx=None, sub=None) -> "B":
        acts = {cid: (act or {}).get(cid, "idle") for cid in self.cast}
        if not transfer:
            acts = keep_moving(acts, who, fx, self.env, self.show_items + self.ground)
        actors = []
        for cid in self.cast:
            actors.append({"id": cid, "action": acts[cid], "hold": self.state[cid].get("hold")})
        overlay = None
        if title:
            overlay = {"text": title, "style": "title", "color": "pink"}
        elif end:
            overlay = {"text": end, "style": "end", "color": "yellow"}
        elif number is not None:
            overlay = {"text": str(number[0]) if isinstance(number, tuple) else str(number), "style": "number",
                       "color": number[1] if isinstance(number, tuple) else "orange", "sub": sub}
        elif letter:
            overlay = {"text": letter, "style": "letter", "color": "purple", "sub": sub}
        elif word:
            overlay = {"text": word[0], "style": "word", "color": word[1], "sub": sub}
        items = []
        for it in self.show_items + self.ground:
            d = {k: v for k, v in it.items() if k != "new"}
            d["appear"] = "pop" if it.get("new") else "already"
            if it.get("new") and it["layout"] == "show":
                d["highlight"] = True
            items.append(d)
            it["new"] = False
        self.beats.append({"speaker": who, "text": text, "env": self.env, "actors": actors, "items": items, "overlay": overlay,
                           "fx": fx, "transfer": transfer, "sfx": list(sfx or [])})
        return self


def _pick_cast(rng: random.Random, uni: dict, k: int) -> list[str]:
    return rng.sample([c["id"] for c in uni["characters"]], k)


def _species(uni: dict, cid: str) -> str:
    return SPECIES_WORD[next(c for c in uni["characters"] if c["id"] == cid)["species"]]


# =====================================================================================
# A — colors, shapes, numbers
# =====================================================================================
def color_walk(rng, uni) -> Story:
    env = rng.choice(["meadow", "garden", "hilltop", "pond", "playroom"])
    prop = rng.choice({"meadow": ["balloon", "flower", "butterfly", "kite"], "garden": ["flower", "butterfly"],
                       "hilltop": ["kite", "balloon"], "pond": ["fish", "boat"],
                       "playroom": ["block", "ball", "balloon", "book", "cup", "hat", "bucket"]}[env])
    colors = rng.sample(["red", "yellow", "blue", "green", "orange", "purple", "pink"], rng.choice([3, 3, 4]))
    who = _pick_cast(rng, uni, 1)[0]
    b = B(uni, env).enter(who)
    N = b.n(who)
    b.say("narrator", f"{N} is going on a color walk in {PLACES[env]}.", title=f"{N}'s Color Walk")
    b.say(who, rng.choice(["I wonder what colors I will find!", "Let's look for colors together!", "So many colors to find today!"]),
          act={who: "wave"})
    for c in colors:
        b.show(prop, c)
        b.say(who, f"{rng.choice(INTERJ)} {cap(an(c))} {spoken_name(prop)}!", act={who: "point"}, word=(c.upper(), c))
        b.say("narrator", COLOR_LIKE[c], act={who: "nod"}, word=(c.upper(), c))
    b.say("narrator", f"{cap(join_words(colors))}. What a colorful day!", act={who: "cheer"}, fx="sparkle")
    b.say(who, rng.choice(["Which color do you like best?", f"Can you find something {colors[0]} near you?"]), act={who: "wave"},
          end=uni["brand"]["end_card"])
    return Story("A", "color_walk", "colour_walk", f"{N}'s Color Walk: {cap(join_words(colors))}",
                 f"{N} goes for a walk in {PLACES[env]} and finds {join_words(colors)} {spoken_name(prop, 2)}.",
                 f"Name the colors {join_words(colors)}.", "bright", [who], b.beats, ["colors"] + colors,
                 {"env": env, "prop": prop, "colors": sorted(colors), "who": who})


def count_with_me(rng, uni) -> Story:
    n = rng.choice([3, 4, 4, 5, 5, 6])
    env, prop, color = rng.choice([("meadow", "balloon", None), ("meadow", "butterfly", "purple"), ("garden", "flower", None),
                                   ("pond", "fish", "orange"), ("forest", "acorn", None), ("forest", "mushroom", None),
                                   ("night", "star", "yellow"), ("playroom", "block", None), ("playroom", "ball", "blue"),
                                   ("garden", "apple", None), ("garden", "carrot", None), ("hilltop", "kite", None),
                                   ("garden", "ladybug", None), ("pond", "frog", None)])
    palette = ["red", "blue", "yellow", "green", "purple", "orange", "pink"]
    who = _pick_cast(rng, uni, 1)[0]
    b = B(uni, env).enter(who)
    N, plural = b.n(who), spoken_name(prop, 2)
    b.say("narrator", f"{N} found some {plural} in {PLACES[env]}.", title=f"Count With {N}: {cap(plural)}")
    b.say(who, rng.choice(["I love counting! Let's count them.", "How many are there? Let's count!"]), act={who: "wave"})
    for i in range(1, n + 1):
        b.show(prop, color or palette[(i - 1) % len(palette)] if prop in ("balloon", "flower", "block", "kite") else color)
        b.say(who, f"{cap(NUM[i])}!", act={who: "point"}, number=i, sfx=["tick"])
    b.say("narrator", f"{cap(NUM[n])} {plural}! {N} counted {NUM[n]} {plural}.", act={who: "cheer"}, number=n, sub=f"{NUM[n]} {plural}")
    b.say(who, "Let's count again, all together!", act={who: "wave"}, number=n)
    b.say(who, ", ".join(NUM[1:n + 1]).capitalize() + "!", act={who: "hop"}, number=n, fx="sparkle")
    b.say("narrator", f"Great counting! Can you count to {NUM[n]} too?", act={who: "cheer"}, end=uni["brand"]["end_card"])
    return Story("A", "count_with_me", "count_with_me", f"Count to {n} With {N}: {cap(plural)}",
                 f"{N} counts {NUM[n]} {plural} one by one in {PLACES[env]}, then counts them again.",
                 f"Count from one to {NUM[n]}.", "bright", [who], b.beats, ["counting", "numbers", prop],
                 {"env": env, "prop": prop, "n": n, "who": who})


SHAPE_FACT = {"circle": "A circle is round. It has no corners.", "square": "A square has four sides, all the same.",
              "triangle": "A triangle has three sides and three corners.", "rectangle": "A rectangle has two long sides and two short sides.",
              "star": "This star has five points.", "heart": "A heart is the shape we draw for love.",
              "diamond": "A diamond has four sides, like a kite.", "oval": "An oval is long and round, like an egg."}
SHAPE_MATCH = {"circle": ["ball", "orange"], "square": ["block"], "rectangle": ["book", "towel"], "oval": ["egg"], "diamond": ["kite"]}


def shape_spotters(rng, uni) -> Story:
    shapes = rng.sample(list(SHAPE_FACT), 3)
    colors = rng.sample(["red", "yellow", "blue", "green", "orange", "purple", "pink"], 3)
    who = _pick_cast(rng, uni, 1)[0]
    env = rng.choice(["playroom", "meadow", "garden"])
    b = B(uni, env).enter(who)
    N = b.n(who)
    b.say("narrator", f"{N} has a box full of shapes. What is inside?", title=f"Shape Spotters With {N}", act={who: "think"})
    for s, c in zip(shapes, colors):
        b.clear().show(s, c)
        b.say(who, f"{rng.choice(INTERJ)} {cap(an(s))}!", act={who: "point"}, word=(s.upper(), c))
        b.say("narrator", SHAPE_FACT[s], act={who: "nod"}, word=(s.upper(), c))
        if s in SHAPE_MATCH and rng.random() < 0.7:
            m = rng.choice(SHAPE_MATCH[s])
            b.show(m)
            b.say(who, f"{cap(an(spoken_name(m)))} is {an(s)} too!", act={who: "cheer"}, word=(s.upper(), c))
    b.clear()
    for s, c in zip(shapes, colors):
        b.show(s, c)
    b.say("narrator", f"{cap(join_words(shapes))}. {N} is a super shape spotter!", act={who: "cheer"}, fx="sparkle")
    b.say(who, f"Can you spot {an(shapes[0])} at home?", act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("A", "shape_spotters", "shape_spotters", f"Shape Spotters: {cap(join_words(shapes))}",
                 f"{N} opens a box of shapes and finds {join_words([an(s) for s in shapes])}.",
                 f"Recognize {join_words(shapes)}.", "bright", [who], b.beats, ["shapes"] + shapes,
                 {"shapes": sorted(shapes), "who": who, "env": env})


def opposites(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    pairs = rng.sample(["big_small", "one_many", "up_down", "day_night", "awake_asleep"], 3)
    b = B(uni, "meadow").enter(who)
    N = b.n(who)
    b.say("narrator", f"{N} is learning about opposites today.", title=f"Opposites With {N}", act={who: "wave"})
    words = []
    for p in pairs:
        b.go("meadow")
        if p == "big_small":
            prop, col = rng.choice([("balloon", "red"), ("ball", "blue"), ("star", "yellow"), ("apple", None)])
            b.show(prop, col, size=150)
            b.say(who, f"This {spoken_name(prop)} is big!", act={who: "point"}, word=("BIG", "red"))
            b.clear().show(prop, col, size=60)
            b.say(who, f"This {spoken_name(prop)} is small.", act={who: "point"}, word=("SMALL", "blue"))
            words += ["big", "small"]
        elif p == "one_many":
            prop = rng.choice(["flower", "star", "butterfly", "fish"])
            b.show(prop, "pink")
            b.say(who, f"Here is one {spoken_name(prop)}.", act={who: "point"}, word=("ONE", "orange"))
            b.clear().show(prop, "pink", 7)
            b.say(who, f"Here are many {spoken_name(prop, 2)}!", act={who: "cheer"}, word=("MANY", "green"))
            words += ["one", "many"]
        elif p == "up_down":
            b.put("kite", "sky", x=540, y=560, size=120, color="purple")
            b.say(who, "The kite is up, up in the sky.", act={who: "look_up"}, word=("UP", "blue"))
            b.clear(ground=True).put("ball", "ground", x=820, size=70, color="red")
            b.say(who, "The ball is down on the ground.", act={who: "nod"}, word=("DOWN", "green"))
            words += ["up", "down"]
        elif p == "day_night":
            b.say("narrator", "In the day, the sky is bright.", act={who: "look_up"}, word=("DAY", "yellow"))
            b.go("night")
            b.say("narrator", "At night, the sky is dark.", act={who: "look_up"}, word=("NIGHT", "purple"))
            words += ["day", "night"]
        elif p == "awake_asleep":
            b.say("narrator", f"Now {N} is awake. Hello!", act={who: "wave"}, word=("AWAKE", "orange"))
            b.go("night")
            b.say("narrator", f"Now {N} is asleep. Shh.", act={who: "sleep"}, word=("ASLEEP", "purple"), fx="zzz")
            words += ["awake", "asleep"]
    b.go("meadow")
    b.say("narrator", f"{cap(words[0])} and {words[1]}. {cap(words[2])} and {words[3]}. Those are opposites!", act={who: "cheer"}, fx="sparkle")
    b.say(who, "Can you think of an opposite?", act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("A", "opposites", "shape_spotters", f"Opposites With {N}: {cap(words[0])} and {cap(words[1])}",
                 f"{N} shows three pairs of opposites: {words[0]} and {words[1]}, {words[2]} and {words[3]}, {words[4]} and {words[5]}.",
                 "Understand simple opposites.", "bright", [who], b.beats, ["opposites"] + words, {"pairs": sorted(pairs), "who": who})


MIXES = [("red", "yellow", "orange"), ("blue", "yellow", "green"), ("red", "blue", "purple"), ("red", "white", "pink")]


def color_mix(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    mixes = rng.sample(MIXES, 2)
    b = B(uni, rng.choice(["playroom", "garden"])).enter(who)
    N = b.n(who)
    b.say("narrator", f"{N} is painting today.", title=f"Mixing Colors With {N}", act={who: "wave"})
    for c1, c2, r in mixes:
        b.clear().show("circle", c1).show("circle", c2)
        b.say(who, f"I have {c1} paint and {c2} paint.", act={who: "point"})
        b.say("narrator", f"What happens when we mix {c1} and {c2}?", act={who: "think"})
        b.clear().show("circle", r, size=150)
        b.say(who, f"{cap(c1)} and {c2} make {r}!", act={who: "cheer"}, word=(r.upper(), r), fx="sparkle")
    b.say("narrator", f"{cap(mixes[0][0])} and {mixes[0][1]} make {mixes[0][2]}. {cap(mixes[1][0])} and {mixes[1][1]} make {mixes[1][2]}.",
          act={who: "nod"})
    b.say(who, "Mixing colors is so much fun!", act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("A", "color_mix", "colour_walk", f"Mixing Colors With {N}: {cap(mixes[0][2])} and {cap(mixes[1][2])}",
                 f"{N} mixes paint: {mixes[0][0]} and {mixes[0][1]} make {mixes[0][2]}, {mixes[1][0]} and {mixes[1][1]} make {mixes[1][2]}.",
                 "Two colors can be mixed to make a new color.", "bright", [who], b.beats,
                 ["colors", "color mixing", mixes[0][2], mixes[1][2]], {"mixes": sorted(m[2] for m in mixes), "who": who})


def one_more(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    start = rng.choice([1, 2, 3])
    env, prop, col = rng.choice([("garden", "apple", None), ("meadow", "balloon", "blue"), ("pond", "fish", "orange"),
                                 ("playroom", "block", "green"), ("night", "star", "yellow"), ("garden", "flower", "pink"),
                                 ("forest", "acorn", None), ("playroom", "teddy", None)])
    b = B(uni, env).enter(who)
    N, one, plural = b.n(who), spoken_name(prop), spoken_name(prop, 2)
    b.show(prop, col, start)
    b.say("narrator", f"{N} has {NUM[start]} {one if start == 1 else plural}.", title=f"One More! Counting With {N}", number=start)
    cur = start
    for _ in range(2):
        b.say(who, rng.choice(["Here comes one more!", "Look, one more!"]), act={who: "point"}, number=cur)
        b.show(prop, col)
        cur += 1
        b.say("narrator", f"{cap(NUM[cur - 1])} and one more makes {NUM[cur]}.", act={who: "nod"}, number=cur, sfx=["ding"])
        b.say(who, f"{cap(NUM[cur])} {plural}!", act={who: "cheer"}, number=cur)
    b.say("narrator", f"One more makes the number grow. Now there are {NUM[cur]}!", act={who: "cheer"}, number=cur, fx="sparkle")
    b.say(who, f"What comes after {NUM[cur]}?", act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("A", "one_more", "count_with_me", f"One More! {N} Counts {cap(plural)} From {start} to {cur}",
                 f"{N} starts with {NUM[start]} {plural} and adds one more, twice, to reach {NUM[cur]}.",
                 "Adding one more makes the next number.", "bright", [who], b.beats, ["counting", "one more", "numbers", prop],
                 {"prop": prop, "start": start, "who": who, "env": env})


# =====================================================================================
# B — animal adventures
# =====================================================================================
FIND = {
    "frog": ("pond", "A little green frog! Frogs love to hop."), "fish": ("pond", "A shiny fish! Fish swim in the water."),
    "snail": ("garden", "A snail! It carries its home on its back."), "ladybug": ("garden", "A ladybug with little black spots!"),
    "ant": ("meadow", "A tiny ant! Ants are small but strong."), "mushroom": ("forest", "A mushroom! Mushrooms grow in shady places."),
    "acorn": ("forest", "An acorn! It can grow into a big oak tree."), "nest": ("forest", "A nest! Birds lay their eggs in a nest."),
    "flower": ("garden", "A flower! Flowers need sun and water."), "butterfly": ("meadow", "A butterfly with colorful wings!"),
    "kite": ("hilltop", "A kite, dancing in the wind!"), "rainbow": ("hilltop", "A rainbow, with so many colors!"),
}
LEADERS = {"butterfly": "fluttered away", "ladybug": "flew away", "leaf": "danced away on the wind"}


def meadow_explorers(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    leader = rng.choice(list(LEADERS))
    finds = rng.sample([f for f in FIND if f != leader], 2)
    while FIND[finds[0]][0] == FIND[finds[1]][0]:
        finds = rng.sample([f for f in FIND if f != leader], 2)
    b = B(uni, "meadow").enter(who)
    N = b.n(who)
    lcol = {"butterfly": "purple", "ladybug": None, "leaf": "orange"}[leader]
    b.put(leader, "fly", color=lcol, size=58, y=760)
    b.say("narrator", f"One {rng.choice(['sunny', 'bright', 'lovely'])} morning, {N} saw a little {leader}.",
          title=f"{N} and the Little {cap(leader)}", act={who: "look_up"})
    b.say(who, f"Hello, little {leader}! Where are you going?", act={who: "wave"})
    b.say("narrator", f"The {leader} {LEADERS[leader]}. {N} followed. Hop, hop, hop!", act={who: "hop"}, sfx=["boing"])
    for f in finds:
        env, fact = FIND[f]
        b.go(env).put(leader, "fly", color=lcol, size=58, y=820)
        if f == "rainbow":
            b.put("rainbow", "sky", x=540, y=600, size=230)
        else:
            b.show(f, "pink" if f in ("flower", "butterfly", "kite") else None)
        b.say("narrator", f"They came to {PLACES[env]}. What did {N} find?", act={who: "look_up"})
        b.say(who, fact, act={who: "point"}, word=(spoken_name(f).upper(), "green"))
    b.say("narrator", f"What a wonderful adventure! {N} waved goodbye to the {leader}.", act={who: "wave"}, fx="sparkle",
          end=uni["brand"]["end_card"])
    return Story("B", "meadow_explorers", "meadow_explorers", f"{N} Follows a {cap(leader)}: A Little Adventure",
                 f"{N} follows a {leader} across Wonder Meadow and discovers {an(spoken_name(finds[0]))} and {an(spoken_name(finds[1]))}.",
                 f"Learn one true fact about {an(spoken_name(finds[0]))} and {an(spoken_name(finds[1]))}.", "adventure", [who], b.beats,
                 ["adventure", "nature", "animals", leader] + finds, {"leader": leader, "finds": sorted(finds), "who": who})


def lost_and_found(rng, uni) -> Story:
    who, friend = _pick_cast(rng, uni, 2)
    item, col = rng.choice([("hat", "orange"), ("ball", "red"), ("teddy", None), ("sock", "purple"), ("kite", "blue"),
                            ("book", "green"), ("key", None), ("bucket", "yellow")])
    wrong = rng.sample([("pond", "frog"), ("garden", "snail"), ("forest", "mushroom"), ("garden", "ladybug"), ("pond", "fish")], 2)
    final = rng.choice([e for e in ("forest", "hilltop", "meadow") if e not in (wrong[0][0], wrong[1][0])])
    b = B(uni, "meadow").enter(who)
    N, F, it = b.n(who), b.n(friend), spoken_name(item)
    b.say("narrator", f"Oh dear. {N} cannot find the {it}.", title=f"Where Is {N}'s {cap(it)}?", act={who: "sad"})
    b.say(who, f"Where is my {it}? Let's go and look!", act={who: "think"})
    for env, thing in wrong:
        b.go(env).show(thing)
        b.say(who, f"Is it at {PLACES[env]}?", act={who: "look_up"})
        b.say("narrator", f"No. That is {an(spoken_name(thing))}!", act={who: "nod"}, word=(spoken_name(thing).upper(), "green"))
    b.go(final).enter(friend).put(item, "ground", x=540, size=74, color=col, front=True)
    b.say(friend, f"Look, {N}! Is this your {it}?", act={friend: "point", who: "wow"})
    b.say(who, f"Yes! My {it}! Thank you, {F}!", act={who: "cheer", friend: "clap"}, fx="hearts", sfx=["chime"])
    b.say("narrator", f"{N} kept looking and a friend helped. Hooray!", act={who: "cheer", friend: "cheer"}, end=uni["brand"]["end_card"])
    return Story("B", "lost_and_found", "meadow_explorers", f"Where Is {N}'s {cap(it)}? A Lost and Found Adventure",
                 f"{N} looks for a lost {it} by the {wrong[0][0]} and the {wrong[1][0]}, and {F} helps find it.",
                 "Keep looking calmly; friends can help.", "adventure", [who, friend], b.beats,
                 ["adventure", "lost and found", "helping", item], {"item": item, "who": who, "friend": friend, "final": final})


HOMES = [("pond", "fish", "Who lives in the pond?", "A fish! Fish live in the water."),
         ("pond", "frog", "Who sits by the pond?", "A frog! Frogs live near the water."),
         ("forest", "nest", "Who lives in the nest?", "A bird! Birds make nests in trees."),
         ("garden", "snail", "Who carries a home along?", "A snail! The shell is the snail's home."),
         ("garden", "ladybug", "Who lives among the leaves?", "A ladybug! It rests on leaves and flowers."),
         ("meadow", "ant", "Who lives under the ground?", "Ants! Ants dig tiny tunnels.")]


def who_lives_here(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    homes = rng.sample(HOMES, 3)
    b = B(uni, "meadow").enter(who)
    N = b.n(who)
    b.say("narrator", f"{N} is exploring Wonder Meadow. Who lives here?", title="Who Lives Here?", act={who: "wave"})
    names = []
    for env, thing, q, a in homes:
        b.go(env)
        b.say(who, q, act={who: "think"})
        b.show(thing)
        b.say("narrator", a, act={who: "point"}, word=(spoken_name(thing).upper(), "blue"), sfx=["ding"])
        names.append(spoken_name(thing))
    b.go("meadow")
    b.say("narrator", f"And who lives in the cozy burrow? {N} and friends!", act={who: "cheer"}, fx="hearts")
    b.say(who, "Everyone needs a cozy home!", act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("B", "who_lives_here", "meadow_explorers", f"Who Lives Here? {N} Finds Animal Homes",
                 f"{N} explores and finds out where {join_words(names)} live.",
                 "Different animals live in different homes.", "adventure", [who], b.beats,
                 ["animals", "animal homes", "nature"] + names, {"homes": sorted(h[1] for h in homes), "who": who})


# =====================================================================================
# C — friendship and kindness
# =====================================================================================
def _v(rng, *options: str) -> str:
    """One of several real wordings, so two episodes of a format do not read the same."""
    return rng.choice(options)


def sharing(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    toy, col = rng.choice([("ball", "red"), ("kite", "purple"), ("drum", None), ("teddy", None), ("book", "blue"), ("balloon", "yellow"),
                           ("boat", "orange"), ("bucket", "green"), ("bell", None)])
    env = rng.choice(["playroom", "meadow", "hilltop" if toy == "kite" else "garden"])
    b = B(uni, env).enter(x)
    X, Y, t = b.n(x), b.n(y), spoken_name(toy)
    b.hold(x, toy, col, 62)
    b.say("narrator", _v(rng, f"{X} has a {t}. It is {X}'s favorite toy.", f"Today {X} is playing with a {t}.",
                         f"{X} loves this {t} very much."), title=f"{X} Learns to Share", act={x: "hold_up"})
    b.enter(y)
    b.say("narrator", _v(rng, f"{Y} would like to play too.", f"Along comes {Y}. {Y} wants to play too.",
                         f"{Y} watches and wishes for a turn."), act={y: "look_up"})
    b.say(y, _v(rng, f"May I have a turn with the {t}, please?", f"Could I play with the {t} too, please?",
                f"That {t} looks fun. May I try, please?"), act={y: "wave"})
    b.say("narrator", _v(rng, f"{X} stops to think. Sharing a favorite toy can be hard.", f"{X} holds the {t} tight. Sharing can feel hard.",
                         f"Hmm. {X} is not sure. It is a special {t}."), act={x: "think"})
    b.hold(x, None)
    b.say(x, _v(rng, f"Here you go, {Y}. It is your turn!", f"Okay, {Y}. You can have a turn!", f"Yes! Let's share it, {Y}."),
          act={x: "give", y: "receive"}, transfer={"name": toy, "color": col, "from": x, "to": y, "size": 62}, fx="hearts", sfx=["chime"])
    b.hold(y, toy, col, 62, side=-1)
    b.say(y, _v(rng, f"Thank you, {X}! Let's play together.", f"Thank you, {X}! You are a kind friend.", f"Hooray! Thank you for sharing, {X}."),
          act={y: "cheer", x: "clap"})
    b.say("narrator", _v(rng, "Sharing makes playtime twice as fun.", "When we share, everyone gets to smile.",
                         "Sharing turns one happy friend into two."), act={x: "dance", y: "dance"}, fx="sparkle", end=uni["brand"]["end_card"])
    return Story("C", "sharing", "kind_friends", f"{X} Shares the {cap(t)} With {Y}",
                 f"{Y} asks for a turn with {X}'s {t}. {X} thinks about it and decides to share.",
                 "Sharing and asking politely for a turn.", "warm", [x, y], b.beats, ["sharing", "friendship", "kindness", toy],
                 {"toy": toy, "x": x, "y": y})


def saying_sorry(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    env, prop, col, doing = rng.choice([("playroom", "block", "blue", "building a row of blocks"), ("playroom", "book", "green", "lining up the story books"),
                                        ("pond", "boat", "red", "lining up little toy boats"), ("garden", "bucket", "yellow", "filling buckets with water"),
                                        ("playroom", "cup", "pink", "setting out cups for a tea party")])
    b = B(uni, env).enter(y)
    X, Y, many = b.n(x), b.n(y), spoken_name(prop, 2)
    b.put(prop, "ground", x=540, size=56, count=4, color=col, front=True)
    b.say("narrator", f"{Y} is {doing}. One, two, three, four!", title=f"{X} Says Sorry", act={y: "clap"})
    b.enter(x)
    b.say("narrator", _v(rng, f"Here comes {X}, hopping fast. Oh no!", f"{X} comes running by. Watch out!",
                         f"{X} is dancing and not looking. Uh oh!"), act={x: "hop"}, sfx=["boing"])
    b.clear(ground=True).put(prop, "ground", x=540, size=56, count=1, color=col, front=True)
    b.say("narrator", _v(rng, f"Bump! The {many} tumble down.", f"Crash! The {many} are all knocked over.",
                         f"Oops! Down go the {many}."), act={y: "sad", x: "wow"}, sfx=["pop"])
    b.say(x, _v(rng, f"Oh no. I am sorry, {Y}. It was an accident.", f"I am so sorry, {Y}. I did not mean to.",
                f"Sorry, {Y}. I was going too fast."), act={x: "sad", y: "sad"})
    b.say(y, _v(rng, "That is okay. Thank you for saying sorry.", "It is all right. Accidents happen.",
                "Thank you for telling me. I feel better."), act={y: "nod"})
    b.say(x, _v(rng, "Let's build it again, together!", "I will help you fix it!", "Can I help put them back?"), act={x: "cheer", y: "cheer"})
    b.clear(ground=True).put(prop, "ground", x=540, size=56, count=5, color=col, front=True)
    b.say("narrator", _v(rng, "Now there are even more. Saying sorry helps friends feel better.",
                         "All fixed, with one extra! Sorry is a small word that helps a lot.",
                         "Together they fix it. Saying sorry and helping makes things right."), act={x: "clap", y: "clap"},
          fx="hearts", end=uni["brand"]["end_card"])
    return Story("C", "saying_sorry", "kind_friends", f"{X} Says Sorry to {Y}",
                 f"{X} knocks over {Y}'s {many} by accident, says sorry, and helps put them back.",
                 "Saying sorry and making it right.", "warm", [x, y], b.beats, ["saying sorry", "friendship", "kindness", "feelings"],
                 {"x": x, "y": y, "prop": prop})


def helping(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    env, prop, col = rng.choice([("garden", "apple", None), ("forest", "acorn", None), ("garden", "carrot", None),
                                 ("playroom", "block", "green"), ("garden", "flower", "pink"), ("forest", "mushroom", None),
                                 ("playroom", "book", "blue"), ("meadow", "balloon", "red")])
    b = B(uni, env).enter(y)
    X, Y, plural = b.n(x), b.n(y), spoken_name(prop, 2)
    b.put(prop, "ground", x=540, size=50, count=5, color=col, front=True)
    b.say("narrator", _v(rng, f"{Y} has so many {plural} to carry.", f"{Y} is gathering {plural}. So many!",
                         f"Look at all the {plural}! {Y} has a big job."), title=f"{X} Helps {Y}", act={y: "think"})
    b.say(y, _v(rng, f"Oh my. Five {plural} are too many for me.", f"I cannot carry all the {plural} by myself.",
                f"One, two, three, four, five. That is a lot!"), act={y: "sad"})
    b.enter(x)
    b.say(x, _v(rng, f"Hello, {Y}! Can I help you?", f"You look busy, {Y}. May I help?", f"{Y}, do you need a helping hand?"), act={x: "wave"})
    b.say(y, _v(rng, "Yes, please! Thank you.", "Oh, yes please! That would be lovely.", "Yes, please. You are so kind."), act={y: "nod"})
    b.clear(ground=True).put(prop, "ground", x=540, size=50, count=1, color=col, front=True)
    b.hold(x, prop, col, 46).hold(y, prop, col, 46, side=-1)
    b.say("narrator", _v(rng, f"{X} carries some. {Y} carries some. Together it is easy!", f"Two friends, working together. The job is quick!",
                         f"{X} helps, and soon the work is done."), act={x: "hold_up", y: "hold_up"}, sfx=["chime"])
    b.say(y, _v(rng, f"Thank you for helping, {X}!", f"We did it! Thank you, {X}!", f"{X}, you are a wonderful helper!"), act={y: "cheer"}, fx="hearts")
    b.say(x, _v(rng, "You are welcome! Helping feels good.", "Any time! Friends help each other.", "I love helping my friends!"),
          act={x: "cheer"}, end=uni["brand"]["end_card"])
    return Story("C", "helping", "kind_friends", f"{X} Helps {Y} With the {cap(plural)}",
                 f"{Y} has too many {plural} to carry alone, so {X} offers to help.",
                 "Offering help and saying thank you.", "warm", [x, y], b.beats, ["helping", "friendship", "kindness", "teamwork"],
                 {"x": x, "y": y, "prop": prop})


def taking_turns(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    toy, col, sound = rng.choice([("drum", None, "Boom, boom, boom!"), ("ball", "blue", "Bounce, bounce, bounce!"),
                                  ("kite", "red", "Whoosh! Up it goes!"), ("bell", None, "Ding, ding, ding!"),
                                  ("book", "green", "Flip, flip, I turn the pages!"), ("balloon", "pink", "Boing! It floats so high!")])
    b = B(uni, "hilltop" if toy == "kite" else rng.choice(["playroom", "meadow"])).enter(x, y)
    X, Y, t = b.n(x), b.n(y), spoken_name(toy)
    b.put(toy, "ground", x=540, size=70, color=col, front=True)
    b.say("narrator", _v(rng, f"There is one {t}, and two friends want to play.", f"One {t}. Two friends. What can they do?",
                         f"{X} and {Y} both want the {t}."), title=f"Taking Turns With {X} and {Y}", act={x: "look_up", y: "look_up"})
    b.say(x, _v(rng, "Let's take turns! First me, then you.", "I know! We can take turns.", "Let's share it. I go first, you go next."), act={x: "wave"})
    b.clear(ground=True).hold(x, toy, col, 64)
    b.say(x, sound, act={x: "hold_up", y: "clap"}, word=("FIRST", "blue"), sfx=["boing"])
    b.say("narrator", _v(rng, f"{Y} waits nicely. Waiting can be hard, but {Y} can do it.", f"{Y} waits and watches. Good waiting, {Y}!",
                         f"{Y} counts slowly while waiting. One, two, three."), act={x: "hold_up", y: "nod"})
    b.hold(x, None)
    b.say(x, _v(rng, f"Now it is your turn, {Y}.", f"Your turn, {Y}! Here you go.", f"I am done. You can go now, {Y}."),
          act={x: "give", y: "receive"}, transfer={"name": toy, "color": col, "from": x, "to": y, "size": 64})
    b.hold(y, toy, col, 64, side=-1)
    b.say(y, sound, act={y: "hold_up", x: "clap"}, word=("THEN", "green"), sfx=["boing"])
    b.say("narrator", _v(rng, "First one friend, then the other. Taking turns is fair.", "Everybody gets a turn. That is fair and fun.",
                         "When we take turns, nobody is left out."), act={x: "cheer", y: "cheer"}, fx="sparkle", end=uni["brand"]["end_card"])
    return Story("C", "taking_turns", "kind_friends", f"{X} and {Y} Take Turns With the {cap(t)}",
                 f"{X} and {Y} both want the {t}, so they take turns: first {X}, then {Y}.",
                 "Taking turns and waiting: first, then.", "warm", [x, y], b.beats, ["taking turns", "friendship", "fairness", toy],
                 {"x": x, "y": y, "toy": toy})


def new_friend(rng, uni) -> Story:
    x, y, z = _pick_cast(rng, uni, 3)
    toy, col, game = rng.choice([("ball", "red", "playing ball"), ("kite", "blue", "flying a kite"), ("drum", None, "playing the drum"),
                                 ("block", "green", "building with blocks"), ("balloon", "yellow", "tossing a balloon")])
    b = B(uni, "hilltop" if toy == "kite" else rng.choice(["meadow", "garden", "playroom"])).enter(x, y)
    X, Y, Z = b.n(x), b.n(y), b.n(z)
    b.put(toy, "ground", x=540, size=60, color=col, front=True)
    b.say("narrator", f"{X} and {Y} are {game}.", title="Room for One More Friend", act={x: "cheer", y: "clap"})
    b.enter(z)
    b.say("narrator", _v(rng, f"{Z} is watching. {Z} feels a little shy.", f"{Z} stands nearby, all alone.",
                         f"{Z} would like to join, but feels too shy to ask."), act={z: "sad"})
    b.say(x, _v(rng, f"Look, {Y}. {Z} is all alone.", f"{Y}, I think {Z} wants to play.", f"Oh! There is {Z}."), act={x: "point"})
    b.say(y, _v(rng, f"Hello, {Z}! Would you like to play with us?", f"{Z}, come and play with us!", f"Hi, {Z}! We have room for you."), act={y: "wave"})
    b.say(z, _v(rng, "Yes, please! I would love to play.", "Really? Thank you! Yes, please.", "Oh, thank you! I was hoping you would ask."),
          act={z: "cheer"}, sfx=["chime"])
    b.say("narrator", _v(rng, "Now three friends play together.", "Three friends are even more fun than two.", f"Now {Z} is smiling too."),
          act={x: "dance", y: "dance", z: "dance"}, fx="hearts")
    b.say("narrator", _v(rng, "There is always room for one more friend.", "A kind hello can make a new friend.",
                         "When someone is alone, we can invite them in."), act={x: "cheer", y: "cheer", z: "cheer"}, end=uni["brand"]["end_card"])
    return Story("C", "new_friend", "kind_friends", f"{X} and {Y} Invite {Z} to Play",
                 f"{Z} feels shy and watches from the side until {X} and {Y} invite {Z} to join in {game}.",
                 "Including others who feel left out.", "warm", [x, y, z], b.beats, ["friendship", "including others", "kindness", "feelings"],
                 {"x": x, "y": y, "z": z, "toy": toy})


def cheering_up(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    thing, col, why = rng.choice([("balloon", "red", "My balloon floated away."), ("kite", "blue", "My kite got stuck up high."),
                                  ("icecream", None, "My ice cream fell on the ground."), ("boat", "orange", "My little boat sailed away."),
                                  ("flower", "pink", "My flower lost all its petals."), ("cupcake", None, "I dropped my cupcake.")])
    b = B(uni, rng.choice(["meadow", "garden", "hilltop"])).enter(y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"{Y} looks sad today.", f"Oh. {Y} is not smiling today.", f"{Y} sits quietly, feeling blue."),
          title=f"{X} Cheers Up {Y}", act={y: "sad"})
    b.enter(x)
    b.say(x, _v(rng, f"{Y}, are you okay? What happened?", f"What is wrong, {Y}?", f"{Y}, you look sad. Can you tell me why?"),
          act={x: "think", y: "sad"})
    b.say(y, why, act={y: "sad"})
    b.say(x, _v(rng, "Oh, that is sad. I am here with you.", "I am sorry that happened. Would you like a hug?",
                "That would make me sad too. I will stay with you."), act={x: "hug", y: "hug"}, fx="hearts")
    b.hold(x, thing, col, 60)
    b.say(x, _v(rng, f"Look! We can share my {spoken_name(thing)}.", f"I have {an(spoken_name(thing))}. Let's share it!",
                f"Here. You can have a turn with my {spoken_name(thing)}."), act={x: "hold_up", y: "wow"}, sfx=["chime"])
    b.say(y, _v(rng, f"Thank you, {X}. I feel better now.", f"You are a good friend, {X}. Thank you.", f"Thank you, {X}. That makes me happy."),
          act={y: "cheer"})
    b.say("narrator", _v(rng, "A kind word and a hug can brighten a sad day.", "When a friend is sad, we can listen and stay close.",
                         "Feeling sad is okay. Kind friends help us feel better."), act={x: "cheer", y: "cheer"}, fx="sparkle",
          end=uni["brand"]["end_card"])
    return Story("C", "cheering_up", "kind_friends", f"{X} Cheers Up {Y}",
                 f"{Y} is sad, so {X} asks what happened, gives a hug and shares.",
                 "Noticing a friend's feelings and comforting them.", "warm", [x, y], b.beats,
                 ["feelings", "kindness", "friendship", "comfort"], {"x": x, "y": y, "thing": thing})


# =====================================================================================
# D — good habits and manners
# =====================================================================================
def brush_teeth(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    when = rng.choice(["morning", "bedtime"])
    col = rng.choice(["blue", "green", "pink", "orange"])
    b = B(uni, "bathroom").enter(who)
    N = b.n(who)
    b.say("narrator", _v(rng, f"It is {when}. Time for {N} to brush those teeth!", f"Good {'morning' if when == 'morning' else 'evening'}, {N}! It is tooth brushing time.",
                         f"{N} is in the washroom. What time is it? Brushing time!"), title=f"{N} Brushes Teeth", act={who: "wave"})
    b.hold(who, "toothbrush", col, 66)
    b.say(who, _v(rng, "First, a little bit of toothpaste.", f"Here is my {col} toothbrush. A tiny dot of toothpaste!",
                  "A small squeeze of toothpaste. Ready!"), act={who: "hold_up"})
    steps = [("Brush, brush, brush. Up and down.", "UP & DOWN", "blue"), ("Brush the front. Brush the back.", "FRONT & BACK", "green"),
             ("Round and round, nice and gentle.", "ROUND", "purple"), ("Brush the top teeth. Brush the bottom teeth.", "TOP & BOTTOM", "orange"),
             ("Little circles, slow and soft.", "CIRCLES", "pink")]
    for line, w, c in rng.sample(steps, 3):
        b.say("narrator", line, act={who: "brush"}, word=(w, c))
    b.hold(who, None).put("bubbles", "sky", x=250, y=640, size=100)
    b.say(who, _v(rng, "Rinse, and smile! Sparkly clean teeth!", "Swish, swish, rinse. All clean!", "Rinse and grin! My teeth feel so clean."),
          act={who: "cheer"}, fx="sparkle", sfx=["sparkle"])
    b.say("narrator", _v(rng, "We brush our teeth every morning and every night.", "Brushing in the morning and at night keeps teeth healthy.",
                         "Morning and night, we brush our teeth."), act={who: "nod"}, end=uni["brand"]["end_card"])
    return Story("D", "brush_teeth", "little_habits", f"{N} Brushes Teeth: A {cap(when)} Routine",
                 f"{N} brushes teeth at {when}, step by step, then rinses.",
                 "Brush teeth every morning and night.", "warm", [who], b.beats, ["brushing teeth", "healthy habits", "routine"],
                 {"who": who, "when": when, "color": col})


def wash_hands(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    before = rng.choice(["snack time", "lunch", "dinner", "breakfast"])
    b = B(uni, "bathroom").enter(who)
    N = b.n(who)
    b.say("narrator", _v(rng, f"It is almost {before}. First, {N} washes those hands.", f"{N} played outside all morning. Time to wash hands!",
                         f"Before {before}, {N} always washes up."), title=f"{N} Washes Hands", act={who: "wave"})
    b.put("raindrop", "sky", x=300, y=620, size=70)
    b.say("narrator", _v(rng, "Step one. Wet your hands with water.", "One. Turn on the water and wet your hands."), act={who: "wash"}, number=1, sfx=["splash"])
    b.clear(ground=True).put("soap", "sky", x=300, y=640, size=90)
    b.say("narrator", _v(rng, "Step two. Add some soap.", "Two. A little soap goes on."), act={who: "wash"}, number=2, sfx=["pop"])
    b.clear(ground=True).put("bubbles", "sky", x=300, y=620, size=110).put("bubbles", "sky", x=800, y=700, size=80)
    b.say("narrator", _v(rng, "Step three. Scrub the fronts, the backs and between the fingers.", "Three. Scrub, scrub, scrub. Do not forget the thumbs!"),
          act={who: "wash"}, number=3)
    b.clear(ground=True).put("raindrop", "sky", x=300, y=620, size=70)
    b.say("narrator", _v(rng, "Step four. Rinse the bubbles away.", "Four. Rinse until the bubbles are gone."), act={who: "wash"}, number=4, sfx=["splash"])
    b.clear(ground=True).put("towel", "sky", x=300, y=640, size=90)
    b.say("narrator", _v(rng, "Step five. Dry with a clean towel.", "Five. Dry, dry, dry with a towel."), act={who: "clap"}, number=5)
    b.clear(ground=True)
    b.say(who, _v(rng, f"Clean hands! Now I am ready for {before}.", "All clean! High five!", f"My hands are clean. Time for {before}!"),
          act={who: "cheer"}, fx="sparkle", end=uni["brand"]["end_card"])
    return Story("D", "wash_hands", "little_habits", f"{N} Washes Hands in Five Steps",
                 f"{N} washes hands before {before}: wet, soap, scrub, rinse and dry.",
                 "The five steps of hand washing.", "warm", [who], b.beats, ["washing hands", "healthy habits", "hygiene"],
                 {"who": who, "before": before})


def tidy_up(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    toys = rng.sample([("ball", "red"), ("block", "blue"), ("teddy", None), ("book", "green"), ("drum", None), ("boat", "orange"),
                       ("bucket", "yellow"), ("bell", None), ("kite", "purple")], 3)
    b = B(uni, "playroom").enter(who)
    N = b.n(who)
    xs = [230, 850, 540]
    for (t, c), x in zip(toys, xs):
        b.put(t, "ground", x=x, size=58, color=c, front=True)
    b.say("narrator", _v(rng, "Playtime is over. The toys are everywhere!", f"What a fun playtime! But look at the floor, {N}.",
                         "Oh my. The playroom is messy."), title=f"{N} Tidies Up", act={who: "wow"})
    b.say(who, _v(rng, "Time to tidy up! Every toy has a home.", "I can tidy up, one toy at a time.", "Let's put the toys away!"), act={who: "wave"})
    left = len(toys)
    for t, _ in toys:
        b.drop(t)
        left -= 1
        tail = f"{cap(NUM[left])} more to go!" if left else "All done!"
        b.say("narrator", f"The {spoken_name(t)} goes back on the shelf. {tail}", act={who: "hold_up"}, sfx=["pop"])
    b.say("narrator", _v(rng, "Now the playroom is neat and tidy.", "Look at that! A clean, tidy room.", "Everything is back in its place."),
          act={who: "cheer"}, fx="sparkle")
    b.say(who, _v(rng, "Tidying up is easy, one toy at a time!", "A tidy room feels so good!", "Now I can find my toys tomorrow!"),
          act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("D", "tidy_up", "little_habits", f"{N} Tidies Up the Toys",
                 f"{N} puts the {join_words([spoken_name(t) for t, _ in toys])} back where they belong, one at a time.",
                 "Putting toys away after playing.", "warm", [who], b.beats, ["tidying up", "good habits", "responsibility"],
                 {"who": who, "toys": sorted(t for t, _ in toys)})


def magic_words(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    snack, col = rng.choice([("apple", None), ("banana", None), ("orange", None), ("cupcake", None), ("carrot", None), ("icecream", None)])
    b = B(uni, rng.choice(["garden", "playroom", "meadow"])).enter(x, y)
    X, Y, s = b.n(x), b.n(y), spoken_name(snack)
    b.hold(y, snack, col, 56, side=-1)
    b.say("narrator", _v(rng, f"{Y} has a yummy {s}. {X} would like one too.", f"Mmm! {Y} has {an(s)}. {X} feels hungry.",
                         f"It is snack time. {Y} has {an(s)} to share."), title="The Magic Words", act={x: "look_up", y: "hold_up"})
    b.say("narrator", _v(rng, f"How can {X} ask nicely?", f"What should {X} say?", "Is there a kind way to ask?"), act={x: "think"})
    b.say(x, _v(rng, f"May I have {an(s)}, please?", f"{Y}, could I have some, please?", f"Please may I have {an(s)}?"), act={x: "wave"},
          word=("PLEASE", "pink"))
    b.hold(y, None)
    b.say(y, _v(rng, "Of course! Here you are.", "Yes, you may! Here you go.", "Sure! This one is for you."), act={y: "give", x: "receive"},
          transfer={"name": snack, "color": col, "from": y, "to": x, "size": 56})
    b.hold(x, snack, col, 56)
    b.say(x, _v(rng, f"Thank you, {Y}!", f"Thank you so much, {Y}!", "Oh, thank you!"), act={x: "cheer"}, word=("THANK YOU", "green"), sfx=["chime"])
    b.say(y, _v(rng, "You are welcome!", "You are very welcome!", "My pleasure!"), act={y: "wave"}, word=("YOU'RE WELCOME", "blue"))
    b.say("narrator", _v(rng, "Please and thank you are magic words. They make everyone smile.", "Please. Thank you. Kind words make friends happy.",
                         "Magic words are easy to say, and they feel so good."), act={x: "cheer", y: "cheer"}, fx="hearts",
          end=uni["brand"]["end_card"])
    return Story("D", "magic_words", "little_habits", f"The Magic Words: {X} Says Please and Thank You",
                 f"{X} asks {Y} for {an(s)} with 'please' and says 'thank you'.",
                 "Using please, thank you and you're welcome.", "warm", [x, y], b.beats, ["manners", "please and thank you", "kindness"],
                 {"x": x, "y": y, "snack": snack})


def good_morning(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    food = rng.choice(["banana", "apple", "orange"])
    b = B(uni, "meadow").enter(who)
    N = b.n(who)
    b.say("narrator", _v(rng, f"The sun is up. Good morning, {N}!", f"Wake up, {N}! A new day is here.", f"Rise and shine, {N}!"),
          title=f"Good Morning, {N}!", act={who: "yawn"})
    b.say(who, _v(rng, "A big, big stretch!", "Reach up high! Stretch!", "Good morning, sun! Time to stretch."), act={who: "stretch"},
          word=("STRETCH", "orange"))
    b.go("bathroom").put("bubbles", "sky", x=280, y=640, size=90)
    b.say("narrator", _v(rng, "Wash your face. Splash, splash!", "First, a splash of water on the face."), act={who: "wash"}, word=("WASH", "blue"), sfx=["splash"])
    b.clear(ground=True).hold(who, "toothbrush", "green", 66)
    b.say("narrator", _v(rng, "Brush your teeth. Brush, brush!", "Next, brush those teeth until they shine."), act={who: "brush"}, word=("BRUSH", "green"))
    b.hold(who, None).go("garden").show(food)
    b.say("narrator", _v(rng, f"Eat a healthy breakfast. Yummy {spoken_name(food)}!", f"Then, breakfast time. {cap(an(spoken_name(food)))} today!"),
          act={who: "point"}, word=("EAT", "red"))
    b.clear()
    b.say("narrator", "Stretch, wash, brush and eat. That is a good morning!", act={who: "nod"})
    b.say(who, _v(rng, "Now I am ready for a brand new day!", "I am ready to play!", "Hello, new day! Here I come."), act={who: "cheer"},
          fx="sparkle", end=uni["brand"]["end_card"])
    return Story("D", "good_morning", "little_habits", f"Good Morning, {N}! A Morning Routine",
                 f"{N} wakes up, stretches, washes, brushes teeth and eats {an(spoken_name(food))} for breakfast.",
                 "The steps of a morning routine.", "warm", [who], b.beats, ["morning routine", "healthy habits", "good morning"],
                 {"who": who, "food": food})


SNACK_LINE = {"apple": ["A crisp red apple. Crunch!", "An apple, shiny and sweet."], "banana": ["A sweet yellow banana. Yum!", "A banana. Peel it, and take a bite!"],
              "carrot": ["A crunchy orange carrot. Crunch, crunch!", "A carrot, fresh from the garden."], "orange": ["A juicy orange. Squirt!", "An orange, round and juicy."]}


def healthy_snack(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    foods = rng.sample(list(SNACK_LINE), 3)
    b = B(uni, rng.choice(["garden", "meadow"])).enter(who)
    N = b.n(who)
    b.say("narrator", _v(rng, f"{N} is hungry. It is snack time!", f"Rumble, rumble. {N} has a hungry tummy.", f"What will {N} eat for a snack today?"),
          title=f"{N}'s Healthy Snack", act={who: "wave"})
    fcol = {"apple": "red", "banana": "yellow", "carrot": "orange", "orange": "orange"}
    for f in foods:
        b.show(f)
        b.say(who, rng.choice(SNACK_LINE[f]), act={who: "point"}, word=(spoken_name(f).upper(), fcol[f]))
    b.say("narrator", f"{cap(join_words([spoken_name(f) for f in foods]))}. What a tasty snack!", act={who: "cheer"})
    b.say("narrator", _v(rng, "Fruits and vegetables help us grow strong.", "Fruits and vegetables give us energy to play.",
                         "Eating fruits and vegetables is good for our bodies."), act={who: "nod"}, fx="sparkle")
    b.say(who, _v(rng, "What is your favorite fruit?", "Yum! Which one would you pick?"), act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("D", "healthy_snack", "little_habits", f"{N}'s Healthy Snack: {cap(join_words([spoken_name(f) for f in foods]))}",
                 f"{N} picks {join_words([an(spoken_name(f)) for f in foods])} for snack time.",
                 "Fruits and vegetables are healthy snacks.", "warm", [who], b.beats, ["healthy eating", "fruits", "vegetables", "snack"],
                 {"who": who, "foods": sorted(foods)})


# =====================================================================================
# E — original rhymes ("songs": rhythmic rhymes spoken on the beat of an original tune)
# =====================================================================================
MOVES = {"hop": ("Hop, hop, hop, hop up high,", "Hop, hop, hop, touch the sky!"),
         "clap": ("Clap, clap, clap, clap your hands,", "Clap, clap, clap, with all your friends!"),
         "wave": ("Wave, wave, wave, wave hello,", "Wave, wave, wave, high and low!"),
         "stretch": ("Stretch, stretch, stretch, reach up tall,", "Stretch, stretch, stretch, then curl up small!"),
         "dance": ("Wiggle, wiggle, wiggle, side to side,", "Wiggle, wiggle, wiggle, smile so wide!"),
         "nod": ("Nod, nod, nod, nod your head,", "Nod, nod, nod, just like I said!")}


def action_song(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    moves = rng.sample(list(MOVES), 3)
    b = B(uni, rng.choice(["meadow", "hilltop", "garden", "playroom"])).enter(who)
    N = b.n(who)
    label = {"dance": "wiggle"}
    b.say("narrator", f"It is time to move with {N}! Are you ready?", title=f"Move With {N}!", act={who: "wave"})
    for m in moves:
        a, c = MOVES[m]
        b.say(who, a, act={who: m}, word=(label.get(m, m).upper(), "orange"), fx="notes")
        b.say(who, c, act={who: m}, word=(label.get(m, m).upper(), "orange"), fx="notes")
    b.say(who, f"{cap(join_words([label.get(m, m) for m in moves]))}. Hooray for you!", act={who: "cheer"}, fx="sparkle",
          end=uni["brand"]["end_card"])
    words = [label.get(m, m) for m in moves]
    return Story("E", "action_song", "sing_along", f"Move With {N}: {cap(join_words(words))} Rhyme",
                 f"An original action rhyme: {N} invites everyone to {join_words(words)}.",
                 "Moving the body to a rhyme; following simple actions.", "song", [who], b.beats, ["action song", "movement", "rhyme"] + words,
                 {"who": who, "moves": sorted(moves)}, song=True)


COUNT_LINES = {1: ("One little {one}, {first}", "{first2}"), 2: ("Two little {many}, what shall we do?", "I will count them all with you!"),
               3: ("Three little {many}, look and see,", "Count along, along with me!"),
               4: ("Four little {many}, here come more,", "One, two, three and four!"),
               5: ("Five little {many}, side by side,", "Count them all with pride!")}
COUNT_FIRST = {"star": ("shining bright,", "Twinkling in the night!"), "fish": ("swimming in the sea,", "Happy as can be!"),
               "default": ("sitting in the sun,", "Counting is such fun!")}


def counting_song(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    n = rng.choice([3, 4, 5])
    env, prop, col = rng.choice([("night", "star", "yellow"), ("pond", "fish", "orange"), ("garden", "flower", "pink"),
                                 ("meadow", "butterfly", "blue"), ("garden", "apple", None), ("meadow", "balloon", "red"),
                                 ("garden", "ladybug", None)])
    b = B(uni, env).enter(who)
    N, one, many = b.n(who), spoken_name(prop), spoken_name(prop, 2)
    first = COUNT_FIRST.get(prop, COUNT_FIRST["default"])
    b.say("narrator", f"Sing and count with {N}!", title=f"{cap(NUM[n])} Little {cap(many)}", act={who: "wave"})
    for i in range(1, n + 1):
        b.show(prop, col)
        a, c = COUNT_LINES[i]
        b.say(who, a.format(one=one, many=many, first=first[0]), act={who: "point"}, number=i, fx="notes", sfx=["tick"])
        b.say(who, c.format(first2=first[1]), act={who: "dance"}, number=i, fx="notes")
    b.say(who, f"{cap(NUM[n])} little {many}. We counted them all!", act={who: "cheer"}, number=n, fx="sparkle",
          end=uni["brand"]["end_card"])
    return Story("E", "counting_song", "sing_along", f"{cap(NUM[n])} Little {cap(many)}: A Counting Rhyme With {N}",
                 f"An original counting rhyme: {N} counts up to {NUM[n]} little {many}.",
                 f"Count to {NUM[n]} with a rhyme.", "song", [who], b.beats, ["counting song", "numbers", "rhyme", prop],
                 {"who": who, "prop": prop, "n": n}, song=True)


COLOR_SONG = {"red": ("apple", None, "Red, red, the apple is red,", "Round and shiny, like I said!"),
              "yellow": ("sun", None, "Yellow, yellow, the sun so bright,", "Filling up the day with light!"),
              "blue": ("balloon", "blue", "Blue, blue, balloon so high,", "Floating in the big blue sky!"),
              "green": ("leaf", None, "Green, green, the leaf on the tree,", "Green is all around, you see!"),
              "orange": ("orange", None, "Orange, orange, sweet and round,", "A juicy orange I have found!"),
              "purple": ("butterfly", "purple", "Purple, purple, butterfly,", "Flutter, flutter, way up high!"),
              "pink": ("cupcake", "pink", "Pink, pink, the frosting swirl,", "Round and round, a pretty curl!")}


def colors_song(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    colors = rng.sample(list(COLOR_SONG), 4)
    b = B(uni, rng.choice(["meadow", "garden", "hilltop"])).enter(who)
    N = b.n(who)
    b.say("narrator", f"Sing the colors with {N}!", title="The Wonder Meadow Color Rhyme", act={who: "wave"})
    for c in colors:
        prop, pc, l1, l2 = COLOR_SONG[c]
        b.clear().show(prop, pc)
        b.say(who, l1, act={who: "point"}, word=(c.upper(), c), fx="notes")
        b.say(who, l2, act={who: "dance"}, word=(c.upper(), c), fx="notes")
    b.clear()
    b.say(who, "Colors, colors, everywhere,", act={who: "dance"}, fx="notes")
    b.say(who, "So many colors we can share!", act={who: "cheer"}, fx="sparkle", end=uni["brand"]["end_card"])
    return Story("E", "colors_song", "sing_along", f"The Color Rhyme: {cap(join_words(colors))}",
                 f"An original color rhyme with {N}: {join_words(colors)}.",
                 f"Name the colors {join_words(colors)} with a rhyme.", "song", [who], b.beats, ["color song", "colors", "rhyme"] + colors,
                 {"who": who, "colors": sorted(colors)}, song=True)


FRIEND_LINE = {"bobo": ("Bobo the bunny goes hop, hop, hop,", "hop"), "mimi": ("Mimi the kitten goes purr, purr, purr,", "nod"),
               "toto": ("Toto the elephant goes stomp, stomp, stomp,", "dance"), "zuzu": ("Zuzu the duckling goes quack, quack, quack,", "clap"),
               "lolo": ("Lolo the bear goes stretch and yawn,", "yawn")}
FRIEND_END = {"bobo": "Hopping, hopping, never stop!", "mimi": "Soft and cozy, purr, purr, purr!",
              "toto": "Stomping round the meadow, stomp!", "zuzu": "Splashing puddles, quack, quack, quack!",
              "lolo": "Sleepy, sleepy, until dawn!"}


def friends_song(rng, uni) -> Story:
    cast = _pick_cast(rng, uni, 3)
    b = B(uni, rng.choice(["meadow", "garden", "hilltop"]))
    b.say("narrator", "Meet the friends of Wonder Meadow!", title="The Wonder Meadow Friends Rhyme")
    for cid in cast:
        b.enter(cid)
        line, action = FRIEND_LINE[cid]
        b.say("narrator", line, act={cid: action}, fx="notes")
        b.say(cid, FRIEND_END[cid], act={cid: action}, fx="notes")
    b.say("narrator", "All the friends in Wonder Meadow,", act={c: "dance" for c in cast}, fx="notes")
    b.say("narrator", "Play together all day long!", act={c: "cheer" for c in cast}, fx="sparkle", end=uni["brand"]["end_card"])
    names = [b.n(c) for c in cast]
    return Story("E", "friends_song", "sing_along", f"Meet {join_words(names)}: The Friends Rhyme",
                 f"An original rhyme that introduces {join_words(names)} and how each one likes to move.",
                 "Meet the characters; animal movements and sounds.", "song", cast, b.beats, ["friends song", "animals", "rhyme"] + names,
                 {"cast": cast}, song=True)


def rain_song(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    ucol = rng.choice(["red", "yellow", "purple", "green"])
    b = B(uni, "rainy").enter(who)
    N = b.n(who)
    b.hold(who, "umbrella", ucol, 110)
    b.say("narrator", f"It is raining! Sing the rain rhyme with {N}.", title=f"{N}'s Rainy Day Rhyme", act={who: "wave"})
    b.say(who, "Pitter, patter, pitter, patter, raindrops fall,", act={who: "look_up"}, fx="notes")
    b.say(who, "Pitter, patter, pitter, patter, big and small!", act={who: "dance"}, fx="notes")
    b.say(who, "Splash, splash, splash, the puddles are fun,", act={who: "hop"}, word=("SPLASH!", "blue"), sfx=["splash"])
    b.say(who, "Splash, splash, splash, until the rain is done!", act={who: "hop"}, word=("SPLASH!", "blue"), sfx=["splash"])
    b.hold(who, None).go("meadow").put("rainbow", "sky", x=540, y=640, size=250)
    b.say(who, "Here comes the sun, the clouds roll away,", act={who: "look_up"}, fx="notes")
    b.say(who, "And a rainbow says: what a lovely day!", act={who: "cheer"}, word=("RAINBOW", "purple"), fx="sparkle",
          end=uni["brand"]["end_card"])
    return Story("E", "rain_song", "sing_along", f"{N}'s Rainy Day Rhyme: Pitter Patter, Splash!",
                 f"An original rainy-day rhyme: {N} splashes in puddles until the sun brings a rainbow.",
                 "Weather words: rain, puddle, sun, rainbow.", "song", [who], b.beats, ["rain song", "weather", "rhyme", "rainbow"],
                 {"who": who, "umbrella": ucol}, song=True)


def wash_song(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    b = B(uni, "bathroom").enter(who)
    N = b.n(who)
    b.put("soap", "sky", x=280, y=640, size=90)
    b.say("narrator", f"Wash your hands with {N} and this little rhyme!", title=f"{N}'s Hand Washing Rhyme", act={who: "wave"})
    b.say(who, "Wash, wash, wash your hands, make the bubbles grow,", act={who: "wash"}, fx="notes")
    b.clear(ground=True).put("bubbles", "sky", x=280, y=620, size=110).put("bubbles", "sky", x=820, y=700, size=80)
    b.say(who, "Scrub the fronts and scrub the backs, nice and slow!", act={who: "wash"}, fx="notes")
    b.say(who, "In between your fingers too, round and round we go,", act={who: "wash"}, fx="notes")
    b.clear(ground=True).put("raindrop", "sky", x=280, y=620, size=70)
    b.say(who, "Rinse them, dry them, clean and bright, now you know!", act={who: "clap"}, fx="notes", sfx=["splash"])
    b.clear(ground=True)
    b.say(who, "Clean hands, hooray!", act={who: "cheer"}, fx="sparkle", end=uni["brand"]["end_card"])
    return Story("E", "wash_song", "sing_along", f"{N}'s Hand Washing Rhyme",
                 f"An original hand-washing rhyme with {N}: soap, scrub, rinse and dry.",
                 "Hand washing steps set to a rhyme.", "song", [who], b.beats, ["hand washing song", "healthy habits", "rhyme"],
                 {"who": who}, song=True)


# =====================================================================================
# F — bedtime stories (calm pacing, night palette, music-box score)
# =====================================================================================
def sleepy_friends(rng, uni) -> Story:
    cast = _pick_cast(rng, uni, 3)
    b = B(uni, "night").enter(*cast)
    names = [b.n(c) for c in cast]
    b.say("narrator", "The sun has gone to bed. The stars are waking up.", title="Sleepy Time in Wonder Meadow", sfx=["twinkle"])
    asleep: dict[str, str] = {}
    for i, cid in enumerate(cast):
        acts = {**asleep, cid: "yawn"}
        b.say("narrator", f"{b.n(cid)} gives a big, slow yawn.", act=acts)
        nxt = cast[(i + 1) % len(cast)]
        b.say(cid, f"Goodnight, {b.n(nxt)}." if i < len(cast) - 1 else "Goodnight, stars.", act={**asleep, cid: "sleepy"})
        asleep[cid] = "sleep"
    b.say("narrator", "One by one, the friends close their eyes.", act=asleep, fx="zzz")
    b.say("narrator", f"Goodnight, {join_words(names)}. Sweet dreams.", act=asleep, fx="zzz", end="Goodnight from Wonder Meadow")
    return Story("F", "sleepy_friends", "sleepy_time", f"Goodnight, {join_words(names)}: A Sleepy Meadow Story",
                 f"A calm bedtime story: {join_words(names)} yawn, say goodnight and fall asleep under the stars.",
                 "Winding down for sleep.", "calm", cast, b.beats, ["bedtime story", "goodnight", "sleep", "calm"], {"cast": cast})


def counting_stars(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    n = rng.choice([4, 5])
    thing, col, env = rng.choice([("star", "yellow", "night"), ("firefly", None, "night"), ("star", "yellow", "bedroom")])
    b = B(uni, env).enter(who)
    N, many = b.n(who), spoken_name(thing, 2)
    b.say("narrator", f"It is bedtime, but {N} is not sleepy yet.", title=f"{N} Counts the {cap(many)}", act={who: "look_up"})
    b.say("narrator", f"So {N} counts the {many}. Slowly. Softly.", act={who: "look_up"})
    for i in range(1, n + 1):
        b.show(thing, col)
        b.say("narrator", f"{cap(NUM[i])}.", act={who: "sleepy" if i > n - 2 else "look_up"}, number=(i, "yellow"), sfx=["twinkle"] if i == 1 else [])
    b.say("narrator", f"{cap(NUM[n])} little {many}, twinkling in the dark.", act={who: "yawn"})
    b.say("narrator", f"And {N} is fast asleep. Goodnight.", act={who: "sleep"}, fx="zzz", end="Goodnight from Wonder Meadow")
    return Story("F", "counting_stars", "sleepy_time", f"{N} Counts {cap(NUM[n])} {cap(many)}: A Bedtime Story",
                 f"A calm bedtime story: {N} counts {NUM[n]} {many} slowly and falls asleep.",
                 "Slow counting to settle down.", "calm", [who], b.beats, ["bedtime story", "counting", "sleep", thing], {"who": who, "n": n, "thing": thing})


def bedtime_routine(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    b = B(uni, "bathroom").enter(who)
    N = b.n(who)
    b.put("bubbles", "sky", x=280, y=640, size=110)
    b.say("narrator", f"It is time for bed, {N}.", title=f"{N}'s Bedtime Routine", act={who: "yawn"})
    b.say("narrator", "First, a warm wash. Splish, splash.", act={who: "wash"}, number=(1, "blue"))
    b.clear(ground=True).hold(who, "toothbrush", "blue", 66)
    b.say("narrator", "Then, brush those teeth. Brush, brush.", act={who: "brush"}, number=(2, "green"))
    b.hold(who, None).go("bedroom").show("book", "green")
    b.say("narrator", "Next, a quiet bedtime story.", act={who: "sleepy"}, number=(3, "purple"))
    b.clear().put("teddy", "ground", x=800, size=64, front=True)
    b.say("narrator", "Now snuggle in with teddy. The blanket is soft and warm.", act={who: "sleepy"}, number=(4, "pink"))
    b.say("narrator", f"Goodnight, {N}. Sleep tight.", act={who: "sleep"}, fx="zzz", end="Goodnight from Wonder Meadow")
    return Story("F", "bedtime_routine", "sleepy_time", f"{N}'s Bedtime Routine: Wash, Brush, Story, Sleep",
                 f"A calm bedtime story: {N} washes, brushes teeth, hears a story and snuggles into bed.",
                 "The steps of a bedtime routine.", "calm", [who], b.beats, ["bedtime routine", "bedtime story", "sleep", "healthy habits"],
                 {"who": who})


def goodnight_meadow(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    stops = rng.sample([("The little pond is quiet now. Shh.", "puddle", None), ("The flowers have closed their petals.", "flower", "purple"),
                        ("The fireflies glow like tiny lanterns.", "firefly", None), ("The snail is tucked inside its shell.", "snail", None),
                        ("The moon watches over the meadow.", "moon", None), ("The little nest is warm and still.", "nest", None)], 4)
    b = B(uni, "night").enter(who)
    N = b.n(who)
    b.say("narrator", f"Night has come to Wonder Meadow. {N} says goodnight.", title="Goodnight, Wonder Meadow", act={who: "wave"},
          sfx=["twinkle"])
    for line, prop, col in stops:
        b.clear().show(prop, col)
        b.say("narrator", line, act={who: "sleepy"})
    b.clear()
    b.say(who, "Goodnight, meadow. Goodnight, stars.", act={who: "yawn"})
    b.say("narrator", f"And {N} drifts off to sleep.", act={who: "sleep"}, fx="zzz", end="Goodnight from Wonder Meadow")
    return Story("F", "goodnight_meadow", "sleepy_time", f"Goodnight, Wonder Meadow: {N}'s Bedtime Walk",
                 f"A calm bedtime story: {N} says goodnight to the quiet meadow at night.",
                 "A calm goodnight ritual.", "calm", [who], b.beats, ["bedtime story", "goodnight", "night", "calm"],
                 {"who": who, "stops": sorted(s[1] for s in stops)})


def calm_breathing(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    b = B(uni, rng.choice(["night", "bedroom"])).enter(who)
    N = b.n(who)
    b.say("narrator", f"Let's take slow, sleepy breaths with {N}.", title=f"Calm Breathing With {N}", act={who: "wave"})
    for _ in range(2):
        b.clear().show("flower", "pink", size=140)
        b.say("narrator", "Breathe in. Smell the flower.", act={who: "stretch"}, word=("IN", "pink"))
        b.clear().show("bubbles", None, size=140)
        b.say("narrator", "Breathe out. Blow the bubbles.", act={who: "sleepy"}, word=("OUT", "blue"))
    b.clear()
    b.say("narrator", "In, and out. Slow and soft.", act={who: "sleepy"})
    b.say("narrator", f"Now {N} feels calm and cozy. Goodnight.", act={who: "sleep"}, fx="zzz", end="Goodnight from Wonder Meadow")
    return Story("F", "calm_breathing", "sleepy_time", f"Calm Breathing With {N}: In and Out",
                 f"A calming bedtime moment: {N} breathes in to smell a flower and out to blow bubbles.",
                 "Slow breathing to feel calm.", "calm", [who], b.beats, ["calm breathing", "bedtime", "relaxation", "feelings"], {"who": who})


# =====================================================================================
# G — alphabet and early learning
# =====================================================================================
CHAR_LETTER = {"B": ["bobo"], "M": ["mimi"], "T": ["toto"], "Z": ["zuzu"], "L": ["lolo"]}


def letter_day(rng, uni) -> Story:
    letter = rng.choice([k for k, v in LETTERS.items() if len(v) >= 2])
    words = rng.sample(LETTERS[letter], min(3, len(LETTERS[letter])))
    star = CHAR_LETTER.get(letter, [None])[0]
    host = star or _pick_cast(rng, uni, 1)[0]
    b = B(uni, rng.choice(["meadow", "playroom", "garden"])).enter(host)
    H = b.n(host)
    b.say("narrator", f"Today's letter is {letter}!", letter=f"{letter} {letter.lower()}", act={host: "wave"}, sfx=["ding"])
    b.say(host, f"{letter}! I know words that start with {letter}.", act={host: "think"}, letter=f"{letter} {letter.lower()}")
    for w in words:
        b.clear().show(w, size=140)
        b.say(host, f"{letter} is for {spoken_name(w)}.", act={host: "point"}, word=(cap(spoken_name(w)), "purple"), sfx=["pop"])
    if star:
        b.clear()
        b.say("narrator", f"And {letter} is for {H}, too!", act={host: "cheer"}, word=(H, "pink"), fx="sparkle")
    b.clear()
    for w in words:
        b.show(w)
    b.say("narrator", f"{cap(join_words([spoken_name(w) for w in words]))}. They all start with {letter}.", act={host: "nod"},
          letter=f"{letter} {letter.lower()}")
    b.say(host, f"What else starts with {letter}?", act={host: "wave"}, end=uni["brand"]["end_card"])
    names = [spoken_name(w) for w in words]
    return Story("G", "letter_day", "letter_day", f"Letter {letter}: {letter} Is for {cap(names[0])}" + (f" and {cap(names[1])}" if len(names) > 1 else ""),
                 f"Letter of the day with {H}: {letter} is for {join_words(names)}.",
                 f"Recognize the letter {letter} and words that start with it.", "bright", [host], b.beats,
                 ["alphabet", f"letter {letter}", "abc", "phonics"] + names, {"letter": letter, "words": sorted(words), "host": host})


def find_the_letter(rng, uni) -> Story:
    letters = rng.sample("ABCDEFGHIJKLMNOPRSTUVWYZ", 3)
    target = rng.choice([l for l in letters if l in LETTERS] or letters)
    who = _pick_cast(rng, uni, 1)[0]
    b = B(uni, "playroom").enter(who)
    N = b.n(who)
    cols = rng.sample(["red", "blue", "green", "orange", "purple"], 3)
    for l, c in zip(letters, cols):
        b.show("block", c, label=l, size=112)
    b.say("narrator", f"{N} has three letter blocks: {letters[0]}, {letters[1]} and {letters[2]}.", title=f"Find the Letter {target}",
          act={who: "wave"})
    b.say(who, f"Where is the letter {target}? Let's look!", act={who: "think"})
    for i, l in enumerate(x for x in letters if x != target):
        b.say("narrator", f"Is it this one? No, this is {l}." if i == 0 else f"This one? No, this is {l}.", act={who: "nod"}, letter=l)
    b.say(who, f"Here it is! The letter {target}!", act={who: "point"}, letter=f"{target} {target.lower()}", fx="sparkle", sfx=["chime"])
    if target in LETTERS:
        w = rng.choice(LETTERS[target])
        b.clear().show(w, size=140)
        b.say("narrator", f"{target} is for {spoken_name(w)}.", act={who: "cheer"}, word=(cap(spoken_name(w)), "purple"))
    b.say(who, f"Can you find the letter {target} today?", act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("G", "find_the_letter", "letter_day", f"Find the Letter {target} With {N}",
                 f"{N} looks at three letter blocks ({', '.join(letters)}) and finds the letter {target}.",
                 f"Pick out the letter {target} from other letters.", "bright", [who], b.beats, ["alphabet", f"letter {target}", "abc", "letters"],
                 {"letters": sorted(letters), "target": target, "who": who})


# =====================================================================================
# H — everyday discoveries
# =====================================================================================
def rain_to_rainbow(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    ucol = rng.choice(["red", "yellow", "blue", "purple"])
    b = B(uni, "rainy").enter(who)
    N = b.n(who)
    b.hold(who, "umbrella", ucol, 110)
    b.say("narrator", "Drip, drop. It is raining in Wonder Meadow.", title="Where Do Rainbows Come From?", act={who: "look_up"})
    b.say(who, f"I have my {ucol} umbrella. I am nice and dry!", act={who: "hold_up"})
    b.hold(who, None).go("meadow")
    b.say("narrator", "Look! The sun is peeking out.", act={who: "look_up"}, word=("SUN", "yellow"))
    b.put("rainbow", "sky", x=540, y=640, size=260)
    b.say("narrator", "When the sun shines through the rain, we can see a rainbow.", act={who: "wow"}, word=("RAINBOW", "purple"), sfx=["chime"])
    b.say(who, "Red, orange, yellow, green, blue and purple!", act={who: "point"})
    b.say("narrator", "Sun and rain together make a rainbow.", act={who: "cheer"}, fx="sparkle")
    b.say(who, "Have you ever seen a rainbow?", act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("H", "rain_to_rainbow", "i_wonder", f"Where Do Rainbows Come From? {N} Finds Out",
                 f"It rains in Wonder Meadow, then the sun comes out and {N} sees a rainbow.",
                 "A rainbow appears when sunlight shines through rain.", "bright", [who], b.beats, ["rainbow", "weather", "rain", "science for kids"],
                 {"who": who, "umbrella": ucol})


def seed_to_flower(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    col = rng.choice(["pink", "red", "yellow", "purple", "orange"])
    b = B(uni, "garden").enter(who)
    N = b.n(who)
    b.show("seed", size=120)
    b.say("narrator", f"{N} plants a tiny seed in the soil.", title="How Does a Flower Grow?", act={who: "point"})
    b.put("raindrop", "sky", x=300, y=560, size=60)
    b.say("narrator", "The seed needs water.", act={who: "nod"}, word=("WATER", "blue"), sfx=["splash"])
    b.clear(ground=True).put("sun", "sky", x=800, y=560, size=90)
    b.say("narrator", "The seed needs sunshine.", act={who: "look_up"}, word=("SUN", "yellow"))
    b.say(who, "Now we wait. And wait. And wait.", act={who: "think"})
    b.clear().show("sprout", size=130)
    b.say("narrator", "Look! A little green sprout.", act={who: "wow"}, word=("SPROUT", "green"), sfx=["pop"])
    b.clear().show("flower", col, size=150)
    b.say(who, f"And now, a beautiful {col} flower!", act={who: "cheer"}, word=("FLOWER", col), fx="sparkle", sfx=["chime"])
    b.say("narrator", "Seeds need soil, water and sun to grow.", act={who: "nod"}, end=uni["brand"]["end_card"])
    return Story("H", "seed_to_flower", "i_wonder", f"How Does a Flower Grow? {N} Plants a Seed",
                 f"{N} plants a seed, gives it water and sun, waits, and watches it grow into a {col} flower.",
                 "Seeds need soil, water and sun to grow.", "bright", [who], b.beats, ["plants", "seed", "flower", "science for kids", "nature"],
                 {"who": who, "color": col})


def day_and_night(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    b = B(uni, "meadow").enter(who)
    N = b.n(who)
    b.say("narrator", f"{N} wonders about day and night.", title="Day and Night", act={who: "think"})
    b.say("narrator", "In the day, the sun is in the sky.", act={who: "look_up"}, word=("DAY", "yellow"))
    b.say(who, "It is bright. We can play outside!", act={who: "hop"})
    b.go("night")
    b.say("narrator", "At night, we can see the moon and the stars.", act={who: "look_up"}, word=("NIGHT", "purple"), sfx=["twinkle"])
    b.say(who, "It is dark and quiet. Time to rest.", act={who: "yawn"})
    b.go("meadow")
    b.say("narrator", "After every night, a new day begins.", act={who: "stretch"}, word=("DAY", "yellow"), fx="sparkle")
    b.say(who, "Is it day or night where you are?", act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("H", "day_and_night", "i_wonder", f"Day and Night With {N}",
                 f"{N} looks at the sunny day sky and the starry night sky.",
                 "Day has the sun; night has the moon and stars.", "bright", [who], b.beats, ["day and night", "sun", "moon", "science for kids"],
                 {"who": who})


FLOATERS = {"leaf": True, "boat": True, "apple": True, "ball": True, "key": False}


def float_or_sink(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    things = rng.sample([k for k, v in FLOATERS.items() if v], 2) + ["key"]
    rng.shuffle(things)
    b = B(uni, "pond").enter(who)
    N = b.n(who)
    b.say("narrator", f"{N} is by the pond. Will it float, or will it sink?", title="Float or Sink?", act={who: "think"})
    for t in things:
        b.clear().show(t, "red" if t in ("boat", "ball") else None)
        b.say(who, f"Here is {an(spoken_name(t))}. Float or sink?", act={who: "point"})
        b.clear()
        if FLOATERS[t]:
            b.put(t, "ground", x=540, y=1640, size=60, color="red" if t in ("boat", "ball") else None, front=True)
            b.say("narrator", f"The {spoken_name(t)} floats on top of the water!", act={who: "cheer"}, word=("FLOAT", "blue"), sfx=["splash"])
        else:
            b.put("bubbles", "ground", x=540, y=1660, size=44, front=True)
            b.say("narrator", f"Plop! The {spoken_name(t)} sinks to the bottom.", act={who: "wow"}, word=("SINK", "purple"), sfx=["splash"])
        b.clear(ground=True)
    b.say("narrator", "Some things float. Some things sink. It is fun to find out!", act={who: "cheer"}, fx="sparkle")
    b.say(who, "What would you like to test?", act={who: "wave"}, end=uni["brand"]["end_card"])
    names = [spoken_name(t) for t in things]
    return Story("H", "float_or_sink", "i_wonder", f"Float or Sink? {N} Tests {cap(join_words(names))}",
                 f"{N} tests {join_words([an(n) for n in names])} at the pond to see which float and which sink.",
                 "Some objects float and some sink; we can test to find out.", "bright", [who], b.beats, ["float or sink", "science for kids", "experiment", "water"],
                 {"who": who, "things": sorted(things)})


def falling_leaves(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    b = B(uni, "forest").enter(who)
    N = b.n(who)
    b.say("narrator", f"{N} is walking in the friendly woods. It is autumn.", title="Why Do Leaves Fall?", act={who: "look_up"})
    for c in ("red", "orange", "yellow", "brown"):
        b.show("leaf", c)
    b.say("narrator", "In autumn, many leaves change color.", act={who: "point"}, word=("AUTUMN", "orange"))
    b.say(who, "Red, orange, yellow and brown!", act={who: "cheer"})
    b.clear().put("leaf", "fall", count=9, color="orange", size=36)
    b.say("narrator", "Then the leaves fall down, down, down.", act={who: "look_up"}, word=("FALL", "red"))
    b.hold(who, "leaf", "orange", 50)
    b.say(who, "I caught one! Hello, little leaf.", act={who: "hold_up"}, sfx=["pop"])
    b.say("narrator", "In spring, new green leaves will grow again.", act={who: "nod"}, word=("SPRING", "green"), fx="sparkle")
    b.say(who, "Crunch, crunch! Leaves are fun to walk on.", act={who: "hop"}, end=uni["brand"]["end_card"])
    return Story("H", "falling_leaves", "i_wonder", f"Why Do Leaves Fall? {N}'s Autumn Walk",
                 f"{N} sees leaves change color and fall in autumn, and learns new leaves grow in spring.",
                 "In autumn many trees lose their leaves; new ones grow in spring.", "bright", [who], b.beats,
                 ["autumn", "leaves", "seasons", "nature", "science for kids"], {"who": who})


def bubbles(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    b = B(uni, rng.choice(["meadow", "garden", "hilltop"])).enter(who)
    N = b.n(who)
    b.say("narrator", f"{N} is blowing bubbles today.", title=f"{N} and the Bubbles", act={who: "wave"})
    b.show("bubbles", None, size=150)
    b.say(who, "Look at all my bubbles!", act={who: "point"}, word=("BUBBLES", "blue"), sfx=["pop"])
    b.say("narrator", "Bubbles are round, like little balls.", act={who: "nod"}, word=("ROUND", "purple"))
    b.say("narrator", "They float up, up, up in the air.", act={who: "look_up"}, word=("UP", "green"))
    b.clear()
    b.say(who, "Pop! Where did it go?", act={who: "wow"}, word=("POP!", "red"), sfx=["pop"])
    b.show("bubbles", None, size=150)
    b.say("narrator", "A bubble is soapy water with air inside.", act={who: "think"})
    b.say(who, "Let's blow some more!", act={who: "cheer"}, fx="sparkle", end=uni["brand"]["end_card"])
    return Story("H", "bubbles", "i_wonder", f"{N} and the Bubbles: Round, Up and Pop!",
                 f"{N} blows bubbles and notices they are round, float up and pop.",
                 "A bubble is soapy water with air inside.", "bright", [who], b.beats, ["bubbles", "science for kids", "play", "discovery"],
                 {"who": who})


def what_to_wear(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    b = B(uni, "rainy").enter(who)
    N = b.n(who)
    b.say("narrator", f"{N} looks outside. What is the weather today?", title="What Should We Wear?", act={who: "look_up"})
    b.say("narrator", "It is raining. What do we need?", act={who: "think"}, word=("RAIN", "blue"))
    b.hold(who, "umbrella", "yellow", 110)
    b.say(who, "An umbrella keeps me dry!", act={who: "hold_up"}, word=("UMBRELLA", "yellow"), sfx=["pop"])
    b.hold(who, None).go("meadow")
    b.say("narrator", "Now it is sunny. What do we need?", act={who: "think"}, word=("SUN", "yellow"))
    b.show("hat", "orange", size=140)
    b.say(who, "A sun hat keeps me cool!", act={who: "point"}, word=("HAT", "orange"), sfx=["pop"])
    b.clear()
    b.say("narrator", "We look at the weather, then we choose what to wear.", act={who: "nod"}, fx="sparkle")
    b.say(who, "What is the weather like for you?", act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("H", "what_to_wear", "i_wonder", f"What Should We Wear? {N} Checks the Weather",
                 f"{N} checks the weather: an umbrella for rain and a sun hat for sunshine.",
                 "Choosing clothes to match the weather.", "bright", [who], b.beats, ["weather", "getting dressed", "rain", "sun"], {"who": who})


FORMATS = {
    "A": [color_walk, count_with_me, shape_spotters, opposites, color_mix, one_more],
    "B": [meadow_explorers, lost_and_found, who_lives_here],
    "C": [sharing, saying_sorry, helping, taking_turns, new_friend, cheering_up],
    "D": [brush_teeth, wash_hands, tidy_up, magic_words, good_morning, healthy_snack],
    "E": [action_song, counting_song, colors_song, friends_song, rain_song, wash_song],
    "F": [sleepy_friends, counting_stars, bedtime_routine, goodnight_meadow, calm_breathing],
    "G": [letter_day, find_the_letter],
    "H": [rain_to_rainbow, seed_to_flower, day_and_night, float_or_sink, falling_leaves, bubbles, what_to_wear],
}
CATEGORY_NAMES = {"A": "Colors, Shapes & Numbers", "B": "Animal Adventures", "C": "Friendship & Kindness", "D": "Good Habits & Manners",
                  "E": "Rhymes & Sing-Along", "F": "Bedtime Stories", "G": "Alphabet & Early Learning", "H": "Everyday Discoveries"}


# =====================================================================================
# More formats, so the channel can keep four new episodes a day without repeating itself.
# Each one is a different KIND of episode (a listening game, a riddle, a prediction, a
# comparison, a countdown, a call-and-response, a wind-down...). Each draws its moments
# from a bank of small, true situations, so two episodes of one format visit different
# animals, objects and places instead of reading the same script with one word swapped.
# =====================================================================================
NIGHT_END = "Goodnight from Wonder Meadow"


def _cycle_pair(seq: list, i: int):
    """Alternate the asker and the answerer between two cast members."""
    return (seq[0], seq[1]) if i % 2 == 0 else (seq[1], seq[0])


# ------------------------------------------------------------------ H: discoveries ---
SOUND_BANK = [  # prop, color, env, sound, overlay, clue, guess, reveal
    ("bee", None, "garden", "Buzz, buzz, buzz.", "BUZZ", "It visits flower after flower.", "a bee",
     "A bee! Its fast little wings make the buzz."),
    ("bell", None, "playroom", "Ding, ding, ding!", "DING", "It is shiny, and it swings.", "a bell", "A bell! A bell rings when it swings."),
    ("drum", None, "playroom", "Boom, boom, boom!", "BOOM", "You tap the top to play it.", "a drum", "A drum! Tap the top, and it goes boom."),
    ("cow", None, "meadow", "Moo, moo.", "MOO", "It is big, and it munches grass.", "a cow", "A cow! Cows say moo."),
    ("sheep", None, "hilltop", "Baa, baa.", "BAA", "It has a soft, woolly coat.", "a sheep", "A sheep! Sheep say baa."),
    ("pig", None, "meadow", "Oink, oink.", "OINK", "It has a curly tail and a round nose.", "a pig", "A pig! Pigs say oink."),
    ("frog", None, "pond", "Ribbit, ribbit.", "RIBBIT", "It sits by the pond, ready to hop.", "a frog", "A frog! Frogs say ribbit."),
    ("owl", None, "night", "Hoo, hoo.", "HOO", "It has big round eyes and wakes at night.", "an owl", "An owl! Owls call hoo, hoo."),
    ("chick", None, "garden", "Peep, peep, peep.", "PEEP", "It is small, yellow and fluffy.", "a chick", "A chick! Baby chickens say peep."),
    ("bird", "blue", "forest", "Tweet, tweet, tweet.", "TWEET", "It sings up high in a tree.", "a bird", "A bird! Birds sing tweet, tweet."),
    ("clock", "blue", "playroom", "Tick, tock, tick, tock.", "TICK TOCK", "It has two hands, but no fingers.", "a clock",
     "A clock! A clock goes tick, tock."),
    ("xylophone", None, "playroom", "Plink, plink, plonk!", "PLINK", "It has colorful bars in a row.", "a xylophone",
     "A xylophone! Each bar plays a different note."),
    ("raindrop", None, "rainy", "Pitter, patter, pitter, patter.", "PITTER PATTER", "It falls from gray clouds.", "rain",
     "Rain! Raindrops go pitter, patter."),
    ("broom", None, "playroom", "Swish, swish, swish.", "SWISH", "It sweeps the floor clean.", "a broom", "A broom! The broom goes swish."),
    ("bubbles", None, "bathroom", "Pop! Pop! Pop!", "POP", "They are round and full of air.", "bubbles", "Bubbles! Bubbles go pop."),
    ("leaf", "orange", "forest", "Crunch, crunch, crunch.", "CRUNCH", "Trees drop them in autumn.", "dry leaves",
     "Dry leaves! They crunch under our feet."),
]


def guess_the_sound(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    picks = rng.sample(SOUND_BANK, 3)
    b = B(uni, picks[0][2]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"Shh. {X} and {Y} hear something. What makes that sound?",
                         f"Listen with {X} and {Y}. What makes that sound?", f"{X} and {Y} play a listening game. What makes that sound?"),
          title="What Makes That Sound?", act={x: "think", y: "think"})
    for i, (prop, col, env, snd, ov, clue, guess, reveal) in enumerate(picks):
        b.go(env)
        g, o = _cycle_pair([x, y], i)
        b.say("narrator", snd, act={x: "look_up", y: "look_up"}, word=(ov, "orange"))
        b.say(o, _v(rng, f"Here is a clue, {b.n(g)}. {clue}", f"Listen again. {clue}", clue), act={o: "point", g: "think"})
        b.say(g, _v(rng, f"I think it is {guess}!", f"Could it be {guess}?", f"I know! It is {guess}!"), act={g: "wow"})
        b.show(prop, col, 3 if prop == "leaf" else 1)
        b.say("narrator", reveal, act={g: "cheer", o: "clap"}, word=(spoken_name(prop).upper(), "blue"), sfx=["ding"])
    b.clear()
    b.say("narrator", _v(rng, "Our ears help us find out what is around us.", "Listen closely, and sounds tell us so much!",
                         "Ears are for listening. What good listeners!"), act={x: "cheer", y: "cheer"}, fx="sparkle")
    b.say(x, _v(rng, "What sounds can you hear right now?", "Can you make one of those sounds?", "Which sound did you like best?"),
          act={x: "wave"}, end=uni["brand"]["end_card"])
    names = [p[6] for p in picks]
    return Story("H", "guess_the_sound", "i_wonder", f"What Makes That Sound? {X} and {Y} Listen",
                 f"{X} and {Y} listen to three sounds, use a clue for each, and find {join_words(names)}.",
                 "Listening carefully: our ears tell us what makes a sound.", "bright", [x, y], b.beats,
                 ["listening", "sounds", "senses", "science for kids"] + [p[0] for p in picks],
                 {"picks": sorted(p[0] for p in picks), "x": x, "y": y})


SENSES = {  # sense: (body part, verb phrase, ask verb, intro, [(prop, color, env, describe, overlay)])
    "touch": ("hands", "touches", "feel", "Our hands can feel things. Let's touch and feel with {N}.", [
        ("feather", None, "meadow", "It feels soft and tickly.", "SOFT"), ("rock", None, "forest", "It feels hard and bumpy.", "HARD"),
        ("snowflake", None, "meadow", "Brr! It feels cold and wet.", "COLD"), ("yarn", "pink", "playroom", "It feels fuzzy and soft.", "FUZZY"),
        ("shell", None, "pond", "It feels smooth inside and ridgy outside.", "RIDGY"),
        ("towel", "green", "bathroom", "It feels fluffy and dry.", "FLUFFY"), ("pinecone", None, "forest", "It feels rough and scratchy.", "ROUGH"),
        ("spoon", None, "playroom", "It feels smooth and cool.", "SMOOTH"), ("teddy", None, "playroom", "It feels cuddly and squishy.", "CUDDLY")]),
    "smell": ("nose", "smells", "smell", "Sniff, sniff! Our noses can smell. Let's sniff with {N}.", [
        ("flower", "pink", "garden", "Mmm. It smells sweet.", "SWEET"), ("bread", None, "playroom", "Mmm. Warm bread smells yummy.", "YUMMY"),
        ("strawberry", None, "garden", "It smells sweet and fruity.", "FRUITY"), ("soap", None, "bathroom", "It smells fresh and clean.", "CLEAN"),
        ("orange", None, "garden", "It smells fresh and tangy.", "TANGY"), ("pinecone", None, "forest", "It smells like the woods.", "PINE"),
        ("banana", None, "meadow", "It smells sweet and ripe.", "RIPE")]),
    "see": ("eyes", "looks at", "see", "Look, look! Our eyes can see. Let's look closely with {N}.", [
        ("rainbow", None, "meadow", "It has so many colors.", "COLORS"), ("ladybug", None, "garden", "It is red with black spots.", "SPOTS"),
        ("moon", None, "night", "It is round and bright.", "ROUND"), ("fish", "orange", "pond", "It is orange and shiny.", "SHINY"),
        ("snail", None, "garden", "Its shell has a swirl.", "SWIRL"), ("butterfly", "purple", "meadow", "Its wings have pretty patterns.", "PATTERNS"),
        ("star", "yellow", "night", "It twinkles far away.", "TWINKLE"), ("caterpillar", None, "garden", "It is long and green.", "LONG")]),
    "taste": ("tongue", "tastes", "taste", "Yum! Our tongues can taste. It is snack time with {N}.", [
        ("strawberry", None, "garden", "It tastes sweet and juicy.", "SWEET"), ("carrot", None, "garden", "It tastes crunchy and fresh.", "CRUNCHY"),
        ("banana", None, "meadow", "It tastes soft and sweet.", "SOFT"), ("apple", None, "garden", "It tastes crisp and juicy.", "CRISP"),
        ("grapes", None, "garden", "They taste juicy and sweet.", "JUICY"), ("bread", None, "playroom", "It tastes warm and soft.", "WARM"),
        ("milk", None, "playroom", "It tastes cool and creamy.", "CREAMY"), ("pear", None, "garden", "It tastes sweet and juicy.", "JUICY")]),
}


def five_senses(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    sense = rng.choice(list(SENSES))
    part, verb, ask, intro, bank = SENSES[sense]
    picks = rng.sample(bank, 3)
    b = B(uni, picks[0][2]).enter(who)
    N = b.n(who)
    b.say("narrator", intro.format(N=N), title=f"{cap(sense)} With {N}", act={who: "wave"}, word=(sense.upper(), "pink"))
    b.say(who, _v(rng, "I wonder what I will find!", "Here I go!", f"Let's {ask} together!"), act={who: "hop"})
    for prop, col, env, desc, ov in picks:
        b.go(env).show(prop, col)
        the = "the grapes" if prop == "grapes" else f"the {spoken_name(prop)}"
        b.say("narrator", _v(rng, f"{N} {verb} {the}.", f"Now {N} {verb} {the}.", f"Next, {N} {verb} {the}."), act={who: "point"})
        b.say(who, desc, act={who: "wow"}, word=(ov, "purple"))
    b.clear()
    words = [p[4].lower() for p in picks]
    b.say("narrator", f"{cap(join_words(list(dict.fromkeys(words))))}. We {ask} so much with our {part}!", act={who: "cheer"}, fx="sparkle")
    b.say(who, _v(rng, f"What can you {ask} right now?", f"What do you like to {ask}?"), act={who: "wave"}, end=uni["brand"]["end_card"])
    return Story("H", "five_senses", "i_wonder", f"{cap(sense)} With {N}: {cap(join_words([spoken_name(p[0]) for p in picks]))}",
                 f"{N} uses the sense of {sense} to explore {join_words([spoken_name(p[0]) for p in picks])}.",
                 f"We {ask} with our {part}.", "bright", [who], b.beats, ["five senses", sense, "science for kids", "discovery"],
                 {"sense": sense, "picks": sorted(p[0] for p in picks), "who": who})


SEASON_CLUES = {
    "spring": [("garden", "sprout", None, "Little green sprouts are poking up."), ("garden", "flower", "pink", "New flowers are opening."),
               ("garden", "chick", None, "Fluffy baby chicks are hatching."), ("garden", "bee", None, "Busy bees are visiting the blossoms."),
               ("forest", "nest", None, "Birds are building nests in the trees."), ("rainy", "raindrop", None, "Gentle rain helps the plants grow.")],
    "summer": [("meadow", "sun", None, "The sun is hot, and the days are long."), ("garden", "strawberry", None, "Sweet strawberries are ripe."),
               ("meadow", "hat", "orange", "We wear sun hats to stay cool."), ("night", "firefly", None, "Fireflies glow on warm evenings."),
               ("garden", "icecream", None, "A cold treat tastes good on a hot day."),
               ("meadow", "butterfly", "orange", "Butterflies flutter over the warm grass.")],
    "autumn": [("forest", "leaf", "orange", "Leaves turn red, orange and yellow."), ("forest", "acorn", None, "Acorns drop from the oak trees."),
               ("forest", "pinecone", None, "Pine cones fall to the ground."), ("garden", "apple", None, "Apples are ready to pick."),
               ("hilltop", "kite", "red", "Cool, windy days are good for kites."), ("playroom", "scarf", "orange", "We put on a cozy scarf.")],
    "winter": [("meadow", "snowflake", None, "Snowflakes are falling from the sky."),
               ("playroom", "mitten", "red", "We wear mittens to keep our hands warm."), ("playroom", "boot", "blue", "Warm boots keep our feet dry."),
               ("bedroom", "quilt", None, "The nights are long and cold. Time for a quilt."),
               ("playroom", "scarf", "green", "A warm scarf keeps our neck cozy."), ("playroom", "milk", None, "Warm milk after playing in the cold.")],
}
SEASON_FACT = {"spring": "In spring, many plants start to grow again.", "summer": "Summer is the warmest season of the year.",
               "autumn": "In autumn, the air gets cooler and many leaves fall.",
               "winter": "Winter is the coldest season. In some places, it snows."}
SEASON_COLOR = {"spring": "green", "summer": "yellow", "autumn": "orange", "winter": "blue"}


def guess_the_season(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    season = rng.choice(list(SEASON_CLUES))
    clues = rng.sample(SEASON_CLUES[season], 3)
    wrong = rng.choice([s for s in SEASON_CLUES if s != season])
    b = B(uni, clues[0][0]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"{X} has three clues. Can {Y} guess the season?", f"Let's play a game! {X} gives three clues. Guess the season!"),
          title="Guess the Season!", act={x: "wave", y: "think"})
    for i, (env, prop, col, line) in enumerate(clues):
        b.go(env).show(prop, col)
        b.say(x, (_v(rng, "Clue number one. ", "First clue. ", "") if i == 0 else "") + line, act={x: "point", y: "look_up"},
              number=(i + 1, SEASON_COLOR[season]))
        if i == 1:
            b.say(y, _v(rng, f"Hmm. Is it {wrong}?", f"Maybe it is {wrong}?", f"I think it is {wrong}!"), act={y: "think"})
            b.say(x, _v(rng, "Not quite! Here is one more clue.", "Good try! Listen to one more clue.", f"Close, {Y}! One more clue."),
                  act={x: "nod"})
    b.say(y, _v(rng, f"Now I know! It is {season}!", f"It is {season}!", f"{cap(season)}! It is {season}!"), act={y: "cheer"},
          word=(season.upper(), SEASON_COLOR[season]), sfx=["chime"])
    b.clear()
    b.say("narrator", SEASON_FACT[season], act={x: "clap", y: "nod"}, word=(season.upper(), SEASON_COLOR[season]))
    b.say("narrator", "Spring, summer, autumn, winter. Then spring comes again!", act={x: "dance", y: "dance"}, fx="sparkle")
    b.say(x, _v(rng, "Which season do you like best?", f"What do you like to do in {season}?"), act={x: "wave"}, end=uni["brand"]["end_card"])
    return Story("H", "guess_the_season", "i_wonder", f"Guess the Season! {X} Gives Three Clues",
                 f"{X} gives three clues about {season}: {join_words([spoken_name(c[1], 2) for c in clues])}. {Y} guesses.",
                 f"Signs of {season}; the four seasons in order.", "bright", [x, y], b.beats, ["seasons", season, "weather", "science for kids"],
                 {"season": season, "clues": sorted(c[1] + str(c[2]) for c in clues), "x": x, "y": y})


CYCLES = {  # key: (question, env, recap, [(prop, color, size, overlay, [line variants])])
    "butterfly": ("How does a caterpillar become a butterfly?", "garden", "Egg, caterpillar, chrysalis, butterfly!", [
        ("egg", None, 70, "EGG", ["A tiny egg sits on a leaf.", "Look closely. There is a tiny egg on a leaf."]),
        ("caterpillar", None, 120, "CATERPILLAR", ["Out comes a hungry caterpillar. Munch, munch!", "A little caterpillar hatches and eats leaves."]),
        ("cocoon", None, 130, "CHRYSALIS", ["The caterpillar makes a chrysalis and rests inside.", "It hangs very still, safe inside a chrysalis."]),
        ("butterfly", "purple", 140, "BUTTERFLY", ["Out comes a butterfly! It opens its wings.", "Surprise! A butterfly with beautiful wings."])]),
    "frog": ("How does a tadpole become a frog?", "pond", "Eggs, tadpole, little legs, frog!", [
        ("bubbles", None, 110, "EGGS", ["Frog eggs float in the pond, like little jelly beads.", "In the pond, there are soft, jelly frog eggs."]),
        ("tadpole", None, 110, "TADPOLE", ["A tadpole hatches. It swims with a long tail.", "Out wiggles a tadpole, swishing its tail."]),
        ("frog", None, 80, "LEGS", ["The tadpole grows legs, and its tail gets smaller.", "Little legs grow, and the tail shrinks away."]),
        ("frog", None, 140, "FROG", ["Now it is a frog! Ribbit!", "Hop! It is a frog at last."])]),
    "chick": ("How does a chick hatch?", "garden", "Nest, egg, crack, chick!", [
        ("nest", None, 120, "NEST", ["A mother hen keeps her eggs warm in the nest.", "A hen sits on her eggs to keep them warm."]),
        ("egg", None, 110, "EGG", ["Tap, tap. Something is moving inside an egg.", "Listen. Tap, tap, tap, from inside the egg."]),
        ("chick", None, 90, "CRACK", ["Crack! Out comes a wet little chick.", "The shell cracks open. Hello, little chick!"]),
        ("chick", None, 140, "CHICK", ["The chick dries off, fluffy and yellow. Peep!", "Soon the chick is dry and fluffy. Peep, peep!"])]),
    "oak": ("How does an acorn become an oak tree?", "forest", "Acorn, root, sprout, oak tree!", [
        ("acorn", None, 110, "ACORN", ["An acorn falls from an oak tree.", "Plop! An acorn drops to the ground."]),
        ("seed", None, 120, "ROOT", ["Under the soil, the acorn sends a root down.", "In the soil, a tiny root starts to grow."]),
        ("sprout", None, 120, "SPROUT", ["A little green sprout pokes up.", "Up comes a small sprout with two leaves."]),
        ("tree", None, 150, "OAK TREE", ["After many, many years, it is a tall oak tree!", "Slowly, over many years, it grows into a big oak."])]),
    "apple": ("How does an apple grow?", "garden", "Blossom, bee, little apple, red apple!", [
        ("flower", "pink", 120, "BLOSSOM", ["In spring, the apple tree is full of blossoms.", "Pink blossoms open on the apple tree."]),
        ("bee", None, 110, "BEE", ["Bees visit the blossoms and carry pollen.", "Buzz! Bees carry pollen from blossom to blossom."]),
        ("apple", "green", 90, "APPLE", ["A tiny green apple starts to grow.", "Where a blossom was, a little apple grows."]),
        ("apple", "red", 140, "RED", ["It grows big and turns red. Ready to pick!", "All summer it grows, until it is red and ripe."])]),
}


def life_cycle(rng, uni) -> Story:
    key = rng.choice(list(CYCLES))
    q, env, recap, stages = CYCLES[key]
    x, y = _pick_cast(rng, uni, 2)
    b = B(uni, env).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say(x, _v(rng, f"{Y}, I wonder. {q}", f"I have a question. {q}", q), title=q, act={x: "think"})
    b.say(y, _v(rng, f"Let's find out, {X}. Step by step!", f"We can find out together, {X}.", f"Let's look closely and find out, {X}."),
          act={y: "nod"})
    for i, (prop, col, size, ov, lines) in enumerate(stages):
        if i == len(stages) - 1:
            b.say(y, _v(rng, f"What do you think comes next, {X}?", "What comes next?", "And then what happens?"), act={y: "think", x: "think"})
        b.clear().show(prop, col, size=size)
        if key == "butterfly" and i == 0:
            b.show("leaf", None, size=90)
        b.say("narrator", rng.choice(lines), act={x: "point" if i % 2 else "wow", y: "look_up"}, number=(i + 1, "green"), sub=ov.lower())
    b.clear()
    b.say("narrator", recap + " " + _v(rng, "Living things grow and change.", "Step by step, it grew and changed."), act={x: "cheer", y: "cheer"},
          fx="sparkle")
    b.say(x, _v(rng, "Nature is full of surprises!", "What else grows and changes?", "I love finding out how things grow!"), act={x: "wave"},
          end=uni["brand"]["end_card"])
    return Story("H", "life_cycle", "i_wonder", f"{q[:-1]}? {X} and {Y} Find Out",
                 f"{X} and {Y} watch, step by step: {recap.rstrip('!').lower()}.", "Living things grow and change in steps.", "bright",
                 [x, y], b.beats, ["life cycle", key, "nature", "science for kids"], {"cycle": key, "x": x, "y": y})


COMPARE = {  # dimension: (question, overlay, outro word, [(a, a color, a size, b, b color, b size, env, fact)])
    "heavy": ("Which one is heavier?", "HEAVY", "heavy", [
        ("rock", None, 110, "feather", "blue", 110, "forest", "The rock is heavy. The feather is very light."),
        ("block", "green", 110, "balloon", "red", 110, "playroom", "The block is heavier. The balloon is light and floats."),
        ("book", "blue", 110, "leaf", None, 110, "forest", "The book is heavier than the little leaf.")]),
    "tall": ("Which one is taller?", "TALL", "tall", [
        ("tree", None, 150, "flower", "pink", 70, "garden", "The tree is taller than the flower."),
        ("lamp", None, 140, "cup", "pink", 60, "playroom", "The lamp is taller than the cup."),
        ("tree", None, 150, "sprout", None, 60, "forest", "The tree is tall. The little sprout is short.")]),
    "fast": ("Which one is faster?", "FAST", "fast", [
        ("bird", "blue", 110, "snail", None, 110, "garden", "The bird flies fast. The snail moves slowly."),
        ("bee", None, 110, "turtle", None, 110, "pond", "The bee zooms fast. The turtle walks slowly."),
        ("butterfly", "orange", 110, "caterpillar", None, 110, "meadow", "The butterfly flutters fast. The caterpillar crawls slowly.")]),
    "long": ("Which one is longer?", "LONG", "long", [
        ("worm", None, 120, "ant", None, 70, "garden", "The worm is longer than the ant."),
        ("scarf", "green", 130, "mitten", "red", 80, "playroom", "The scarf is longer than the mitten."),
        ("broom", None, 140, "spoon", None, 80, "playroom", "The broom is longer than the spoon.")]),
    "hot": ("Which one is hot?", "HOT", "hot", [("sun", None, 120, "snowflake", None, 110, "meadow", "The sun is hot. Snow is cold.")]),
    "soft": ("Which one is softer?", "SOFT", "soft", [
        ("pillow", None, 110, "rock", None, 110, "playroom", "The pillow is soft. The rock is hard."),
        ("teddy", None, 110, "block", "blue", 110, "playroom", "The teddy is soft. The block is hard."),
        ("yarn", "pink", 110, "shell", None, 110, "pond", "The yarn is soft. The shell is hard.")]),
    "big": ("Which one is bigger?", "BIG", "big", [
        ("cow", None, 150, "ladybug", None, 50, "meadow", "The cow is much bigger than the ladybug."),
        ("sheep", None, 150, "bee", None, 55, "hilltop", "The sheep is bigger than the bee."),
        ("pig", None, 150, "ant", None, 50, "meadow", "The pig is bigger than the ant.")]),
}


def which_one(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    dims = rng.sample(list(COMPARE), 3)
    picks = [(d, rng.choice(COMPARE[d][3])) for d in dims]
    b = B(uni, picks[0][1][6]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"{X} and {Y} are comparing things. Which one is which?", f"Let's compare with {X} and {Y}!",
                         f"Two things, side by side. {X} and {Y} will compare them."), title="Which One Is Bigger, Faster, Softer?",
          act={x: "wave", y: "wave"})
    for i, (d, (a, ac, asz, o, oc, osz, env, fact)) in enumerate(picks):
        q, ov, _ = COMPARE[d][:3]
        asker, answer = _cycle_pair([x, y], i)
        b.go(env)
        pair = [(a, ac, asz), (o, oc, osz)]
        rng.shuffle(pair)
        for p, c, s in pair:
            b.show(p, c, size=s)
        b.say(asker, _v(rng, f"{b.n(answer)}, {q[0].lower()}{q[1:]}", q, f"Look at these two. {q}"), act={asker: "point", answer: "think"})
        b.say(answer, _v(rng, f"The {spoken_name(a)}!", f"I think the {spoken_name(a)}.", f"That is easy. The {spoken_name(a)}!"),
              act={answer: "point"}, word=(ov, "orange"))
        b.say("narrator", fact, act={x: "nod", y: "nod"}, word=(ov, "orange"))
    b.clear()
    b.say("narrator", f"{cap(join_words([COMPARE[d][2] for d in dims]))}. {X} and {Y} are great at comparing!", act={x: "cheer", y: "cheer"},
          fx="sparkle")
    b.say(y, _v(rng, "What two things can you compare today?", "Which is bigger, you or a ladybug?"), act={y: "wave"},
          end=uni["brand"]["end_card"])
    return Story("H", "which_one", "i_wonder", f"{COMPARE[dims[0]][0][:-1].title()}? {X} and {Y} Compare",
                 f"{X} and {Y} compare pairs of things: {join_words([COMPARE[d][2] for d in dims])}.",
                 "Comparing two things: heavier, taller, faster, longer, softer, bigger.", "bright", [x, y], b.beats,
                 ["comparing", "opposites", "science for kids"] + dims, {"picks": sorted(f"{d}:{p[0]}{p[3]}" for d, p in picks), "x": x, "y": y})


WHERE_FROM = [  # item, color, question, source, source color, env, answer, thanks
    ("milk", None, "where does milk come from?", "cow", None, "meadow", "Milk comes from cows on a farm.", "Thank you, cows!"),
    ("egg", None, "where do eggs come from?", "nest", None, "garden", "Eggs come from hens. A hen is a mother chicken.", "Thank you, hens!"),
    ("jar", None, "where does honey come from?", "bee", None, "garden", "Honey comes from bees. Bees make it from flower nectar.",
     "Thank you, busy bees!"),
    ("yarn", "pink", "where does yarn come from?", "sheep", None, "hilltop", "Lots of yarn is made from wool. Wool comes from sheep.",
     "Thank you, sheep!"),
    ("apple", None, "where do apples come from?", "tree", None, "garden", "Apples grow on apple trees.", "Thank you, apple tree!"),
    ("strawberry", None, "where do strawberries come from?", "sprout", None, "garden",
     "Strawberries grow on small plants, close to the ground.", "Yum. Thank you, little plants!"),
    ("bread", None, "where does bread come from?", "seed", None, "meadow", "Bread is made from flour. Flour comes from wheat seeds.",
     "Thank you, wheat!"),
    ("carrot", None, "where do carrots come from?", "sprout", None, "garden", "Carrots grow under the soil. Only the leaves poke out.",
     "Under the ground! Who knew?"),
    ("feather", "blue", "where do feathers come from?", "bird", "blue", "forest", "Feathers come from birds. Birds are covered in them.",
     "Thank you, birds!"),
    ("raindrop", None, "where does rain come from?", "cloud", None, "rainy", "Rain falls from clouds. Clouds hold tiny drops of water.",
     "Thank you, clouds!"),
    ("pinecone", None, "where do pine cones come from?", "tree", None, "forest", "Pine cones grow on pine trees. They hold the seeds.",
     "Thank you, pine tree!"),
    ("acorn", None, "where do acorns come from?", "tree", None, "forest", "Acorns grow on oak trees. Each acorn is a seed.",
     "Thank you, oak tree!"),
]


def where_from(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    picks = rng.sample(WHERE_FROM, 3)
    b = B(uni, picks[0][5]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"{X} has a question. Where does it come from?", f"{X} and {Y} are curious today. Where does it come from?"),
          title="Where Does It Come From?", act={x: "think", y: "look_up"})
    for i, (item, ic, q, src, sc, env, answer, thanks) in enumerate(picks):
        asker, other = _cycle_pair([x, y], i)
        b.go(env).show(item, ic)
        b.say(asker, _v(rng, f"{b.n(other)}, {q}", f"Hmm. {cap(q)}", f"I wonder, {q}"), act={asker: "point", other: "think"})
        b.show(src, sc)
        b.say("narrator", answer, act={asker: "wow", other: "nod"}, sfx=["ding"])
        b.say(other, thanks, act={other: "cheer"})
    b.clear()
    b.say("narrator", _v(rng, "So many good things come from plants and animals.", "Everything comes from somewhere. Asking is how we learn!"),
          act={x: "cheer", y: "cheer"}, fx="sparkle")
    b.say(y, _v(rng, "What would you like to ask about?", "What do you wonder about?"), act={y: "wave"}, end=uni["brand"]["end_card"])
    topics = [p[2].split(" ")[2] for p in picks]
    return Story("H", "where_from", "i_wonder", f"Where Does It Come From? {X} and {Y} Ask",
                 f"{X} and {Y} find out where {join_words(topics)} come from.", "Food and things we use come from plants and animals.",
                 "bright", [x, y], b.beats, ["where things come from", "farm", "nature", "science for kids"] + topics,
                 {"picks": sorted(p[0] for p in picks), "x": x, "y": y})


WEATHER = {  # kind: (env, overlay color, observe line, do line)
    "sunny": ("meadow", "yellow", "The sun is shining. It is sunny and warm.", "Time for a sun hat!"),
    "rainy": ("rainy", "blue", "Drip, drop. It is rainy today.", "Time for an umbrella and boots!"),
    "windy": ("hilltop", "green", "Whoosh! The wind is blowing the leaves.", "A windy day is good for a kite!"),
    "cloudy": ("meadow", "purple", "Big gray clouds cover the sun. It is cloudy.", "Maybe rain will come later."),
    "snowy": ("meadow", "blue", "Snowflakes are falling. It is snowy and cold.", "Time for mittens and a scarf!"),
    "foggy": ("forest", "purple", "Fog is a cloud close to the ground. It is foggy.", "We stay close together and walk slowly."),
}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def weather_week(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    kinds = rng.sample(list(WEATHER), 3)
    d0 = rng.randrange(5)
    b = B(uni, WEATHER[kinds[0]][0]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"{X} and {Y} check the weather every day. What will it be?",
                         f"Every morning, {X} and {Y} look outside. What is the weather?"), title="What Is the Weather Today?",
          act={x: "look_up", y: "look_up"})
    for i, k in enumerate(kinds):
        env, col, obs, do = WEATHER[k]
        day = DAYS[d0 + i]
        speaker, other = _cycle_pair([x, y], i)
        b.go(env)
        if k == "sunny":
            b.put("sun", "sky", x=820, y=560, size=110)
        elif k == "rainy":
            b.hold(speaker, "umbrella", "yellow", 110)
        elif k == "windy":
            b.put("leaf", "fly", count=3, color="orange", size=40, y=680)
        elif k == "cloudy":
            b.put("cloud", "sky", x=330, y=540, size=130, color="#D8DEE8").put("cloud", "sky", x=780, y=620, size=110, color="#D8DEE8")
        elif k == "snowy":
            b.put("snowflake", "fall", count=10, size=34)
        elif k == "foggy":
            b.put("cloud", "sky", x=540, y=760, size=200, color="#EEF2F6")
        b.say("narrator", f"On {day}, {obs[0].lower()}{obs[1:]}", act={speaker: "look_up", other: "look_up"}, word=(k.upper(), col))
        if k == "sunny":
            b.show("hat", "orange")
        elif k == "windy":
            b.show("kite", "red")
        elif k == "snowy":
            b.show("mitten", "red").show("scarf", "green")
        elif k == "rainy":
            b.show("boot", "yellow")
        b.say(speaker, do, act={speaker: "hold_up" if k == "rainy" else "point", other: "nod"})
        b.hold(speaker, None)
    b.clear()
    b.say("narrator", f"{cap(join_words(kinds))}. The weather can change every day!", act={x: "cheer", y: "cheer"}, fx="sparkle")
    b.say(y, _v(rng, "What is the weather like today?", "What do you wear when it rains?"), act={y: "wave"}, end=uni["brand"]["end_card"])
    return Story("H", "weather_week", "i_wonder", f"What Is the Weather Today? {cap(join_words(kinds))}",
                 f"{X} and {Y} check the weather on {DAYS[d0]}, {DAYS[d0 + 1]} and {DAYS[d0 + 2]}: {join_words(kinds)}.",
                 "Weather words, and choosing what to wear for the weather.", "bright", [x, y], b.beats,
                 ["weather", "days of the week", "science for kids"] + kinds, {"kinds": kinds, "day": d0, "x": x, "y": y})


CHANGES = [  # before, color, after, color, env, after env, question, answer, overlay
    ("snowflake", None, "raindrop", None, "meadow", None, "Here is a snowflake. What happens when it gets warm?",
     "It melts into a drop of water!", "MELT"),
    ("puddle", None, "sun", None, "meadow", None, "Here is a puddle. What happens when the sun shines all day?",
     "The sun dries it up, little by little.", "DRY"),
    ("icecream", None, "raindrop", None, "garden", None, "Here is an ice cream on a hot day. What will happen?",
     "It melts and drips! Warm air melts ice cream.", "MELT"),
    ("egg", None, "chick", None, "garden", None, "Here is an egg, warm in a nest. What will happen?", "Crack! A chick hatches out.", "HATCH"),
    ("seed", None, "sprout", None, "garden", None, "Here is a seed, with soil and water. What will happen?",
     "It sprouts! A tiny plant grows.", "GROW"),
    ("bubbles", None, "bubbles", None, "meadow", None, "Here are some bubbles. What happens when they touch the grass?",
     "Pop! They burst and are gone.", "POP"),
    ("cloud", "#C9D3E0", "raindrop", None, "meadow", "rainy", "Here is a big gray cloud. What will happen?", "Rain falls from the cloud!",
     "RAIN"),
    ("caterpillar", None, "butterfly", "orange", "garden", None, "Here is a caterpillar. What will it become?",
     "A butterfly, after it rests in a chrysalis!", "CHANGE"),
    ("tadpole", None, "frog", None, "pond", None, "Here is a tadpole. What will it grow into?", "A frog! It grows legs and hops.", "GROW"),
    ("sun", None, "moon", None, "meadow", "night", "The sun goes down in the evening. What comes next?",
     "Night comes, with the moon and stars.", "NIGHT"),
    ("acorn", None, "sprout", None, "forest", None, "An acorn is in the soil. What will happen?", "A little oak sprout pops up!", "GROW"),
    ("leaf", None, "leaf", "orange", "forest", None, "Here is a green leaf in summer. What happens in autumn?",
     "It turns orange, then it falls.", "AUTUMN"),
]


def what_will_happen(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    picks = rng.sample(CHANGES, 3)
    b = B(uni, picks[0][4]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"{X} and {Y} like to guess what will happen next.", f"Watch closely with {X} and {Y}. What will happen?"),
          title="What Will Happen Next?", act={x: "think", y: "think"})
    for i, (bef, bc, aft, ac, env, env2, q, ans, ov) in enumerate(picks):
        g, o = _cycle_pair([x, y], i)
        b.go(env).show(bef, bc)
        b.say("narrator", q, act={g: "think", o: "look_up"})
        b.say(g, _v(rng, f"Let's watch and see, {b.n(o)}!", "I have a guess. Let's watch!", "Hmm. I think I know!"), act={g: "point"})
        if env2:
            b.go(env2)
        b.clear()
        if not (bef == "bubbles"):
            b.show(aft, ac)
        b.say("narrator", ans, act={g: "wow", o: "cheer"}, word=(ov, "green"), sfx=["pop"] if bef == "bubbles" else ["chime"])
    b.clear()
    b.say("narrator", _v(rng, "Things change all around us. We can watch and find out!", "Guess, then watch. That is how we learn."),
          act={x: "cheer", y: "cheer"}, fx="sparkle")
    b.say(y, _v(rng, "What change will you watch for today?", "Which change surprised you?"), act={y: "wave"}, end=uni["brand"]["end_card"])
    return Story("H", "what_will_happen", "i_wonder", f"What Will Happen Next? {X} and {Y} Watch Things Change",
                 f"{X} and {Y} guess, then watch: {join_words([p[7].split('!')[0].split('.')[0].lower() for p in picks])}.",
                 "Things change: melting, drying, hatching, growing. We can predict, then watch.", "bright", [x, y], b.beats,
                 ["changes", "predicting", "science for kids"], {"picks": sorted(p[0] + p[2] for p in picks), "x": x, "y": y})


# ------------------------------------------------------------------ B: animals -------
RIDDLES = [  # prop, color, env, clue one, clue two
    ("cow", None, "meadow", "I am big, and I munch on grass all day.", "I say moo."),
    ("bee", None, "garden", "I am small, with yellow and black stripes.", "I buzz from flower to flower."),
    ("owl", None, "night", "I have big round eyes.", "I am awake at night, and I say hoo."),
    ("turtle", None, "pond", "I carry a hard shell on my back.", "I walk very, very slowly."),
    ("frog", None, "pond", "I am green, and I love the pond.", "I hop and say ribbit."),
    ("fish", "orange", "pond", "I live in the water.", "I swim with fins and a tail."),
    ("snail", None, "garden", "I am slow, and I leave a shiny trail.", "My shell is my home."),
    ("ladybug", None, "garden", "I am tiny and red.", "I have black spots on my back."),
    ("butterfly", "purple", "meadow", "I have big, colorful wings.", "I was once a caterpillar."),
    ("sheep", None, "hilltop", "I have a thick, woolly coat.", "I say baa."),
    ("pig", None, "meadow", "I have a curly tail.", "I say oink, and I roll in mud to stay cool."),
    ("ant", None, "meadow", "I am tiny, but I am very strong.", "I live with my big family in tunnels."),
    ("bird", "blue", "forest", "I have feathers and wings.", "I build a nest and sing tweet, tweet."),
    ("chick", None, "garden", "I am small, fluffy and yellow.", "I hatched from an egg."),
    ("caterpillar", None, "garden", "I am long and wiggly, and I munch leaves.", "One day I will be a butterfly."),
    ("worm", None, "garden", "I have no legs, and I wiggle.", "I live in the soil and help plants grow."),
]


def animal_riddles(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    picks = rng.sample(RIDDLES, 3)
    b = B(uni, picks[0][2]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"Riddle time with {X} and {Y}! Who am I?", f"{X} and {Y} love animal riddles. Listen to the clues!",
                         "Here come three animal riddles. Can you guess? Who am I?"), title="Who Am I? Animal Riddles",
          act={x: "clap", y: "clap"})
    for i, (prop, col, env, c1, c2) in enumerate(picks):
        g, o = _cycle_pair([x, y], i)
        b.go(env)
        b.say("narrator", c1, act={g: "think", o: "nod"}, word=("?", "purple"))
        b.say("narrator", f"{c2} Who am I?", act={g: "think", o: "nod"}, word=("?", "purple"))
        name = an(spoken_name(prop))
        b.say(g, _v(rng, f"I know! You are {name}!", f"I think you are {name}.", f"{b.n(o)}, I think it is {name}!"), act={g: "hop", o: "look_up"})
        b.show(prop, col)
        b.say("narrator", _v(rng, f"Yes! It is {name}.", f"That is right. {cap(name)}!", f"Hooray! {cap(name)}!"), act={g: "cheer", o: "clap"},
              word=(spoken_name(prop).upper(), "green"), sfx=["chime"])
    b.clear()
    b.say("narrator", _v(rng, "Listening to clues helps us figure things out.", "Three riddles, three animals. Great guessing!"),
          act={x: "dance", y: "dance"}, fx="sparkle")
    b.say(y, _v(rng, "Can you make up an animal riddle?", "Which animal riddle was your favorite?"), act={y: "wave"},
          end=uni["brand"]["end_card"])
    names = [spoken_name(p[0]) for p in picks]
    return Story("B", "animal_riddles", "meadow_explorers", f"Who Am I? Animal Riddles With {X} and {Y}",
                 f"{X} and {Y} solve three animal riddles: {join_words([an(n) for n in names])}.",
                 f"Recognize {join_words(names)} from clues about how they look and live.", "adventure", [x, y], b.beats,
                 ["animals", "riddles", "guessing game"] + names, {"picks": sorted(p[0] for p in picks), "x": x, "y": y})


BABIES = [  # grown-up prop, baby prop, baby word, env, line
    ("sheep", "sheep", "lamb", "hilltop", "A baby sheep is called a lamb."),
    ("cow", "cow", "calf", "meadow", "A baby cow is called a calf."),
    ("pig", "pig", "piglet", "meadow", "A baby pig is called a piglet."),
    ("owl", "owl", "owlet", "forest", "A baby owl is called an owlet."),
    ("turtle", "turtle", "hatchling", "pond", "A baby turtle is called a hatchling. It hatches from an egg."),
    ("frog", "tadpole", "tadpole", "pond", "A baby frog is a tadpole. It swims with a tail."),
    ("butterfly", "caterpillar", "caterpillar", "garden", "A butterfly starts out as a caterpillar."),
    ("bird", "bird", "chick", "forest", "A baby bird is called a chick."),
    ("fish", "fish", "fry", "pond", "Baby fish are called fry. They are very tiny."),
    ("bee", "bee", "larva", "garden", "A baby bee is called a larva. It grows inside the hive."),
]
CHAR_BABY = {"bobo": ("bunny", "kit"), "mimi": ("cat", "kitten"), "toto": ("elephant", "calf"), "zuzu": ("duck", "duckling"),
             "lolo": ("bear", "cub")}


def animal_babies(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    picks = rng.sample(BABIES, 3)
    b = B(uni, picks[0][3]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"{X} and {Y} are looking for animal babies today.", f"Grown-ups and babies! {X} and {Y} go exploring.",
                         f"Who is the baby? {X} and {Y} are finding out."), title="Animal Babies: What Are They Called?",
          act={x: "hop", y: "hop"})
    for i, (big, small, word, env, line) in enumerate(picks):
        a, o = _cycle_pair([x, y], i)
        b.go(env).show(big, "orange" if big == "fish" else ("blue" if big == "bird" else None), size=130)
        b.show(small, "orange" if small == "fish" else ("blue" if small == "bird" else None), size=60)
        b.say(a, _v(rng, f"Look, {b.n(o)}! A big {spoken_name(big)} and a little one.", f"There is a grown-up {spoken_name(big)} with a baby!",
                    f"A {spoken_name(big)} family!"), act={a: "nod", o: "look_up"})
        b.say(o, f"What is a baby {spoken_name(big)} called?", act={o: "think", a: "nod"})
        b.say("narrator", line, act={a: "clap", o: "cheer"}, word=(word.upper(), "pink"), sfx=["ding"])
    b.clear()
    kind, baby = CHAR_BABY[x]
    b.say(x, _v(rng, f"And me? I am a {kind}. A baby {kind} is a {baby}!", f"I am a {kind}. When I was a baby, I was a {baby}!"),
          act={x: "dance", y: "clap"}, word=(baby.upper(), "pink"), fx="hearts")
    b.say(y, _v(rng, "Which animal baby do you like best?", "Every grown-up was a baby once!"), act={y: "wave"},
          end=uni["brand"]["end_card"])
    words = [p[2] for p in picks]
    return Story("B", "animal_babies", "meadow_explorers", f"Animal Babies: {cap(join_words(words))}",
                 f"{X} and {Y} meet animal families and learn the baby names {join_words(words)}.",
                 f"Baby animal names: {join_words(words)}.", "adventure", [x, y], b.beats, ["animals", "animal babies", "nature"] + words,
                 {"picks": sorted(p[2] for p in picks), "x": x, "y": y})


EATS = [  # animal, color, env, food prop, food color, line
    ("cow", None, "meadow", None, None, "Cows munch green grass, all day long."),
    ("sheep", None, "hilltop", None, None, "Sheep nibble the grass on the hill."),
    ("bee", None, "garden", "flower", "pink", "Bees drink sweet nectar from flowers."),
    ("caterpillar", None, "garden", "leaf", None, "Caterpillars munch and munch on green leaves."),
    ("bird", "blue", "forest", "worm", None, "Many birds eat worms, seeds and berries."),
    ("frog", None, "pond", "ant", None, "Frogs catch little bugs with long, sticky tongues."),
    ("snail", None, "garden", "leaf", None, "Snails nibble on soft leaves."),
    ("pig", None, "meadow", "apple", None, "Pigs eat many foods, like apples and vegetables."),
    ("ladybug", None, "garden", None, None, "Ladybugs eat tiny bugs that live on plants."),
    ("chick", None, "garden", "seed", None, "Chicks peck at seeds and grains."),
    ("turtle", None, "pond", "leaf", None, "Many turtles munch on plants and leaves."),
    ("fish", "orange", "pond", None, None, "Fish eat tiny plants and bugs in the water."),
    ("worm", None, "garden", "leaf", "orange", "Worms eat old leaves in the soil."),
]
LUNCH = [("apple", "carrot"), ("banana", "strawberry"), ("pear", "grapes"), ("bread", "milk"), ("orange", "banana")]


def who_eats_what(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    picks = rng.sample(EATS, 3)
    lunch = rng.choice(LUNCH)
    b = B(uni, picks[0][2]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"It is lunchtime in Wonder Meadow. What do the animals eat?",
                         f"{X} and {Y} are hungry. Are the animals hungry too?"), title="Who Eats What? Lunchtime for Animals",
          act={x: "nod", y: "nod"})
    for i, (an_, ac, env, food, fc, line) in enumerate(picks):
        a, o = _cycle_pair([x, y], i)
        b.go(env).show(an_, ac)
        q = f"What do {spoken_name(an_, 2)} eat?"
        b.say(a, _v(rng, q, f"{b.n(o)}, {q[0].lower()}{q[1:]}", f"I wonder. {q}"), act={a: "think", o: "nod"})
        if food:
            b.show(food, fc)
        b.say("narrator", line, act={a: "nod", o: "clap"}, word=("YUM", "green"))
    b.clear().show(lunch[0]).show(lunch[1])
    b.say("narrator", f"And {X} and {Y} eat {spoken_name(lunch[0], 2) if lunch[0] not in ('bread', 'milk') else spoken_name(lunch[0])} "
                      f"and {spoken_name(lunch[1], 2) if lunch[1] not in ('bread', 'milk', 'grapes') else spoken_name(lunch[1])}.",
          act={x: "cheer", y: "cheer"}, fx="hearts")
    b.say(y, _v(rng, "Different animals eat different foods. What do you like?", "What will you eat for lunch today?"), act={y: "wave"},
          end=uni["brand"]["end_card"])
    names = [spoken_name(p[0], 2) for p in picks]
    return Story("B", "who_eats_what", "meadow_explorers", f"Who Eats What? {cap(join_words(names))}",
                 f"At lunchtime, {X} and {Y} find out what {join_words(names)} eat.", "Different animals eat different foods.", "adventure",
                 [x, y], b.beats, ["animals", "what animals eat", "nature"] + names, {"picks": sorted(p[0] for p in picks), "x": x, "y": y})


GENTLE = [  # (env, [(role, text, act, show)]) roles: n narrator, x, y
    ("garden", [("n", "A snail is crossing the path, slow and steady.", {"x": "look_up"}, ("snail", None)),
                ("x", "Let's wait for the snail, {Y}.", {"y": "nod"}, None),
                ("y", "Good idea. We can step around it.", {"x": "nod"}, None),
                ("n", "Little animals need space. The friends wait patiently.", {"x": "clap", "y": "clap"}, None)]),
    ("garden", [("n", "A bee buzzes near {X}'s snack.", {"x": "wow"}, ("bee", None)),
                ("x", "Oh! What should I do?", {"y": "think"}, None),
                ("y", "Stay calm and move slowly. The bee is looking for flowers.", {"x": "nod"}, None),
                ("n", "Buzz! The bee flies away to the flowers.", {"x": "cheer", "y": "cheer"}, ("flower", "pink"))]),
    ("meadow", [("n", "It is a hot day. A little bird looks thirsty.", {"x": "look_up"}, ("bird", "blue")),
                ("y", "Let's put out a bowl of water, {X}.", {"x": "nod"}, ("bowl", "blue")),
                ("n", "Sip, sip. The bird drinks and sings a happy song.", {"x": "clap", "y": "clap"}, None)]),
    ("garden", [("n", "A ladybug lands on {X}'s arm. It tickles!", {"y": "look_up"}, ("ladybug", None)),
                ("x", "Hello, ladybug. You can rest here a while.", {"y": "nod"}, None),
                ("n", "{X} keeps very still. Soon, the ladybug flies away.", {"y": "nod"}, None)]),
    ("garden", [("n", "After the rain, a worm wiggles on the path.", {"x": "look_up"}, ("worm", None)),
                ("y", "Worms like soft soil. Let's help it with a leaf.", {"x": "nod"}, ("leaf", None)),
                ("n", "{Y} gently moves the worm back onto the soil.", {"x": "clap"}, None)]),
    ("forest", [("n", "Shh. An owl is sleeping in a tree.", {"x": "look_up"}, ("owl", None)),
                ("x", "Owls sleep in the day and wake up at night.", {"y": "nod"}, None),
                ("y", "Let's whisper and tiptoe past, {X}.", {"x": "nod"}, None)]),
    ("pond", [("n", "A turtle is walking to the pond, step by step.", {"x": "look_up"}, ("turtle", None)),
              ("x", "Should we pick it up, {Y}?", {"y": "think"}, None),
              ("y", "No, let's just watch. The turtle knows the way.", {"x": "nod"}, None),
              ("n", "Plop! The turtle slides into the pond.", {"x": "cheer", "y": "cheer"}, None)]),
    ("garden", [("n", "A caterpillar is crawling across the path.", {"y": "look_up"}, ("caterpillar", None)),
                ("y", "Let's put a leaf beside it, so it can climb on.", {"x": "nod"}, ("leaf", None)),
                ("n", "The caterpillar climbs on, and {Y} sets it by a plant.", {"x": "clap"}, None)]),
    ("pond", [("n", "Fish are swimming round and round in the pond.", {"x": "look_up"}, ("fish", "orange")),
              ("x", "Can we give them our cupcake, {Y}?", {"y": "think"}, None),
              ("y", "Cupcakes are not good for fish. Let's just watch them.", {"x": "nod"}, None)]),
    ("meadow", [("n", "A butterfly rests on a flower.", {"x": "look_up"}, ("butterfly", "orange")),
                ("x", "Let's look closely, but not touch its wings.", {"y": "nod"}, None),
                ("n", "Butterfly wings are delicate. Looking is the kind thing to do.", {"y": "nod"}, None)]),
    ("meadow", [("n", "A line of ants is carrying crumbs home.", {"x": "look_up"}, ("ant", None)),
                ("x", "Look how strong they are, {Y}!", {"y": "nod"}, None),
                ("y", "Let's walk around them, so they can get home.", {"x": "nod"}, None)]),
]


def gentle_with_animals(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    idx = rng.sample(range(len(GENTLE)), 2)
    b = B(uni, GENTLE[idx[0]][0]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    who = {"x": x, "y": y}
    b.say("narrator", _v(rng, f"{X} and {Y} go for a walk. Who will they meet?", f"Today {X} and {Y} meet some little animals.",
                         f"Off go {X} and {Y}, looking for little animals."), title=f"{X} and {Y} Are Gentle With Animals",
          act={x: "hop", y: "hop"})
    for k in idx:
        env, lines = GENTLE[k]
        b.go(env)
        for role, text, act, show in lines:
            if show:
                b.show(*show)
            b.say("narrator" if role == "n" else who[role], text.format(X=X, Y=Y), act={who[r]: a for r, a in act.items()})
    b.clear()
    b.say("narrator", _v(rng, "Being gentle with animals is a way to be kind.", "Quiet, gentle and kind. That is how we treat animals."),
          act={x: "cheer", y: "cheer"}, fx="hearts")
    b.say(x, _v(rng, "Which little animal would you like to see?", "How can you be gentle with animals?"), act={x: "wave"},
          end=uni["brand"]["end_card"])
    return Story("B", "gentle_with_animals", "meadow_explorers", f"{X} and {Y} Are Gentle With Animals",
                 f"On a walk, {X} and {Y} meet two little animals and find kind, gentle ways to help or give them space.",
                 "Being gentle with animals: give them space, stay calm, look without touching.", "adventure", [x, y], b.beats,
                 ["animals", "kindness", "nature", "adventure"], {"situations": sorted(idx), "x": x, "y": y})


MOVE_LIKE = [  # prop, color, env, fact, invite, action
    ("frog", None, "pond", "Frogs have strong back legs for hopping.", "Let's hop like a frog! Hop, hop, hop!", "hop"),
    ("bird", "blue", "forest", "Birds flap their wings to fly.", "Let's flap like a bird! Flap, flap!", "cheer"),
    ("fish", "orange", "pond", "Fish swish their tails to swim.", "Let's swim like a fish! Swish, swish!", "dance"),
    ("snail", None, "garden", "Snails glide very, very slowly.", "Let's go slow like a snail. Slow... and slow...", "nod"),
    ("worm", None, "garden", "Worms have no legs. They wiggle and stretch.", "Let's wiggle like a worm! Wiggle, wiggle!", "dance"),
    ("bee", None, "garden", "Bees zip from flower to flower.", "Let's buzz like a bee! Bzzz, bzzz!", "dance"),
    ("turtle", None, "pond", "Turtles take slow, steady steps.", "Let's walk like a turtle. Step... and step...", "nod"),
    ("butterfly", "purple", "meadow", "Butterflies flutter their wings gently.", "Let's flutter like a butterfly. Flutter, flutter.", "cheer"),
    ("ant", None, "meadow", "Ants march along in a long line.", "Let's march like ants! Left, right, left, right!", "hop"),
    ("owl", None, "forest", "Owls can turn their heads very far.", "Let's turn our heads like an owl. Left, and right!", "nod"),
    ("caterpillar", None, "garden", "Caterpillars scrunch up, then stretch out.", "Let's scrunch and stretch like a caterpillar!", "stretch"),
    ("chick", None, "garden", "Chicks peck and hop around the yard.", "Let's peck and hop like a chick! Peep!", "hop"),
]


def move_like_animals(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    picks = rng.sample(MOVE_LIKE, 4)
    b = B(uni, picks[0][2]).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"Animals move in so many ways. Move along with {X} and {Y}!", f"Get ready to move! {X} and {Y} copy the animals."),
          title="Move Like the Animals!", act={x: "stretch", y: "stretch"})
    for i, (prop, col, env, fact, invite, move) in enumerate(picks):
        a = [x, y][i % 2]
        b.go(env).show(prop, col)
        b.say("narrator", fact, act={x: "nod", y: "nod"}, word=(spoken_name(prop).upper(), "blue"))
        b.say(a, invite, act={x: move, y: move})
    b.clear()
    b.say("narrator", _v(rng, "Hop, fly, swim and crawl. Animals move in different ways!", "So many ways to move! Every animal has its own."),
          act={x: "cheer", y: "cheer"}, fx="sparkle")
    b.say(y, _v(rng, "Which animal will you move like next?", "Can you move like your favorite animal?"), act={y: "wave"},
          end=uni["brand"]["end_card"])
    names = [spoken_name(p[0], 2) for p in picks]
    return Story("B", "move_like_animals", "meadow_explorers", f"Move Like the Animals! {X} and {Y} Hop, Swim and Wiggle"
                 if {"frog", "fish", "worm"} <= {p[0] for p in picks} else f"Move Like the Animals With {X} and {Y}",
                 f"{X} and {Y} learn how {join_words(names)} move, then move like them.",
                 "Animals move in different ways; moving our bodies like them.", "adventure", [x, y], b.beats,
                 ["animals", "movement", "action game"] + names, {"picks": sorted(p[0] for p in picks), "x": x, "y": y})


# ------------------------------------------------------------------ E: rhymes --------
ANIMAL_VERSES = {  # prop: (color, env, line one, line two, action)
    "cow": (None, "meadow", "Spotty cow is munching on the green,", "Moo, moo, moo, the friendliest cow I've seen!", "nod"),
    "sheep": (None, "hilltop", "Woolly sheep up on the hill,", "Baa, baa, baa, then standing still.", "nod"),
    "pig": (None, "meadow", "Pink little pig with a curly tail,", "Oink, oink, oink, as round as a pail!", "dance"),
    "frog": (None, "pond", "Green little frog by the pond so wide,", "Ribbit, ribbit, hop to the other side!", "hop"),
    "owl": (None, "night", "Round-eyed owl up in the tree,", "Hoo, hoo, hoo, the owl sees me!", "nod"),
    "bee": (None, "garden", "Busy bee in the garden bed,", "Buzz, buzz, buzz, from blue to red!", "dance"),
    "chick": (None, "garden", "Fluffy chick so small and new,", "Peep, peep, peep, I see you too!", "hop"),
    "bird": ("blue", "forest", "Little bird on a branch so high,", "Tweet, tweet, tweet, across the sky!", "cheer"),
    "turtle": (None, "pond", "Slow, slow turtle, one step more,", "Carries a shell from shore to shore!", "nod"),
    "snail": (None, "garden", "Little snail goes slow, so slow,", "Home on its back wherever you go!", "nod"),
    "fish": ("orange", "pond", "Shiny fish goes swish, swish, swish,", "Round the pond as quick as a wish!", "dance"),
    "butterfly": ("purple", "meadow", "Flutter, flutter, butterfly,", "Colors dancing way up high!", "cheer"),
    "caterpillar": (None, "garden", "Wiggly caterpillar, munch, munch, munch,", "Eating leaves for breakfast and lunch!", "dance"),
}


def animal_rhyme(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    picks = rng.sample(list(ANIMAL_VERSES), 4)
    b = B(uni, ANIMAL_VERSES[picks[0]][1]).enter(who)
    N = b.n(who)
    b.say("narrator", _v(rng, f"Sing the animal rhyme with {N}!", f"{N} knows a rhyme about meadow animals. Sing along!"),
          title="The Meadow Animal Rhyme", act={who: "clap"}, fx="notes")
    for p in picks:
        col, env, l1, l2, move = ANIMAL_VERSES[p]
        b.go(env).show(p, col)
        b.say(who, l1, act={who: "nod"}, fx="notes", word=(spoken_name(p).upper(), "green"))
        b.say(who, l2, act={who: move}, fx="notes", word=(spoken_name(p).upper(), "green"))
    b.clear()
    b.say(who, "Animals, animals, big and small,", act={who: "dance"}, fx="notes")
    b.say(who, "We love the meadow friends, one and all!", act={who: "cheer"}, fx="sparkle", end=uni["brand"]["end_card"])
    names = [spoken_name(p) for p in picks]
    return Story("E", "animal_rhyme", "sing_along", f"The Meadow Animal Rhyme: {cap(join_words(names))}",
                 f"An original rhyme with {N} about the {join_words(names)}.", "Animal names and sounds in a rhyme.", "song", [who], b.beats,
                 ["animal song", "animals", "rhyme"] + names, {"picks": sorted(picks), "who": who}, song=True)


CALLS = [  # call, answer, rhyme tag, call action, answer action
    ("up", "down", "Up and down, round and round!", "stretch", "nod"),
    ("hello", "goodbye", "Hello, goodbye, wave it high!", "cheer", "cheer"),
    ("big", "small", "Big and small, we love them all!", "stretch", "nod"),
    ("fast", "slow", "Fast and slow, off we go!", "hop", "nod"),
    ("day", "night", "Day and night, dark and bright!", "cheer", "nod"),
    ("loud", "quiet", "Loud and quiet, let's all try it!", "clap", "nod"),
    ("open", "close", "Open, close, wiggle your nose!", "stretch", "nod"),
    ("hot", "cold", "Hot and cold, brave and bold!", "hop", "dance"),
    ("in", "out", "In and out, turn about!", "nod", "dance"),
    ("stand", "sit", "Stand up, sit, wiggle a bit!", "stretch", "dance"),
    ("left", "right", "Left and right, hold on tight!", "dance", "nod"),
    ("clap", "stomp", "Clap and stomp, a happy romp!", "clap", "hop"),
]


def call_and_response(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    picks = rng.sample(CALLS, 4)
    b = B(uni, rng.choice(["meadow", "hilltop", "playroom", "garden"])).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"{X} calls, and {Y} answers. Can you answer too?", f"A call and answer rhyme! {X} goes first."),
          title=f"Call and Answer With {X} and {Y}", act={x: "clap", y: "clap"}, fx="notes")
    for a, r, tag, ca, ra in picks:
        b.say(x, f"When I say {a}, you say {r}!", act={x: "nod", y: "nod"}, fx="notes")
        b.say(x, f"{cap(a)}!", act={x: ca}, word=(a.upper(), "orange"), fx="notes")
        b.say(y, f"{cap(r)}! {tag}", act={y: ra, x: "clap"}, word=(r.upper(), "blue"), fx="notes")
    b.say(y, _v(rng, "You are a great answerer! Hooray!", "We did it! What a fun rhyme."), act={x: "cheer", y: "cheer"}, fx="sparkle",
          end=uni["brand"]["end_card"])
    words = [f"{p[0]} and {p[1]}" for p in picks]
    return Story("E", "call_and_response", "sing_along", f"Call and Answer With {X} and {Y}: {cap(picks[0][0])} and {cap(picks[0][1])}",
                 f"An original call-and-answer rhyme: {X} calls a word, {Y} answers its opposite ({'; '.join(words)}).",
                 "Opposite words in an original call-and-answer rhyme.", "song", [x, y], b.beats, ["call and response", "opposites", "rhyme"],
                 {"picks": sorted(p[0] for p in picks), "x": x, "y": y}, song=True)


COUNTDOWNS = [  # prop, color, env, line with {k}, line with {m} and maybe {W}
    ("bubbles", None, "meadow", "{K} round bubbles floating in the air,", "One went pop! Now {m} are there."),
    ("star", "yellow", "night", "{K} little stars are twinkling in the night,", "One hid behind a cloud. Now {m} shine bright."),
    ("apple", None, "garden", "{K} shiny apples hanging on the tree,", "{W} picked one for a snack. Now {m}, you see!"),
    ("leaf", "orange", "forest", "{K} orange leaves are holding on so tight,", "Whoosh! One floated down. Now {m} in sight."),
    ("boat", "red", "pond", "{K} little boats are sailing on the pond,", "One sailed home to rest. Now {m} sail on."),
    ("butterfly", "purple", "meadow", "{K} pretty butterflies sitting in a row,", "One fluttered to a flower. Now {m}, you know!"),
    ("cupcake", None, "playroom", "{K} yummy cupcakes waiting on a plate,", "{W} shared one with a friend. Now {m}. How great!"),
    ("balloon", "blue", "hilltop", "{K} bright balloons are bobbing up and down,", "{W} gave one to a friend. Now {m} around."),
    ("fish", "orange", "pond", "{K} little fish are swimming in a ring,", "One swam home for a nap. Now {m}, we sing!"),
    ("block", "green", "playroom", "{K} wooden blocks are stacked up very tall,", "{W} put one on the shelf. Now {m} in all."),
    ("firefly", None, "night", "{K} glowing fireflies are blinking in the dark,", "One flew home to sleep. Now {m} make a spark."),
]


def countdown_rhyme(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    prop, col, env, l1, l2 = rng.choice(COUNTDOWNS)
    n = rng.choice([3, 4, 5])
    b = B(uni, env).enter(who)
    N, many = b.n(who), spoken_name(prop, 2)
    b.say("narrator", _v(rng, f"Count down with {N}! {cap(NUM[n])}, {NUM[n - 1]}, {NUM[n - 2]}...",
                         f"A counting-down rhyme with {N}. Ready?"), title=f"{cap(NUM[n])} Little {cap(many)}: Count Down With {N}",
          act={who: "clap"}, fx="notes")
    for k in range(n, 0, -1):
        b.clear().show(prop, col, k)
        b.say(who, l1.format(K=cap(NUM[k])), act={who: "nod"}, number=k, fx="notes")
        b.clear()
        if k > 1:
            b.show(prop, col, k - 1)
        b.say(who, l2.format(m=NUM[k - 1] if k > 1 else "none", W=N), act={who: "dance"}, number=(k - 1, "blue"), fx="notes")
    b.say("narrator", f"{cap(', '.join(NUM[n:0:-1]))}, zero! We counted down from {NUM[n]}.", act={who: "cheer"}, fx="sparkle",
          end=uni["brand"]["end_card"])
    return Story("E", "countdown_rhyme", "sing_along", f"{cap(NUM[n])} Little {cap(many)}: Count Down With {N}",
                 f"An original counting-down rhyme: {N} counts {many} down from {NUM[n]} to zero.", f"Count backward from {NUM[n]} to zero.",
                 "song", [who], b.beats, ["counting down", "numbers", "rhyme", prop], {"prop": prop, "n": n, "who": who}, song=True)


def _couplet_song(rng, uni, *, fmt, verses: dict, k: int, title: str, intro: list[str], chorus: tuple[str, str], goal: str,
                  topics: list[str], word_color=None) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    picks = rng.sample(list(verses), k)
    first = verses[picks[0]]
    b = B(uni, first[1]).enter(who)
    N = b.n(who)
    b.say("narrator", rng.choice(intro).format(N=N), title=title, act={who: "clap"}, fx="notes")
    for p in picks:
        prop, env, col, l1, l2, a1, a2 = verses[p]
        b.go(env)
        if prop:
            b.show(prop, col)
        wc = word_color or (col if col in ("red", "orange", "yellow", "green", "blue", "purple", "pink") else "orange")
        b.say(who, l1, act={who: a1}, fx="notes", word=(p.upper(), wc))
        b.say(who, l2, act={who: a2}, fx="notes", word=(p.upper(), wc))
    b.clear()
    b.say(who, chorus[0], act={who: "dance"}, fx="notes")
    b.say(who, chorus[1], act={who: "cheer"}, fx="sparkle", end=uni["brand"]["end_card"])
    return Story("E", fmt, "sing_along", f"{title}: {cap(join_words(picks))}", f"An original rhyme with {N}: {join_words(picks)}.", goal,
                 "song", [who], b.beats, topics + picks, {"picks": sorted(picks), "who": who}, song=True)


WEATHER_VERSES = {  # name: (prop, env, color, line, line, action, action)
    "sunshine": ("sun", "meadow", None, "Sunshine, sunshine, warm and bright,", "Filling the meadow with golden light!", "stretch", "cheer"),
    "rain": ("raindrop", "rainy", None, "Raindrops falling, drip, drip, drop,", "Watering the flowers, plip, plip, plop!", "nod", "hop"),
    "wind": ("kite", "hilltop", "red", "Windy, windy, whoosh, whoosh, whoosh,", "The wind gives my kite a gentle push!", "dance", "cheer"),
    "snow": ("snowflake", "meadow", None, "Snowflakes falling, soft and white,", "Dancing down from morning to night.", "nod", "dance"),
    "clouds": ("cloud", "meadow", None, "Fluffy clouds go floating by,", "Like woolly sheep up in the sky!", "nod", "stretch"),
    "rainbow": ("rainbow", "meadow", None, "Rain and sun, together they play,", "And paint a rainbow across the day!", "nod", "cheer"),
    "fog": ("cloud", "forest", "#EEF2F6", "Foggy, foggy, soft and gray,", "Where did all the trees go today?", "nod", "dance"),
}
SHAPE_VERSES = {
    "circle": ("circle", "playroom", "red", "Circle, circle, round and round,", "Like a ball that bounces on the ground!", "nod", "hop"),
    "square": ("square", "playroom", "blue", "Square, square, four sides the same,", "Like a block in a building game!", "nod", "clap"),
    "triangle": ("triangle", "playroom", "green", "Triangle, triangle, one, two, three,", "Three sides, three corners, count with me!", "nod",
                 "clap"),
    "rectangle": ("rectangle", "playroom", "orange", "Rectangle, rectangle, long and neat,", "Two long sides and two short. How sweet!",
                  "stretch", "dance"),
    "star": ("star", "night", "yellow", "Star, star, with five points bright,", "Shining in the sky at night!", "stretch", "cheer"),
    "heart": ("heart", "garden", "pink", "Heart, heart, a shape we share,", "Draw a heart to show you care!", "nod", "dance"),
    "oval": ("oval", "garden", "purple", "Oval, oval, long and round,", "Like an egg the hen just found!", "nod", "hop"),
    "diamond": ("diamond", "hilltop", "pink", "Diamond, diamond, like a kite,", "Pointy top and flying bright!", "stretch", "cheer"),
}
FOOD_VERSES = {
    "apple": ("apple", "garden", None, "Crunch, crunch, a crunchy apple treat,", "Red and shiny, juicy and sweet!", "nod", "dance"),
    "banana": ("banana", "garden", None, "Peel a banana, one, two, three,", "Soft and yellow, yum for me!", "clap", "dance"),
    "orange": ("orange", "garden", None, "Orange, orange, juicy and bright,", "Peel it slowly, take a bite!", "nod", "cheer"),
    "strawberry": ("strawberry", "garden", None, "Little strawberry, red and sweet,", "Seeds on the outside, what a treat!", "nod", "hop"),
    "grapes": ("grapes", "garden", None, "Grapes, grapes, in a bunch,", "Purple and round, a yummy lunch!", "clap", "dance"),
    "pear": ("pear", "garden", None, "Green pear, green pear, shaped like a bell,", "Juicy and sweet, I like it well!", "nod", "dance"),
    "carrot": ("carrot", "garden", None, "Crunchy carrot, orange and long,", "Munch, munch, munch, it helps me grow strong!", "nod", "cheer"),
}
BODY_VERSES = {
    "nose": (None, "playroom", None, "Point to your nose, your nose, your nose,", "Sniff, sniff, sniff, that's how it goes!", "nod", "nod"),
    "ears": (None, "playroom", None, "Touch your ears, one and two,", "Ears are for listening, it's true!", "nod", "clap"),
    "tummy": (None, "playroom", None, "Pat your tummy, round and round,", "Pat, pat, pat, a gentle sound!", "nod", "dance"),
    "hands": (None, "meadow", None, "Clap your hands, clap, clap, clap,", "Then rest them softly in your lap.", "clap", "nod"),
    "feet": (None, "meadow", None, "Tap your feet upon the floor,", "Tap, tap, tap, and then once more!", "hop", "hop"),
    "shoulders": (None, "playroom", None, "Lift your shoulders up so high,", "Then drop them down and give a sigh.", "stretch", "nod"),
    "cheeks": (None, "meadow", None, "Puff your cheeks up, big and round,", "Pop! Let the air out, what a sound!", "nod", "cheer"),
    "knees": (None, "hilltop", None, "Bend your knees and bounce, bounce, bounce,", "Every little bounce, it counts!", "hop", "hop"),
    "arms": (None, "hilltop", None, "Stretch your arms out like a tree,", "Sway in the breeze, one, two, three!", "stretch", "dance"),
    "chin": (None, "playroom", None, "Tap your chin and say hello,", "Chin goes up, and chin goes low.", "nod", "nod"),
}


def weather_rhyme(rng, uni) -> Story:
    return _couplet_song(rng, uni, fmt="weather_rhyme", verses=WEATHER_VERSES, k=3, title="The Weather Rhyme",
                         intro=["Sun or rain? Sing the weather rhyme with {N}!", "{N} sings about the weather. Sing along!"],
                         chorus=("Sun or rain or wind or snow,", "We love the weather, high and low!"),
                         goal="Weather words in an original rhyme.", topics=["weather song", "weather", "rhyme"], word_color="blue")


def shape_rhyme(rng, uni) -> Story:
    return _couplet_song(rng, uni, fmt="shape_rhyme", verses=SHAPE_VERSES, k=4, title="The Shape Rhyme",
                         intro=["Sing the shape rhyme with {N}!", "Shapes are everywhere! {N} has a rhyme about them."],
                         chorus=("Shapes, shapes, all around,", "Look and see what shapes you found!"),
                         goal="Shape names and features in an original rhyme.", topics=["shape song", "shapes", "rhyme"])


def fruit_rhyme(rng, uni) -> Story:
    return _couplet_song(rng, uni, fmt="fruit_rhyme", verses=FOOD_VERSES, k=4, title="The Yummy Fruit Rhyme",
                         intro=["Snack time! Sing the yummy fruit rhyme with {N}.", "{N} loves fruits and veggies. Sing along!"],
                         chorus=("Fruits and veggies, yum, yum, yum,", "Healthy snacks for every tum!"),
                         goal="Names of fruits and vegetables in an original rhyme.", topics=["food song", "fruits", "rhyme"], word_color="green")


def body_rhyme(rng, uni) -> Story:
    return _couplet_song(rng, uni, fmt="body_rhyme", verses=BODY_VERSES, k=4, title="The Wiggle and Touch Rhyme",
                         intro=["Stand up and move with {N}! Ready?", "{N} has a wiggle and touch rhyme. Do it too!"],
                         chorus=("Wiggle, touch and tap and sway,", "Our bodies love to move and play!"),
                         goal="Naming body parts while moving to an original rhyme.", topics=["action song", "body parts", "rhyme"],
                         word_color="pink")


# ------------------------------------------------------------------ F: bedtime -------
ANIMAL_NIGHTS = [  # prop, color, line
    ("bird", "blue", "The little bird tucks its head and sleeps in the tree."),
    ("cow", None, "The cow lies down in the soft, sweet hay."),
    ("sheep", None, "The sheep huddle close together, warm and woolly."),
    ("pig", None, "The pig snuggles into the warm straw."),
    ("fish", "orange", "The fish rest quietly near the bottom of the pond."),
    ("bee", None, "The bees rest inside their cozy hive."),
    ("ladybug", None, "The ladybug rests under a leaf."),
    ("snail", None, "The snail tucks itself into its shell."),
    ("butterfly", "purple", "The butterfly rests on a flower, wings folded."),
    ("frog", None, "The frog settles down beside the pond."),
    ("chick", None, "The chick snuggles under its mother's wing."),
    ("turtle", None, "The turtle pulls its head into its shell."),
]


def goodnight_animals(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    picks = rng.sample(ANIMAL_NIGHTS, 4)
    owl = rng.random() < 0.5
    b = B(uni, "night").enter(who)
    N = b.n(who)
    b.say("narrator", _v(rng, f"Night is here. {N} says goodnight to the meadow animals.",
                         f"The stars are out. Who is going to sleep? {N} goes to see."), title="Goodnight, Meadow Animals",
          act={who: "sleepy"}, sfx=["twinkle"])
    for prop, col, line in picks:
        b.clear().show(prop, col)
        b.say("narrator", line, act={who: "sleepy"})
        b.say(who, _v(rng, f"Goodnight, little {spoken_name(prop)}.", f"Sleep well, {spoken_name(prop)}.", f"Shh. Goodnight, {spoken_name(prop)}."),
              act={who: "nod"})
    b.clear()
    if owl:
        b.show("owl")
        b.say("narrator", "But the owl is just waking up. Owls are awake at night.", act={who: "nod"})
        b.say(who, "Good morning, owl! And goodnight, everyone.", act={who: "yawn"})
        b.clear()
    b.say("narrator", f"Now {N} curls up too. Goodnight, everyone.", act={who: "sleep"}, fx="zzz", end=NIGHT_END)
    names = [spoken_name(p[0]) for p in picks]
    return Story("F", "goodnight_animals", "sleepy_time", f"Goodnight, Meadow Animals: {cap(join_words(names))}",
                 f"A calm bedtime story: {N} says goodnight to the {join_words(names)} as each one settles down to sleep.",
                 "Animals rest at night too; a calm goodnight ritual.", "calm", [who], b.beats, ["bedtime story", "animals", "goodnight", "sleep"],
                 {"picks": sorted(p[0] for p in picks), "owl": owl, "who": who})


RELAX = [  # order, part, instruction
    (0, "toes", "Wiggle your toes. Wiggle, wiggle. Now let them rest."),
    (1, "feet", "Point your feet, then let them flop. So floppy."),
    (2, "legs", "Make your legs long and straight. Now let them go soft."),
    (3, "tummy", "Put a hand on your tummy. Breathe in, and out."),
    (4, "hands", "Squeeze your hands tight. Now open them slowly."),
    (5, "arms", "Stretch your arms up high. Now let them float down."),
    (6, "shoulders", "Lift your shoulders up to your ears. Now let them drop."),
    (7, "face", "Make a big smile. Now let your face go soft."),
]


def sleepy_body(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    steps = sorted(rng.sample(RELAX, 4))
    env = rng.choice(["bedroom", "night"])
    b = B(uni, env).enter(who)
    N = b.n(who)
    b.put("pillow", "ground", x=840, size=60, front=True)
    b.say("narrator", _v(rng, f"Let's get our bodies sleepy with {N}. Slow and soft.", f"{N} is getting ready to sleep. Let's relax, too."),
          title=f"Sleepy Body With {N}", act={who: "yawn"})
    for _, part, line in steps:
        b.say("narrator", line, act={who: "stretch"}, word=(part.upper(), "purple"))
        b.say(who, _v(rng, f"Ahh. My {part} feel sleepy now." if part not in ("tummy", "face") else f"Ahh. My {part} feels sleepy now.",
                      f"So soft and heavy. Goodnight, {part}.", f"Mmm. Cozy {part}."), act={who: "sleepy"})
    b.say("narrator", "Now close your eyes, slow and gentle.", act={who: "sleepy"}, word=("EYES", "purple"))
    b.say("narrator", f"Goodnight, {N}. Goodnight, sleepy body.", act={who: "sleep"}, fx="zzz", end=NIGHT_END)
    parts = [s[1] for s in steps]
    return Story("F", "sleepy_body", "sleepy_time", f"Sleepy Body With {N}: {cap(join_words(parts))}",
                 f"A calm wind-down: {N} relaxes the {join_words(parts)}, one at a time, then closes both eyes.",
                 "Relaxing the body, one part at a time, to get ready for sleep.", "calm", [who], b.beats,
                 ["bedtime", "relaxation", "calm", "body parts"] + parts, {"parts": parts, "env": env, "who": who})


QUIET_SOUNDS = [  # prop, color, env, line
    ("clock", "blue", "bedroom", "Tick, tock, goes the clock on the wall."),
    ("owl", None, "night", "Hoo, hoo, calls an owl in a tree."),
    ("raindrop", None, "bedroom", "Pitter, patter, rain taps softly on the window."),
    ("leaf", None, "night", "Whoosh, whispers the wind in the leaves."),
    ("frog", None, "night", "Ribbit, ribbit, sing the frogs by the pond."),
    ("book", "green", "bedroom", "Swish, a page turns in a bedtime book."),
    ("moon", None, "night", "The moon makes no sound at all."),
    ("pillow", None, "bedroom", "Fluff, fluff, goes the soft pillow."),
    ("quilt", None, "bedroom", "Rustle, rustle, the quilt tucks in."),
    ("teddy", None, "bedroom", "Shh. Even Teddy is quiet now."),
]


def quiet_sounds(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    picks = rng.sample(QUIET_SOUNDS, 4)
    b = B(uni, picks[0][2]).enter(who)
    N = b.n(who)
    b.say("narrator", _v(rng, f"It is quiet time. {N} listens for soft night sounds.", f"Shh. Let's listen to the quiet night with {N}."),
          title=f"{N} Listens to Quiet Night Sounds", act={who: "sleepy"}, sfx=["twinkle"])
    for prop, col, env, line in picks:
        b.go(env).show(prop, col)
        b.say("narrator", line, act={who: "nod"})
        b.say(who, _v(rng, "I hear it. So soft.", f"Mmm. {cap(spoken_name(prop))}, goodnight.", "Shh. Soft and slow."), act={who: "sleepy"})
    b.clear()
    b.say("narrator", f"Soft sounds, slow breaths. {N}'s eyes are getting heavy.", act={who: "yawn"})
    b.say("narrator", f"Goodnight, {N}. Sleep tight.", act={who: "sleep"}, fx="zzz", end=NIGHT_END)
    names = [spoken_name(p[0]) for p in picks]
    return Story("F", "quiet_sounds", "sleepy_time", f"{N} Listens to Quiet Night Sounds",
                 f"A calm bedtime story: {N} listens to quiet sounds ({join_words(names)}) and drifts off to sleep.",
                 "Listening to quiet sounds to calm down for sleep.", "calm", [who], b.beats, ["bedtime story", "listening", "calm", "sleep"],
                 {"picks": sorted(p[0] for p in picks), "who": who})


GOOD_THINGS = [  # prop, color, line ({F} = the friend)
    ("kite", "blue", "I flew my kite on the hilltop."), ("apple", None, "I ate a crunchy apple."),
    ("book", "green", "{F} read me a story."), ("flower", "pink", "I smelled a pink flower."),
    ("ball", "red", "I played ball with {F}."), ("boot", "yellow", "I splashed in a puddle in my boots."),
    ("butterfly", "purple", "I saw a purple butterfly."), ("block", "blue", "I built a tall tower."),
    ("drum", None, "I played the drum. Boom, boom!"), ("bubbles", None, "I blew big, round bubbles."),
    ("sprout", None, "I watered our little sprout."), ("strawberry", None, "I picked a sweet strawberry."),
    ("rainbow", None, "I saw a rainbow after the rain."), ("teddy", None, "I gave Teddy a big hug."),
    ("cupcake", None, "I shared a cupcake with {F}."), ("shell", None, "I found a pretty shell."),
    ("bird", "blue", "I heard a bird singing."), ("xylophone", None, "I played a song on the xylophone."),
]
GOOD_REPLY = ["That sounds lovely.", "I liked that too.", "What a happy thing.", "Mmm. That was fun.", "I am glad."]


def three_good_things(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    picks = rng.sample(GOOD_THINGS, 3)
    replies = rng.sample(GOOD_REPLY, 3)
    b = B(uni, "bedroom").enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"It is bedtime. {X} and {Y} think about their day.", f"The lamp is low. {X} and {Y} remember today."),
          title=f"{X}'s Three Happy Things", act={x: "sleepy", y: "sleepy"})
    b.say(y, _v(rng, f"{X}, what made you happy today?", f"Tell me three happy things, {X}.", f"What was good today, {X}?"),
          act={y: "nod", x: "sleepy"})
    for i, ((prop, col, line), reply) in enumerate(zip(picks, replies)):
        b.clear().show(prop, col)
        b.say(x, line.format(F=Y), act={x: "nod", y: "sleepy"}, number=(i + 1, "purple"))
        b.say(y, reply, act={y: "nod", x: "sleepy"})
    b.clear()
    b.say("narrator", _v(rng, "Thinking of happy things helps us feel calm and cozy.", "Three happy things. A thankful heart is a sleepy heart."),
          act={x: "yawn", y: "yawn"})
    b.say(x, _v(rng, "Thank you, today. Goodnight.", f"Goodnight, {Y}. Goodnight, today."), act={x: "sleep", y: "sleep"}, fx="zzz", end=NIGHT_END)
    return Story("F", "three_good_things", "sleepy_time", f"{X}'s Three Happy Things: A Bedtime Story",
                 f"At bedtime, {X} tells {Y} three happy things from the day, then falls asleep.",
                 "Remembering happy moments to feel calm and thankful at bedtime.", "calm", [x, y], b.beats,
                 ["bedtime story", "gratitude", "feelings", "calm"], {"picks": sorted(p[0] for p in picks), "x": x, "y": y})


DREAMS = [  # prop, color, env, line, follow
    ("boat", "blue", "night", "Imagine a little boat on a calm, still pond.", "It rocks gently, back and forth."),
    ("cloud", None, "night", "Imagine floating on a soft, fluffy cloud.", "So light, so slow, so cozy."),
    ("flower", "purple", "night", "Imagine a garden where the flowers are closing up.", "Every petal folds in, sleepy and still."),
    ("sheep", None, "night", "Imagine woolly sheep, walking slowly over a hill.", "One... and two... and three."),
    ("nest", None, "night", "Imagine a cozy nest, high in a quiet tree.", "Warm and safe, under the stars."),
    ("moon", None, "night", "Imagine the moon, round and soft like a pillow.", "Its gentle light shines on the meadow."),
    ("firefly", None, "night", "Imagine fireflies glowing, blink, blink, in the grass.", "Little lights, slow and soft."),
    ("quilt", None, "bedroom", "Imagine a big quilt, covered in stars.", "It wraps you up, warm and snug."),
    ("feather", "purple", "night", "Imagine a feather, drifting down, down, down.", "It lands softly on the grass."),
    ("star", "yellow", "night", "Imagine one star, twinkling just for you.", "Twinkle... twinkle... slow and bright."),
    ("turtle", None, "night", "Imagine a turtle, taking slow, sleepy steps.", "Slow... and slow... all the way home."),
    ("shell", None, "night", "Imagine listening to a shell. Whoosh, like soft waves.", "In, and out. In, and out."),
]


def imagine_journey(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    picks = rng.sample(DREAMS, 3)
    b = B(uni, "bedroom").enter(who)
    N = b.n(who)
    b.say("narrator", _v(rng, f"{N} is tucked in. Let's imagine something calm together.", f"Close your eyes with {N}. Let's imagine."),
          title=f"Imagine With {N}: A Calm Bedtime Journey", act={who: "sleepy"})
    for prop, col, env, line, follow in picks:
        b.go(env).show(prop, col)
        b.say("narrator", line, act={who: "sleepy"})
        b.say("narrator", follow, act={who: "nod"})
    b.go("bedroom")
    b.say(who, _v(rng, "Mmm. That was so calm.", "I feel so cozy now.", "Thank you. I am sleepy."), act={who: "yawn"})
    b.say("narrator", f"Sweet dreams, {N}. Goodnight.", act={who: "sleep"}, fx="zzz", end=NIGHT_END)
    names = [spoken_name(p[0]) for p in picks]
    return Story("F", "imagine_journey", "sleepy_time", f"Imagine With {N}: A Calm Bedtime Journey",
                 f"A calm bedtime imagination journey: {N} imagines {join_words([an(n) for n in names])}, then falls asleep.",
                 "Using calm imagination to settle down for sleep.", "calm", [who], b.beats, ["bedtime story", "imagination", "calm", "sleep"],
                 {"picks": sorted(p[0] for p in picks), "who": who})


TOYS = [  # prop, color, line
    ("teddy", None, "Teddy gets a soft pillow."), ("drum", None, "The drum is quiet now. No more booms."),
    ("ball", "red", "The ball rolls into the toy basket."), ("book", "green", "The book closes. The story is done."),
    ("boat", "orange", "The little boat rests on the shelf."), ("kite", "purple", "The kite folds up its tail."),
    ("block", "blue", "The blocks stack up in a quiet pile."), ("bell", None, "The bell stops ringing. Shh."),
    ("xylophone", None, "The xylophone plays one last, soft note."), ("yarn", "pink", "The yarn ball curls up small."),
    ("bucket", "yellow", "The bucket sits by the door, ready for tomorrow."),
]


def toys_goodnight(rng, uni) -> Story:
    who = _pick_cast(rng, uni, 1)[0]
    n = rng.choice([3, 4])
    picks = rng.sample(TOYS, n)
    b = B(uni, "bedroom").enter(who)
    N = b.n(who)
    for i, (prop, col, _) in enumerate(picks):
        b.put(prop, "ground", x=230 + i * (620 / max(1, n - 1)), size=50, color=col, front=True)
    b.say("narrator", _v(rng, f"It is bedtime, but {N}'s toys are still awake!", f"Before bed, {N} tucks in the toys."),
          title=f"{N} Puts the Toys to Bed", act={who: "nod"}, number=(n, "purple"))
    for i, (prop, col, line) in enumerate(picks):
        b.say(who, f"Goodnight, {spoken_name(prop)}.", act={who: "nod"})
        b.drop(prop)
        left = n - i - 1
        b.say("narrator", f"{line} {cap(NUM[left])} still awake." if left else f"{line} All the toys are asleep.", act={who: "sleepy"},
              number=(left, "purple"))
    b.say("narrator", f"Now it is {N}'s turn. Snuggle in, nice and warm.", act={who: "yawn"})
    b.say("narrator", f"Goodnight, {N}. Goodnight, toys.", act={who: "sleep"}, fx="zzz", end=NIGHT_END)
    names = [spoken_name(p[0]) for p in picks]
    return Story("F", "toys_goodnight", "sleepy_time", f"{N} Puts the Toys to Bed",
                 f"A calm bedtime story: {N} says goodnight to the {join_words(names)}, counting down until all are asleep.",
                 "A calm goodnight routine; counting down.", "calm", [who], b.beats, ["bedtime story", "toys", "counting down", "sleep"],
                 {"picks": sorted(p[0] for p in picks), "who": who})


# ------------------------------------------------------------------ G: letters & early learning
PATTERN_KINDS = {"AB": ("AB", 4), "AAB": ("AAB", 5), "ABB": ("ABB", 5), "ABC": ("ABC", 5)}
PATTERN_PROPS = ["balloon", "star", "heart", "circle", "block", "flower", "fish", "ball"]
PATTERN_PAIRS = [("apple", "banana"), ("star", "moon"), ("sun", "cloud"), ("leaf", "flower"), ("fish", "boat"), ("bee", "flower"),
                 ("strawberry", "pear"), ("shoe", "sock"), ("cup", "spoon"), ("bird", "nest"), ("frog", "snail"), ("acorn", "leaf")]
PATTERN_TRIPLES = [("apple", "banana", "orange"), ("circle", "square", "triangle"), ("sun", "moon", "star"), ("cow", "pig", "sheep")]


def _pattern(rng, colors: bool):
    kind = rng.choice(list(PATTERN_KINDS))
    seq_kind, shown = PATTERN_KINDS[kind]
    k = len(set(seq_kind))
    if colors:
        prop = rng.choice(PATTERN_PROPS)
        cols = rng.sample(["red", "blue", "yellow", "green", "purple", "orange", "pink"], k)
        elems = [(prop, c, c) for c in cols]
    elif k == 3:
        elems = [(p, None, spoken_name(p)) for p in rng.choice(PATTERN_TRIPLES)]
    else:
        pair = list(rng.choice(PATTERN_PAIRS))
        rng.shuffle(pair)
        elems = [(p, None, spoken_name(p)) for p in pair]
    letters = "ABC"
    seq = [elems[letters.index(seq_kind[i % len(seq_kind)])] for i in range(shown + 1)]
    return kind, seq


def what_comes_next(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    rounds = [_pattern(rng, True), _pattern(rng, False)]
    rng.shuffle(rounds)
    b = B(uni, rng.choice(["playroom", "meadow", "garden"])).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"{X} is making patterns. Can {Y} find what comes next?", f"Patterns repeat, again and again. Let's play with {X}!"),
          title="What Comes Next? Pattern Fun", act={x: "clap", y: "nod"})
    for i, (kind, seq) in enumerate(rounds):
        a, o = _cycle_pair([x, y], i)
        b.clear()
        for p, c, _ in seq[:-1]:
            b.show(p, c)
        names = [w for _, _, w in seq[:-1]]
        b.say(a, f"{cap(', '.join(names))}...", act={a: "nod", o: "nod"})
        b.say(a, _v(rng, f"What comes next, {b.n(o)}?", "What comes next?", "Can you guess what comes next?"), act={a: "nod", o: "think"},
              word=("?", "purple"))
        nxt = seq[-1]
        b.show(nxt[0], nxt[1])
        b.say(o, _v(rng, f"{cap(nxt[2])}! The pattern repeats.", f"I know! {cap(nxt[2])} comes next.", f"{cap(nxt[2])}!"),
              act={o: "cheer", a: "clap"}, word=(nxt[2].upper(), nxt[1] or "green"), sfx=["chime"])
    b.clear()
    b.say("narrator", _v(rng, "A pattern repeats in the same order. You can find patterns everywhere!",
                         "Same order, again and again. That is a pattern!"), act={x: "dance", y: "dance"}, fx="sparkle")
    b.say(y, _v(rng, "Can you make a pattern with your toys?", "What pattern can you find today?"), act={y: "wave"},
          end=uni["brand"]["end_card"])
    return Story("G", "what_comes_next", "letter_day", f"What Comes Next? Pattern Fun With {X} and {Y}",
                 f"{X} and {Y} read two patterns aloud and guess what comes next.", "Recognize and continue simple repeating patterns.",
                 "bright", [x, y], b.beats, ["patterns", "early math", "what comes next"],
                 {"rounds": sorted(f"{k}:" + ",".join(f"{p}{c}" for p, c, _ in s) for k, s in rounds), "x": x, "y": y})


def _initial(word: str) -> str:
    return spoken_name(word)[0].upper()


def starts_with(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    letters = rng.sample([k for k in LETTERS if len(LETTERS[k]) >= 1], 3)
    rounds = []
    pool = [w for ws in LETTERS.values() for w in ws]
    for L in letters:
        target = rng.choice(LETTERS[L])
        others = rng.sample([w for w in pool if _initial(w) != L], 2)
        opts = [target] + others
        rng.shuffle(opts)
        rounds.append((L, target, opts))
    b = B(uni, rng.choice(["playroom", "meadow", "garden"])).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"Letter hunt! {X} and {Y} listen for the first sound.", f"Three things, one letter. Which one starts with it?"),
          title="Which One Starts With the Letter?", act={x: "clap", y: "clap"})
    for i, (L, target, opts) in enumerate(rounds):
        a, o = _cycle_pair([x, y], i)
        b.clear()
        for w in opts:
            b.show(w, "red" if w in TINTABLE else None)
        b.say(a, _v(rng, f"Which one starts with {L}?", f"{b.n(o)}, which one starts with {L}?"), act={a: "nod", o: "think"},
              letter=f"{L} {L.lower()}")
        b.say(o, f"{cap(join_words([spoken_name(w) for w in opts]))}. Hmm...", act={o: "nod"})
        b.clear().show(target, "red" if target in TINTABLE else None, size=140)
        b.say(o, f"{cap(spoken_name(target))}! {cap(spoken_name(target))} starts with {L}.", act={o: "cheer", a: "clap"},
              word=(cap(spoken_name(target)), "purple"), sfx=["chime"])
    b.clear()
    b.say("narrator", f"{', '.join(letters)}. Every word starts with a letter sound.", act={x: "dance", y: "dance"}, fx="sparkle")
    b.say(x, _v(rng, f"What else starts with {letters[0]}?", "What letter does your favorite toy start with?"), act={x: "wave"},
          end=uni["brand"]["end_card"])
    return Story("G", "starts_with", "letter_day", f"Which One Starts With {letters[0]}? A Letter Hunt",
                 f"{X} and {Y} find which object starts with {join_words(letters)}.", "Hear and match the first letter of a word.", "bright",
                 [x, y], b.beats, ["alphabet", "phonics", "letters"] + [f"letter {L}" for L in letters],
                 {"rounds": sorted(f"{L}:{t}:" + ",".join(sorted(o)) for L, t, o in rounds), "x": x, "y": y})


RHYMES = [("moon", "spoon"), ("sock", "rock"), ("clock", "sock"), ("rock", "clock"), ("bed", "bread"), ("star", "jar"), ("bell", "shell"),
          ("bee", "tree"), ("bee", "key"), ("tree", "key"), ("owl", "towel")]


def rhyme_time(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    yes = rng.sample(RHYMES, 2)
    used = {w for p in yes for w in p}
    a0 = rng.choice([w for w in ("drum", "kite", "fish", "apple", "frog", "boat", "ball", "hat", "pig", "cow") if w not in used])
    b0 = rng.choice([w for w in ("moon", "sock", "bed", "star", "bell", "bee") if w not in used])
    rounds = [(yes[0], True), (yes[1], True), ((a0, b0), False)]
    rng.shuffle(rounds)
    b = B(uni, rng.choice(["playroom", "meadow", "garden"])).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"Rhyme time! Words that rhyme end with the same sound.", f"{X} and {Y} are listening for rhymes."),
          title=f"Rhyme Time With {X} and {Y}", act={x: "clap", y: "clap"})
    for i, ((w1, w2), rhymes) in enumerate(rounds):
        a, o = _cycle_pair([x, y], i)
        b.clear().show(w1, "red" if w1 in TINTABLE else None).show(w2, "blue" if w2 in TINTABLE else None)
        b.say(a, f"{cap(spoken_name(w1))}, {spoken_name(w2)}. Do they rhyme?", act={a: "nod", o: "think"})
        if rhymes:
            b.say(o, _v(rng, f"Yes! {cap(spoken_name(w1))} and {spoken_name(w2)} rhyme!", f"{cap(spoken_name(w1))}, {spoken_name(w2)}. They rhyme!"),
                  act={o: "cheer", a: "clap"}, word=("RHYME!", "green"), sfx=["chime"])
        else:
            b.say(o, _v(rng, f"No. {cap(spoken_name(w1))} and {spoken_name(w2)} do not rhyme.", "Hmm, no. They sound different at the end."),
                  act={o: "nod", a: "nod"}, word=("NO RHYME", "orange"))
    b.clear()
    good = [f"{spoken_name(p[0][0])} and {spoken_name(p[0][1])}" for p in rounds if p[1]]
    b.say("narrator", f"{cap(good[0])}. {cap(good[1])}. Rhymes are fun to say!", act={x: "dance", y: "dance"}, fx="sparkle")
    b.say(y, _v(rng, f"Can you think of a word that rhymes with {spoken_name(yes[0][0])}?", "What words can you rhyme today?"),
          act={y: "wave"}, end=uni["brand"]["end_card"])
    return Story("G", "rhyme_time", "letter_day", f"Rhyme Time With {X} and {Y}: {cap(spoken_name(yes[0][0]))} and {cap(spoken_name(yes[0][1]))}",
                 f"{X} and {Y} listen to pairs of words and decide whether they rhyme: {'; '.join(good)}.",
                 "Hear when two words rhyme (end with the same sound).", "bright", [x, y], b.beats, ["rhyming words", "phonics", "early reading"],
                 {"yes": sorted("-".join(p) for p in yes), "no": f"{a0}-{b0}", "x": x, "y": y})


def alphabet_walk(rng, uni) -> Story:
    x, y = _pick_cast(rng, uni, 2)
    order = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    start = rng.randrange(0, 23)
    run = order[start:start + 4]
    words = [rng.choice(LETTERS[L]) for L in run]
    b = B(uni, rng.choice(["meadow", "garden", "playroom"])).enter(x, y)
    X, Y = b.n(x), b.n(y)
    b.say("narrator", _v(rng, f"{X} and {Y} walk through the alphabet, from {run[0]} to {run[-1]}.",
                         f"Alphabet walk! Today {X} and {Y} go from {run[0]} to {run[-1]}."), title=f"Alphabet Walk: {run[0]} to {run[-1]}",
          act={x: "hop", y: "hop"}, letter=f"{run[0]} to {run[-1]}")
    for i, (L, w) in enumerate(zip(run, words)):
        a, o = _cycle_pair([x, y], i)
        if i:
            b.say(o, f"What comes after {run[i - 1]}?", act={o: "think", a: "nod"}, letter=f"{run[i - 1]} ?")
        b.clear().show(w, "red" if w in TINTABLE else None, size=140)
        b.say(a, f"{L}! {L} is for {spoken_name(w)}.", act={a: "cheer", o: "clap"}, letter=f"{L} {L.lower()}", sub=spoken_name(w))
    b.clear()
    b.say("narrator", f"{', '.join(run)}. {cap(join_words([spoken_name(w) for w in words]))}!", act={x: "dance", y: "dance"}, fx="sparkle")
    b.say(x, _v(rng, f"What comes after {run[-1]}?" if run[-1] != "Z" else "Z is the last letter. Can you sing the ABC?",
                "Which letter is your favorite?"), act={x: "wave"}, end=uni["brand"]["end_card"])
    return Story("G", "alphabet_walk", "letter_day", f"Alphabet Walk: {run[0]} to {run[-1]} With {X} and {Y}",
                 f"{X} and {Y} walk through the letters {', '.join(run)}: {join_words([spoken_name(w) for w in words])}.",
                 f"Letter order from {run[0]} to {run[-1]}; a word for each letter.", "bright", [x, y], b.beats,
                 ["alphabet", "abc", "letter order"] + [f"letter {L}" for L in run], {"run": run, "words": words, "x": x, "y": y})


FORMATS["B"].extend([animal_riddles, animal_babies, who_eats_what, gentle_with_animals, move_like_animals])
FORMATS["E"].extend([animal_rhyme, call_and_response, countdown_rhyme, weather_rhyme, shape_rhyme, fruit_rhyme, body_rhyme])
FORMATS["F"].extend([goodnight_animals, sleepy_body, quiet_sounds, three_good_things, imagine_journey, toys_goodnight])
FORMATS["G"].extend([what_comes_next, starts_with, rhyme_time, alphabet_walk])
FORMATS["H"].extend([guess_the_sound, five_senses, guess_the_season, life_cycle, which_one, where_from, weather_week, what_will_happen])
