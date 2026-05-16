# MDT — Claude Instructions

## Project
Microsoft Deployment Toolkit (MDT) deployment share for Windows OS rollout across multiple locations (mcfit.com). Covers two business units: **Office** (IT Infrastruktur) and **DST** (Digitale Studiotechnik).

## Structure
- `Control/` — MDT configuration: `CustomSettings.ini`, `Bootstrap.ini`, task sequence XMLs (`ts.xml`), `Unattend.xml` per deployment profile
- `Scripts/` — Deployment scripts: standard MDT scripts (ZTI*/LTI*) and custom scripts
- `Scripts/DST/` — DST-specific scripts (network, wallpaper, users)
- `Scripts/Office/` — Office-location-specific scripts
- `Scripts/AutoPilot/` — Windows Autopilot integration
- `Applications/` — App deployment packages (PSAppDeployToolkit-based)

## Script Languages
- `.wsf` / `.vbs` — Windows Script Host (MDT standard + custom UserExit scripts). No bash equivalents — these run only in Windows PE / Windows.
- `.ps1` — PowerShell for modern tasks (BIOS update, Autopilot, cleanup)
- `.hta` — HTA dialogs for custom wizard pages
- `.cmd` / `.bat` — Simple batch wrappers
- `.xml` — MDT task sequences and wizard definitions
- `.ini` — MDT rules (`CustomSettings.ini`, `Bootstrap.ini`)

## Key Conventions
- `CustomSettings.ini` uses MDT priority/subsection logic — order of sections in `Priority=` matters
- UserExit scripts (`UserExit-*.vbs`) are loaded via `ExitScripts` in `CustomSettings.ini`
- `ModelAlias` / `MakeAlias` drive driver selection — defined in `UserExit-Alias.vbs`
- Deployment server UNC paths follow pattern `\\<site-server>\MDTDeployment$`
- Task sequence IDs: `DST_ML`, `D_W10`, `W10_V3`, `SK9`, `WIN7_OEM`, `CAPTURE`, `REF_WIN10_1809`

## Locations
`CustomSettings.ini` detects location by default gateway:

| Gateway prefix | Location | MDT server |
|---|---|---|
| 10.0.x.1 | Berlin | DEBLNDT01 |
| 10.1.x.1 | SLF | DESLFDT01 |
| 10.4.x.1 | Wien | — |
| 10.5.x.1 | Madrid | ESMADDT02 |
| 10.6.x.1 | Mailand | ITMILDT01 |
| 10.7.x.1 | Warschau | PLWARDT01 |
| 10.9.x.1 | Oberhausen | DEOBDT01 |

## Domain
`int.mcfit.com` — standard OU: `OU=.MCFIT,DC=int,DC=mcfit,DC=com`
Computer OU path pattern: `OU=<Workstations|Notebooks>,OU=Computer,OU=<site>,<StandardOU>`
