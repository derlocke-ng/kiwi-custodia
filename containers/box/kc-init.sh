#!/bin/sh
# kc-init — a kiwi-custodia box's first process. POSIX sh: it runs on busybox
# (Alpine) as well as on bash distros.
#
# Runs as container-root under podman's --init, in a stock distro image that
# kiwi-custodia bind-mounted this script into. On the first start it installs
# the baseline a desktop app needs (sudo, a locale, Mesa, a font, xdg-utils, and
# whatever the box asked for), then — every start — makes sure the host user
# exists with the same uid, has passwordless sudo and a runtime dir, and that
# every shell inherits the box's proxy environment. Then it holds the container
# open for `podman exec`.
#
# The box has no network but the exit: the tunnel sidecar in the same namespace
# makes the default route the exit, so package managers need no proxy setting.
# ALL_PROXY is set regardless, so tools that can speak SOCKS by name do (a
# .onion resolves only that way on a Tor exit).
#
#   KC_USER KC_UID KC_GID   the host user, mirrored (--userns keep-id)
#   KC_HOME                 the user's home in the box (a host directory)
#   KC_FAMILY               dnf | apt | pacman | zypper | apk
#   KC_PACKAGES             extra packages, space-separated
#   KC_SOCKS                the gateway forwarder (127.0.0.1:1080)
#   KC_BOX KC_EXIT_NAME     for the log line and the environment
set -eu

log() { printf 'kc-init: %s\n' "$*"; }
die() { printf 'kc-init: FATAL: %s\n' "$*" >&2; exit 1; }

: "${KC_USER:?KC_USER is required}"
: "${KC_UID:?KC_UID is required}"
: "${KC_GID:?KC_GID is required}"
KC_FAMILY="${KC_FAMILY:-auto}"
KC_HOME="${KC_HOME:-/home/$KC_USER}"
KC_SHELL="${KC_SHELL:-}"
# "auto": any image — find its package manager.
if [ "$KC_FAMILY" = auto ]; then
    for cand in dnf apt-get pacman zypper apk; do
        if command -v "$cand" >/dev/null 2>&1; then KC_FAMILY="$cand"; break; fi
    done
    [ "$KC_FAMILY" = apt-get ] && KC_FAMILY=apt
    [ "$KC_FAMILY" = auto ] && die "no package manager found in this image (dnf, apt, pacman, zypper or apk)"
    log "package manager: $KC_FAMILY"
fi
KC_SOCKS="${KC_SOCKS:-127.0.0.1:1080}"
KC_BOX="${KC_BOX:-box}"
STAMP=/var/lib/kiwi-custodia/initialized
export DEBIAN_FRONTEND=noninteractive

# ----------------------------------------------------------------- packages
baseline() {
    case "$KC_FAMILY" in
      dnf)    echo "sudo shadow-utils passwd ca-certificates curl less bash bash-completion procps-ng gawk
                    glibc-langpack-en mesa-dri-drivers mesa-vulkan-drivers libglvnd-egl libglvnd-gles
                    dejavu-sans-fonts xdg-utils" ;;
      apt)    echo "sudo passwd ca-certificates curl less bash bash-completion procps locales gawk
                    libgl1 libegl1 libgles2 mesa-vulkan-drivers fonts-dejavu-core xdg-utils" ;;
      pacman) echo "sudo shadow ca-certificates curl less bash bash-completion procps-ng gawk
                    mesa vulkan-icd-loader ttf-dejavu xdg-utils" ;;
      zypper) echo "sudo shadow ca-certificates curl less bash bash-completion procps gawk
                    Mesa-dri libvulkan1 dejavu-fonts xdg-utils" ;;
      apk)    echo "sudo shadow bash ca-certificates curl less bash-completion procps gawk
                    mesa-dri-gallium mesa-egl mesa-gles font-dejavu xdg-utils" ;;
      *) die "unknown package family $KC_FAMILY" ;;
    esac
}

pkg_install() {
    # shellcheck disable=SC2086
    case "$KC_FAMILY" in
      dnf)    dnf -y -q install --setopt=install_weak_deps=False "$@" ;;
      apt)    apt-get -qq update && apt-get -qq -y install --no-install-recommends "$@" ;;
      pacman) pacman -Syu --noconfirm --needed --quiet "$@" ;;
      zypper) zypper -q --non-interactive install --no-recommends "$@" ;;
      apk)    apk add -q "$@" ;;
    esac
}

DONE_PKGS=/var/lib/kiwi-custodia/packages
if [ ! -e "$STAMP" ]; then
    log "first start: installing the $KC_FAMILY baseline${KC_PACKAGES:+ and: $KC_PACKAGES}"
    # shellcheck disable=SC2046
    if pkg_install $(baseline) ${KC_PACKAGES:-}; then
        log "packages installed"
    else
        log "WARNING: some packages did not install; the box works, apps may want them"
    fi
    mkdir -p "$(dirname "$STAMP")"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$STAMP"
    printf '%s\n' ${KC_PACKAGES:-} > "$DONE_PKGS"
else
    # A box kept across recreates (its snapshot) installs only what was added
    # to it since — `set --package` — not the baseline again.
    missing=""
    for pkg in ${KC_PACKAGES:-}; do
        grep -qx "$pkg" "$DONE_PKGS" 2>/dev/null || missing="$missing $pkg"
    done
    if [ -n "$missing" ]; then
        log "installing what was added:$missing"
        # shellcheck disable=SC2086
        pkg_install $missing && printf '%s\n' $missing >> "$DONE_PKGS" \
            || log "WARNING: some of$missing did not install"
    fi
fi

# A box made before the baseline grew: the few tools launcher scripts assume.
command -v awk >/dev/null 2>&1 || pkg_install gawk >/dev/null 2>&1 || log "WARNING: could not install gawk"

# ---------------------------------------------------------------- the user
if ! getent group "$KC_GID" >/dev/null 2>&1; then
    groupadd -g "$KC_GID" "$KC_USER" 2>/dev/null || addgroup -g "$KC_GID" "$KC_USER"
fi
group_name="$(getent group "$KC_GID" | cut -d: -f1)"
shell=""
if [ -n "$KC_SHELL" ]; then
    if [ -x "$KC_SHELL" ]; then shell="$KC_SHELL"; else log "WARNING: shell $KC_SHELL is not in this box; using bash"; fi
fi
[ -n "$shell" ] || { shell=/bin/bash; [ -x "$shell" ] || shell=/bin/sh; }
if ! getent passwd "$KC_UID" >/dev/null 2>&1; then
    useradd -M -u "$KC_UID" -g "$KC_GID" -d "$KC_HOME" -s "$shell" "$KC_USER" 2>/dev/null \
        || adduser -D -H -u "$KC_UID" -G "$group_name" -h "$KC_HOME" -s "$shell" "$KC_USER"
fi
user_name="$(getent passwd "$KC_UID" | cut -d: -f1)"
# the shell may have changed (set --shell), or bash arrived with the baseline
[ "$(getent passwd "$KC_UID" | cut -d: -f7)" = "$shell" ] \
    || usermod -s "$shell" "$user_name" 2>/dev/null || chsh -s "$shell" "$user_name" 2>/dev/null || true

# The home is the host's directory for this box; empty on the first start.
mkdir -p "$KC_HOME"
if [ -d /etc/skel ] && [ -z "$(ls -A "$KC_HOME" 2>/dev/null)" ]; then
    cp -r /etc/skel/. "$KC_HOME"/ 2>/dev/null || true
    chown -R "$KC_UID:$KC_GID" "$KC_HOME" 2>/dev/null || true
fi

for g in video render audio input; do
    getent group "$g" >/dev/null 2>&1 && usermod -aG "$g" "$user_name" 2>/dev/null || true
done

if command -v sudo >/dev/null 2>&1; then
    mkdir -p /etc/sudoers.d
    printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$user_name" > /etc/sudoers.d/kiwi-custodia
    chmod 440 /etc/sudoers.d/kiwi-custodia
    # Fedora's sudo ships without includedir on some images; make sure it reads it.
    grep -qs 'sudoers.d' /etc/sudoers || echo '@includedir /etc/sudoers.d' >> /etc/sudoers
fi

# Where the desktop's sockets were mounted; the user owns it, like on the host.
mkdir -p "/run/user/$KC_UID"
chown "$KC_UID:$KC_GID" "/run/user/$KC_UID"
chmod 700 "/run/user/$KC_UID"

# ------------------------------------------------------------- environment
# The default route already is the exit, so no app needs a proxy setting. The
# gateway's SOCKS5 is named in KIWI_CUSTODIA_SOCKS for a tool you want to point
# at it by hand. ALL_PROXY is exported only on a remote-DNS exit (Tor), where a
# .onion resolves only that way — elsewhere it is left unset: Electron apps and
# other Chromium-based ones read all_proxy from the environment and choke on the
# socks5h form (empty responses, "no internet"), and double-proxying buys nothing.
proxy_lines=""
if [ "${KC_PROXY_ENV:-0}" = 1 ]; then
    proxy_lines="export ALL_PROXY=\"socks5h://$KC_SOCKS\" all_proxy=\"socks5h://$KC_SOCKS\"
export NO_PROXY=\"localhost,127.0.0.0/8\" no_proxy=\"localhost,127.0.0.0/8\""
fi
cat > /etc/profile.d/kiwi-custodia.sh <<EOF
# kiwi-custodia: this box is "$KC_BOX"; its only route is the exit "${KC_EXIT_NAME:-}".
# The default route already is the exit; nothing needs a proxy setting. The
# gateway's SOCKS5, for a tool you want to point at it: \$KIWI_CUSTODIA_SOCKS.
export KIWI_CUSTODIA_SOCKS="socks5h://$KC_SOCKS"
$proxy_lines
export LANG="\${LANG:-C.UTF-8}"
export KIWI_CUSTODIA_BOX="$KC_BOX"
EOF
chmod 644 /etc/profile.d/kiwi-custodia.sh
printf '%s\n' "$KC_BOX" > /etc/kiwi-custodia-box

# `kc-shell` is what `kiwi-custodia enter` and `run` exec: the user's login
# shell, so profile.d and the user's own rc files apply.
cat > /usr/local/bin/kc-shell <<'EOF'
#!/bin/sh
# the calling user's login shell; `kc-shell -c CMD` runs one command in it
sh="$(getent passwd "$(id -u)" | cut -d: -f7)"
[ -n "$sh" ] && [ -x "$sh" ] || sh=/bin/sh
exec "$sh" -l "$@"
EOF
chmod 755 /usr/local/bin/kc-shell

log "ready — $user_name in $KC_HOME, exit ${KC_EXIT_NAME:-?}"

# Hold the container open. podman's --init (catatonit) is PID 1 and reaps.
while true; do
    sleep 3600
done
