# Exits and the network

A box reaches the network only through its exit. This page says what that
means for the programs in a box, how it differs between VPN exits and other
exits, how names are resolved, and what a box does not protect against.

An **exit** is a named connection that
[kiwi-proxy](https://kiwi-network.eu/docs/clients/kiwi-proxy/) keeps: a SOCKS5
proxy you were given, or one that a provider module runs, such as Tor, a VPN,
9proxy or Mysterium. For each exit in use, kiwi-proxy runs a **gateway**, a
container that holds the exit's network namespace. A network namespace is a
separate set of network interfaces, routes and firewall rules. Its firewall
drops everything except the way to the exit.

## A box has no route of its own

A box is joined to its exit's gateway. It has no network interfaces of its
own and uses the gateway's namespace, so the only way out is the exit. This
does not depend on proxy settings: it holds for the package manager, for a
game client and for a program that ignores `$ALL_PROXY`. If the exit stops,
the box has no route at all.

Exits are made and changed in kiwi-proxy, never in kiwi-custodia. In the box
dialog, **Open Kiwi Proxy** opens the Kiwi Proxy app. To move a box to another
exit, use `kiwi-custodia set BOX --exit OTHER`, or choose another exit in
**Edit…**. A running box is stopped for that and starts again on the new exit
with everything that was installed in it.

## Two kinds of exit

How a box's traffic gets into the exit depends on the exit.

| | VPN exit | Every other exit |
|---|---|---|
| Which exits | An exit of the VPN module, kiwi-plugin-vpn 0.3 or newer, with kiwi-proxy 0.11 or newer | A SOCKS5 proxy you were given, Tor, 9proxy, Mysterium, and a VPN exit with older versions |
| How the traffic goes | The gateway's namespace routes through the VPN tunnel itself. | A tunnel container sends every connection to the gateway's SOCKS5 proxy. |
| TCP | Yes | Yes |
| UDP | Yes: games, calls and DNS tools work. | No: UDP is dropped. |
| When the exit stops | Nothing leaves while the tunnel is down. | The box has no route. |

### On a VPN exit

The gateway of a VPN exit sits in the VPN's own network namespace, whose
route is the VPN tunnel. A box there sends TCP and UDP straight through the
tunnel and needs no tunnel container. A box's **Details** say "the VPN
itself: TCP and UDP, no sidecar" in the Tunnel row.

### On every other exit

The gateway of any other exit offers a SOCKS5 proxy, and nothing else leaves
it. A SOCKS5 proxy only carries the connections a program hands it, so
kiwi-custodia adds a **tunnel container** (`kc-tun-` and the start of the
exit's id) to the gateway's
namespace. It creates a TUN device, a virtual network interface, makes it the
namespace's default route, and runs tun2socks, which hands every TCP
connection on that device to the gateway's proxy. The box opens connections as
usual, and each of them goes through the exit.

UDP cannot go through this path, so an app's UDP is dropped. Most programs
then fall back to TCP; QUIC does, WebRTC media in calls does not. There is no
IPv6 route.

There is one tunnel container per exit, shared by every box on it. It stops
when the last box on the exit stops. [How it works](architecture.md) has the
details.

## When a VPN is not answering

With kiwi-proxy 0.18 or newer, the app asks every few seconds whether the
tunnel of a running box's VPN exit carries traffic. While the VPN server does
not answer, the box's row says "VPN not answering" and its state icon turns
to a warning. The box keeps running and nothing leaves meanwhile. The tunnel
reconnects by itself once the server answers again, and the row goes back to
normal. `kiwi-custodia list` does not show this.

## Names (DNS)

A box resolves names where its exit's DNS mode says. The mode is set on the
exit in kiwi-proxy.

| The exit's DNS mode | A box resolves names at |
|---|---|
| `resolver` (the default) | The gateway's own resolver at 127.0.0.2, which sends its queries through the exit and blocks advertising domains; see [kiwi-proxy's DNS page](https://kiwi-network.eu/docs/clients/kiwi-proxy/dns/). |
| `remote`, for Tor | A small resolver in the tunnel container at 127.0.0.3, which sends each query over TCP through the exit to a public resolver (1.1.1.1). |

## Boxes on the same exit

Boxes on one exit share its gateway, and on a non-VPN exit its tunnel
container. They have one namespace and one exit address, and on Tor the same
circuits. A kiwi-fox profile on the same exit shares it too. Boxes that must
be kept apart from each other need different exits.

The gateway stops when nothing uses it any longer: no box, no kiwi-fox
profile, and no `kiwi-proxy up`.

## Check the exit

```bash
kiwi-custodia check work
```

`check` asks a geolocation service from inside the box, through the same path
its apps take, and prints the address, the place and the network that the
world sees. It starts the box first if it is stopped. In the app, **Check the
exit** in a row's menu does the same for a running box. When the check fails
on a non-VPN exit, it also names the hosts the exit's proxy refused recently,
because an app sees a refused connection only as an SSL error.

## What a box is not

A box **restricts the network. It is not a sandbox that protects your desktop
from the programs in it.** Like a distrobox container, a box gets your display
and your session bus. A program in the box can therefore show windows, read
the clipboard, use the desktop portals and talk to other programs on the
session bus. What it cannot do is reach the network other than through its
exit.

A box is for using software through a tunnel. An identity that must not share
traits of your hardware with your other identities, such as a browser
fingerprint, is the job of
[kiwi-fox](https://kiwi-network.eu/docs/clients/kiwi-fox/).
