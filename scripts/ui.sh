#!/usr/bin/env bash
# Factory Control UI launcher. Preserves caller cwd as the default target project.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FACTORY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENDOR_DEST="$FACTORY_ROOT/.tools/ui/vendor"

if [[ "${FACTORY_UI_OFFLINE:-0}" == "1" ]]; then
  python3 "$FACTORY_ROOT/scripts/vendor_ui.py" check --destination "$VENDOR_DEST"
else
  python3 "$FACTORY_ROOT/scripts/vendor_ui.py" ensure --destination "$VENDOR_DEST"
fi

exec python3 "$FACTORY_ROOT/tools/factory_ui.py" "$@"
