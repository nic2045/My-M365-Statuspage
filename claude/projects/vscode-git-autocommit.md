# vscode-git-autocommit — Claude Instructions

@../CLAUDE.md
VS Code extension that auto-commits the working state on window close, and provides a command + keybinding to commit and optionally push.

## Behaviour

- **`deactivate()`** — fires on VS Code shutdown; silently runs `git add -A` + a descriptive commit (see Auto-commit message format) if changes exist. No UI (window is closing).
- **Command `gitAutoCommit.saveState`** — interactive: commits, then asks whether to push. Keybinding: `Ctrl+Shift+Alt+S` (Mac: `Cmd+Shift+Alt+S`).

## Structure

```
extension.js    # entry point — activate(), deactivate(), saveState()
package.json    # extension manifest, contributes commands + keybindings
```

No build step — plain JavaScript, no TypeScript compilation needed.

## Versioning

For releases, update `version` in `package.json`.

## Auto-commit message format

Auto-commits describe the changed files and include a timestamp. Format:

```
<verb> <files> YYMMDD.HHMM
```

- Verb: `Add` (only new files), `Remove` (only deletions), `Update` (everything else)
- Up to 3 filenames listed; beyond that: `and N more`
- Falls back to `Save working state YYMMDD.HHMM` if parsing fails
- Max 72 characters total (convention from global CLAUDE.md)

## Installation (development / local)

Copy or symlink the repo into `~/.vscode/extensions/vscode-git-autocommit/`, then restart VS Code.
