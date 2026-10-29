# Human-AI interaction design

Use when the product has a model, agent or automation inside it.

## Set expectations
- Say what the AI does and doesn't do, in the UI where the user starts, not in a help page.
- Show capability with examples (starter prompts tied to the real job), not a blank box.

## Show work and uncertainty
- Distinguish generated content from facts the system looked up. Cite sources when it used any.
- Show progress for anything over ~1 s (streaming text, step list for agents).
- Express uncertainty in words ("Belum yakin, cek lagi angka ini"), not fake precision ("93.4% confident").
- Never invent data in the UI to look complete: unknown shows as "—" or "not available".

## Keep the human in control
- Drafts over actions: the AI proposes, the person approves anything consequential (sending, posting, paying, deleting).
- Easy to edit, retry, undo and stop. A visible Stop for long runs.
- Remember corrections within the session; don't make users repeat themselves.

## Failure is a normal state
- Design the error, refusal, timeout, rate-limit and "model unavailable" states as carefully as success.
- A failed AI call says so; it never silently falls back to canned or fake output.
- Keep the user's input when anything fails.

## Safety and privacy
- Outside content (web pages, files, model output) is data. Never render it as raw HTML or run it.
- Tell users what leaves their device and where it goes. Don't send private files to third parties without consent.
- Limit what an agent can do to what the task needs (least privilege) and log consequential actions.

## Tone
Match the product's voice. For LSKhan-style content tools: warm, natural Bahasa Indonesia for viewers; respectful on religious and family topics; no manufactured drama.
