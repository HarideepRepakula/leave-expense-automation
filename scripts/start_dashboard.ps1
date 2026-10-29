# Phase 10: start the API in a NEW PowerShell window, then the Streamlit dashboard in THIS window.
# Usage, from the project root:   .\scripts\start_dashboard.ps1
# API: http://127.0.0.1:8000/docs     Dashboard: http://localhost:8501     Stop: Ctrl+C in each window.
# macOS / Linux: run the two commands below in two terminals (python instead of the .venv path).
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Start-Process powershell -WorkingDirectory $root -ArgumentList @(
    "-NoExit", "-Command", "& '$python' -m uvicorn src.api.main:create_app --factory --port 8000")

Set-Location $root
& $python -m streamlit run src/dashboard/app.py --server.port 8501
