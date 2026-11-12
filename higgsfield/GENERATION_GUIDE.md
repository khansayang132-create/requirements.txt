# Generation guide (real model facts, checked 2026-11-12)

Always preflight with `get_cost` (connector) or `higgsfield generate cost` (CLI) before generating. Generating spends credits.

## Measured costs

| Job | Model | Credits |
|---|---|---|
| 1 image, 9:16 | `z_image` (fast, stylized) | 0.15 |
| 5 s video, 9:16 | `kling_4_0_flash` image-to-video, 720p | 15 |
| 5 s video, 9:16 | `seedance_2_5`, 720p | 35 |

Free plan balance: 0.76 credits — enough for ~5 test images, **no video**.

## Which model for what (from the model catalog, not assumed)

| Need | Model | Why (catalog) |
|---|---|---|
| Quick stylized frames, look tests | `z_image` | text-only, fast, budget; 1:1, 4:3, 3:4, 16:9, 9:16 |
| Scenes with up to 10/16 reference images (character + set consistency) | `flux_3_image`, `minimax_h3_image` | multi-reference image editing, up to 4K |
| Highest-quality stills, text | `nano_banana_pro` | image_references, 1k–4k |
| Image-to-video (animate an approved still) | `kling_4_0_flash` (cheap 720p), `kling4_0` (1080p, keyframes start/end) | roles start_image, end_image, image_references |
| Reference-driven video with consistent identity | `seedance_2_0`, `seedance_2_5` | tags reference/identity; start/end image, image/video/audio references; 4–30 s |
| Camera motion | `grok_video_v15` | tags camera-motion, start-frame |
| Reusable realistic person/character | `soul_2` + Soul ID training | Soul is aimed at realistic people (UGC/fashion); not suited to toon animals |

## CLI shape

```bash
higgsfield model list --video
higgsfield generate cost z_image --prompt "…"
higgsfield generate create z_image --prompt "…" --wait
higgsfield upload <file>                         # returns an upload id for --image
```
