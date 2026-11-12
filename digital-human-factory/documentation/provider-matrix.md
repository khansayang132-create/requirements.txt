# Provider matrix

"Verified here" = checked in this session (PyPI metadata, SDK source, CLI). Pricing pages and API docs could not be
fetched from the sandbox, so prices are **not** filled in: `configuration/pricing.json` must be completed from each
provider's pricing page before any paid step can run.

| Provider | Capability | Python integration | Auth env var | Pricing risk | Commercial notes (check the provider's terms) | Status |
|---|---|---|---|---|---|---|
| HeyGen | Talking avatar (stock or own avatar), provider lip sync, multilingual voices | REST via httpx (`providers/heygen.py`); no official Python SDK (PyPI `heygen` 0.0.0 is not theirs) | `HEYGEN_API_KEY` | Paid per minute/credit; API plan needed | Stock avatars are licensed actors; own avatar needs the person's consent | Adapter done, mocked tests PASS; live BLOCKED (no key, host blocked) |
| Synthesia | Talking avatar; `test: true` makes free watermarked videos | REST via httpx (`providers/synthesia.py`); PyPI `synthesia` not used | `SYNTHESIA_API_KEY` | API access on paid plans | Content moderation; custom avatars need consent | Adapter done, mocked tests PASS; live BLOCKED |
| D-ID | Talking head from one portrait + text | REST via httpx (`providers/did.py`) | `DID_API_KEY` | Credits per video | You must own/licence the portrait | Adapter done, mocked tests PASS; live BLOCKED |
| ElevenLabs | Voice, multilingual TTS with character timings; voice cloning | **Official SDK** `elevenlabs` 2.78.0 (`providers/elevenlabs.py`) | `ELEVENLABS_API_KEY` | Characters per month by plan | Cloning only with the speaker's consent — enforced via `voice-authorizations.json` | Installed; mocked tests PASS; live BLOCKED |
| Runway | Text-to-image (references), image-to-video (camera motion) | **Official SDK** `runwayml` 5.27.0 (`providers/runway.py`) | `RUNWAYML_API_SECRET` | Credits per second/image | Usage policy applies | Installed; mocked tests PASS; live BLOCKED |
| Higgsfield | Images, image-to-video (Kling, Seedance, …) | Official CLI `@higgsfield/cli` 1.2.2 via subprocess (`providers/higgsfield_cli.py`) | none (CLI sign-in) | Measured: image 0.15 cr, 5 s video 15–35 cr; account has 0.76 cr | Platform terms | CLI installed; BLOCKED until `higgsfield auth login` on a machine with a browser |
| Kling AI | Video | No official Python SDK verified; reachable via Runway (`kling_4`, `kling3.0_*` models) or Higgsfield | — | — | — | BLOCKED as a direct integration; available through Runway/Higgsfield |
| LivePortrait | Local portrait animation | Local GPU model | — | Free compute, GPU needed | Check model-weight licence before commercial use | BLOCKED: no GPU |
| SadTalker | Local talking head | Local GPU model (Apache-2.0 code, third-party face models) | — | Free compute, GPU needed | Check bundled model licences | BLOCKED: no GPU |
| Mock (built in) | All four, free, offline | `providers/mock.py` | — | none | Output is labelled MOCK | PASS (tests and dry runs only) |
