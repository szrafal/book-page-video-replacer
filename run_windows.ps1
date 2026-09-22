param(
    [ValidateSet("clean", "replace")]
    [string]$Mode = "clean",
    [string]$Pages = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Virtual environment missing. Running installer..."
    powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
}

$inputFile = Get-ChildItem -Path .\input -File | Where-Object { $_.Extension -match '^\.(mp4|mov|mkv|avi|m4v)$' } | Select-Object -First 1
if (-not $inputFile) {
    throw "Put a video file into the input folder first."
}

New-Item -ItemType Directory -Force -Path .\output | Out-Null
if ($Mode -eq "replace") {
    $arguments = @("-m", "src.main", "--input", $inputFile.FullName, "--mode", "replace", "--output", ".\output\replaced.mp4", "--device", "auto", "--quality", "best")
    if ($Pages) {
        $arguments += @("--pages", $Pages)
    }
    & .\.venv\Scripts\python.exe @arguments
} else {
    & .\.venv\Scripts\python.exe -m src.main --input $inputFile.FullName --mode clean --output .\output\cleaned.mp4 --device auto --quality best
}
