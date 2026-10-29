# Generate the dataset twice into two temporary folders and compare row counts and SHA-256 checksums
# (docs/07 section 10, acceptance criterion 17, metric M13).
# Usage (project root, PowerShell):
#   .\scripts\reproducibility_check.ps1                       # full baseline 400 / 800 / 1000
#   .\scripts\reproducibility_check.ps1 -Employees 40 -LeaveRequests 80 -ExpenseClaims 100   # starter
param(
    [int]$Seed = 20261022,
    [int]$Employees = 400,
    [int]$LeaveRequests = 800,
    [int]$ExpenseClaims = 1000
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$work = Join-Path ([IO.Path]::GetTempPath()) ("lea_repro_" + [guid]::NewGuid().ToString("N"))
Push-Location $root
try {
    foreach ($run in @("run_a", "run_b")) {
        & $python -m src.data.generate --seed $Seed --employees $Employees --leave-requests $LeaveRequests `
            --expense-claims $ExpenseClaims --out (Join-Path $work $run) | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "generator failed for $run" }
    }
    & $python -m src.data.compare_runs (Join-Path $work "run_a") (Join-Path $work "run_b") `
        --report (Join-Path $root "data\validation\reproducibility.json")
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
exit $code
