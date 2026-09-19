# Windows WSL2 + Docker Setup Guide

Automated setup for running M365 Statuspage on Windows 10/11 with WSL2 and Docker Desktop.

## Quick Start

**1. Open PowerShell as Administrator** and run:

```powershell
cd C:\path\to\My-M365-Statuspage
.\setup-wsl2.ps1
```

**Or simply double-click:** `setup-wsl2.bat`

That's it! The script will:
- ✓ Verify Windows version
- ✓ Enable WSL2 features
- ✓ Install Ubuntu 24.04 LTS
- ✓ Configure Docker Desktop
- ✓ Set resource limits

---

## System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| OS | Windows 10 21H2+ | Windows 11 |
| RAM | 8 GB | 16 GB |
| Disk | 30 GB free | 50 GB free |
| CPU | Dual-core | Quad-core |
| Virtualization | VT-x/AMD-V enabled | Enabled in BIOS |

### Check Your System

```powershell
# Check Windows version
[System.Environment]::OSVersion.Version

# Check RAM
Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize

# Check free disk space
Get-Volume C | Select-Object SizeRemaining
```

---

## Setup Options

### Basic Setup (Recommended)
```powershell
.\setup-wsl2.ps1
```

### Clean Install (Remove Everything First)
```powershell
.\setup-wsl2.ps1 -CleanStart
```
⚠️ This removes all Docker containers and the WSL2 distro.

### Skip Checks (If You Know What You're Doing)
```powershell
.\setup-wsl2.ps1 -SkipWSL -SkipDocker
```

### Get Help
```powershell
.\setup-wsl2.ps1 -Help
```

---

## What Gets Installed

| Component | Version | Purpose |
|-----------|---------|---------|
| WSL2 | Built-in | Linux kernel for Windows |
| Ubuntu | 24.04 LTS | Linux distribution |
| Docker Desktop | Latest | Container runtime |
| Docker Compose | Latest | Multi-container orchestration |
| Node.js | 20.x | Frontend tooling (npm, build) |
| uv | Latest | Python package manager |
| Python | 3.12 | Backend runtime |

---

## After Setup

### 1. Start Development Environment

```powershell
# Option A: Docker (recommended)
cd My-M365-Statuspage
make docker

# Option B: Direct (requires local Python/Node)
make install
make dev
```

### 2. Access the App

- **Web UI**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

### 3. Common Commands

```powershell
# Follow logs
make logs

# Open shell in container
make shell

# Run tests
make test

# Run linter
make lint

# Stop everything
make stop
```

---

## Troubleshooting

### "Administrator privileges required"
```powershell
# Right-click PowerShell → Run as Administrator
# Then run the script again
```

### "WSL2 not found" or "Kernel update required"
```powershell
# Update WSL2 kernel
wsl --update

# Restart Windows after update
```

### "Docker daemon not responding"
```powershell
# Make sure Docker Desktop is running
# Check: Settings > Resources > WSL integration is enabled

# If still failing:
docker ps
# If this fails, restart Docker Desktop
```

### "Out of disk space"
```powershell
# Check WSL disk usage
wsl df -h

# Clean Docker
docker system prune -a

# Expand WSL disk (advanced)
# See: https://learn.microsoft.com/en-us/windows/wsl/disk-space
```

### "Virtualization disabled in BIOS"
1. Restart computer
2. Enter BIOS (typically F2, F10, Del, or Esc during boot)
3. Find "Virtualization Technology" or "VT-x" setting
4. Enable it
5. Save and restart

### "Permission denied" in WSL terminal
```bash
# Inside WSL, fix permissions
sudo chown -R $USER:$USER /mnt/c/Users/$WINDOWS_USER/...
```

### "Port 8000 already in use"
```powershell
# Find process using port 8000
netstat -ano | findstr :8000

# Kill the process
taskkill /PID <PID> /F

# Or use different port
$env:PORT = "8001"
make dev
```

---

## Resource Configuration

The script creates `~\.wslconfig` with:

```ini
[wsl2]
memory=4GB
processors=4
swap=2GB
localhostForwarding=true
```

**Adjust these values** if you have different hardware:

```ini
[wsl2]
memory=8GB          # Increase for better performance
processors=8        # Match your CPU cores
swap=4GB
```

Then restart WSL:
```powershell
wsl --shutdown
wsl
```

---

## WSL2 Management

```powershell
# List distros
wsl --list --verbose

# Set default distro
wsl --set-default Ubuntu-24.04

# Stop WSL (frees RAM)
wsl --shutdown

# Open WSL terminal
wsl

# Run commands in WSL
wsl make docker
wsl npm run build:css
```

---

## Docker Desktop Settings

**Recommended settings** in Docker Desktop:

- **Resources > Memory**: 4-8 GB
- **Resources > CPU**: 4-8 cores
- **Resources > Swap**: 2-4 GB
- **WSL Integration**: Enable "Ubuntu-24.04"
- **Docker Engine > Live Restore**: Enable

---

## Development Workflow

### 1. Terminal in Windows PowerShell

```powershell
# Navigate to project
cd C:\Users\YourName\Projects\My-M365-Statuspage

# Start dev environment
make docker

# In another PowerShell window, follow logs
make logs
```

### 2. Using WSL Terminal

```powershell
# Open WSL terminal
wsl

# Inside WSL:
cd /mnt/c/Users/YourName/Projects/My-M365-Statuspage
make docker
```

### 3. VS Code Integration

**Best experience**: Install ["Remote - WSL" extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-wsl)

```powershell
# Open VS Code in WSL
wsl code .

# Or from VS Code: Remote Explorer > WSL
```

---

## Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| Setup hangs | Network issues | Check internet, retry |
| Docker fails to start | Hyper-V disabled | Enable in Windows Features |
| WSL command not found | Not installed | Run setup script again |
| Permission errors | File ownership | Use `sudo chown` in WSL |
| Slow performance | Insufficient resources | Increase memory in .wslconfig |
| Port conflicts | Another app using port | Change port or kill process |

---

## Uninstall / Cleanup

```powershell
# Remove just the distro (keep Docker Desktop)
wsl --unregister Ubuntu-24.04

# Clean Docker (containers, images, volumes)
docker system prune -a

# Uninstall Docker Desktop
# Settings > Apps > Installed apps > Docker Desktop > Uninstall
```

---

## Advanced Topics

### Mount a Different Drive

```powershell
# Edit ~/.wslconfig
[interop]
appendWindowsPath = true

# Then access from WSL:
# /mnt/d  → D: drive
# /mnt/e  → E: drive
```

### Configure Firewall

If you can't access localhost:8000 from other machines:

```powershell
# Allow through Windows Firewall
New-NetFirewallRule -DisplayName "WSL2 Docker" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 8000
```

### Enable GPU Support

If you have an NVIDIA GPU:

```bash
# Inside WSL, check NVIDIA support
nvidia-smi

# Then in docker-compose.yml
services:
  statuspage:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

---

## Getting Help

- **Script help**: `.\setup-wsl2.ps1 -Help`
- **WSL docs**: https://learn.microsoft.com/windows/wsl/
- **Docker docs**: https://docs.docker.com/
- **Repository**: https://github.com/nic2045/My-M365-Statuspage
- **Issues**: https://github.com/nic2045/My-M365-Statuspage/issues

---

## Next Steps

1. **Verify Installation**
   ```powershell
   docker ps
   wsl --list -v
   ```

2. **Start Development**
   ```powershell
   make docker
   ```

3. **Read Documentation**
   - Check `README.md` for project overview
   - Check `Makefile` for available commands
   - Check `.env.example` for configuration options

---

## Performance Tips

✓ **Fast SSD** (NVMe) – WSL performance depends heavily on storage  
✓ **Allocate 4+ cores** – Most dev work needs parallelism  
✓ **8+ GB RAM** – Docker + app needs headroom  
✓ **Update regularly** – `wsl --update` and Docker updates  
✓ **Use WSL volumes** – Store project in `/home` not `/mnt/c`  

---

**Last updated**: September 2026  
**Windows versions tested**: Windows 10 21H2, Windows 11
