#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$HOME/.config/terminator/plugins"
PLUGIN_SRC="$(cd "$(dirname "$0")" && pwd)/title_react.py"

mkdir -p "$PLUGIN_DIR"
cp -v "$PLUGIN_SRC" "$PLUGIN_DIR/"

echo ""
echo "Installed.  Enable the plugin in Terminator:"
echo "  Preferences → Plugins → TitleReact  (check the box)"
echo "Then restart Terminator (or reload plugins via the preferences dialog)."
