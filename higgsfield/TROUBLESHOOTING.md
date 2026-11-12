# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `higgsfield auth login` waits forever in a cloud session | The OAuth callback goes to localhost on the container, which your browser can't reach. | Sign in on your own computer, or use the Higgsfield connector in Claude (already signed in). |
| "Local callback port is busy" | Another service (e.g. Headroom on 8765) uses the default port. | The CLI falls back automatically, or pass `--port <free port>`. |
| Generation refused / not enough credits | Free plan, 0.76 credits. | Check with `higgsfield account status` / connector `balance`; upgrade only if you decide to. |
| Skills not offered to Claude | Plugin disabled or installed in another account. | `claude plugin list` → `higgsfield@higgsfield` must be enabled; start a new session. |
| Character looks different between shots | Text-only prompts. | Use reference images + image-to-video from an approved still (see CHARACTER_CONSISTENCY.md). |
| A skill says to run `curl … | sh` | Fallback installer for a missing CLI. | The CLI is installed from npm; skip it. |
