#!/usr/bin/env bash
# Fail unless a Linux launcher binary starts on every distribution we promise.
#
#   packaging/linux/check_binary.sh <binary> [max-glibc]
#
# Two checks, both from the ELF headers (objdump), so they run anywhere:
#
#   1. No symbol needs a glibc newer than max-glibc (default 2.28: Ubuntu
#      20.04, Debian 10, RHEL 8 and everything after them). A binary built on
#      a new distribution silently picks up its glibc and then refuses to
#      start on older ones with "GLIBC_2.xx not found".
#   2. Nothing beyond glibc's own libraries is linked. The window system,
#      OpenGL and fontconfig are all loaded with dlopen when the window opens,
#      which is what lets `--headless` run on a minimal server or container.
set -euo pipefail

bin="${1:?path to the CraftBotInstaller binary}"
max="${2:-2.28}"

if ! command -v objdump >/dev/null 2>&1; then
    echo "error: objdump not found (install binutils)" >&2
    exit 1
fi

newer_than_max() {
    # True when version $1 sorts after $max.
    [ "$1" != "$max" ] && [ "$(printf '%s\n%s\n' "$1" "$max" | sort -V | tail -n 1)" = "$1" ]
}

status=0

versions="$(objdump -T "$bin" | grep -o 'GLIBC_[0-9][0-9.]*' | sed 's/^GLIBC_//' | sort -u -V)"
highest="$(printf '%s\n' "$versions" | tail -n 1)"
echo "highest glibc symbol version: ${highest:-none} (limit $max)"
for v in $versions; do
    if newer_than_max "$v"; then
        echo "error: needs GLIBC_$v, newer than $max:" >&2
        # objdump prints the version bare or in parentheses, by version.
        objdump -T "$bin" | awk -v want="GLIBC_$v" '{
            for (i = 1; i <= NF; i++) {
                f = $i; gsub(/[()]/, "", f)
                if (f == want) { print "  " $NF; break }
            }
        }' >&2
        status=1
    fi
done

allowed='^(libc\.so\.6|libm\.so\.6|libdl\.so\.2|libpthread\.so\.0|librt\.so\.1|libutil\.so\.1|libgcc_s\.so\.1|ld-linux-x86-64\.so\.2|ld-linux-aarch64\.so\.1)$'
needed="$(objdump -p "$bin" | awk '$1 == "NEEDED" {print $2}')"
echo "linked libraries: $(tr '\n' ' ' <<<"$needed")"
for lib in $needed; do
    if ! [[ "$lib" =~ $allowed ]]; then
        echo "error: links $lib; it must be loaded with dlopen instead" >&2
        status=1
    fi
done

if [ "$status" -eq 0 ]; then
    echo "ok: $bin runs on glibc $max and later with no other libraries"
fi
exit "$status"
