#!/usr/bin/env bash
# Local equivalent of CI. Copy to scripts/verify.sh in the TaikaTranslator repo.
# Prints each step's result and exits nonzero if any required step failed.
# The visual step is optional locally: a missing renderer is reported, not hidden.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2
failed=0
step() {
  local name=$1; shift
  printf '\n== %s\n' "$name"
  if "$@"; then echo "PASS  $name"; else echo "FAIL  $name"; failed=1; fi
}

python=${PYTHON:-python3}
step "python version"   "$python" --version
step "pip version"      "$python" -m pip --version
step "vision syntax"    "$python" -m compileall -q vision
if "$python" -c "import pytest" 2>/dev/null; then
  step "vision tests"   "$python" -m pytest -q vision/tests
else
  echo "SKIP  vision tests (pytest not installed)"
fi
step "java version"     java -version
step "maven verify"     mvn -B -ntp clean verify

docx=target/e2e-evidence/service-agreement.ES.docx
baseline=src/test/resources/baselines/service-agreement.ES
if [ -f "$docx" ] && [ -d "$baseline" ]; then
  "$python" scripts/visual_diff.py compare "$docx" --baseline "$baseline" --out target/visual-out
  rc=$?
  case $rc in
    0) echo "PASS  visual" ;;
    3) echo "NOT RUN  visual (renderer missing; see message above)" ;;
    *) echo "FAIL  visual (see target/visual-out/report.json)"; failed=1 ;;
  esac
else
  echo "NOT RUN  visual (no DOCX or baseline)"
fi

echo
[ "$failed" = 0 ] && echo "verify: all required steps passed" || echo "verify: FAILED"
exit "$failed"
