#!/usr/bin/env bash
# Usage: packaging/build-deb.sh [outdir]   ->  <outdir>/gitdesk_<ver>_all.deb
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/server/gitdesk/__init__.py")"
OUT="${1:-$ROOT/dist}"; mkdir -p "$OUT"
B="$(mktemp -d)"; chmod 755 "$B"; trap 'rm -rf "$B"' EXIT
PY="$B/usr/lib/python3/dist-packages/gitdesk"
install -d "$B/DEBIAN" "$B/usr/bin" "$PY" "$B/usr/share/applications" \
           "$B/usr/share/icons/hicolor/scalable/apps" "$B/usr/share/doc/gitdesk"
install -m644 "$ROOT"/server/gitdesk/*.py "$PY/"
install -m755 "$ROOT/packaging/deb/gitdesk" "$B/usr/bin/gitdesk"
install -m644 "$ROOT/packaging/deb/gitdesk.desktop" "$B/usr/share/applications/"
install -m644 "$ROOT/packaging/deb/gitdesk.svg" "$B/usr/share/icons/hicolor/scalable/apps/"
install -m644 "$ROOT/packaging/deb/copyright" "$B/usr/share/doc/gitdesk/"
sed "s/@VERSION@/$VER/" "$ROOT/packaging/deb/control.in" > "$B/DEBIAN/control"
echo "Installed-Size: $(du -sk "$B/usr" | cut -f1)" >> "$B/DEBIAN/control"
dpkg-deb --root-owner-group --build "$B" "$OUT/gitdesk_${VER}_all.deb"
