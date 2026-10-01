#!/usr/bin/env bash
# Render a report's HTML to a PDF alongside it via headless Chrome.
#
#   ./render.sh ../reports/<name>.html   # -> ../reports/<name>.pdf
#
# Chrome is used because it is the only HTML->PDF engine present on this machine
# (no pandoc / weasyprint / wkhtmltopdf). It honors @page, print color adjust,
# and break-inside: avoid, which the report's styling relies on.
#
# The CVDisplayLink / task_policy_set lines Chrome prints on macOS are harmless
# headless noise -- check for the "bytes written" line to confirm success.

set -euo pipefail

[ $# -eq 1 ] || { echo "usage: $0 <report.html>" >&2; exit 1; }
SRC="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
[ -f "$SRC" ] || { echo "No such file: $1" >&2; exit 1; }
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT="${SRC%.html}.pdf"

[ -x "$CHROME" ] || { echo "Chrome not found at: $CHROME" >&2; exit 1; }

"$CHROME" \
  --headless \
  --disable-gpu \
  --no-pdf-header-footer \
  --print-to-pdf="$OUT" \
  "file://$SRC" 2>&1 | grep -E "bytes written" || true

[ -f "$OUT" ] || { echo "PDF was not produced" >&2; exit 1; }
echo "wrote $OUT"
