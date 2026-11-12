"""Originality checks: generated names and titles must not match or nearly match well-known characters or shows.

This is a guard rail, not a legal clearance: a trademark search is still the owner's job before publishing.
"""

from __future__ import annotations

KNOWN = {
    # characters
    "mickey", "minnie", "donald", "goofy", "pluto", "daisy", "simba", "nala", "elsa", "anna", "olaf", "moana", "stitch", "woody", "buzz",
    "nemo", "dory", "shrek", "fiona", "peppa", "george", "bluey", "bingo", "elmo", "grover", "oscar", "ernie", "bert", "cookie",
    "tigger", "piglet", "eeyore", "pooh", "kanga", "roo", "pikachu", "eevee", "snoopy", "charlie", "garfield", "odie", "barney", "dora",
    "boots", "diego", "chase", "marshall", "skye", "rubble", "rocky", "zuma", "everest", "caillou", "arthur", "clifford", "curious",
    "paddington", "thomas", "percy", "gordon", "masha", "tom", "jerry", "bugs", "daffy", "tweety", "sylvester", "scooby", "shaggy",
    "spongebob", "patrick", "squidward", "sonic", "tails", "kirby", "mario", "luigi", "yoshi", "totoro", "hello", "kitty", "miffy",
    "pingu", "noddy", "postman", "pat", "fireman", "sam", "bob", "wendy", "teletubbies", "tinky", "winky", "dipsy", "laa", "po",
    "cocomelon", "jj", "baby", "shark", "pinkfong", "hogi", "blippi", "barbie", "ken", "kipper", "maisy", "wombles", "gruffalo",
    # this repo's own first universe, so a new universe is really new
    "bobo", "mimi", "toto", "zuzu", "lolo", "wonder", "meadow",
}
# brands and ordinary words that make poor or unkind names for a children's character
BLOCK = {"chex", "kix", "lego", "oreo", "nike", "pepsi", "coke", "tide", "bic", "rap", "pee", "poo", "poop", "butt", "fart", "dumb", "fat",
         "sex", "kill", "gun", "war", "hell", "damn", "bum", "nob", "tit", "fag", "cum", "pis", "piss", "shit", "crap", "dope", "weed",
         "booze", "beer", "rum", "gin", "vape", "lame", "ugly", "mad", "sad", "bad", "dead", "die", "sin", "tax", "bomb", "pump", "chin",
         "shin", "bean", "bun", "pin", "tin", "fan", "man", "van", "map", "nap", "tap", "mop", "pop", "top", "hop", "job", "rob", "bob"}


def distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def check_name(name: str) -> list[str]:
    n = name.lower()
    if n in BLOCK or any(n.startswith(b) and len(b) >= 4 for b in BLOCK):
        return [f"'{name}' is a brand or an ordinary/unsuitable word"]
    hits = [k for k in KNOWN if n == k or (len(n) >= 4 and len(k) >= 4 and distance(n, k) <= 1)]
    return [f"'{name}' is too close to the existing name '{h}'" for h in hits]


def check_words(text: str) -> list[str]:
    import re

    words = set(re.findall(r"[a-z]+", text.lower()))
    multi = {"hello kitty", "paw patrol", "peppa pig", "baby shark", "winnie the pooh", "sesame street", "toy story", "frozen"}
    hits = [w for w in multi if w in text.lower()]
    hits += [w for w in words & {"disney", "pixar", "cocomelon", "nickelodeon", "dreamworks", "pokemon", "bluey"}]
    return [f"mentions an existing property: '{h}'" for h in hits]
