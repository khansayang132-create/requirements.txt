from __future__ import annotations

import json

from ..state import CharacterSpec, ProductionState
from ..utils.files import safe_id
from .base import AgentResult, BaseAgent

DEFAULT_PRESENTER = {
    "name": "Amara Lin", "age_range": "early 30s", "appearance": "warm, composed professional presenter, natural proportions",
    "face": "oval face, dark brown almond eyes, soft defined brows, straight nose, natural lips, light freckles",
    "hair": "shoulder-length dark brown hair, gentle waves, tucked behind one ear", "skin": "medium warm skin tone, natural texture, no heavy retouching",
    "clothing": "navy tailored blazer over a cream crew-neck top, small silver stud earrings",
    "expression": "friendly, calm, natural smile, steady eye contact", "voice_style": "clear, warm, mid-pitch, measured pace",
}


class DigitalHumanDirectorAgent(BaseAgent):
    name = "digital-human-director"
    description = "Owns the character's identity: face, proportions, skin, hair, clothing and the rules that keep them consistent."

    async def run(self, state: ProductionState, step: str) -> AgentResult:
        spec = {**DEFAULT_PRESENTER, **(self.ctx.presenter.get("character") or {})}
        if not spec.get("fictional", True) and not spec.get("likeness_consent"):
            return AgentResult(status="failed", error="a real person's likeness needs a recorded consent reference (character.likeness_consent)")
        char = CharacterSpec(character_id=safe_id(spec.get("character_id") or spec["name"]), language=state.language,
                             consistency_rules=["same face shape, eye colour and spacing in every shot", "same hairstyle and parting",
                                                "same outfit unless the scene asks for a change", "same skin tone and lighting temperature",
                                                "one reference set; every generation is conditioned on it"],
                             **{k: v for k, v in spec.items() if k in CharacterSpec.model_fields and k not in ("character_id", "language")})
        out = self.ctx.root / "characters" / char.character_id / "character.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(char.model_dump_json(indent=2), encoding="utf-8")
        state.character = char
        return AgentResult(status="success", artifact_paths=[str(out)], metadata={"anchor": char.anchor()})

    async def identity(self, state: ProductionState) -> AgentResult:
        """STEP 4: freeze the identity: anchor text, reference hashes, provider."""
        from pathlib import Path

        from ..utils.files import sha256

        char = state.character
        refs = [{"path": p, "sha256": sha256(Path(p))} for p in state.reference_images]
        ident = {"character_id": char.character_id, "anchor": char.anchor(), "references": refs, "image_provider": state.providers.get("image"),
                 "rules": char.consistency_rules}
        out = self.ctx.root / "characters" / char.character_id / "identity.json"
        out.write_text(json.dumps(ident, indent=2), encoding="utf-8")
        return AgentResult(status="success", artifact_paths=[str(out)], metadata={"references": len(refs)})
