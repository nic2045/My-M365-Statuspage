<#
.SYNOPSIS
    VS Code startup script for M365 Statuspage development on Windows

.DESCRIPTION
    Automatically detects and configures WSL2 + Docker environment when opening
    the project in VS Code on Windows. Runs on folder open if configured in .vscode/settings.json

.NOTES
    Place in project root and configure VS Code:
    {
      "terminal.integrated.profiles.windows": {
        "PowerShell": {
          "source": "PowerShell",
          "args": ["-NoExit", "-ExecutionPolicy", "Bypass", "-File", ".\\Start.ps1"]
        }
      }
    }
#>

param(
    [switch]$Force,
    [switch]$Help
)

$ErrorActionPreference = "Continue"

# Colors
$colors = @{
    Success = "Green"
    Error   = "Red"
    Warning = "Yellow"
    Info    = "Cyan"
}

function Write-Log {
    param([string]$Message, [string]$Type = "Info")
    $color = $colors[$Type] ?? "White"
    $prefix = "[$Type]" | PadRight(10)
    Write-Host "$prefix $Message" -ForegroundColor $color
}

function Show-Help {
    Write-Host @"
╔════════════════════════════════════════════════════════════════════════╗
║  M365 Statuspage - VS Code Windows Dev Environment Startup              ║
╚════════════════════════════════════════════════════════════════════════╝

This script runs automatically when opening the project in VS Code.

OPTIONS:
  -Force     Skip all checks and run setup-wsl2.ps1
  -Help      Show this message

WHAT THIS SCRIPT DOES:
  1. Detects if running on Windows
  2. Checks if WSL2 is available
  3. Checks if Docker is running
  4. Offers to run setup if anything is missing
  5. Prints next steps for development

MANUAL SETUP:
  If you want to run setup manually:
    .\setup-wsl2.ps1
    .\setup-wsl2.ps1 -Help

For more info: https://github.com/nic2045/My-M365-Statuspage
"@
}

if ($Help) {
    Show-Help
    return
}

Write-Host ""
Write-Log "M365 Statuspage - Windows Dev Environment" "Info"
Write-Host ""

# Check if Windows
if ($PSVersionTable.Platform -eq "Unix") {
    Write-Log "Already on Linux/WSL2, skipping Windows-specific setup" "Info"
    return
}

# Check WSL2
$wslAvailable = $false
try {
    $wslList = wsl --list --quiet 2>$null
    if ($wslList -match "Ubuntu" -or $wslList -match "ubuntu") {
        $wslAvailable = $true
        Write-Log "WSL2 with Ubuntu detected ✓" "Success"
    }
} catch {
    Write-Log "WSL2 not available or needs configuration" "Warning"
}

# Check Docker
$dockerRunning = $false
try {
    docker ps 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $dockerRunning = $true
        Write-Log "Docker Desktop running ✓" "Success"
    }
} catch {
    Write-Log "Docker not running or not installed" "Warning"
}

Write-Host ""

# If everything is ready, show next steps
if ($wslAvailable -and $dockerRunning -and -not $Force) {
    Write-Log "Environment is ready! ✓" "Success"
    Write-Host ""
    Write-Host "Available commands:"
    Write-Host "  make docker    - Start Docker dev environment"
    Write-Host "  make install   - Install dependencies only"
    Write-Host "  make dev       - Run dev server directly"
    Write-Host "  make help      - Show all available commands"
    Write-Host ""
    return
}

# If something is missing, offer to run setup
Write-Log "Environment setup needed" "Warning"
Write-Host ""
Write-Host "Would you like to run the setup script? (y/n): " -NoNewline
$response = Read-Host

if ($response -eq "y" -or $response -eq "Y") {
    Write-Host ""
    # Run setup-wsl2.ps1
    $setupScript = Join-Path $PSScriptRoot "setup-wsl2.ps1"
    if (Test-Path $setupScript) {
        Write-Log "Running setup-wsl2.ps1..." "Info"
        & $setupScript
    } else {
        Write-Log "setup-wsl2.ps1 not found in project root" "Error"
    }
} else {
    Write-Log "Setup skipped. Run manually when ready:" "Info"
    Write-Host "  .\setup-wsl2.ps1"
    Write-Host "  or double-click: setup-wsl2.bat"
}

Write-Host ""
