# Workflow 01: a new production, start to finish

1. `hv doctor`: read reports/capability-report.md; anything BLOCKED stays BLOCKED until fixed.
2. Character Designer writes `project/cast/CHAR-HUM-NNN.json` from `templates/character.template.json` (five for a pilot).
3. Screenwriter writes `project/story/screenplay.json` from `templates/screenplay.template.json`; `hv design`.
4. `hv build-cast`; open every `characters/<id>/sheet_views.png`, `sheet_expressions.png`, `sheet_deform.png`.
   Fix what looks wrong (hair through hats, clothes clipping, weak expressions) in the cast file or hvchar, rebuild.
5. `hv voice`; listen to a few lines (project/audio/lines/*.wav).
6. Storyboard Director copies `templates/blocking.example.py` to `project/story/blocking.py` and blocks each scene;
   `hv storyboard`; Executive Director reads storyboard.md, then `hv storyboard --approve-as "<name>"`.
7. `hv scenes`; render one frame per shot as a preview (workflows/02); fix framing/posing; rebuild.
8. `hv sound`, `hv render` (resumable, run scenes in parallel with --threads), `hv edit`, `hv qa`.
9. Watch the MP4. Only then `hv approve --as "<name>"` and `hv deliver`.
