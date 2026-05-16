# dotfiles

Personal environment configuration — Claude Code instructions for all projects.

## Structure

```
dotfiles/
  claude/
    CLAUDE.md              # Global instructions — loaded for every project
    projects/
      ha-garden-water.md   # HA blueprint rules, versioning convention
      JIRA_WeeklyUpdater.md
      Script-Libary.md
      SW-Deployment.md
      ADGroupChecker.md
      PS-Script-Libary.md
      MDT.md
      RSG-Intune.md
  git-templates/
    hooks/
      post-checkout        # Auto-links CLAUDE.md on git clone
  gitconf/
    gitignore_global       # Global gitignore (macOS, Windows, Editor, Secrets)
  setup.sh                 # Run once on a new machine
  add-project.sh           # Add a new project and link it immediately
```

## Architecture

Source of truth: `dotfiles` repo on GitHub
├── claude/CLAUDE.md → copied to ~/.claude/CLAUDE.md (global)
├── claude/projects/*.md → symlinked to ~/Coding/<project>/CLAUDE.md (per-project)
├── git-templates/hooks/post-checkout → installed to ~/.git-templates (auto-link on clone)
├── gitconf/gitignore_global → configured as core.excludesfile (all repos)
└── vscode-extensions/dotfiles-check → auto-sync every 6 hours

How it flows:
1. Clone dotfiles repo → run setup.sh once
2. setup.sh creates symlinks to all known projects
3. VSCode extension runs in background: every 6h, fetch origin → pull if behind
4. Edit any dotfiles file → change propagates via symlink to all repos
5. Multiple machines: all run VSCode extension → all sync to same GitHub state

## How it works

- **Global** (`~/.claude/CLAUDE.md`) — Claude Code loads this automatically for every project. Contains cross-project rules and preferences.
- **Per-project** (`<repo>/CLAUDE.md`) — Claude Code loads this when working in a specific repo. Symlinked from `dotfiles/claude/projects/` so there is a single source of truth.
- **Global gitignore** — Applied to every git repo without touching project `.gitignore` files.
- **post-checkout hook** — Fires automatically after `git clone` for any `nic2045` repo and calls `add-project.sh` to link `CLAUDE.md` if none exists yet.
- **Symlinks everywhere** — Editing a file in `dotfiles/` immediately takes effect everywhere via the symlink — no copy needed.
- **Background sync** — VSCode extension `dotfiles-check` runs every 6 hours: fetch origin, detect if behind, auto-stash local changes, pull. Status shown in status bar.

---

## Setup Flow

What `bash ~/dotfiles/setup.sh` does:

1. Copy global instructions
   ~/.claude/CLAUDE.md ← ~/dotfiles/claude/CLAUDE.md (symlink, absolute path)

2. Configure git globally
   core.excludesfile → dotfiles/gitconf/gitignore_global
   alias.ignored → custom git alias
   dotfiles.dir → dotfiles repo location (used by git hooks)

3. Install git hook template
   ~/.git-templates/hooks/post-checkout ← dotfiles/git-templates/hooks/post-checkout
   init.templateDir → ~/.git-templates
   (will run on future `git clone` for nic2045 repos)

4. Create relative symlinks for all known projects
   For each project in dotfiles/claude/projects/:
   If ~/Coding/<project>/ exists:
     → symlink ~/Coding/<project>/CLAUDE.md to ../dotfiles/claude/projects/<project>.md (relative)
     → uses Python to calculate optimal relative path
     → if Python unavailable, falls back to standard layout path
   Else:
     → skip with warning

Result: All symlinks created. Future git clones auto-link via post-checkout hook.

5. Install VSCode extension separately (see next section)

## VSCode Extension: vscode-dotfiles-check

The background sync extension lives in a separate repo (no circular dependency).

**Install from source** (during development):
```bash
git clone git@github.com:nic2045/vscode-dotfiles-check.git ~/Coding/vscode-dotfiles-check
bash ~/Coding/vscode-dotfiles-check/install.sh
```

**Or install from VSCode Marketplace** (when available):
Extensions → Search "Dotfiles Check" → Install

The extension will:
- Run on VSCode startup
- Schedule 6h background syncs of ~/Coding/dotfiles
- Auto-pull if behind origin/main
- Show status in status bar, notifications on sync

## Symlink Logic

All files in dotfiles repo are symlinked, not copied. Single source of truth.

**macOS / Linux / Windows (Git Bash)** — Relative symlinks:
Scripts automatically create relative symlinks:
```
~/Coding/ha-garden-water/CLAUDE.md → ../dotfiles/claude/projects/ha-garden-water.md
```
Relative paths are portable: work on any machine without path adjustment.

How setup.sh does it:
1. Calculate relative path from target to source using Python
2. Create symlink with relative path
3. Fallback: use `../dotfiles/claude/projects/...` for standard layout

**Windows (PowerShell without Developer Mode)** — Manual step required:
Symlinks require Developer Mode on Windows. If unavailable, create hard link manually:
```powershell
New-Item -ItemType HardLink `
  -Path "C:\Users\<user>\Coding\ha-garden-water\CLAUDE.md" `
  -Target "C:\Users\<user>\Coding\dotfiles\claude\projects\ha-garden-water.md"
```
Caveat: `git pull` in dotfiles rewrites files (new inode) → hard link breaks. Re-create if needed.

**Edit strategy**: Edit in the symlink (project repo) or in source (dotfiles repo) — both stay in sync automatically via symlink.

---

## Background Sync: dotfiles-check Extension

Logic:

VSCode startup
→ dotfiles-check extension activates
→ verify dotfiles exists
→ show status in status bar
→ schedule background task: every 6 hours

Every 6 hours:
1. cd ~/Coding/dotfiles
2. Check git status
   - Has local changes? Auto-stash them (safe save)
   - Clean? Continue
3. git fetch origin main (check what's new)
4. Compare local HEAD vs origin/main
   - Behind? Pull the changes
   - Up-to-date? Skip
5. Update status bar icon and log

User can also:
- Click status bar icon → sync immediately
- Command Palette → "Dotfiles: Sync Now"

Notifications appear:
- ✓ Dotfiles synced (success)
- ⚠ Sync failed: <reason> (error)

Full log visible in View → Output → "Dotfiles Check"

---

## Multi-Machine Sync Example

Scenario: Two machines, both running VSCode with dotfiles-check extension.

Initial state:
  Machine A (macOS): ~/Coding/dotfiles cloned, setup.sh run
  Machine B (Linux): ~/Coding/dotfiles cloned, setup.sh run
  Both: VSCode installed with dotfiles-check extension
  GitHub: origin/main HEAD = commit X

Timeline:

Step 1 — Machine A makes a change
  User edits ~/Coding/dotfiles/claude/CLAUDE.md (or via symlink in any project)
  Machine A commits & pushes
  GitHub: origin/main HEAD = commit Y

Step 2 — Machine A's extension syncs
  Next background sync: fetch origin → already at origin/main
  No action needed

Step 3 — Machine B's extension syncs (6h later, or user clicks manually)
  Background sync: fetch origin → sees origin/main = commit Y
  Machine B HEAD = commit X (behind)
  Auto-pull: git pull origin main
  Local files updated
  Symlinks propagate changes to all projects
  Notification: ✓ Dotfiles synced
  ~/.claude/CLAUDE.md automatically reflects Machine A's edit

Result: Both machines in sync, single source of truth on GitHub.

---

## Setup: macOS / Linux

Prerequisites: Git, Claude Code CLI, Python 3 (for relative path calculation).

```bash
git clone git@github.com:nic2045/dotfiles.git ~/Coding/dotfiles
bash ~/Coding/dotfiles/setup.sh
```

`setup.sh` autodetects your environment and:
1. Symlinks `~/.claude/CLAUDE.md` → `~/Coding/dotfiles/claude/CLAUDE.md`
2. Sets git config: `core.excludesfile`, `alias.ignored`, `dotfiles.dir`
3. Installs `git-templates/hooks/post-checkout` for auto-linking on future clones
4. Creates relative symlinks for all known projects at `~/Coding/<repo-name>`
5. Installs VSCode extension (reads version from package.json)

Repos are expected at `~/Coding/<repo-name>`. Missing repos are skipped with a warning.

If Python is unavailable, setup falls back to standard relative path format (`../dotfiles/...`).

Verify symlinks were created correctly:
```bash
readlink ~/Coding/ha-garden-water/CLAUDE.md
# Should show relative path like: ../dotfiles/claude/projects/ha-garden-water.md
```

---

## Setup: Windows

### Option A: Git Bash (Recommended)

**Prerequisites**: 
- Git for Windows (includes Git Bash)
- Claude Code CLI
- Developer Mode (recommended, but setup works without it)
- Python 3

**Activate Developer Mode** (one-time, no reboot needed):
```powershell
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" /t REG_DWORD /f /v AllowDevelopmentWithoutDevLicense /d 1
```

Or manually: Settings → System → For developers → Developer Mode → On.

**Install dotfiles** — Open **Git Bash** (not PowerShell or CMD):
```bash
git clone git@github.com:nic2045/dotfiles.git ~/Coding/dotfiles
bash ~/Coding/dotfiles/setup.sh
```

`setup.sh` detects Windows and runs the same logic as macOS:
- Creates relative symlinks (if Developer Mode active)
- If Developer Mode inactive: symlinks still created (Git Bash can use them), but PowerShell cannot see them

**Verify symlinks**:
```bash
# Git Bash
readlink ~/Coding/ha-garden-water/CLAUDE.md
# Should show: ../dotfiles/claude/projects/ha-garden-water.md
```

### Option B: PowerShell (Manual Symlinks)

If you prefer PowerShell or cannot use Developer Mode, create symlinks manually:

```powershell
# For each project:
New-Item -ItemType SymbolicLink `
  -Path "C:\Users\<username>\Coding\ha-garden-water\CLAUDE.md" `
  -Target "C:\Users\<username>\Coding\dotfiles\claude\projects\ha-garden-water.md"
```

Run `setup.sh` in Git Bash for everything else (git config, hooks, etc.).

### Hard Link Fallback (Developer Mode Unavailable)

If symbolic links fail, create hard links (manual, one-time):
```powershell
New-Item -ItemType HardLink `
  -Path "C:\Users\<username>\Coding\<repo>\CLAUDE.md" `
  -Target "C:\Users\<username>\Coding\dotfiles\claude\projects\<repo>.md"
```

**Caveat**: Hard links break when `git pull` rewrites dotfiles (new inode). Re-create them after pulling.

### Path Mapping

Git Bash on Windows:
- `~` = `C:\Users\<username>` (from `$HOME`)
- `~/Coding/` = `C:\Users\<username>\Coding\`

If your repos are at `C:\Users\<username>\Documents\Coding\`, either:
1. Move repos to `~/Coding/` (recommended)
2. Edit `setup.sh` and change `CODING_DIR` lines

---

## Integrating into an existing setup

If git repos and config already exist on the machine, run `setup.sh` only after resolving the conflicts below. The script is otherwise safe to re-run.

### 1 — Existing `~/.claude/CLAUDE.md`

`setup.sh` overwrites this file with a plain `cp`. If a custom `CLAUDE.md` already exists:

```bash
# Compare before running setup
diff ~/.claude/CLAUDE.md ~/dotfiles/claude/CLAUDE.md
```

Merge any local additions into `dotfiles/claude/CLAUDE.md` first, commit them, then run `setup.sh`.

### 2 — Existing global gitignore (`core.excludesfile`)

`setup.sh` sets `core.excludesfile` to `dotfiles/gitconf/gitignore_global`. Any previously configured file is replaced. Check first:

```bash
git config --global core.excludesfile
```

If a file is already set, copy its contents into `dotfiles/gitconf/gitignore_global`, commit, then run `setup.sh`.

### 3 — Existing `init.templateDir`

`setup.sh` sets `init.templateDir` to `~/.git-templates`. If another template dir is already configured:

```bash
git config --global init.templateDir
```

If it points somewhere else, either copy relevant hooks from there into `~/.git-templates/hooks/` after setup, or manually merge hook logic into `dotfiles/git-templates/hooks/post-checkout`.

### 4 — Existing repos (already cloned before dotfiles setup)

The `post-checkout` hook only fires on **new** clones. Repos that already exist on the machine get no symlink automatically. Link them manually:

```bash
# macOS / Git Bash on Windows
bash ~/dotfiles/add-project.sh <repo-name>
```

Or re-run `setup.sh` — it iterates over all known projects and creates the symlink if the repo folder exists.

To check which repos are missing a link:

```bash
# List known projects and whether a CLAUDE.md symlink exists
for md in ~/dotfiles/claude/projects/*.md; do
  name=$(basename "$md" .md)
  target=~/Coding/$name/CLAUDE.md
  if [ -L "$target" ]; then
    echo "✓ $name"
  elif [ -d ~/Coding/$name ]; then
    echo "✗ $name  (repo exists, no symlink)"
  else
    echo "– $name  (repo not cloned)"
  fi
done
```

### 5 — Repos at non-standard paths

`setup.sh` hardcodes `~/Coding/<repo-name>`. If repos live elsewhere (e.g., `~/Documents/Coding/` on Windows), either:

- **Adjust `setup.sh`** — change the `link` calls for affected repos to use the actual path, then commit
- **Or symlink manually** — `ln -sf ~/dotfiles/claude/projects/<repo>.md <actual-path>/CLAUDE.md`

The `add-project.sh` script also assumes `~/Coding/` — edit `REPO=` on line 16 if needed.

---

## Adding a new project

### Option A — manual

1. Create `claude/projects/<repo-name>.md` with project-specific instructions
2. Add a `link` line to `setup.sh`
3. Re-run `bash ~/dotfiles/setup.sh` (safe to re-run — existing symlinks are overwritten)
4. Commit and push

### Option B — script (macOS / Git Bash on Windows)

```bash
bash ~/dotfiles/add-project.sh <repo-name>
```

This creates the placeholder `.md`, adds the link to `setup.sh`, sets the symlink immediately (if the repo exists locally), and commits + pushes automatically.

### Option C — automatic on clone

When you clone any `nic2045` repo, the `post-checkout` hook fires and calls `add-project.sh` automatically. No manual step needed.

---

## Roadmap

- Shell config (`~/.zshrc` / PowerShell profile, aliases, PATH)
- SSH config skeleton
- macOS system preferences script
- Windows-native setup script (PowerShell) for machines without Git Bash
- App-specific configs (VS Code settings, keybindings)
