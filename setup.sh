#!/bin/bash
# Run once on a new machine after cloning this repo.
set -e

DOTFILES="$(cd "$(dirname "$0")" && pwd)"

# Detect projects directory (Windows: ~/Documents/Coding, macOS/Linux: ~/Coding)
if [ -d "$HOME/Documents/Coding" ]; then
  CODING_DIR="$HOME/Documents/Coding"
else
  CODING_DIR="$HOME/Coding"
fi

echo "Dotfiles : $DOTFILES"
echo "Projects : $CODING_DIR"

echo "Setting up Claude global config..."
mkdir -p ~/.claude
ln -sf "$DOTFILES/claude/CLAUDE.md" ~/.claude/CLAUDE.md

echo "Setting up git config..."
git config --global core.excludesfile "$DOTFILES/gitconf/gitignore_global"
git config --global alias.ignored '!git status --ignored --porcelain | grep "^!!" | sed "s/^!! //" | sed "s/^\"\(.*\)\"$/\1/" | while IFS= read -r f; do result=$(git check-ignore -v -- "$f" 2>/dev/null); source=$(echo "$result" | cut -f1); printf "%-45s %s\n" "$source" "$f"; done'
git config --global dotfiles.dir "$DOTFILES"

echo "Setting up git hook (auto-link CLAUDE.md on clone)..."
mkdir -p ~/.git-templates/hooks
cp "$DOTFILES/git-templates/hooks/post-checkout" ~/.git-templates/hooks/post-checkout
chmod +x ~/.git-templates/hooks/post-checkout
git config --global init.templateDir ~/.git-templates

# Project-specific CLAUDE.md files (relative symlinks, repairs broken symlinks, idempotent)
link() {
  local src="$1"
  local dir="$2"
  local target="$dir/CLAUDE.md"

  if [ ! -d "$dir" ]; then
    echo "⊘ Skipping $dir (not found)"
    return
  fi

  # Calculate relative path from target directory to source
  local rel_src=$(cd "$dir" && python3 -c "import os.path; print(os.path.relpath('$src', '.'))" 2>/dev/null)
  if [ -z "$rel_src" ]; then
    # Fallback: standard layout
    rel_src="../dotfiles/$(echo "$src" | sed "s|.*/dotfiles/||")"
  fi

  # Repair broken/wrong symlink
  if [ -L "$target" ]; then
    if [ ! -e "$target" ] || [ "$(readlink "$target")" != "$rel_src" ]; then
      rm "$target"
      echo "🔧 Repaired symlink in $dir"
    fi
  elif [ -e "$target" ]; then
    echo "⚠ $target exists but is not a symlink (skipping)"
    return
  fi

  # Create symlink if not exists
  if [ ! -e "$target" ]; then
    ln -s "$rel_src" "$target" && echo "✓ Linked $dir" || echo "⚠ Failed to symlink $dir"
  fi
}

link "$DOTFILES/claude/projects/ha-garden-water.md"       "$CODING_DIR/ha-garden-water"
link "$DOTFILES/claude/projects/JIRA_WeeklyUpdater.md"    "$CODING_DIR/JIRA_WeeklyUpdater"
link "$DOTFILES/claude/projects/Script-Libary.md"         "$CODING_DIR/Script-Libary"
link "$DOTFILES/claude/projects/SW-Deployment.md"         "$CODING_DIR/SW-Deployment"
link "$DOTFILES/claude/projects/ADGroupChecker.md"        "$CODING_DIR/ADGroupChecker"
link "$DOTFILES/claude/projects/PS-Script-Libary.md"      "$CODING_DIR/PS-Script-Libary"
link "$DOTFILES/claude/projects/MDT.md"                   "$CODING_DIR/MDT"
link "$DOTFILES/claude/projects/RSG-Intune.md"            "$CODING_DIR/RSG-Intune"
link "$DOTFILES/claude/projects/ha-config.md"             "$CODING_DIR/ha-config"
link "$DOTFILES/claude/projects/vscode-git-autocommit.md" "$CODING_DIR/vscode-git-autocommit"

link "$DOTFILES/claude/projects/vscode-dotfiles-check-2.md" "$CODING_DIR/vscode-dotfiles-check-2"
link "$DOTFILES/claude/projects/My-M365-Statuspage.md" "$CODING_DIR/My-M365-Statuspage"
echo "Done."
echo ""
echo "Next steps:"
echo "- Install vscode-dotfiles-check extension separately (see README)"
