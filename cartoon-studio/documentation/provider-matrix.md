# Provider matrix (V3.0)

Checked 2026-11-12 against the installed packages. Provider hosts were not reachable from the build machine, so every
paid provider is **NOT TESTED live**. PASS for a provider needs a real authenticated, non-billable check on your machine
(`cartoon-studio doctor`).

| Provider | Capability | Integration | Auth (env) | Paid | Status here |
|---|---|---|---|---|---|
| Local engine (`../wonderland-studio`) | 3D toon or 2D animation, backgrounds, voices, Foley, music, mix, edit | in-process | none | no | **PASS**: episode rendered, see test-reports |
| Runway | image→video, image | official SDK `runwayml` 5.27 (`image_to_video.create`, `tasks.retrieve`, health: `organization.retrieve`) | `RUNWAYML_API_SECRET` | yes | BLOCKED (no key) |
| FLUX / BFL | image with reference (`flux-kontext-pro`) | REST `api.bfl.ai/v1/<model>`, header `x-key`, poll `polling_url` | `BFL_API_KEY` | yes | BLOCKED (no key); request shape from public docs, mocked only |
| ComfyUI Cloud | workflows | official SDK `comfy-sdk` 0.5 (Comfy Org) | `COMFY_API_KEY` (+ optional `COMFY_BASE_URL`) | yes | BLOCKED (no key) |
| ComfyUI local server | workflows | not driven yet | `COMFYUI_BASE_URL` (v0.3 name) | local compute | BLOCKED / NOT IMPLEMENTED |
| Kling | image→video | REST `/v1/videos/image2video`, JWT HS256 from the access and secret keys | `KLING_ACCESS_KEY` + `KLING_SECRET_KEY` | yes | BLOCKED (no keys); no official Python SDK on PyPI; mocked only |
| Higgsfield | image, video | official SDK `higgsfield-client` 0.2 (`subscribe`) | `HF_KEY`, or `HF_API_KEY` + `HF_API_SECRET`; v0.3 `HIGGSFIELD_API_KEY` is accepted as `HF_KEY` | yes | BLOCKED (no key) |
| ElevenLabs | voice with timestamps | official SDK `elevenlabs` 2.78 (`convert_with_timestamps`; health: `user.subscription.get`) | `ELEVENLABS_API_KEY` | yes | BLOCKED (no key) |
| Blender | 3D render | CLI `blender --background --python` | none | local compute | BLOCKED (not installed) |
| FFmpeg / FFprobe | edit, probe, decode test | subprocess | none | no | PASS |

v0.3's `KLING_API_KEY` alone cannot authenticate: Kling signs every request with the access and secret key pair, and
`doctor` says so.
