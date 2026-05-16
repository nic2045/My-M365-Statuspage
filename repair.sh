#!/bin/bash
# Repair CLAUDE.md symlinks for all projects (idempotent)
# Called by git hooks on clone/merge/rebase

DOTFILES="$(cd "$(dirname "$0")" && pwd)"

# Detect projects directory
if [ -d "$HOME/Documents/Coding" ]; then
  CODING_DIR="$HOME/Documents/Coding"
else
  CODING_DIR="$HOME/Coding"
fi

# Repair function (same as in setup.sh, uses relative paths)
link() {
  local project_name="$1"
  local dir="$2"
  local target="$dir/CLAUDE.md"
  local rel_src="../dotfiles/claude/projects/$project_name"

  if [ ! -d "$dir" ]; then
    return
  fi

  # Remove broken/wrong symlink
  if [ -L "$target" ]; then
    if [ ! -e "$target" ] || [ "$(readlink "$target")" != "$rel_src" ]; then
      rm "$target"
      ln -s "$rel_src" "$target"
    fi
  elif [ ! -e "$target" ]; then
    ln -s "$rel_src" "$target"
  fi
}

# Repair all project symlinks
link "ha-garden-water.md"       "$CODING_DIR/ha-garden-water"
link "JIRA_WeeklyUpdater.md"    "$CODING_DIR/JIRA_WeeklyUpdater"
link "Script-Libary.md"         "$CODING_DIR/Script-Libary"
link "SW-Deployment.md"         "$CODING_DIR/SW-Depoyment"
link "ADGroupChecker.md"        "$CODING_DIR/ADGroupChecker"
link "PS-Script-Libary.md"      "$CODING_DIR/PS-Script-Libary"
link "MDT.md"                   "$CODING_DIR/MDT"
link "RSG-Intune.md"            "$CODING_DIR/RSG-Intune"
link "ha-config.md"             "$CODING_DIR/ha-config"
link "vscode-git-autocommit.md" "$CODING_DIR/vscode-git-autocommit"
