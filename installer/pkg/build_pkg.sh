#!/usr/bin/env bash
# Construye JobTrackerAI-X.Y.Z.pkg a partir de una release ya generada (scripts/release.py).
# Solo funciona en macOS (pkgbuild/productbuild). Uso: installer/pkg/build_pkg.sh dist/
#
# Firma y notarización (opcionales, requieren cuenta Apple Developer):
#   PKG_SIGN_IDENTITY="Developer ID Installer: Tu Nombre (TEAMID)"
#   NOTARY_PROFILE=<perfil creado con: xcrun notarytool store-credentials>
set -euo pipefail
DIST="${1:-dist}"
HERE="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$DIST/manifest.json")"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/scripts" "$WORK/resources"
cp "$HERE/postinstall" "$WORK/scripts/postinstall"
cp "$DIST/install.sh" "$WORK/scripts/install.sh"
cp "$DIST/manifest.json" "$WORK/scripts/manifest.json"
cp "$DIST/jobtracker-ai-$VERSION.tar.gz" "$WORK/scripts/jobtracker-ai.tar.gz"
chmod +x "$WORK/scripts/postinstall" "$WORK/scripts/install.sh"
sed "s/{{VERSION}}/$VERSION/g" "$HERE/welcome.html" > "$WORK/resources/welcome.html"

pkgbuild --nopayload --scripts "$WORK/scripts" \
  --identifier com.jobtrackerai.installer --version "$VERSION" "$WORK/component.pkg"

cat > "$WORK/distribution.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>JobTracker AI $VERSION</title>
  <welcome file="welcome.html" mime-type="text/html"/>
  <options customize="never" require-scripts="false" hostArchitectures="arm64,x86_64"/>
  <domains enable_currentUserHome="false" enable_localSystem="true"/>
  <volume-check><allowed-os-versions><os-version min="11.0"/></allowed-os-versions></volume-check>
  <choices-outline><line choice="default"><line choice="app"/></line></choices-outline>
  <choice id="default"/>
  <choice id="app" visible="false"><pkg-ref id="com.jobtrackerai.installer"/></choice>
  <pkg-ref id="com.jobtrackerai.installer" version="$VERSION" onConclusion="none">component.pkg</pkg-ref>
</installer-gui-script>
XML

OUT="$DIST/JobTrackerAI-$VERSION.pkg"
productbuild --distribution "$WORK/distribution.xml" --resources "$WORK/resources" \
  --package-path "$WORK" "$WORK/unsigned.pkg"

if [ -n "${PKG_SIGN_IDENTITY:-}" ]; then
  productsign --sign "$PKG_SIGN_IDENTITY" "$WORK/unsigned.pkg" "$OUT"
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    xcrun notarytool submit "$OUT" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$OUT"
  fi
else
  mv "$WORK/unsigned.pkg" "$OUT"
  echo "⚠️  .pkg sin firmar: macOS pedirá clic derecho → Abrir la primera vez."
fi
echo "✅ $OUT"
