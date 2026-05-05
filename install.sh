#!/usr/bin/env bash
# Installer for the Terminator "Titlebar Changer" plugin.
#
# Usage:
#   bash install.sh             # install (or update)
#   bash install.sh --uninstall # remove the plugin

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="$SCRIPT_DIR/titlebar_changer.py"
PLUGIN_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/terminator/plugins"
PLUGIN_DST="$PLUGIN_DIR/titlebar_changer.py"

if [[ "${1:-}" == "--uninstall" ]]; then
    if [[ -f "$PLUGIN_DST" ]]; then
        rm -f "$PLUGIN_DST"
        echo "Removed $PLUGIN_DST"
        echo "Disable 'TitlebarChanger' in Terminator > Preferences > Plugins,"
        echo "then restart Terminator."
    else
        echo "Nothing to remove (no $PLUGIN_DST)."
    fi
    exit 0
fi

if [[ ! -f "$PLUGIN_SRC" ]]; then
    echo "Error: plugin file not found at $PLUGIN_SRC" >&2
    exit 1
fi

if ! command -v terminator >/dev/null 2>&1; then
    echo "Warning: 'terminator' not found in PATH." >&2
    echo "         Installing the plugin file anyway." >&2
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: 'python3' is required." >&2
    exit 1
fi

if ! python3 -c "import ast; ast.parse(open('$PLUGIN_SRC').read())" 2>/dev/null; then
    echo "Error: plugin failed Python syntax check." >&2
    exit 1
fi

mkdir -p "$PLUGIN_DIR"

if [[ -f "$PLUGIN_DST" ]]; then
    backup="$PLUGIN_DST.bak.$(date +%Y%m%d-%H%M%S)"
    cp -p "$PLUGIN_DST" "$backup"
    echo "Backed up existing plugin to $backup"
fi

cp "$PLUGIN_SRC" "$PLUGIN_DST"

cat <<MSG

Installed: $PLUGIN_DST

Next steps:
  1. (Re)start Terminator -- plugins are only scanned at startup.
  2. Open Preferences > Plugins, enable 'TitlebarChanger'.
  3. Right-click any terminal > Titlebar Changer > Preferences...
     to choose a color target and add rules.

Color targets:
  Titlebar  Colors the per-pane title strip independently -- works with splits.
  Window    Colors the OS-level CSD header bar for the whole window;
            any matching pane is enough to trigger it.

Rule examples (Name, Pattern, BG Color, FG Color):
  root        root@          #cc0000  #ffffff
  SSH         @.*\\..*:      #1a5276  #d6eaf8
  production  prod           #7b241c  #fdfefe
  staging     stag           #7d6608  #fef9e7

Notes:
  - Pattern is a Python regex matched against the terminal window title.
  - First matching rule wins.
  - Window target requires GTK3 client-side decorations (default on GNOME).
MSG
