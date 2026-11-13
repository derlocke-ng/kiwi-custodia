# Boxes

A box is one Linux distribution in a rootless Podman container, with a home
folder of its own, joined to one kiwi-proxy exit. You install software in it
with its package manager, and its desktop apps open on your desktop. This page
says how to make a box, what is in it, how it keeps what you install, and how
to change, reset or delete it. How a box reaches the network is on
[Exits and the network](exits.md).

## Make a box

A box needs an exit, so make one in kiwi-proxy first (`kiwi-proxy add`, or
the Kiwi Proxy app). Then:

```bash
kiwi-custodia new work --exit client-a --distro fedora
```

`new` creates the box and starts it. In the app, **+** opens the same dialog
that **Edit…** opens later. The name may contain lower-case letters, digits
and dashes, starts with a letter or a digit, and is at most 63 characters
long, because it is also the box's hostname and part of file names.

| Option | What it does |
|---|---|
| `--exit EXIT` | The kiwi-proxy exit the box goes out through. Required. |
| `--distro KEY` | The distribution; `fedora` when you leave it out. See [Distributions](#distributions). |
| `--image REF` | An image instead of the distribution's, for example `registry/name:tag`. Required with `--distro custom`. |
| `--shell PATH` | The login shell in the box. Bash when you leave it out. |
| `--hostname NAME` | The box's hostname. Its name when you leave it out. |
| `--package NAME` | A package the first start installs. Repeat it for more. |
| `--no-gpu` | Does not pass the GPU (`/dev/dri`) in; apps then draw in software. |
| `--desktop-entry` | Puts a terminal into the box in your app grid; see [Apps in the app grid](apps.md#the-boxs-own-entry). |
| `--no-start` | Creates the box without starting it. |
| `--enter` | Opens a shell in the box once it is up. |

## Distributions

`kiwi-custodia distros` lists them:

| Key | Distribution | Image |
|---|---|---|
| `fedora` | Fedora (the default) | `registry.fedoraproject.org/fedora:latest` |
| `fedora-toolbox` | Fedora Toolbx | `registry.fedoraproject.org/fedora-toolbox:latest` |
| `ubuntu` | Ubuntu 24.04 LTS | `docker.io/library/ubuntu:24.04` |
| `ubuntu-toolbox` | Ubuntu 24.04 Toolbx | `quay.io/toolbx/ubuntu-toolbox:24.04` |
| `debian` | Debian stable | `docker.io/library/debian:stable` |
| `debian-toolbox` | Debian 12 Toolbx | `quay.io/toolbx-images/debian-toolbox:12` |
| `kali` | Kali Linux rolling | `docker.io/kalilinux/kali-rolling:latest` |
| `arch` | Arch Linux | `docker.io/library/archlinux:latest` |
| `arch-toolbox` | Arch Linux Toolbx | `quay.io/toolbx/arch-toolbox:latest` |
| `opensuse` | openSUSE Tumbleweed | `registry.opensuse.org/opensuse/tumbleweed:latest` |
| `rocky` | Rocky Linux 9 | `quay.io/toolbx-images/rockylinux-toolbox:9` |
| `alpine` | Alpine Linux | `docker.io/library/alpine:latest` |
| `custom` | Any image you name with `--image` | |

The Toolbx images already contain what toolbx and distrobox put into a
container. Kali is the bare rolling image; its tool collections are packages
you install on top. Alpine uses musl instead of glibc, so many proprietary
desktop apps do not run there. For a custom image, the first start finds its
package manager; kiwi-custodia knows dnf, apt, pacman, zypper and apk.

A box keeps the image it was made from. Its distribution and image cannot be
changed later; make a new box for another one.

## The first start

Podman pulls the distribution's image when a box that uses it starts for the
first time. The box's first process, `kc-init`, then installs a small
baseline with the distribution's package manager: sudo, bash, curl, gawk,
Mesa's graphics drivers, a font, `xdg-utils` and a few basic tools. The list
for each package manager is in
[kc-init.sh](https://github.com/derlocke-ng/kiwi-custodia/blob/main/containers/box/kc-init.sh).
It also installs the packages you named with `--package`. This takes as long
as the distribution's mirrors take, through the exit. If a package does not
install, the box still comes up, and its log says so (**Logs** in the app).

## What is in a box

- **Your user.** The box has a user with your name, your user id and your
  group id, so files in its home belong to you on both sides. `sudo` works
  without a password.
- **A home of its own.** The box's home is
  `~/.local/share/kiwi-custodia/boxes/<id>/home` on your machine, not your
  real home. Two boxes are two separate identities, and deleting a box deletes
  its home. To move files in or out, copy them there, or use the file chooser
  of an app in the box.
- **Your desktop.** Your Wayland display, X11 for programs that need
  Xwayland, the session bus, PipeWire and its PulseAudio socket, and the GPU
  are passed in. So a GTK, Qt or Electron app in the box opens on your
  desktop, uses your theme, plays sound and talks to the desktop portals. The
  box also uses your machine's time zone.
- **Its hostname** is the box's name unless you set another one, so the
  prompt reads `you@work`.
- **No proxy settings.** The box's only route already is the exit, so no
  program needs a proxy setting. `$KIWI_CUSTODIA_SOCKS` names the gateway's
  SOCKS5 proxy for a tool you want to point at it by hand. On an exit with
  remote DNS, such as Tor, `ALL_PROXY` is set as well, because a `.onion`
  address resolves only that way. Elsewhere it is not set, because Chromium and
  Electron apps that read it fail with "no internet".

Shells that `enter` and `run` open are login shells, so the box's
`/etc/profile.d` and your own shell files in its home apply.

## Use a box

```bash
kiwi-custodia enter work               # a shell in the box
kiwi-custodia run work -- htop         # one command in the box
kiwi-custodia stop work
```

`enter` and `run` start the box when it is stopped. In the app, the terminal
button of a row opens a terminal with a shell in the box. To start a box
without entering it, use `kiwi-custodia up work` or **Start** in the app.

## Keep what you installed

A box keeps what you install in it: packages, repositories you added, tools
you built. When the box stops, kiwi-custodia saves its container as an image
of its own, `localhost/kiwi-custodia/box-<id8>:latest` (`<id8>` is the first
8 characters of the box's id), and the next start
comes from that image. This matters because Podman cannot move a container to
another exit, so a box's container is made anew at every start.

Taking the exit down in Kiwi Proxy (its stop button, `kiwi-proxy down`)
removes the containers inside the exit's gateway, the box's among them.
kiwi-proxy 0.7.1 and newer save the box's image first, so nothing is lost. A
box container that a crash or a reboot left behind is saved before it is
replaced, too.

The box's image stays on this device. To have the box on another device, see
[Snapshots](snapshots.md).

## Change a box

```bash
kiwi-custodia set work --exit client-b
kiwi-custodia set work --package htop --package git
```

| Option | What it changes |
|---|---|
| `--name NAME` | The box's name. |
| `--exit EXIT` | The exit. A running box is stopped first and starts again on the new exit with everything that was installed in it. |
| `--hostname NAME` | The hostname; `''` goes back to the box's name. |
| `--shell PATH` | The login shell; `''` goes back to bash. |
| `--package NAME` | Adds a package. It is installed at the box's next start; to have it now, install it with `sudo` in the box. |
| `--gpu`, `--no-gpu` | Whether the GPU is passed in. |
| `--desktop-entry`, `--no-desktop-entry` | Whether the box has its own entry in your app grid. |
| `--setup-script FILE` | A shell script that runs once as root after the packages whenever the box is built from its base image. `-` reads it from standard input; `''` removes it. |

Changes to the hostname, the shell, the packages and the GPU apply at the
next start of a running box. In the app, **Edit…** changes the same things,
and the box's colour as well.

## Reset a box

```bash
kiwi-custodia reset work
```

`reset` takes a box back to its base image. Its container and its saved image
are removed; its home stays. The next start installs the baseline again, then
the box's packages, and runs its setup script. `reset` asks before it does
this; `--yes` does not ask.

## Delete a box

```bash
kiwi-custodia rm work
```

`rm` stops the box and removes its container, its saved image, its apps and
its own entry in your app grid, its record and its home. It asks first;
`--yes` does not ask. In the app, **Delete** in a row's menu does the same.
The exit stays in kiwi-proxy. Snapshots of the box in your snapshot folder
stay too; `kiwi-custodia snapshot forget` deletes them.

## Colours

Each box has a colour. Its icon, the Kiwi Custodia cube in that colour, shows
in the window's list and on the box's own entry in your app grid, so two boxes
do not look alike. Apps you export from a box keep their own icons.

A new box gets a colour no other box has. The first ones are far apart:
ember, ocean, forest, violet, honey, teal, crimson, indigo, kiwi, orchid, rose
and graphite, then three two-colour ones. When every colour is taken, a new box
gets the one fewest boxes have. Boxes made before kiwi-custodia 0.6.0 keep
Kiwi Custodia's own colours until you pick one.

The **Colour** row in the box dialog changes it. For a new box it starts at
"A colour of its own", which means the next free colour. There is no
command-line option for the colour.
