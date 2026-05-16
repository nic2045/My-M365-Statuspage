#!/bin/bash
# Usage: bash add-project.sh <repo-name>
# Adds a new project to dotfiles and links it immediately.
set -e

DOTFILES="$(cd "$(dirname "$0")" && pwd)"
NAME="$1"

if [ -z "$NAME" ]; then
  echo "Usage: bash add-project.sh <repo-name>"
  exit 1
fi

# Detect projects directory (Windows: ~/Documents/Coding, macOS/Linux: ~/Coding)
if [ -d "$HOME/Documents/Coding" ]; then
  CODING_DIR="$HOME/Documents/Coding"
else
  CODING_DIR="$HOME/Coding"
fi

PLACEHOLDER="$DOTFILES/claude/projects/$NAME.md"
REPO="$CODING_DIR/$NAME"

# 1. Create placeholder if it doesn't exist
if [ -f "$PLACEHOLDER" ]; then
  echo "✓ $PLACEHOLDER already exists"
else
  cat > "$PLACEHOLDER" << EOF
# $NAME — Claude Instructions

@../CLAUDE.md

<!-- Add project-specific instructions here -->
EOF
  echo "✓ Created $PLACEHOLDER"
fi

# 2. Add link line to setup.sh if not already present
if grep -q "\"$NAME\"" "$DOTFILES/setup.sh"; then
  echo "✓ setup.sh already contains $NAME"
else
  # Portable insert before "echo "Done."" — awk works on macOS, Linux, and Git Bash
  awk -v line="link \"\$DOTFILES/claude/projects/$NAME.md\" \"\$CODING_DIR/$NAME\"" \
    '/^echo "Done\."/{print line} {print}' \
    "$DOTFILES/setup.sh" > "$DOTFILES/setup.sh.tmp" && mv "$DOTFILES/setup.sh.tmp" "$DOTFILES/setup.sh"
  echo "✓ Added link line to setup.sh"
fi

# 3. Set symlink immediately if repo exists locally (relative path)
if [ -d "$REPO" ]; then
  # Calculate relative path from repo to dotfiles
  rel_path=$(cd "$REPO" && python3 -c "import os.path; print(os.path.relpath('$PLACEHOLDER', '.'))" 2>/dev/null)
  if [ -z "$rel_path" ]; then
    # Fallback: use simple relative for same-parent case
    rel_path="../dotfiles/claude/projects/$NAME.md"
  fi
  ln -sf "$rel_path" "$REPO/CLAUDE.md" && echo "✓ Symlink set: $REPO/CLAUDE.md → $rel_path" || echo "⚠ Failed to create symlink"
else
  echo "  Repo not found locally, skipping symlink (will be set on next setup.sh run)"
fi

# 4. Commit and push
git -C "$DOTFILES" add .
git -C "$DOTFILES" commit -m "add project: $NAME"
git -C "$DOTFILES" push

echo ""
echo "Done. Edit $PLACEHOLDER to add project-specific instructions."
