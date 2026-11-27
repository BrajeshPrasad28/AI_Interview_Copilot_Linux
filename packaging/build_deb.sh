#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="${1:-0.1.2}"

if [[ ! "$VERSION" =~ ^[0-9][A-Za-z0-9.+:~-]*$ ]]; then
    printf 'Invalid Debian package version: %s\n' "$VERSION" >&2
    exit 1
fi

if ! command -v dpkg-deb >/dev/null 2>&1; then
    printf '%s\n' "dpkg-deb is required to build the Ubuntu package." >&2
    exit 1
fi
if ! git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf '%s\n' "Build the .deb from a Git checkout so the source file list can be verified." >&2
    exit 1
fi

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf -- "$BUILD_DIR"' EXIT
PACKAGE_ROOT="$BUILD_DIR/ai-interview-copilot"
APP_ROOT="$PACKAGE_ROOT/opt/ai-interview-copilot"
OUTPUT_DIR="$PROJECT_DIR/dist"
OUTPUT="$OUTPUT_DIR/ai-interview-copilot_${VERSION}_all.deb"

mkdir -p "$APP_ROOT" "$PACKAGE_ROOT/DEBIAN" "$PACKAGE_ROOT/usr/bin"
mkdir -p "$PACKAGE_ROOT/usr/share/applications"
mkdir -p "$PACKAGE_ROOT/usr/share/icons/hicolor/256x256/apps"

while IFS= read -r -d '' source_file; do
    case "$source_file" in
        tests/*|packaging/*|README.md|.gitignore|setup.sh|run.sh|stop_copilot.sh|AI_Interview_Copilot_Postman_Collection.json)
            continue
            ;;
    esac
    mkdir -p "$APP_ROOT/$(dirname "$source_file")"
    cp -p "$PROJECT_DIR/$source_file" "$APP_ROOT/$source_file"
done < <(git -C "$PROJECT_DIR" ls-files -z)

sed "s/@VERSION@/$VERSION/" "$SCRIPT_DIR/deb/control" > "$PACKAGE_ROOT/DEBIAN/control"
install -m 755 "$SCRIPT_DIR/deb/postinst" "$PACKAGE_ROOT/DEBIAN/postinst"
install -m 755 "$SCRIPT_DIR/deb/postrm" "$PACKAGE_ROOT/DEBIAN/postrm"
install -m 755 "$SCRIPT_DIR/deb/launcher" "$PACKAGE_ROOT/usr/bin/ai-interview-copilot"
install -m 644 "$SCRIPT_DIR/deb/ai-interview-copilot.desktop" \
    "$PACKAGE_ROOT/usr/share/applications/ai-interview-copilot.desktop"
install -m 644 "$PROJECT_DIR/app_icon.png" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/256x256/apps/ai-interview-copilot.png"
install -m 644 "$PROJECT_DIR/app_icon.png" "$APP_ROOT/app_icon.png"

# Do not carry group/world write permissions from the source checkout into the system package.
chmod -R go-w "$PACKAGE_ROOT"

mkdir -p "$OUTPUT_DIR"
dpkg-deb --build --root-owner-group "$PACKAGE_ROOT" "$OUTPUT"
printf 'Built package: %s\n' "$OUTPUT"
