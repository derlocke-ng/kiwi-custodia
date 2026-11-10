#!/bin/sh
# kc-record — what was added to a kiwi-custodia box, read from its image.
#
# kiwi-custodia runs this in a throwaway container of the box's committed image
# (or of its base image), with no network: it only reads the package database
# and the files. POSIX sh, for busybox (Alpine) as well as bash distros.
#
#   kc-record packages             explicit packages, one per line: "NAME SOURCE"
#                                  SOURCE is the repository, "@local" for one
#                                  installed from a file, "-" when not known
#   kc-record files  < PATHS       of the candidate paths (one per line), the
#                                  ones a snapshot must carry: "keep PATH" for a
#                                  file no package owns, or one changed from its
#                                  package's version
#   kc-record local NAME...        a package installed from a file: its files
#                                  ("file PATH") and what it requires ("req CAP")
#
#   KC_FAMILY   dnf | apt | pacman | zypper | apk | auto
set -eu

FAMILY="${KC_FAMILY:-auto}"
if [ "$FAMILY" = auto ]; then
    for cand in dnf apt-get pacman zypper apk; do
        if command -v "$cand" >/dev/null 2>&1; then FAMILY="$cand"; break; fi
    done
    [ "$FAMILY" = apt-get ] && FAMILY=apt
fi

# "rpm -V" style output -> the paths whose content, size or link changed
changed_paths() {
    # 9-character flags, an optional attribute letter, then the path
    awk '$1 ~ /^[.SM5DLUGTP?]+$/ && ($1 ~ /[S5L]/) { print $NF }'
}

packages() {
    case "$FAMILY" in
      dnf)
        dnf -C -q repoquery --userinstalled --qf '%{name} %{from_repo}\n' 2>/dev/null \
            | sed 's/ @commandline$/ @local/' ;;
      zypper)
        auto=/var/lib/zypp/AutoInstalled
        rpm -qa --qf '%{NAME}\n' | sort -u | while read -r name; do
            grep -qx "$name" "$auto" 2>/dev/null || printf '%s -\n' "$name"
        done ;;
      apt)
        apt-mark showmanual 2>/dev/null | sed 's/$/ -/' ;;
      pacman)
        foreign=$(pacman -Qqm 2>/dev/null || true)
        pacman -Qqe 2>/dev/null | while read -r name; do
            if printf '%s\n' "$foreign" | grep -qx "$name"; then
                printf '%s @local\n' "$name"
            else
                printf '%s -\n' "$name"
            fi
        done ;;
      apk)
        sed 's/[<>=~].*$//' /etc/apk/world 2>/dev/null | grep -v '^$' | sed 's/$/ -/' ;;
      *) ;;
    esac
}

files() {
    candidates=$(mktemp)
    owners=$(mktemp)
    cat > "$candidates"
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        # a directory on its own carries nothing; its files are candidates too
        if [ -d "$f" ] && [ ! -L "$f" ]; then continue; fi
        [ -e "$f" ] || [ -L "$f" ] || continue
        case "$FAMILY" in
          dnf|zypper) owner=$(rpm -qf --qf '%{NAME}\n' "$f" 2>/dev/null | head -1) || owner="" ;;
          apt)        owner=$(dpkg -S "$f" 2>/dev/null | head -1 | cut -d: -f1) || owner="" ;;
          pacman)     owner=$(pacman -Qoq "$f" 2>/dev/null | head -1) || owner="" ;;
          apk)        owner=$(apk info -q --who-owns "$f" 2>/dev/null | head -1) || owner="" ;;
          *)          owner="" ;;
        esac
        case "$owner" in
          ""|*"not owned"*) printf 'keep %s\n' "$f" ;;
          *) printf '%s\n' "$owner" >> "$owners" ;;
        esac
    done < "$candidates"
    # owned files count only when they differ from what their package installed
    if [ -s "$owners" ]; then
        changed=$(mktemp)
        case "$FAMILY" in
          dnf|zypper)
            # shellcheck disable=SC2046
            rpm -V --nomtime --nouser --nogroup $(sort -u "$owners") 2>/dev/null | changed_paths > "$changed" || true ;;
          apt)
            dpkg --verify 2>/dev/null | changed_paths > "$changed" || true ;;
          pacman)
            pacman -Qkk 2>&1 | sed -n 's/^warning: [^:]*: \(\/[^ ]*\) (.*checksum mismatch)$/\1/p' > "$changed" || true ;;
          apk)
            apk audit --system 2>/dev/null | awk '{print "/" $2}' > "$changed" || true ;;
        esac
        grep -Fxf "$changed" "$candidates" 2>/dev/null | sed 's/^/keep /' || true
        rm -f "$changed"
    fi
    rm -f "$candidates" "$owners"
}

local_package() {
    for name in "$@"; do
        case "$FAMILY" in
          dnf|zypper)
            # a listed file can be missing (images install without docs): skip it;
            # every loop and pipeline ends true, or set -e ends the script quietly
            rpm -ql "$name" 2>/dev/null | while IFS= read -r f; do
                if [ -d "$f" ] && [ ! -L "$f" ]; then continue; fi
                if [ -e "$f" ] || [ -L "$f" ]; then printf 'file %s\n' "$f"; fi
            done || true
            rpm -q --requires "$name" 2>/dev/null \
                | grep -v '^rpmlib(' | grep -v '^/' | sed 's/ .*$//' | sort -u | sed 's/^/req /' \
                || true ;;
          pacman)
            pacman -Qlq "$name" 2>/dev/null | while IFS= read -r f; do
                if [ -d "$f" ] && [ ! -L "$f" ]; then continue; fi
                if [ -e "$f" ] || [ -L "$f" ]; then printf 'file %s\n' "$f"; fi
            done || true ;;
          *) ;;
        esac
    done
}

case "${1:-}" in
  packages) packages ;;
  files) files ;;
  local) shift; local_package "$@" ;;
  family) printf '%s\n' "$FAMILY" ;;
  *) echo "usage: kc-record packages|files|local NAME...|family" >&2; exit 2 ;;
esac
