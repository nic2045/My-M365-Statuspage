# Script Audit — Path Handling & Cross-Platform Compatibility

**Status**: ✅ ALL FIXED + EXTENSION SEPARATED

## Issues Found & Fixed

### 1. ✅ setup.sh Line 19: Symlink vs Copy Mismatch
**Problem**: README said "copy" but code did symlink.

**Fixed**: Updated README to document symlink behavior (absolute path for `~/.claude/CLAUDE.md`, relative for project repos).
```bash
# Now (absolute symlink):
ln -sf "$DOTFILES/claude/CLAUDE.md" ~/.claude/CLAUDE.md

# Why: ~/.claude and ~/Coding are different parents, relative path would be complex
# Project repos use relative symlinks (both under ~/Coding)
```

---

### 2. ✅ setup.sh & add-project.sh: Absolute vs Relative Symlinks
**Problem**: Scripts created absolute symlinks; documentation said relative.

**Fixed**: Now creates relative symlinks for project repos:

**setup.sh** — Enhanced `link()` function:
```bash
link() {
  if [ -d "$2" ]; then
    # Calculate relative path from target to source using Python
    local rel_path=$(cd "$2" && python3 -c "import os.path; print(os.path.relpath('$1', '.'))" 2>/dev/null)
    # Fallback to standard layout: ../dotfiles/claude/projects/...
    if [ -z "$rel_path" ]; then
      rel_path="../dotfiles/$(echo "$1" | sed "s|.*/dotfiles/||")"
    fi
    ln -sf "$rel_path" "$2/CLAUDE.md"
  fi
}
```

**add-project.sh** — Same logic added (Line 51):
```bash
local rel_path=$(cd "$REPO" && python3 -c "import os.path; print(os.path.relpath('$PLACEHOLDER', '.'))" 2>/dev/null)
if [ -z "$rel_path" ]; then
  rel_path="../dotfiles/claude/projects/$NAME.md"
fi
ln -sf "$rel_path" "$REPO/CLAUDE.md"
```

**Portability**: Relative symlinks work across machines without path adjustment.
**Fallback**: If Python unavailable, uses standard `../dotfiles/...` pattern.

---

### 3. ✅ setup.sh Line 38: Typo in Project Name
**Problem**: `SW-Depoyment` (typo) should be `SW-Deployment`.

**Fixed**: Corrected to:
```bash
link "$DOTFILES/claude/projects/SW-Deployment.md"         "$CODING_DIR/SW-Deployment"
```

---

### 4. ✅ Windows Compatibility: Clarified Bash-Only Approach
**Problem**: Documentation mentioned PowerShell, but scripts are bash-only.

**Fixed**: README now clearly documents:
- **Primary approach**: Git Bash on Windows (same as macOS/Linux)
- **Alternative**: Manual PowerShell commands if preferred
- **Fallback**: Hard links if Developer Mode unavailable
- **Requirement**: Developer Mode recommended but not required (Git Bash works either way)

All scripts remain bash (portable across platforms), no PowerShell versions needed.

---

### 5. ✅ setup.sh Line 48: Hardcoded VSCode Extension Version
**Problem**: Version hardcoded to `1.0.0`. If bumped, symlink path becomes stale.

**Fixed**: Now reads version dynamically from package.json:
```bash
EXTENSION_VERSION=$(grep '"version"' "$DOTFILES/vscode-extensions/dotfiles-check/package.json" | head -1 | sed 's/.*"\([^"]*\)".*/\1/')
EXTENSION_DIR=~/.vscode/extensions/nico.dotfiles-check-$EXTENSION_VERSION
```
Auto-updates on version bump.

---

### 6. ✅ add-project.sh Line 51: Missing Relative Path Conversion
**Problem**: Created absolute symlinks.

**Fixed**: Now calculates and creates relative symlinks (same as setup.sh).

---

## Summary Table

| Issue | Status | Fix |
|-------|--------|-----|
| Symlink vs Copy mismatch | ✅ | Documentation clarified |
| Absolute paths (no portability) | ✅ | Relative symlinks + Python fallback |
| Typo: SW-Depoyment | ✅ | Corrected to SW-Deployment |
| Windows bash-only confusion | ✅ | README clarified Git Bash primary, alternatives listed |
| Hardcoded extension version | ✅ | Dynamic read from package.json |
| No relative path in add-project.sh | ✅ | Added Python-based relative path logic |
| Silent extension symlink errors | ✅ | Explicit log messages added |

## What Was Fixed

1. **Path Portability** — All project symlinks now relative (portable across machines/paths)
2. **Error Messages** — Explicit logging instead of silent failures
3. **Documentation** — Clear explanation of symlink strategy and Windows approaches
4. **Dynamic Configuration** — Extension version read from package.json, not hardcoded
5. **Typo** — SW-Depoyment → SW-Deployment
6. **Fallback Logic** — Python-based relative path with fallback to standard pattern

## Extension Separation

VSCode extension moved to separate repo: `~/Coding/vscode-dotfiles-check`

Why: Extension should not be self-referential (no circular dependency).

Changes:
- Removed `vscode-extensions/dotfiles-check` from dotfiles repo
- Created separate `vscode-dotfiles-check` repo with README + install.sh
- `setup.sh` no longer installs extension (user installs separately)
- README documents extension as separate installation

Benefits:
- No circular dependency
- Extension can be versioned independently
- Can be published to VSCode Marketplace separately
- Clearer separation of concerns

## Testing Checklist (Recommended)

- [ ] Run `bash setup.sh` on macOS → verify `readlink ~/Coding/ha-garden-water/CLAUDE.md` shows relative path
- [ ] Run on Linux → same relative path format
- [ ] Run on Windows Git Bash (with Developer Mode) → symlinks created
- [ ] Move `~/Coding/dotfiles` to different path → re-run setup.sh → symlinks auto-adjust
- [ ] `bash add-project.sh test-project` → verify relative symlink created
- [ ] `cd ~/Coding/vscode-dotfiles-check && bash install.sh` → extension installs separately
- [ ] Verify Windows setup with and without Developer Mode (behavior documented)
