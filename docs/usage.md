# Using kiwi-custodia

kiwi-custodia has two faces: the app, **Kiwi Custodia** in your app grid
(`kiwi-custodia-gui`), and the command `kiwi-custodia`. The app is a layer
over the command, so both do nearly the same things: `reset` is only a
command, and a box's colour is only in the app. This page describes the app,
its Preferences, and every command. What a box is and what it holds is on
[Boxes](boxes.md).

## The window

The window lists your boxes. Each row shows:

- the box's icon in its colour, so that boxes can be told apart at a glance
  (see [Colours](boxes.md#colours));
- a state icon that is green while the box runs, amber while it runs
  without a route or while its VPN is not answering, and grey while it is
  stopped;
- the box's name, its distribution and its exit, for example
  "Fedora, through client-a (proxy.example.net:1080)". On a VPN exit
  whose server does not answer, the line ends with "VPN not answering"; see
  [Exits and the network](exits.md#when-a-vpn-is-not-answering);
- a second line about its snapshots, when you use them;
- a terminal button, which opens a terminal with a shell in the box and
  starts the box first if it is stopped;
- **Start** or **Stop**;
- a menu with **Applications…**, **Details**, **Edit…**, **Check the exit**,
  **Open the home folder**, **Logs**, **Snapshots…** and **Delete**.

Clicking a row opens its **Details**: the distribution and image, the
hostname, the home folder, the container's name, the exit, its gateway, the
tunnel, the DNS, and the commands that enter the box.

The window checks the state of every box every four seconds. When it opens,
it removes containers that a crash left behind (see
[Repair on start](#general)), and it takes the snapshots that stopped boxes
still owe (see [Snapshots](snapshots.md#when-snapshots-are-taken)).

## The header bar

| Button | What it does |
|---|---|
| **+** | Opens the dialog for a new box. |
| Refresh | Reads the boxes and their states again. |
| Gear | Opens Preferences. **Ctrl+,** does the same. |
| Menu | **Stop every box**, and **About Kiwi Custodia**. |

Two banners can appear under the header bar. "Setup incomplete" names what is
missing and has a **Set up** button, which runs the
[first setup](install.md#first-setup). "Snapshots are locked on this device"
has an **Unlock** button, which asks for the snapshot passphrase.

When there are no boxes yet, the window shows **New box** and, with
kiwi-proxy 0.8.1 or newer, **Use a snapshot folder**, which brings the boxes of
another device here; see [Snapshots](snapshots.md).

## The box dialog

**New box** and **Edit…** open the same dialog:

| Group | Rows |
|---|---|
| Box | **Name**, **Distribution**, **Image** and **Hostname**. The distribution and the image are fixed once the box exists. |
| Network | **Exit**, a choice of kiwi-proxy's exits, and **Open Kiwi Proxy**, where you add or change an exit. |
| Desktop | **Hardware rendering**, **Show in the app grid**, **Colour**, **Extra packages** and **Shell**. |
| What travels to another device | Only when you edit a box: what its snapshots carry, with sizes. |
| Extra setup script | A shell script that runs once as root when the box is built. |

[Boxes](boxes.md#make-a-box) explains each of these. When you save a running
box, changes to its hostname, hardware rendering, packages and shell apply at
its next start; the app says so. A new exit stops a running box first.

## Preferences

Preferences has three pages. The Snapshots page needs kiwi-proxy 0.8.1 or
newer; without it, Preferences has only General and Maintenance.

### General

| Row | What it does |
|---|---|
| **Repair on start** | On by default. Before anything starts, the app removes kiwi-custodia's containers that an unclean shutdown left. A box's container is first kept in the box's own image, so nothing installed in it is lost. |
| **Distribution** | The distribution the dialog for a new box starts with. Fedora by default. |
| **Exit** | The exit the dialog for a new box starts with, or **Ask every time**. |
| **Size** | The window's size, kept when you close the window. **Reset** goes back to 1040 × 840. |

These settings are kept in `~/.config/kiwi-custodia/settings.json`, and the
window's size in `window.json` next to it.

### Snapshots

This page is kiwi-proxy's, and it is the same in Kiwi Proxy and Kiwi Fox: the
snapshot folder, this device's name, **Snapshot automatically**, **Ask before
using an older copy**, **Snapshot everything now** and the encryption.
[Snapshots](snapshots.md) explains them.

### Maintenance

| Row | What it does |
|---|---|
| **Set up environment** | Runs the [first setup](install.md#first-setup) again: images and DNS data. |
| **Check environment** | Says what is missing before a box can start. |
| **Check and repair** | Opens kiwi-proxy's check of Podman's storage, which is shared with Kiwi Proxy and Kiwi Fox. Needs kiwi-proxy 0.8.2 or newer. |
| **Tidy up** | Removes containers nobody uses, the same as `kiwi-custodia reap`. |

Each button closes Preferences and shows its result in the window.

## Every command

A box is named by its name or by the start of its id, the way git accepts a
short commit hash. Commands that need a running box start it first.

| Command | What it does |
|---|---|
| `kiwi-custodia setup` | Builds the tunnel image and runs kiwi-proxy's setup. |
| `kiwi-custodia doctor` | Says whether this machine is ready; see [Check the setup](install.md#check-the-setup). |
| `kiwi-custodia distros` | Lists the distributions a box can be. |
| `kiwi-custodia new NAME --exit EXIT` | Creates a box and starts it; see [Make a box](boxes.md#make-a-box). |
| `kiwi-custodia up BOX` | Starts a box without entering it. `--as-is` and `--restore` answer the [snapshot question](snapshots.md#before-a-box-starts) in advance. |
| `kiwi-custodia enter BOX` | Opens a shell in the box. |
| `kiwi-custodia run BOX -- COMMAND` | Runs one command in the box. |
| `kiwi-custodia stop BOX` | Stops a box and keeps what was installed in it. |
| `kiwi-custodia list` | Lists every box with its state: `running`, `stopped`, or `gateway-down` (it runs, but its gateway or tunnel is gone, so it has no route). |
| `kiwi-custodia show BOX` | Shows one box: its distribution, image, exit, gateway, container, home and more. |
| `kiwi-custodia set BOX …` | Changes a box; see [Change a box](boxes.md#change-a-box). |
| `kiwi-custodia reset BOX` | Takes a box back to its base image. The home stays. |
| `kiwi-custodia rm BOX` | Deletes a box and its home. |
| `kiwi-custodia check BOX` | Shows the address, place and network the world sees from inside the box. |
| `kiwi-custodia apps BOX` | Lists the desktop apps installed in the box. `--all` includes hidden ones. |
| `kiwi-custodia export BOX APP` | Puts one of the box's apps into your app grid. `--rm` takes it out again. |
| `kiwi-custodia desktop sync` | Rewrites the app-grid entry of every box and removes the ones of deleted boxes. |
| `kiwi-custodia ps` | Lists kiwi-custodia's containers, running or not. |
| `kiwi-custodia reap` | Removes containers nobody uses. A stopped box's container is kept in its image first. |
| `kiwi-custodia repair` | Removes containers that an unclean stop left. A box's container is kept in its image first. |
| `kiwi-custodia snapshot …` | Snapshots of your boxes; see [Snapshots](snapshots.md#commands). |

`distros`, `list`, `show`, `check`, `apps` and `ps` print JSON with `--json`.
`kiwi-custodia COMMAND --help` lists each command's options.
