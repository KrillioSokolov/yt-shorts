# yt-shorts one-click installer for Windows.
# Right-click this file -> "Run with PowerShell". Click "Yes" on any prompt.
# It installs the free tools the skill needs, copies the skill into Claude Code's skills folder,
# and runs the skill's own setup (which downloads the speech model, about 500 MB).

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

Write-Host ""
Write-Host "=== yt-shorts installer ===" -ForegroundColor Cyan
Write-Host ""

function Missing($cmd) { -not (Get-Command $cmd -ErrorAction SilentlyContinue) }

if (Missing "winget") {
    Write-Host "winget (Windows package manager) is missing. Open the Microsoft Store, install 'App Installer', then run this again." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$packages = @(
    @{ id = "Git.Git";            cmd = "git";    why = "Claude Code needs Git Bash" },
    @{ id = "Python.Python.3.12"; cmd = "py";     why = "runs the scripts" },
    @{ id = "Gyan.FFmpeg";        cmd = "ffmpeg"; why = "cuts the video" },
    @{ id = "yt-dlp.yt-dlp";      cmd = "yt-dlp"; why = "downloads from YouTube" },
    @{ id = "DenoLand.Deno";      cmd = "deno";   why = "YouTube download helper" }
)

foreach ($p in $packages) {
    if (Missing $p.cmd) {
        Write-Host ("Installing {0} ({1}) ..." -f $p.id, $p.why) -ForegroundColor Yellow
        winget install --id $p.id -e --accept-source-agreements --accept-package-agreements --silent
    } else {
        Write-Host ("{0} already installed" -f $p.cmd) -ForegroundColor Green
    }
}

# Make the freshly installed tools visible to this window.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

$dest = Join-Path $env:USERPROFILE ".claude\skills\yt-shorts"
$src  = $PSScriptRoot
if ((Resolve-Path $src).Path -ne $dest) {
    Write-Host "Copying the skill to $dest ..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    robocopy $src $dest /E /XD .venv workspace .git .superpowers __pycache__ .pytest_cache /XF config.json /NFL /NDL /NJH /NJS | Out-Null
}

Write-Host ""
Write-Host "Running the skill setup (downloads the speech model, a few minutes) ..." -ForegroundColor Yellow
& py -3.12 (Join-Path $dest "scripts\setup.py")

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "1. Fully quit Claude Code (or the Claude desktop app) and start it again."
Write-Host "2. In Claude Code type:  /yt-shorts setup   and give it your YouTube channel link."
Write-Host "3. Evening:  /yt-shorts prep <video link>     Morning:  /yt-shorts clip"
Write-Host ""
Read-Host "Press Enter to close"
