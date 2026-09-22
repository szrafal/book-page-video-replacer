$ErrorActionPreference = "Stop"

Write-Host "[1/4] Checking Python..."
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    } else {
        throw "Python not found and winget is unavailable. Run this project through Codex and let it install Python using an available package manager."
    }
}

Write-Host "[2/4] Checking FFmpeg..."
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    } else {
        Write-Warning "FFmpeg missing. Codex should install a local build into tools/ffmpeg."
    }
}

Write-Host "[3/4] Creating virtual environment..."
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel

Write-Host "[4/4] Installing base Python dependencies..."
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "Base environment ready. Codex may install additional AI/video-inpainting dependencies when needed."
