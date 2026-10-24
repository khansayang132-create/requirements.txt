# Known Issues (auto-generated)

Found by HarnessFlow initialize (fast) on 2026-10-22, from a read of the key scripts. The capability gaps tracked in `apex/STATUS.md` (BLOCKED / NOT IMPLEMENTED) are not repeated here; that file owns them.

## Some written forms still read wrong in Indonesian narration
Found 2026-10-24 by probing `normalize_for_speech` (`apex/apex/tts.py`):
- `jam 08.30` becomes "delapan.tiga puluh" (should be "jam delapan tiga puluh").
- `tanggal 17/8` becomes "tujuh belas/delapan".
- `3x sehari` stays "3x", because the number isn't split from the x.
- `Rp1.5 juta` (English decimal point) becomes "satu rupiah.lima juta".
- `10%` becomes "sepuluh%"; untested whether espeak-ng says "persen".

Root cause: the normalizer only knows Rp amounts, thousands dots and decimal commas.
Consequences: narration says the wrong thing when a script uses these forms. Fix one form at a time, each with a parametrized case in `tests/test_core.py`; check espeak-ng's own reading in Docker before adding a rule for it.
