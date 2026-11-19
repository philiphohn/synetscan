#!/bin/sh
# Build dist/SynetScan-<version>-noarch.spk
set -eu
cd "$(dirname "$0")"
VERSION_BASE=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/lib/synetscan/__init__.py)
BUILD=${BUILD:-0001}
VERSION="$VERSION_BASE-$BUILD"
OUT=dist
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

[ -f src/share/oui.txt.gz ] || python3 tools/build_oui.py third_party/manuf src/share/oui.txt.gz
[ -f src/ui/images/icon_64.png ] || python3 tools/make_icons.py src/ui/images spk

# package.tgz – the application payload
mkdir -p "$WORK/pkg"
cp -R src/bin src/lib src/share src/ui "$WORK/pkg/"
find "$WORK/pkg" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$WORK/pkg" -name '*.pyc' -delete
find "$WORK/pkg" -type d -exec chmod 755 {} +
find "$WORK/pkg" -type f -exec chmod 644 {} +
chmod 755 "$WORK/pkg/bin/synetscand" "$WORK/pkg/ui/api.cgi"
tar --owner=0 --group=0 --numeric-owner -C "$WORK/pkg" -czf "$WORK/package.tgz" .

# SPK container
mkdir -p "$WORK/spk"
cp "$WORK/package.tgz" "$WORK/spk/"
cp -R spk/scripts spk/conf "$WORK/spk/"
cp spk/PACKAGE_ICON.PNG spk/PACKAGE_ICON_256.PNG "$WORK/spk/"
cp LICENSE "$WORK/spk/LICENSE" 2>/dev/null || true
chmod 755 "$WORK/spk/scripts/"*
CHECKSUM=$(md5sum "$WORK/package.tgz" | cut -d' ' -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@CREATE_TIME@/$(date +%Y%m%d-%H:%M:%S)/" -e "s/@CHECKSUM@/$CHECKSUM/" \
    spk/INFO.in > "$WORK/spk/INFO"

mkdir -p "$OUT"
SPK="$OUT/SynetScan-$VERSION-noarch.spk"
(cd "$WORK/spk" && tar --owner=0 --group=0 --numeric-owner -cf - INFO package.tgz scripts conf PACKAGE_ICON.PNG PACKAGE_ICON_256.PNG $( [ -f LICENSE ] && echo LICENSE )) > "$SPK"
echo "built $SPK ($(du -h "$SPK" | cut -f1))"
