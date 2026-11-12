# Troubleshooting

| Symptom | Meaning | Fix |
|---|---|---|
| doctor: provider BLOCKED "set X_API_KEY" | No credentials | Add the key to `.env` or the environment's secrets |
| doctor: BLOCKED "network/proxy refused" | The machine can't reach the provider (cloud sandbox egress policy) | Allow the host in the environment's network settings, or run on your own machine |
| doctor: higgsfield BLOCKED "sign in once" | CLI not signed in / no workspace | `higgsfield auth login`, then `higgsfield workspace set <id>` (needs a browser on the same machine) |
| step `blocked_pending_approval` | Paid step reached without approval or price | Fill `configuration/pricing.json`, then `dhfactory run --job ID --approve-spend` |
| step blocked "presenter.json: … missing" | Avatar/voice ids not set | Fill `configuration/presenter.json` |
| QC `real_production: BLOCKED` | The video was made by the mock provider | Select a real avatar provider in `init-job` |
| QC duration FAIL | Script too long/short for the target | Edit the script or pass `--duration` |
| A run was interrupted | — | Run the same `dhfactory run --job ID` again; it resumes and never pays twice for a finished provider job |
