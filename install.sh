#!/usr/bin/env bash
# install.sh — kiwi-custodia, installed by `kiwi` (see kiwi.manifest)
#
# User scope only: rootless podman needs no root, so a plain user install is
# fully functional and nothing outside $HOME is ever written.
#
#   KIWI_SCOPE  user        KIWI_PREFIX  ~/.local
#   KIWI_ACTION install|update|uninstall
#   KIWI_GUI    0 on a headless machine
#   KIWI_PURGE  1 only when the user asked for --purge
set -euo pipefail

KIWI_SCOPE="${KIWI_SCOPE:-user}"
KIWI_PREFIX="${KIWI_PREFIX:-$HOME/.local}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP=kiwi-custodia
DESKTOP_ID=eu.kiwinetwork.KiwiCustodia   # the GTK application id: entry and icon carry it
LIBDIR="$KIWI_PREFIX/lib/$APP"
# The proxy engine: exits, gateways, DNS. A separate kiwi app (DEPENDS), whose
# package the launchers put on the path.
PROXY_LIB="$KIWI_PREFIX/lib/kiwi-proxy"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/$APP"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if [[ "$KIWI_SCOPE" != user ]]; then
    echo "install.sh: $APP is user-scope only; nothing to do for scope '$KIWI_SCOPE'"
    exit 0
fi

refresh_desktop_caches() {
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -qtf "$KIWI_PREFIX/share/icons/hicolor" 2>/dev/null || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q "$KIWI_PREFIX/share/applications" 2>/dev/null || true
        update-desktop-database -q "$APPS" 2>/dev/null || true
    fi
}

do_install() {
    mkdir -p "$LIBDIR" "$KIWI_PREFIX/bin"
    rm -rf "$LIBDIR/kiwi_custodia" "$LIBDIR/containers"
    cp -r "$SRC/src/kiwi_custodia" "$LIBDIR/kiwi_custodia"
    cp -r "$SRC/containers" "$LIBDIR/containers"
    find "$LIBDIR" -name __pycache__ -type d -prune -exec rm -rf {} +

    cat > "$KIWI_PREFIX/bin/$APP" <<EOW
#!/usr/bin/env bash
export PYTHONPATH="$LIBDIR:$PROXY_LIB\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m kiwi_custodia "\$@"
EOW
    chmod +x "$KIWI_PREFIX/bin/$APP"

    if [[ "${KIWI_GUI:-1}" == 1 ]]; then
        cat > "$KIWI_PREFIX/bin/$APP-gui" <<EOW
#!/usr/bin/env bash
export PYTHONPATH="$LIBDIR:$PROXY_LIB\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m kiwi_custodia.ui "\$@"
EOW
        chmod +x "$KIWI_PREFIX/bin/$APP-gui"
        # Entry and icon are named after the GTK application id, so GNOME links
        # the window to them; Exec is the launcher's absolute path, as the app
        # grid may not have ~/.local/bin on its PATH.
        mkdir -p "$KIWI_PREFIX/share/applications"
        sed "s|^Exec=.*|Exec=$KIWI_PREFIX/bin/$APP-gui|" "$SRC/data/$DESKTOP_ID.desktop" \
            > "$KIWI_PREFIX/share/applications/$DESKTOP_ID.desktop"
        install -Dm644 "$SRC/data/$DESKTOP_ID.svg" \
            "$KIWI_PREFIX/share/icons/hicolor/scalable/apps/$DESKTOP_ID.svg" 2>/dev/null || true
        refresh_desktop_caches
    fi

    # Entries written for boxes and their apps carry the launcher's absolute
    # path; rewrite them in case the install moved.
    if [[ -d "$DATA/boxes" ]]; then
        "$KIWI_PREFIX/bin/$APP" desktop sync >/dev/null 2>&1 || true
    fi

    echo "installed $APP to $KIWI_PREFIX"
    echo
    echo "First run needs one command — it builds the tunnel image and runs kiwi-proxy's setup:"
    echo
    echo "    $APP setup"
    echo
    echo "Then:  $APP new work --exit EXIT --distro fedora   (kiwi-proxy list shows the exits)"
    echo "   or: $APP-gui   (\"Kiwi Custodia\" in your app grid)"
}

do_update() { do_install; }

do_uninstall() {
    # Running boxes are stopped so no container is left in a gateway nobody
    # manages; their homes stay unless purged.
    if [[ -x "$KIWI_PREFIX/bin/$APP" ]]; then
        for name in $("$KIWI_PREFIX/bin/$APP" list --json 2>/dev/null \
                        | python3 -c 'import json,sys; print(" ".join(b["id"] for b in json.load(sys.stdin)))' 2>/dev/null); do
            "$KIWI_PREFIX/bin/$APP" stop "$name" >/dev/null 2>&1 || true
        done
    fi
    rm -f "$KIWI_PREFIX/bin/$APP" "$KIWI_PREFIX/bin/$APP-gui"
    rm -f "$KIWI_PREFIX/share/applications/$DESKTOP_ID.desktop"
    rm -f "$KIWI_PREFIX/share/icons/hicolor/scalable/apps/$DESKTOP_ID.svg"
    rm -f "$APPS/$DESKTOP_ID".*.desktop
    rm -rf "$LIBDIR"
    refresh_desktop_caches
    podman rmi -f kiwi-custodia/tunnel:latest >/dev/null 2>&1 || true

    if [[ "${KIWI_PURGE:-0}" == 1 || "${2:-}" == --purge ]]; then
        echo "purging $DATA and $CONFIG — every box's home and snapshot is being deleted"
        rm -rf "$DATA" "$CONFIG"
        podman images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep "^localhost/$APP/box-" \
            | xargs -r podman rmi -f >/dev/null 2>&1 || true
        rm -f "${XDG_DATA_HOME:-$HOME/.local/share}"/icons/hicolor/*/apps/kc-*.* 2>/dev/null || true
    else
        echo "kept $DATA and the boxes' snapshot images (pass --purge to remove them)"
    fi
    echo "uninstalled $APP"
}

case "${KIWI_ACTION:-${1:-install}}" in
    install)   do_install ;;
    update)    do_update ;;
    uninstall) do_uninstall "$@" ;;
    *) echo "usage: $0 install|update|uninstall [--purge]" >&2; exit 1 ;;
esac
