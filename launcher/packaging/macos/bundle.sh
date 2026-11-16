#!/usr/bin/env bash
# Wrap the launcher binary in a macOS application bundle.
#
#   packaging/macos/bundle.sh <binary> <out-dir> [version]
#
# Produces <out-dir>/CraftBotInstaller.app. Finder will not launch a bare
# Unix executable by double-click (it opens Terminal, if it runs at all, and a
# browser download strips the execute bit), so the form a Mac user recognises
# is a bundle: a directory with a fixed layout Finder presents as one app.
#
# The bundle is ONE process. That is the whole reason the launcher exists on
# macOS: the previous PyInstaller onefile bundle was a bootloader plus a child
# process, and the child (the one with the window) was never the process
# macOS had activated, so Tk dropped its mouse presses.
#
# Signing:
#   MACOS_SIGN_IDENTITY set (a "Developer ID Application: ..." identity in an
#   unlocked keychain): signed with the hardened runtime and a secure
#   timestamp, ready for `xcrun notarytool`. release.yml notarizes and
#   staples it afterwards.
#   Unset: ad-hoc signed (`--sign -`). Apple Silicon refuses to run an arm64
#   binary with no signature at all; an ad-hoc one runs once the user allows
#   it in System Settings > Privacy & Security.
#
# LSMinimumSystemVersion comes from MIN_MACOS in src/preflight.rs, the same
# constant the launcher checks before it downloads anything.
set -euo pipefail

binary="${1:?path to the CraftBotInstaller binary}"
out="${2:?output directory}"
version="${3:-0.0.0}"
version="${version#v}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
app="$out/CraftBotInstaller.app"

min_macos="$(sed -n 's/^pub const MIN_MACOS: &str = "\(.*\)";/\1/p' "$repo/launcher/src/preflight.rs")"
if [ -z "$min_macos" ]; then
    echo "error: MIN_MACOS not found in launcher/src/preflight.rs" >&2
    exit 1
fi

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$binary" "$app/Contents/MacOS/CraftBotInstaller"
chmod +x "$app/Contents/MacOS/CraftBotInstaller"

# The icon is produced by the release workflow with sips + iconutil (both
# ship with macOS). Absent on a local build, in which case the bundle simply
# gets the default icon.
icon_key=""
if [ -f "$repo/craftbot_logo_1.icns" ]; then
    cp "$repo/craftbot_logo_1.icns" "$app/Contents/Resources/craftbot_logo_1.icns"
    icon_key="    <key>CFBundleIconFile</key>
    <string>craftbot_logo_1.icns</string>"
fi

cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>CraftBot Setup</string>
    <key>CFBundleDisplayName</key>
    <string>CraftBot Setup</string>
    <key>CFBundleExecutable</key>
    <string>CraftBotInstaller</string>
    <key>CFBundleIdentifier</key>
    <string>dev.craftos.craftbot.installer</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleShortVersionString</key>
    <string>${version}</string>
    <key>CFBundleVersion</key>
    <string>${version}</string>
    <key>LSMinimumSystemVersion</key>
    <string>${min_macos}</string>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.developer-tools</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key>
    <true/>
${icon_key}
</dict>
</plist>
PLIST

echo 'APPL????' > "$app/Contents/PkgInfo"

if [ -n "${MACOS_SIGN_IDENTITY:-}" ]; then
    codesign --force --options runtime --timestamp \
        --sign "$MACOS_SIGN_IDENTITY" "$app"
    codesign --verify --strict --verbose=2 "$app"
    codesign --display --verbose=2 "$app" 2>&1 | grep -E "^(Authority|TeamIdentifier|Runtime)" || true
    echo "built $app (Developer ID, hardened runtime, minimum macOS $min_macos)"
else
    codesign --force --sign - --timestamp=none "$app"
    codesign --verify --verbose=2 "$app"
    echo "built $app (ad-hoc signed, minimum macOS $min_macos)"
fi
