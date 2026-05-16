# Script-Libary — Claude Instructions

@../CLAUDE.md

## Commit Conventions (Conventional Commits)

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/).
release-please uses commit messages to calculate version bumps automatically.

| Prefix | Semver effect | When to use |
|--------|---------------|-------------|
| `feat: ...` | minor (1.0.x → 1.1.0) | New script or new function |
| `fix: ...` | patch (1.0.3 → 1.0.4) | Bug fix, behaviour correction |
| `chore: ...` | no bump | CI, tools, dependencies, formatting |
| `docs: ...` | no bump | README, comments, examples |
| `refactor: ...` | no bump | Restructuring without behaviour change |
| `feat!: ...` / `BREAKING CHANGE` | major (1.x → 2.0.0) | Backwards-incompatible change |

## Release Workflow (fully automated)

1. Create feature branch → commit changes → PR to `master`
2. After merge: release-please automatically opens a **Release PR**
   - Updates `CHANGELOG.md`, `version.txt`, `Modules/NDTools/NDTools.psd1`
3. Review and merge Release PR → GitHub Release + tag are created
4. Scripts with `# Version:` header are automatically stamped with the new version

**Never edit manually:** `version.txt`, `CHANGELOG.md`, `.release-please-manifest.json`

## Branch Strategy

- `master` — stable, always deployment-ready
- Feature branches: `feat/<topic>` or Claude Code generated names
- One branch per feature, PR to master

## Keep Documentation Up to Date

On every change to the collection:

- **New Script**: Add Comment-Based Help at the top (`.SYNOPSIS`, `.DESCRIPTION`, `.EXAMPLE`, `.NOTES` with area and prerequisites). Template: [CountMigration.ps1](Scripts/Exchange/Online/Migration/CountMigration.ps1)
- **New Module Function**: Comment-Based Help in the `.ps1` file under `Modules/NDTools/Public/`. Template: [Connect-MSCloudConnections.ps1](Modules/NDTools/Public/Core/Connect-MSCloudConnections.ps1)
- **New folder in `Scripts/`**: Update the Structure section in [README.md](README.md)
- **Module published**: Update `ReleaseNotes` in [NDTools.psd1](Modules/NDTools/NDTools.psd1)

## Repo Structure

```
Modules/NDTools/   PowerShell module (shared cmdlets)
Build/             Publish script for GitHub Packages
Scripts/
  Azure/           Azure Backup scripts
  Endpoint/        Scripts executed on Windows client
  EntraID/         CA policies, Groups, Licenses, Users
  Exchange/OnPrem/ Exchange 2016
  Exchange/Online/ Exchange Online + Migration/
  Intune/          Compliance reports
  KI/              AI tools
  Teams/           Microsoft Teams
_Archiv/           Deprecated files and export reports
```

## Key Files

| File / Directory | Purpose |
|---|---|
| `Modules/NDTools/` | Shared module: Connect, Config, Helpers |
| `Scripts/` | Admin scripts for production use |
| `Templates/Script.Template.ps1` | Template for new scripts |
| `Config/Config.psd1` | Local org config (**gitignored**, never commit) |
| `Config/Config.Example.psd1` | Template for Config.psd1 (versioned) |
| `PSScriptAnalyzerSettings.psd1` | Central linting rules |
| `version.txt` | Current library version (managed by release-please) |
| `CHANGELOG.md` | Release history (managed by release-please) |

## Module Distribution

Module is distributed via GitHub Packages (`nic2045`).
Publish: `.\Build\Publish-NDTools.ps1 -Token "ghp_TOKEN"`
Install: `Install-Module NDTools -Repository GitHubPackages -Credential $cred`
