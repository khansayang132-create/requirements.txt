"""Invent an original cartoon universe and its five characters from a one-line concept and a seed.

Deterministic (same concept + seed = same universe), so a universe can always be rebuilt and checked. Names are made
from syllables and pass the originality check; colours come from harmonious, kid-friendly palettes; every character
gets a different body plan and signature accessory so silhouettes never repeat inside one cast.
"""

from __future__ import annotations

import hashlib
import random

from ..engine import ACCESSORIES, ENVIRONMENTS, SPECIES
from ..state import AnimationDesign, CharacterSpec, Identity, UniverseBible, VisualDesign
from .originality import check_name, check_words

ONSET = ["b", "d", "f", "g", "h", "j", "k", "l", "m", "n", "p", "r", "s", "t", "v", "w", "z", "ch", "sh", "fl", "pl", "tr", "gr", "br", "cl"]
VOWEL = ["a", "e", "i", "o", "u", "ee", "oo", "ai", "ay"]
CODA = ["", "", "", "n", "m", "l", "p", "b", "s", "x", "ble", "na", "lo", "py", "kin"]
WORLD_A = ["Lantern", "Pebble", "Clover", "Honey", "Puddle", "Velvet", "Maple", "Copper", "Cotton", "Juniper", "Marigold", "Thistle"]
WORLD_B = ["Hollow", "Glen", "Cove", "Bramble", "Ridge", "Nook", "Vale", "Burrow", "Landing", "Fields", "Grove", "Bend"]
PLACE_WORDS = {
    "meadow": ["Breezy Field", "Daisy Patch", "Sunny Field"], "garden": ["Petal Garden", "Bloom Beds", "Busy Garden"],
    "pond": ["Ripple Pond", "Lily Pond", "Glimmer Pond"], "hilltop": ["Windy Top", "Kite Hill", "Cloud Hill"],
    "forest": ["Whisper Woods", "Mossy Woods", "Pinecone Woods"], "rainy": ["Drizzle Lane", "Splash Path", "Puddle Path"],
    "playroom": ["Toy Corner", "Block Room", "Play Den"], "bathroom": ["Bubble Room", "Splash Room", "Soap Room"],
    "bedroom": ["Snooze Room", "Quilt Room", "Dream Room"], "night": ["Starry Slope", "Moon Field", "Firefly Field"],
}
PALETTES = [  # body, belly, inner_ear, accent, nose  — soft, high-value, never neon
    ("#F4A6A0", "#FFF1E8", "#FFD0C9", "#4FB3BF", "#E2686B"), ("#9FD8C2", "#F2FFF8", "#FFC6D9", "#F28C38", "#F27B8C"),
    ("#B7C4F7", "#F4F5FF", "#FFC2D6", "#F7C948", "#F28FAD"), ("#F7D774", "#FFF8DC", "#FFB8A8", "#6C8CE0", "#F08A5D"),
    ("#C9A27E", "#F6E7D6", "#F3B8A6", "#59A96A", "#7A4E36"), ("#D7B4F3", "#FBF2FF", "#FFC4E1", "#3FB5A6", "#E37BB1"),
    ("#8EC5E8", "#EEF8FF", "#FFC9D6", "#F2665F", "#F28C9B"), ("#F2B880", "#FFF4E6", "#FFD3B5", "#7C6BD6", "#E0745B"),
    ("#A8D672", "#F4FFE6", "#FFD2C2", "#E86A92", "#E07B5F"), ("#E8C4C4", "#FFF5F5", "#FFD6E0", "#5B9BD5", "#D9707D"),
]
PERSONALITY = [("curious", "asks big questions", "notices tiny things"), ("brave", "tries first", "cheers others on"),
               ("gentle", "careful with small creatures", "speaks softly"), ("funny", "makes silly faces", "laughs easily"),
               ("thoughtful", "likes a plan", "remembers everything"), ("bouncy", "never walks when a hop will do", "full of energy"),
               ("kind", "shares first", "spots when someone is sad"), ("creative", "builds and draws", "sees shapes in clouds"),
               ("patient", "waits for others", "good at slow jobs"), ("cheerful", "sings while working", "hums when nervous")]
WEAKNESS = ["rushes ahead", "gets shy with new friends", "worries about mistakes", "forgets to listen", "wants to win every game",
            "gets grumpy when hungry", "loses track of time", "is a little scared of the dark", "takes things too seriously"]
STRENGTH = ["good at finding lost things", "great at counting", "fast runner", "strong helper", "clever builder", "kind listener",
            "makes everyone laugh", "remembers songs", "brave explorer", "good at sharing"]
WALK = {"bunny": "springy toe-steps with an ear bounce", "cat": "light, careful paws and a swishing tail",
        "elephant": "slow, heavy-but-soft steps, trunk swaying", "duck": "waddle with a little side-to-side tilt",
        "bear": "rolling steps, big friendly arm swings"}
RUN = {"bunny": "bounding hops", "cat": "quick scamper, tail up", "elephant": "lumbering jog, ears flapping",
       "duck": "fast waddle with flapping wings", "bear": "galumphing run"}
KOKORO = ["af_bella", "af_sky", "am_adam", "bf_emma", "am_michael", "af_nicole", "bm_george", "af_sarah"]
ESPEAK = ["en-us+f1", "en-us+m3", "en-us+f4", "en-us+m1", "en-us+f5", "en-us+m2"]
THEMES = ["friendship", "funny adventure", "educational", "family", "emotional", "animal adventure", "moral lesson"]


def _rng(concept: str, seed: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{concept}|{seed}".encode()).hexdigest()[:16], 16))


SOFT_C = ["b", "d", "f", "h", "j", "k", "l", "m", "n", "p", "r", "s", "t", "v", "w", "z", "fl", "pl", "br", "gr", "sk"]
SOFT_V = ["a", "e", "i", "o", "u", "oo", "ee", "ai"]
MID_C = ["b", "d", "l", "m", "n", "p", "r", "t", "v", "z", "ll", "pp", "nn"]
END_V = ["o", "i", "a", "y", "u", "ee", "ie"]


def make_name(rng: random.Random, taken: set[str]) -> str:
    """Two light syllables (consonant-vowel, consonant-vowel): easy for a 3-year-old to say."""
    for _ in range(500):
        n = (rng.choice(SOFT_C) + rng.choice(SOFT_V) + rng.choice(MID_C) + rng.choice(END_V)).capitalize()
        if 4 <= len(n) <= 7 and n.lower() not in taken and not check_name(n):
            return n
    raise RuntimeError("could not find an original name")


def make_universe(concept: str, seed: str = "1", audience: str = "ages 3-6") -> UniverseBible:
    rng = _rng(concept, seed)
    for _ in range(50):
        title = f"{rng.choice(WORLD_A)} {rng.choice(WORLD_B)}"
        if not check_words(title) and not check_name(title.split()[0]):
            break
    uid = title.lower().replace(" ", "-")
    envs = rng.sample([e for e in ENVIRONMENTS if e not in ("bathroom",)], 6)
    places = {e: rng.choice(PLACE_WORDS[e]) for e in envs}
    species = rng.sample(list(SPECIES), 5)
    accessories = rng.sample(list(ACCESSORIES), 5)
    palettes = rng.sample(PALETTES, 5)
    traits = rng.sample(PERSONALITY, 5)
    taken: set[str] = set()
    kok = rng.sample(KOKORO, 5)
    chars: list[CharacterSpec] = []
    roles = ["lead", "best friend", "friend", "friend", "wise friend"]
    for i in range(5):
        name = make_name(rng, taken)
        taken.add(name.lower())
        sp, acc, pal, tr = species[i], accessories[i], palettes[i], traits[i]
        body, belly, inner, accent, nose = pal
        colors = {"body": body, "belly": belly, "inner_ear": inner, "accent": accent, "nose": nose}
        acc_word = {"scarf": "scarf", "bow": "hair bow", "bandana": "neckerchief", "boots": "rain boots", "overalls": "overalls"}[acc]
        age = rng.choice(["about 4", "about 5", "about 6"]) if i < 4 else "about 7, the oldest"
        catch = rng.choice(["Let's find out!", "One more try!", "Ooh, look!", "Together is better!", "Slow and steady!", "I have an idea!"])
        chars.append(CharacterSpec(
            character_id=name.lower(), name=name, role=roles[i],
            identity=Identity(species=sp, age_category=age, personality=[tr[0], tr[1], tr[2]],
                              background=f"{name} lives in {places[envs[i % len(envs)]]} in {title} and is {tr[0]} — {tr[1]}.",
                              strengths=rng.sample(STRENGTH, 2), weaknesses=[rng.choice(WEAKNESS)],
                              emotions=f"shows feelings openly; when {tr[0]} wins out, {name} {tr[2]}", catchphrase=catch),
            visual=VisualDesign(face="round, soft, big forehead, short snout", eyes="large glossy dark eyes with one white highlight, set wide and low",
                                proportions="head about half of total height, short limbs, round belly", surface=f"soft matte {sp} fur/feathers, no texture noise",
                                clothing=f"{acc_word} in accent colour {accent}", accessory=acc, palette=colors,
                                distinctive=f"{accent} {acc_word}; {belly} belly patch"),
            animation=AnimationDesign(walk=WALK[sp], run=RUN[sp], talk="small head bobs, mouth opens on stressed syllables",
                                      expressions=["happy", "wow", "sleepy", "sad", "thinking"],
                                      reactions=f"{'big jump' if tr[0] in ('bouncy', 'brave', 'funny') else 'small gasp and hands to cheeks'} when surprised",
                                      idle="gentle breathing sway, blinks every 3-4 s", signature_moves=[rng.choice(["double hop", "happy spin", "ear wiggle", "tail swish", "proud nod"]), "waves with both arms"]),
            voice={"kokoro": {"voice": kok[i], "speed": round(0.9 + 0.05 * rng.random(), 2), "pitch": 1.0},
                   "espeak": {"voice": ESPEAK[i % len(ESPEAK)], "rate": 135 + 3 * i, "pitch": 40 + 9 * i},
                   "elevenlabs": {"voice_id": "", "stability": 0.5}},
        ))
    for a in chars:
        others = [c for c in chars if c is not a]
        a.relationships = {others[0].character_id: "best friend", others[1].character_id: "neighbor", others[3].character_id: "learns from"}
    return UniverseBible(
        universe_id=uid, title=title, concept=concept, world=f"{title} is a small, safe valley of {', '.join(places.values())}.",
        tone="warm, gently funny, curious; calm pacing; never scary", audience=audience,
        world_rules=["Nobody is ever in real danger; problems are small and solvable.", "Friends talk about feelings and help each other.",
                     "Facts are true: weather, plants and animals behave as they do in real life.", "Everyone gets a turn to lead."],
        places=places, recurring_storylines=[f"{chars[0].name} learns something new each week", f"{chars[1].name} and {chars[2].name}'s friendly contests",
                                             f"{chars[4].name}'s nature walks"],
        episode_concepts=[f"{chars[0].name}'s lost {rng.choice(['kite', 'ball', 'hat'])}", "The day it rained on the picnic",
                          f"{chars[2].name} is too nervous to try", "Building something big together", "Sharing the last apple"],
        characters=chars, originality={"names_checked": [c.name for c in chars] + [title], "issues": []})


def engine_universe(u: UniverseBible) -> dict:
    """The same universe in the local engine's format (what the renderer, voices and audio read)."""
    return {
        "brand": {"universe": u.title, "channel_name": u.title, "end_card": f"See you next time in {u.title}!"},
        "narrator": {"id": "narrator", "name": "Storyteller",
                     "voice": {"kokoro": {"voice": "af_heart", "speed": 0.9, "pitch": 1.0}, "espeak": {"voice": "en-us+f2", "rate": 132, "pitch": 48}}},
        "characters": [{"id": c.character_id, "name": c.name, "species": c.visual.engine_body or c.identity.species, "role": c.role,
                        "colors": c.visual.palette, "clothing": {"accessory": c.visual.accessory, "color": c.visual.palette["accent"], "note": c.visual.clothing},
                        "facial_features": c.visual.eyes, "personality": c.identity.personality, "voice": c.voice,
                        "proportions": {"build": c.visual.proportions}, "catchphrase": c.identity.catchphrase,
                        "signature_moves": c.animation.signature_moves, "age_representation": c.identity.age_category} for c in u.characters],
    }
