# Activate the virtual environment for ghg_2_RFlux_csv
# This script activates the Python virtual environment in PowerShell

$venvPath = Join-Path $PSScriptRoot "venv\Scripts\Activate.ps1"

if (Test-Path $venvPath) {
    Write-Host "Activating virtual environment..." -ForegroundColor Green
    & $venvPath
    Write-Host "Virtual environment activated successfully!" -ForegroundColor Green
    Write-Host "You can now run: python GHG2RFLUX.py" -ForegroundColor Cyan
} else {
    Write-Host "Error: Virtual environment not found!" -ForegroundColor Red
    Write-Host "Please run: python -m venv venv" -ForegroundColor Yellow
    Write-Host "Then run: .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "Then run: pip install -r requirements.txt" -ForegroundColor Yellow
}
