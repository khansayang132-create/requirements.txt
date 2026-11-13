"""The 15 art styles of the multi-style design engine.

A style is data the 3D renderer (wonderland-studio/render3d/scene.js) understands, plus how its sheets are lit and
staged. What actually changes on screen, per style:

  mode      shading model in the toon shader: 0 toon bands + outline, 1 soft 3D (smooth wrap light, glossy highlight,
            subsurface warmth), 2 clay (matte, procedural thumb-pressed surface), 3 storybook (two painted tones and
            paper grain), 4 anime (one hard terminator, crisp highlight), 5 hyperreal (micro surface texture, fur sheen,
            strong subsurface), 6 sci-fi (dark body, glowing fresnel edge)
  head/body/eye   proportions applied to the rig (chibi: big head, tiny body; baby: round head, big eyes)
  outline   inverted-hull ink thickness (0 = none) and `lights` overrides (key/shade colours, bands, rim, ink)
  palettes  body / belly / accent families the character generator draws from (so universes look different)
  env/grade painted environment used for concepts, and the post grade applied to it

Studio names in the brief ("Pixar-inspired" etc.) describe a general look only; no studio's characters, logos or
designs are reproduced, and every character is generated original.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Style:
    id: str
    name: str
    mode: int
    head: float = 1.0
    body: tuple[float, float, float] = (1.0, 1.0, 1.0)
    eye: float = 1.0
    outline: float = 1.0
    noise: float = 0.35
    noise_scale: float = 0.05
    glow: float = 0.0
    glow_color: str = "#40E0FF"
    lights: dict = field(default_factory=dict)
    palettes: tuple[tuple[str, str, str], ...] = ()      # (body, belly, accent)
    species: tuple[str, ...] = ("bunny", "cat", "elephant", "bear", "duck")
    env: str = "meadow"
    grade: str = "none"
    backdrop: tuple[str, str] = ("#FFF6E3", "#FDE9CF")
    traits: tuple[str, ...] = ()
    summary: str = ""

    def render_style(self) -> dict:
        """What scene.js receives as spec.style."""
        return {"mode": self.mode, "head": self.head, "body": list(self.body), "eye": self.eye, "outline": self.outline,
                "noise": self.noise, "noise_scale": self.noise_scale, "glow": self.glow, "glow_color": self.glow_color}


SOFT_LIGHT = {"lit": [1.0, 0.98, 0.95], "shade1": [0.72, 0.70, 0.84], "shade2": [0.52, 0.50, 0.70], "spec": 0.45,
              "sss": [0.10, 0.04, 0.01]}

STYLES: dict[str, Style] = {s.id: s for s in [
    Style("01-cinematic-3d", "Cinematic 3D (Pixar-inspired)", 1, head=1.05, eye=1.08, outline=0,
          lights=SOFT_LIGHT | {"rim_a": [0.35, 0.55, 0.9], "rim_b": [1.0, 0.7, 0.4]},
          palettes=(("#E8A86B", "#FFF1DE", "#3D7DD8"), ("#8FB8DE", "#F4F8FF", "#F2A541"), ("#C97B63", "#FBE7D6", "#2E8B57"),
                    ("#9C89B8", "#F3EEFA", "#F0B67F"), ("#7A9E7E", "#EEF5EC", "#D1495B")),
          env="meadow", grade="cinematic", backdrop=("#F3EEE6", "#D9CDBE"),
          traits=("earnest", "hopeful", "loyal", "curious", "determined"),
          summary="Soft global-light look, glossy highlights, warm subsurface, no outlines, emotional faces."),
    Style("02-dynamic-3d", "Dynamic 3D (DreamWorks-inspired)", 1, head=1.12, body=(1.08, 0.94, 1.04), eye=0.92, outline=0,
          lights=SOFT_LIGHT | {"lit": [1.05, 1.0, 0.92], "shade2": [0.40, 0.38, 0.6], "spec": 0.6, "rim_a": [0.5, 0.7, 1.0]},
          palettes=(("#6A994E", "#E9F5DB", "#BC4749"), ("#F28F3B", "#FFF3E0", "#2D3047"), ("#5E6472", "#E8E9EB", "#FFB703"),
                    ("#A23B72", "#F9E0EE", "#F18F01"), ("#3E7CB1", "#E3EEF8", "#F2C14E")),
          env="hilltop", grade="punchy", backdrop=("#EFE7DA", "#C8B79F"),
          traits=("cocky", "loud-hearted", "scheming", "big-talking", "unflappable"),
          summary="Stockier, wider build, bigger head, stronger contrast and specular punch for exaggerated attitude."),
    Style("03-fairytale", "Fairytale (Disney-inspired)", 1, head=1.04, body=(0.96, 1.04, 0.96), eye=1.15, outline=0.35,
          lights=SOFT_LIGHT | {"lit": [1.0, 0.97, 1.0], "shade1": [0.80, 0.74, 0.92], "rim_a": [0.9, 0.7, 1.0], "rim_b": [1.0, 0.85, 0.5]},
          palettes=(("#F7C8E0", "#FFF5FA", "#6C5CE7"), ("#A0C4FF", "#F5F9FF", "#FFD166"), ("#FFFFFF", "#FFF7E6", "#E07A9F"),
                    ("#CDB4DB", "#FAF5FF", "#2A9D8F"), ("#FFD6A5", "#FFF8EE", "#4361EE")),
          env="garden", grade="dreamy", backdrop=("#FBF0FF", "#E9D7F5"),
          traits=("kind-hearted", "dreamy", "graceful", "brave", "gentle"),
          summary="Graceful taller build, large sparkling eyes, pastel jewel palette, soft magical lighting."),
    Style("04-hyperreal", "Hyperrealistic 3D Cartoon", 5, head=0.98, eye=0.95, outline=0, noise_scale=0.22,
          lights={"lit": [1.0, 0.97, 0.92], "shade1": [0.62, 0.58, 0.62], "shade2": [0.30, 0.28, 0.34], "spec": 0.3,
                  "sss": [0.16, 0.06, 0.02], "rim_a": [0.6, 0.7, 0.8], "rim_b": [0.9, 0.7, 0.5]},
          palettes=(("#8B6B4E", "#D9C3A5", "#3B5249"), ("#B5B1A8", "#ECE8E1", "#7B2D26"), ("#6E4F3A", "#C9AE8C", "#2F4858"),
                    ("#A07850", "#E6D3B3", "#4A6741"), ("#C8C2B4", "#F2EFE8", "#5A3E36")),
          env="forest", grade="filmic", backdrop=("#D8D4CC", "#9C968B"),
          traits=("weathered", "observant", "proud", "quiet", "resourceful"),
          summary="Natural fur tones with micro surface texture, sheen and deep subsurface; filmic, low-saturation grade."),
    Style("05-cute-baby", "Cute Baby Cartoon", 1, head=1.25, body=(0.84, 0.80, 0.84), eye=1.32, outline=0.45,
          lights=SOFT_LIGHT | {"lit": [1.0, 1.0, 1.0], "shade1": [0.88, 0.84, 0.94], "shade2": [0.74, 0.70, 0.86], "spec": 0.35},
          palettes=(("#FFC8DD", "#FFF4F8", "#A2D2FF"), ("#BDE0FE", "#F5FAFF", "#FFAFCC"), ("#FFF1A8", "#FFFDF0", "#9ADBB5"),
                    ("#CDEAC0", "#F6FCF2", "#FFB4A2"), ("#E4C1F9", "#FBF5FF", "#FFD670")),
          env="playroom", grade="pastel", backdrop=("#FFF5FA", "#FDE4EF"),
          traits=("giggly", "sleepy", "cuddly", "wobbly", "wide-eyed"),
          summary="Round oversized head, huge eyes, tiny body, pastel palette, very soft bright light."),
    Style("06-anime", "Anime", 4, head=1.08, body=(0.94, 1.06, 0.94), eye=1.2, outline=0.55,
          lights={"lit": [1.0, 1.0, 1.0], "shade1": [0.70, 0.72, 0.92], "shade2": [0.70, 0.72, 0.92], "spec": 0.0,
                  "ink": [0.12, 0.10, 0.20], "ink_mix": 0.85, "outline": 3.0},
          palettes=(("#F4F1EA", "#FFFFFF", "#E63946"), ("#2B2D42", "#8D99AE", "#EF233C"), ("#FFB5A7", "#FFF0EB", "#3A86FF"),
                    ("#90E0EF", "#F0FBFF", "#FB5607"), ("#FFD60A", "#FFF9DB", "#003566")),
          env="hilltop", grade="anime", backdrop=("#EAF4FF", "#C9E2FF"),
          traits=("hot-headed", "stoic", "cheerful", "rival-minded", "mysterious"),
          summary="Hard two-tone cel shading, crisp highlight, thin dark linework, saturated sky-blue world."),
    Style("07-chibi", "Chibi", 0, head=1.42, body=(0.78, 0.66, 0.78), eye=1.2, outline=1.25,
          lights={"outline": 5.0, "ink_mix": 0.75},
          palettes=(("#FF99C8", "#FFF0F6", "#A9DEF9"), ("#FCF6BD", "#FFFFFF", "#D0F4DE"), ("#A9DEF9", "#F2FAFF", "#E4C1F9"),
                    ("#D0F4DE", "#F6FFF9", "#FF99C8"), ("#E4C1F9", "#FAF3FF", "#FCF6BD")),
          env="meadow", grade="bright", backdrop=("#FFF9E6", "#FFE8B8"),
          traits=("hyper", "snack-obsessed", "bossy", "clumsy", "sparkly"),
          summary="Head bigger than the body, stubby limbs, bold outlines and candy colours."),
    Style("08-clay", "Clay Animation", 2, head=1.02, body=(1.04, 0.98, 1.04), eye=0.9, outline=0, noise=0.8, noise_scale=0.05,
          lights={"lit": [1.0, 0.96, 0.9], "shade1": [0.72, 0.66, 0.62], "shade2": [0.48, 0.42, 0.42], "spec": 0.05},
          palettes=(("#D98E6A", "#F2D0B5", "#3E6990"), ("#9DB17C", "#E3EBD3", "#C1403D"), ("#E6B655", "#F7E6BF", "#5B4E77"),
                    ("#B07D62", "#E8D2C2", "#4E8098"), ("#7BA5A3", "#D8E8E6", "#E07A5F")),
          env="garden", grade="clay", backdrop=("#EFE3D3", "#CDB89E"),
          traits=("tinkering", "fussy", "warm", "absent-minded", "stubborn"),
          summary="Matte plasticine with thumb-pressed surface variation, no outlines, warm tabletop light."),
    Style("09-storybook", "2D Storybook", 3, head=1.06, eye=0.95, outline=0.7, noise_scale=0.08,
          lights={"lit": [1.0, 0.98, 0.94], "shade1": [0.82, 0.78, 0.84], "ink": [0.30, 0.22, 0.20], "ink_mix": 0.55, "outline": 3.5},
          palettes=(("#E9C46A", "#FAF0D7", "#264653"), ("#A8DADC", "#F1FAEE", "#E63946"), ("#F4A261", "#FDEBD8", "#2A9D8F"),
                    ("#CDB4DB", "#F6EFF8", "#6D597A"), ("#B5C99A", "#EEF3E5", "#B56576")),
          env="forest", grade="storybook", backdrop=("#F7F0E1", "#E8DCC2"),
          traits=("thoughtful", "imaginative", "polite", "wandering", "wise"),
          summary="Two painted tones with paper grain and warm brown ink, like a picture-book illustration."),
    Style("10-comedy", "Comedy Cartoon", 0, head=1.22, body=(1.14, 0.86, 1.1), eye=1.28, outline=1.15,
          lights={"outline": 5.0, "lit": [1.05, 1.02, 0.95]},
          palettes=(("#FFBE0B", "#FFF3C4", "#3A86FF"), ("#FB5607", "#FFE5D6", "#8338EC"), ("#06D6A0", "#E2FBF3", "#EF476F"),
                    ("#FF006E", "#FFE0EE", "#FFBE0B"), ("#8338EC", "#EFE3FF", "#06D6A0")),
          env="meadow", grade="punchy", backdrop=("#FFF4D6", "#FFD68A"),
          traits=("slapstick", "dramatic", "over-confident", "panicky", "prankster"),
          summary="Squat wide bodies, huge eyes and heads for big reactions, loud primary colours."),
    Style("11-animal-adventure", "Animal Adventure", 5, head=1.0, body=(1.02, 1.06, 1.02), eye=1.0, outline=0, noise_scale=0.16,
          lights=SOFT_LIGHT | {"lit": [1.02, 0.97, 0.88], "shade2": [0.40, 0.42, 0.50], "spec": 0.35},
          palettes=(("#A9714B", "#E7CBA9", "#2E6F40"), ("#D4A373", "#FAEDCD", "#1D3557"), ("#6B705C", "#CB997E", "#E76F51"),
                    ("#E9D8A6", "#FFF8E7", "#005F73"), ("#8D6346", "#DDB892", "#9B2226")),
          env="forest", grade="cinematic", backdrop=("#E9E2CF", "#B7A88A"),
          traits=("adventurous", "fearless", "nature-wise", "protective", "quick-witted"),
          summary="Anthropomorphic animals with natural fur texture and explorer gear tones, warm golden light."),
    Style("12-miniature", "Miniature 3D World", 2, head=1.08, body=(0.94, 0.94, 0.94), eye=1.05, outline=0, noise=0.25,
          noise_scale=0.06, lights={"lit": [1.05, 1.0, 0.95], "shade1": [0.78, 0.74, 0.78], "shade2": [0.56, 0.52, 0.60], "spec": 0.3},
          palettes=(("#F28482", "#FFE5E5", "#84A59D"), ("#84A59D", "#E6F0EE", "#F6BD60"), ("#F6BD60", "#FFF3D6", "#5E548E"),
                    ("#9BC1BC", "#EDF6F5", "#ED6A5A"), ("#ED6A5A", "#FCE4E1", "#5CA4A9")),
          env="garden", grade="tiltshift", backdrop=("#F4EEE6", "#DCCFBF"),
          traits=("tiny-but-mighty", "collector", "meticulous", "daydreamer", "neighbourly"),
          summary="Toy-like painted surfaces, macro tilt-shift depth of field and saturated miniature sets."),
    Style("13-scifi", "Futuristic Sci-Fi", 6, head=1.0, body=(0.98, 1.04, 0.98), eye=1.0, outline=0, glow=0.85,
          lights={"lit": [0.9, 0.95, 1.05], "shade1": [0.42, 0.48, 0.62], "shade2": [0.26, 0.30, 0.44], "spec": 0.5},
          palettes=(("#3D4B63", "#AFC3DA", "#00F5D4"), ("#2B2D42", "#8D99AE", "#F72585"), ("#4A4E69", "#C9CBD9", "#4CC9F0"),
                    ("#1B4965", "#BEE9E8", "#FFBE0B"), ("#463F3A", "#BCB8B1", "#7B2CBF")),
          env="night", grade="scifi", backdrop=("#141A2E", "#26304F"),
          traits=("analytical", "rebellious", "hacker", "space-born", "calm-under-pressure"),
          summary="Dark metallic bodies with glowing neon edges, cool night lighting and a neon-teal grade."),
    Style("14-fantasy", "Fantasy Adventure", 1, head=1.02, body=(0.98, 1.06, 0.98), eye=1.1, outline=0.3, glow=0.0,
          lights=SOFT_LIGHT | {"lit": [1.0, 0.95, 1.05], "shade1": [0.70, 0.64, 0.86], "shade2": [0.46, 0.40, 0.66],
                               "rim_a": [0.6, 0.4, 1.0], "rim_b": [1.0, 0.8, 0.4]},
          palettes=(("#7B9E89", "#E3EFE6", "#C9A227"), ("#5E548E", "#E0DDF0", "#F4D35E"), ("#9F86C0", "#F0EAF8", "#2EC4B6"),
                    ("#C08497", "#F7E7EC", "#3D5A80"), ("#8EA604", "#EEF4D4", "#B23A48")),
          env="forest", grade="fantasy", backdrop=("#E9E3F5", "#BFB0DE"),
          traits=("enchanted", "questing", "spell-curious", "noble", "mischievous"),
          summary="Enchanted-forest jewel tones, violet rim light and a glowing magical atmosphere."),
    Style("15-educational", "Educational Cartoon", 0, head=1.12, body=(0.96, 0.96, 0.96), eye=1.12, outline=0.9,
          lights={"outline": 4.0, "lit": [1.02, 1.02, 1.02], "shade1": [0.86, 0.84, 0.94]},
          palettes=(("#4D9DE0", "#EAF4FC", "#FFD23F"), ("#3BCEAC", "#E6FAF5", "#EE4266"), ("#FFD23F", "#FFF8DB", "#540D6E"),
                    ("#EE4266", "#FDE3E9", "#3BCEAC"), ("#9D79BC", "#F2ECF8", "#FFD23F")),
          env="playroom", grade="bright", backdrop=("#F2F8FF", "#D9ECFF"),
          traits=("helpful", "patient", "counting-champion", "question-asker", "encouraging"),
          summary="Clear friendly shapes, primary colours, even classroom light and readable outlines."),
]}

ACCESSORIES = {"bunny": ("scarf", "bow", "bandana"), "cat": ("bow", "scarf", "bandana"), "elephant": ("bandana", "scarf", "overalls"),
               "bear": ("overalls", "scarf", "bandana"), "duck": ("boots", "bow", "scarf")}
SPECIES = ("bunny", "cat", "elephant", "bear", "duck")
AGES = {"baby": {"head": 1.18, "eye": 1.25, "body": 0.84}, "child": {"head": 1.0, "eye": 1.0, "body": 1.0},
        "teen": {"head": 0.94, "eye": 0.95, "body": 1.06}, "adult": {"head": 0.9, "eye": 0.88, "body": 1.12}}
BUILDS = {"round": (1.12, 0.92, 1.1), "standard": (1.0, 1.0, 1.0), "tall": (0.92, 1.12, 0.92), "stocky": (1.15, 0.88, 1.12)}
EXPRESSIONS = {"happy": {}, "talking": {"mouth": 0.7}, "wow": {"mood": "wow"}, "blink": {"blink": 1.0},
               "sleepy": {"mood": "sleepy"}, "sad": {"mood": "sad", "head_tilt": 6}}
ANIMATIONS = {"idle": {}, "wave": {"arm_r": 140, "mouth": 0.4}, "cheer": {"arm_l": 120, "arm_r": 120, "mood": "wow"},
              "hop": {"lift": 70, "arm_l": 60, "arm_r": 60}, "think": {"head_tilt": -8, "arm_r": 95}}
CAMERAS = {"front": 0.0, "three-quarter": 35.0, "side": 90.0, "back": 180.0, "low-hero": 20.0}
LIGHTING = {"style": None, "day": {}, "golden": {"lit": [1.08, 0.94, 0.78], "shade2": [0.5, 0.42, 0.55]},
            "night": {"lit": [0.72, 0.8, 1.05], "shade1": [0.42, 0.46, 0.66], "shade2": [0.28, 0.30, 0.48]},
            "studio": {"lit": [1.0, 1.0, 1.0], "shade1": [0.8, 0.8, 0.86], "shade2": [0.6, 0.6, 0.7]}}
ENVIRONMENTS = ("meadow", "garden", "pond", "hilltop", "forest", "rainy", "playroom", "bathroom", "bedroom", "night")
