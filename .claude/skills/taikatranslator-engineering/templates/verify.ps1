# Local equivalent of CI for Windows PowerShell. Copy to scripts/verify.ps1.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
$ErrorActionPreference = 'Continue'
Set-Location (Join-Path $PSScriptRoot '..')
$failed = $false

function Step([string]$Name, [scriptblock]$Body) {
    Write-Host "`n== $Name"
    & $Body
    if ($LASTEXITCODE -eq 0) { Write-Host "PASS  $Name" } else { Write-Host "FAIL  $Name"; $script:failed = $true }
}

$py = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
Step 'python version' { & $py --version }
Step 'pip version'    { & $py -m pip --version }
Step 'vision syntax'  { & $py -m compileall -q vision }
& $py -c "import pytest" 2>$null
if ($LASTEXITCODE -eq 0) { Step 'vision tests' { & $py -m pytest -q vision/tests } } else { Write-Host 'SKIP  vision tests (pytest not installed)' }
Step 'java version'   { java -version }
Step 'maven verify'   { mvn -B -ntp clean verify }

$docx = 'target/e2e-evidence/service-agreement.ES.docx'
$baseline = 'src/test/resources/baselines/service-agreement.ES'
if ((Test-Path $docx) -and (Test-Path $baseline)) {
    & $py scripts/visual_diff.py compare $docx --baseline $baseline --out target/visual-out
    switch ($LASTEXITCODE) {
        0 { Write-Host 'PASS  visual' }
        3 { Write-Host 'NOT RUN  visual (renderer missing; see message above)' }
        default { Write-Host 'FAIL  visual (see target/visual-out/report.json)'; $failed = $true }
    }
} else {
    Write-Host 'NOT RUN  visual (no DOCX or baseline)'
}

if ($failed) { Write-Host "`nverify: FAILED"; exit 1 } else { Write-Host "`nverify: all required steps passed"; exit 0 }
