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

from ..render.props import LETTERS, spoken_name

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
        actors = []
        for cid in self.cast:
            a = (act or {}).get(cid, "idle")
            actors.append({"id": cid, "action": a, "hold": self.state[cid].get("hold")})
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
