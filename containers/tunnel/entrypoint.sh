#!/bin/sh
# kiwi-custodia tunnel — make a kiwi-proxy gateway's namespace route everything
# into the gateway's own SOCKS5 forwarder, so a box joined to it needs no proxy
# settings at all.
#
# Runs inside the gateway's network namespace (--network container:kf-gw-…) with
# NET_ADMIN and /dev/net/tun. It creates the TUN device, takes the default
# route for it, keeps the gateway's one permitted destination reachable on the
# real interface, and permits output on the TUN in the gateway's nftables.
# tun2socks reads the packets and connects through 127.0.0.1:1080.
#
# If this container dies the TUN device goes with it and with it the default
# route: members have no route at all, which is the fail-closed state kiwi-proxy
# promises. Nothing has to notice.
#
#   KC_SOCKS          the gateway forwarder (127.0.0.1:1080)
#   KC_ENDPOINT_IP    the gateway's permitted destination; read from its
#                     ruleset when unset
#   KC_TUN            device name (kc0)
#   KC_TUN_ADDR       its address (198.18.0.1/15, the benchmarking range)
#   KC_DNS_MODE       resolver | remote — remote starts the DNS stub, because
#                     the gateway has no resolver then and a box needs one
#   KC_DNS_STUB       the stub's address (127.0.0.3)
#   KC_DNS_UPSTREAM   where the stub sends queries, over TCP through the exit
set -eu

log() { printf 'tunnel: %s\n' "$*"; }
die() { printf 'tunnel: FATAL: %s\n' "$*" >&2; exit 1; }

KC_SOCKS="${KC_SOCKS:-127.0.0.1:1080}"
KC_TUN="${KC_TUN:-kc0}"
KC_TUN_ADDR="${KC_TUN_ADDR:-198.18.0.1/15}"
KC_DNS_MODE="${KC_DNS_MODE:-resolver}"
KC_DNS_STUB="${KC_DNS_STUB:-127.0.0.3}"
KC_DNS_UPSTREAM="${KC_DNS_UPSTREAM:-1.1.1.1:53}"

[ -c /dev/net/tun ] || die "/dev/net/tun is not in this container"
nft list table inet kiwiproxy >/dev/null 2>&1 || die "this is not a kiwi-proxy gateway namespace"

# ------------------------------------------------------- permitted destination
if [ -z "${KC_ENDPOINT_IP:-}" ]; then
    KC_ENDPOINT_IP="$(nft list chain inet kiwiproxy output \
        | sed -n 's/.*ip daddr \([0-9.]*\) tcp dport.*/\1/p' | head -n 1)"
fi
[ -n "$KC_ENDPOINT_IP" ] || die "cannot tell the gateway's permitted destination"

# The forwarder must keep reaching it on the real interface once the default
# route is the TUN. An on-link destination (a provider on the kf-providers
# bridge) already has its connected route; a remote one gets a host route via
# the gateway the default route used.
route="$(ip -4 route get "$KC_ENDPOINT_IP" 2>/dev/null | head -n 1 || true)"
[ -n "$route" ] || die "no route to $KC_ENDPOINT_IP"
case "$route" in
  *" dev $KC_TUN "*) die "the permitted destination already routes into the tunnel";;
  *" via "*)
    via="$(printf '%s\n' "$route" | sed -n 's/.* via \([0-9.]*\).*/\1/p')"
    dev="$(printf '%s\n' "$route" | sed -n 's/.* dev \([^ ]*\).*/\1/p')"
    ip route replace "$KC_ENDPOINT_IP/32" via "$via" dev "$dev"
    log "pinned $KC_ENDPOINT_IP via $via dev $dev";;
  *)
    log "$KC_ENDPOINT_IP is on-link; its connected route stays";;
esac

# ------------------------------------------------------------------ firewall
# One rule into the gateway's output chain: packets leaving on the TUN are
# accepted. They do not leave the namespace there — tun2socks reads them and
# opens a connection to the forwarder on lo, which the ruleset already permits,
# and the forwarder leaves by the one permitted destination.
if ! nft list chain inet kiwiproxy output | grep -q "oifname \"$KC_TUN\""; then
    nft insert rule inet kiwiproxy output oifname "$KC_TUN" accept
fi

# ----------------------------------------------------------------- tun2socks
log "tun2socks: $KC_TUN -> socks5://$KC_SOCKS"
tun2socks --device "tun://$KC_TUN" --proxy "socks5://$KC_SOCKS" --mtu 1500 --loglevel warn &
T2S_PID=$!
ready=false
for _ in $(seq 1 50); do
    kill -0 "$T2S_PID" 2>/dev/null || die "tun2socks exited during startup"
    if ip link show "$KC_TUN" >/dev/null 2>&1; then ready=true; break; fi
    sleep 0.1
done
[ "$ready" = true ] || die "tun2socks never created $KC_TUN"

ip addr replace "$KC_TUN_ADDR" dev "$KC_TUN"
ip link set "$KC_TUN" up

# The default route: taken from whatever had it (pasta's or the bridge's) and
# given to the TUN. IPv6 gets none at all: the gateway drops it anyway.
while ip -4 route show default | grep -q .; do
    ip -4 route del default
done
ip -4 route replace default dev "$KC_TUN"

# ------------------------------------------------------------------ DNS stub
STUB_PID=""
if [ "$KC_DNS_MODE" = remote ]; then
    log "dns: stub on $KC_DNS_STUB:53, queries over TCP to $KC_DNS_UPSTREAM through the exit"
    python3 /usr/local/bin/kc-dnsstub --listen "$KC_DNS_STUB" --socks "$KC_SOCKS" \
        --upstream "$KC_DNS_UPSTREAM" &
    STUB_PID=$!
    for _ in $(seq 1 30); do
        kill -0 "$STUB_PID" 2>/dev/null || die "dns stub exited during startup"
        if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); s.connect(('$KC_DNS_STUB',53))" 2>/dev/null; then break; fi
        sleep 0.1
    done
fi

cleanup() {
    log "shutting down"
    [ -n "$STUB_PID" ] && kill "$STUB_PID" 2>/dev/null || true
    kill "$T2S_PID" 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}
trap cleanup TERM INT

log "ready — default route is $KC_TUN"

while true; do
    sleep 5
    kill -0 "$T2S_PID" 2>/dev/null || die "tun2socks died"
    if [ -n "$STUB_PID" ]; then
        kill -0 "$STUB_PID" 2>/dev/null || die "dns stub died"
    fi
done
