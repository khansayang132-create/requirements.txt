# Digital Human AI Factory (`dhfactory`)

A Python package that turns a script into a checked talking-presenter video through seven typed agents:
director → avatar engineer → video engineer → voice engineer → cinematic editor → quality control, run by a
production manager over a resumable 14-step graph. It runs real providers (HeyGen, Synthesia, D-ID, ElevenLabs, Runway,
Higgsfield) when you add credentials, and a free, clearly-labelled mock provider for tests and dry runs.

Status of everything: [`documentation/installation-report.md`](documentation/installation-report.md).

```bash
make install                      # uv venv + package + official SDKs + dev tools
.venv/bin/dhfactory doctor        # environment + provider health (read-only)
.venv/bin/dhfactory init-job --script scripts/demo-presenter.txt --job demo        # mock providers by default
.venv/bin/dhfactory run --job demo                                                 # free dry run → rendered-videos/demo/final.mp4
.venv/bin/dhfactory init-job --script scripts/demo-presenter.txt --job live --avatar synthesia
.venv/bin/dhfactory run --job live --approve-spend                                 # paid steps need this flag + a confirmed price
.venv/bin/dhfactory qc --video rendered-videos/demo/final.mp4 --duration 10
make test
```

Rules built into the code: no paid call without `--approve-spend`, a price in `configuration/pricing.json` and room under
`DHF_MAX_SPEND_USD`; a finished paid job is never paid for twice; missing credentials make a step BLOCKED (never a fake
result); characters are fictional unless a likeness consent is recorded; cloned voices need an entry in
`configuration/voice-authorizations.json`; secrets only in `.env` / environment, redacted from every log and report.

Docs: [provider matrix](documentation/provider-matrix.md) · [API configuration](documentation/api-configuration.md) ·
[architecture](documentation/pipeline-architecture.md) · [troubleshooting](documentation/troubleshooting.md) ·
[first production test](documentation/test-reports/demo-status.md)
