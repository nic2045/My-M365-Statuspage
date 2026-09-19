<#
.SYNOPSIS
    Setup WSL2 + Docker environment for M365 Statuspage on Windows

.DESCRIPTION
    Installs and configures WSL2, Docker Desktop, and project dependencies.
    Includes error handling and recovery options.

.PARAMETER Help
    Show this help message

.PARAMETER CleanStart
    Start fresh: remove all Docker containers/images and WSL2 distro

.PARAMETER SkipWSL
    Skip WSL2 checks (assumes already installed)

.PARAMETER SkipDocker
    Skip Docker checks (assumes already installed)

.EXAMPLE
    .\setup-wsl2.ps1
    .\setup-wsl2.ps1 -CleanStart
    .\setup-wsl2.ps1 -Help

.NOTES
    Requires: Windows 10/11, Administrator privileges
    Installation takes ~5-10 minutes depending on internet speed
#>

param(
    [switch]$Help,
    [switch]$CleanStart,
    [switch]$SkipWSL,
    [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Colors for output
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
║  M365 Statuspage - WSL2/Docker Setup for Windows                       ║
╚════════════════════════════════════════════════════════════════════════╝

USAGE:
  .\setup-wsl2.ps1 [OPTIONS]

OPTIONS:
  -Help           Show this message
  -CleanStart     Remove existing WSL2 distro & Docker containers
  -SkipWSL        Skip WSL2 validation (assumes installed)
  -SkipDocker     Skip Docker validation (assumes installed)

REQUIREMENTS:
  • Windows 10 (21H2+) or Windows 11
  • 8GB+ RAM (16GB recommended)
  • Administrator privileges
  • ~30GB free disk space

WHAT THIS SCRIPT DOES:
  1. Verify Windows version compatibility
  2. Enable WSL2 and Hyper-V features
  3. Install Ubuntu 24.04 LTS distro (if needed)
  4. Verify Docker Desktop installation
  5. Configure WSL2 resources
  6. Clone repo and install dependencies

TROUBLESHOOTING:
  • Virtualization disabled in BIOS?
    → Restart and enable VT-x/AMD-V in BIOS settings

  • Docker Desktop won't start?
    → Check Event Viewer > Windows Logs > System for Hyper-V errors

  • Out of disk space?
    → WSL2 default size is ~256GB virtual
    → Check: wsl --list --verbose

  • Permission denied errors?
    → Run PowerShell as Administrator

EXAMPLES:
  Clean install (remove everything first):
    .\setup-wsl2.ps1 -CleanStart

  Skip checks (faster, if you know everything is ready):
    .\setup-wsl2.ps1 -SkipWSL -SkipDocker

For more info: https://github.com/nic2045/My-M365-Statuspage
"@
}

function Test-Admin {
    $isAdmin = [bool]([System.Security.Principal.WindowsIdentity]::GetCurrent().Groups -match 'S-1-5-32-544')
    if (-not $isAdmin) {
        Write-Log "This script requires Administrator privileges" "Error"
        Write-Log "Please run PowerShell as Administrator and try again" "Info"
        exit 1
    }
}

function Test-WindowsVersion {
    $version = [System.Environment]::OSVersion.Version
    $releaseId = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -Name "ReleaseID" -ErrorAction SilentlyContinue).ReleaseId

    if ($version.Major -lt 10) {
        Write-Log "Windows 10+ required (you have $version)" "Error"
        exit 1
    }

    if ($version.Build -lt 19041) {
        Write-Log "Windows 10 21H2+ or Windows 11 required (build: $($version.Build))" "Error"
        Write-Log "Please update Windows and try again" "Info"
        exit 1
    }

    Write-Log "Windows version $version (build $($version.Build)) ✓" "Success"
}

function Enable-WSLFeatures {
    if ($SkipWSL) {
        Write-Log "Skipping WSL2 checks" "Info"
        return
    }

    Write-Log "Checking Windows features..." "Info"

    $features = @("Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform")

    foreach ($feature in $features) {
        $state = (Get-WindowsOptionalFeature -Online -FeatureName $feature -ErrorAction SilentlyContinue).State

        if ($state -ne "Enabled") {
            Write-Log "Enabling $feature..." "Warning"
            Enable-WindowsOptionalFeature -Online -FeatureName $feature -NoRestart -ErrorAction Stop | Out-Null
        }
    }

    Write-Log "Windows features enabled ✓" "Success"
    Write-Log "You may need to restart your computer" "Warning"
}

function Install-WSLDistro {
    if ($SkipWSL) { return }

    Write-Log "Checking WSL2 distributions..." "Info"

    try {
        $distros = wsl --list --quiet 2>$null
        if ($distros -match "Ubuntu") {
            Write-Log "Ubuntu WSL2 distro already installed ✓" "Success"
            return
        }
    } catch {
        Write-Log "WSL2 command failed - may need restart" "Warning"
    }

    Write-Log "Installing Ubuntu 24.04 LTS from Microsoft Store..." "Info"
    Write-Log "Please wait, this may take 2-3 minutes..." "Info"

    $storeUri = "ms-windows-store://pdp/?ProductId=9NZ3KJ0F5FBK"
    Start-Process $storeUri

    Write-Log "Microsoft Store opened - please install 'Ubuntu 24.04 LTS'" "Warning"
    Write-Log "Once installed, re-run this script" "Warning"
    exit 0
}

function Set-WSLConfig {
    if ($SkipWSL) { return }

    Write-Log "Configuring WSL2 resources..." "Info"

    # Set WSL2 as default
    try {
        wsl --set-default-version 2 2>$null
    } catch {
        Write-Log "Could not set WSL2 default (may need restart)" "Warning"
    }

    # Create/update .wslconfig for resource limits
    $wslConfigPath = "$env:USERPROFILE\.wslconfig"
    $wslConfig = @"
[wsl2]
memory=4GB
processors=4
swap=2GB
localhostForwarding=true
"@

    if (-not (Test-Path $wslConfigPath)) {
        Set-Content -Path $wslConfigPath -Value $wslConfig -ErrorAction Stop
        Write-Log "Created ~/.wslconfig with resource limits" "Success"
    }
}

function Test-DockerDesktop {
    if ($SkipDocker) {
        Write-Log "Skipping Docker checks" "Info"
        return
    }

    Write-Log "Checking Docker Desktop..." "Info"

    # Check if Docker CLI is available
    $dockerPath = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $dockerPath) {
        Write-Log "Docker not found in PATH" "Error"
        Write-Log "Please install Docker Desktop from https://www.docker.com/products/docker-desktop" "Info"
        exit 1
    }

    # Check if Docker daemon is running
    try {
        docker ps 2>&1 | Out-Null
        Write-Log "Docker Desktop running ✓" "Success"
    } catch {
        Write-Log "Docker daemon not responding" "Error"
        Write-Log "Please start Docker Desktop and try again" "Info"
        exit 1
    }
}

function Test-GitInstalled {
    Write-Log "Checking Git installation..." "Info"

    $gitPath = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitPath) {
        Write-Log "Git not found" "Error"
        Write-Log "Please install Git from https://git-scm.com/download/win" "Info"
        exit 1
    }

    Write-Log "Git $(git --version) ✓" "Success"
}

function Clean-Environment {
    if (-not $CleanStart) { return }

    Write-Log "Clean start requested - removing existing setup..." "Warning"

    # Stop Docker containers
    Write-Log "Stopping Docker containers..." "Info"
    try {
        docker compose down -v 2>$null
        docker system prune -f 2>$null
    } catch {
        Write-Log "Could not clean Docker (may not be running)" "Warning"
    }

    # Remove WSL distro
    Write-Log "Removing WSL Ubuntu distro..." "Warning"
    try {
        wsl --unregister Ubuntu-24.04 2>$null
        Write-Log "WSL distro removed" "Success"
    } catch {
        Write-Log "Could not remove distro (may not exist)" "Warning"
    }
}

function Install-Dependencies {
    Write-Log "Installing project dependencies inside WSL2..." "Info"

    # Run setup inside WSL
    $setupCmd = @"
#!/bin/bash
set -e
echo "[Info] Updating package manager..."
sudo apt-get update -qq
echo "[Info] Installing Node.js (via nvm)..."
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - 2>/dev/null
sudo apt-get install -y nodejs 2>&1 | grep -v "^Get:\|^Hit:\|^Reading\|^Building" || true
echo "[Info] Installing uv (Python package manager)..."
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.cargo/env 2>/dev/null || true
echo "[Info] Done! Next steps:"
echo "  1. cd /mnt/c/path/to/My-M365-Statuspage"
echo "  2. make install"
echo "  3. make docker"
"@

    Write-Log "Opening WSL2 terminal for dependency installation..." "Info"

    # Write setup script
    $setupFile = "$env:TEMP\wsl-setup.sh"
    Set-Content -Path $setupFile -Value $setupCmd

    # Execute in WSL
    wsl bash $setupFile
}

function Show-Summary {
    Write-Host @"

╔════════════════════════════════════════════════════════════════════════╗
║  ✓ Setup Complete                                                      ║
╚════════════════════════════════════════════════════════════════════════╝

NEXT STEPS:
  1. Open PowerShell or WSL Terminal
  2. Navigate to project: cd My-M365-Statuspage
  3. Start development:
     • make docker        (start with Docker)
     • make install       (install dependencies only)
     • make dev          (run dev server directly)

USEFUL COMMANDS:
  wsl --list --verbose          List WSL distros
  wsl --terminate Ubuntu-24.04  Stop WSL (save RAM)
  docker compose logs -f        View app logs
  docker compose exec statuspage bash  Shell in container

DOCUMENTATION:
  • WSL2: https://learn.microsoft.com/en-us/windows/wsl/
  • Docker: https://docs.docker.com/desktop/install/windows-install/
  • Makefile targets: make help

"@
}

# ───────────────────────────────────────────────────────────────────
# Main execution
# ───────────────────────────────────────────────────────────────────

if ($Help) {
    Show-Help
    exit 0
}

Write-Host ""
Write-Log "Starting M365 Statuspage WSL2 setup..." "Info"
Write-Host ""

try {
    Test-Admin
    Test-WindowsVersion
    Enable-WSLFeatures
    Install-WSLDistro
    Set-WSLConfig
    Test-GitInstalled
    Test-DockerDesktop
    Clean-Environment
    Install-Dependencies
    Show-Summary
} catch {
    Write-Log "Setup failed: $_" "Error"
    Write-Log "Common solutions:" "Info"
    Write-Host @"
  1. Run as Administrator
  2. Restart your computer (especially after enabling features)
  3. Check Event Viewer for Hyper-V errors
  4. Ensure virtualization is enabled in BIOS
  5. Free up disk space (~30GB needed)

For more help: .\setup-wsl2.ps1 -Help
"@
    exit 1
}
