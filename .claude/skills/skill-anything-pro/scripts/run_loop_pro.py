"""Phase 6 (description optimization) with the fixed trigger eval.

Runs skill-anything's own scripts/run_loop.py unchanged, but with trigger_eval.run_eval
swapped in for its broken run_eval, and a current default improvement model.
Same flags as upstream: --skill-path --eval-file [--max-iterations --train-ratio
--model --improvement-model --max-workers --output-dir].
Needs `pip install anthropic` and ANTHROPIC_API_KEY (or ANTHROPIC_BASE_URL) for the
improvement step; without them upstream raises and nothing is changed.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM = HERE.parents[1] / "skill-anything"
DEFAULT_IMPROVEMENT_MODEL = "claude-sonnet-5-5"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(UPSTREAM))

import trigger_eval  # noqa: E402
from scripts import run_loop  # noqa: E402  (skill-anything's package)

run_loop.run_eval = trigger_eval.run_eval

if __name__ == "__main__":
    if not any(a.startswith("--improvement-model") for a in sys.argv[1:]):
        sys.argv += ["--improvement-model", DEFAULT_IMPROVEMENT_MODEL]
    sys.exit(run_loop.main())
