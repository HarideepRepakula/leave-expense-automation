# One command sequence from a prepared PostgreSQL to a verified system (docs/14_setup.md section 9).
# Prerequisites: PostgreSQL 16 running, .env filled in (copy .env.example), roles and databases created once with
#   .\scripts\init_local_db.ps1 -SuperuserPassword "<postgres password>"   (or docker compose up -d)
# and the venv installed: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
#
# Usage (project root, PowerShell):   .\scripts\run_all.ps1            # stops at the first failing step
#                                     .\scripts\run_all.ps1 -SkipTests  # everything except pytest
# macOS / Linux: run the same python commands in order (see docs/14_setup.md section 9).
# Afterwards start the API and the dashboard:  .\scripts\start_dashboard.ps1
param([switch]$SkipTests)
# "Continue", not "Stop": Windows PowerShell 5.1 turns any stderr line of a native command (alembic logs INFO to
# stderr) into a terminating error. Each step's exit code is checked instead.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
Push-Location $root
try {
    $steps = @(
        @("migrate", @("-m", "alembic", "upgrade", "head")),
        @("generate and load", @("-m", "src.data.generate", "--seed", "20261022", "--employees", "400",
                                 "--leave-requests", "800", "--expense-claims", "1000", "--load")),
        @("validation", @("-m", "src.validation")),
        @("leave vs oracle", @("-m", "src.evaluation.leave_service_vs_oracle")),
        @("expense vs oracle", @("-m", "src.evaluation.expense_service_vs_oracle"))
    )
    foreach ($s in $steps) {
        Write-Host "=== $($s[0]) ==="
        & $py @($s[1])
        if ($LASTEXITCODE -ne 0) { throw "step '$($s[0])' failed (exit $LASTEXITCODE)" }
    }
    Write-Host "=== reproducibility ==="
    & (Join-Path $PSScriptRoot "reproducibility_check.ps1")
    if ($LASTEXITCODE -ne 0) { throw "reproducibility check failed" }
    Write-Host "=== metrics ==="
    & $py -m src.evaluation.metrics
    if ($LASTEXITCODE -ne 0) { throw "metrics failed" }
    if (-not $SkipTests) {
        Write-Host "=== tests ==="
        & $py -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw "tests failed" }
    }
    Write-Host "ALL STEPS PASSED. Start the API and dashboard with .\scripts\start_dashboard.ps1"
}
finally { Pop-Location }
