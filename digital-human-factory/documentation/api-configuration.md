# API configuration

1. `cp .env.example .env` and fill only the providers you use. `.env` is gitignored; never commit it. In Claude Code
   cloud sessions, put keys in the environment's secrets instead of a file.
2. Fill `configuration/presenter.json` for the chosen avatar provider:
   - HeyGen: `heygen.avatar_id`, `heygen.voice_id` (from your HeyGen account's avatar and voice lists)
   - D-ID: `did.source_url` (HTTPS image you own or a generated fictional portrait), `did.voice_id`
   - Synthesia: `synthesia.avatar`, keep `test: true` for free watermarked trials
   - ElevenLabs: `elevenlabs.voice_id`
3. Fill `configuration/pricing.json` with prices from each provider's pricing page (USD per unit). A paid step with an
   unknown price is refused.
4. Cloned voices: add the voice id to `configuration/voice-authorizations.json` only with the speaker's written consent
   stored outside git.
5. `dhfactory doctor` must show PASS for every provider you selected before a paid run.

| Env var | Used by |
|---|---|
| `HEYGEN_API_KEY` | HeyGen (`X-Api-Key` header) |
| `ELEVENLABS_API_KEY` | ElevenLabs SDK |
| `RUNWAYML_API_SECRET` | Runway SDK |
| `DID_API_KEY` | D-ID (`Authorization: Basic …`) |
| `SYNTHESIA_API_KEY` | Synthesia (`Authorization` header) |
| `DHF_MAX_SPEND_USD` | per-job spending cap (default 5) |
| `DHF_WORKSPACE` | folder that holds characters/, jobs/, rendered-videos/ |
