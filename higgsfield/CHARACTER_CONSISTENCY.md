# Character consistency

The five Wonder Meadow characters already exist as code (the 3D renderer in `wonderland-studio/render3d/`), so the
studio's own episodes cannot drift. Higgsfield is for extra material (key art, thumbnails, B-roll, trailers), and there
identity must be held by references, not by hoping a prompt repeats.

1. **Anchor text from the bible, never by hand:**
   `python3 .claude/skills/3d-cartoon-studio/scripts/anchors.py bobo` → paste the CHARACTER ANCHOR into every prompt.
2. **Reference images from the studio itself:** render the 3D character sheet / 7-angle turnaround
   (`wonderland-studio`, `character_sheet` / `character_turnaround`) and upload them (`higgsfield upload` or the
   connector's media upload). Pass them as `image_references` to a multi-reference model (`flux_3_image`,
   `minimax_h3_image`, `seedance_2_x`).
3. **Approve a still, then animate it:** image-to-video from the approved still (`start_image`), never text-to-video,
   for any shot where the character must look right.
4. **Never drift:** eye spacing and shape, head/body proportions, body color hex, signature accessory
   (Bobo yellow scarf, Mimi teal bow, Toto red neckerchief, Zuzu blue boots, Lolo green overalls).
5. **Reject** any generation where those change, and log why.

Soul ID training is for realistic people (5–20 photos); it is the wrong tool for these toon animals.
