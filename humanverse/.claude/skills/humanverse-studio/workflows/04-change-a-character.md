# Workflow 04: approved design change

1. Executive Director approves the change in writing (what changes and why).
2. Edit `project/cast/<id>.json` only; `hv design` (identity files) then `hv build-cast` (rebuilds that character
   because its source hash changed).
3. Re-check the contact sheets; rebuild scenes that use the character (`hv scenes`), re-render, re-run QA.
Scenes append the character .blend, so every scene picks up the approved version and nothing else.
