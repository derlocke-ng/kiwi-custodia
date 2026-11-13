# Snapshots

A snapshot is an encrypted copy of a box in a folder that your sync client
(for example Nextcloud) carries to your other devices. With snapshots you can
have the same box, with its home and what you installed in it, on your laptop
and your desktop, and you can go back to an earlier state of it. The folder,
the passphrase and the encryption belong to kiwi-proxy, which keeps its exits
in the same folder, and Kiwi Fox keeps its profiles there too; see
[kiwi-proxy's snapshot page](https://kiwi-network.eu/docs/clients/kiwi-proxy/snapshots/).

Snapshots need kiwi-proxy 0.8.1 or newer.

## Set it up

```bash
kiwi-proxy snapshot setup ~/Nextcloud/kiwi-snapshots   # once per device
kiwi-custodia snapshot list
```

`kiwi-custodia snapshot setup`, `status`, `unlock`, `lock` and `set` are the
same as the `kiwi-proxy snapshot` commands, because there is one folder and
one passphrase for every Kiwi app. In the app, the **Snapshots** page of
Preferences does the same, and so does **Use a snapshot folder** in an empty
window.

## What a snapshot holds

A snapshot does not hold the box's image, which is about 2 GB for a Fedora box
with a desktop app in it. It holds what you did to the box, recorded each time:

- **The box's record**: its name, distribution, exit, packages, setup script
  and exported apps.
- **Its home**, without `.cache`.
- **The packages you added**, from the package manager's own list of what was
  installed on purpose, minus what the base image and the baseline bring.
- **The system files you added or changed** outside the home: repository
  files and signing keys, changes under `/etc`, and what you unpacked into
  `/opt`, `/usr/local`, `/srv` or `/root`. A file that a package brings
  unchanged is left out, because the package brings it back. So are files that
  belong to this machine, such as users, the hostname, the resolver and
  certificate bundles.
- **Packages installed from a downloaded file**, on dnf boxes, and packages
  not from the repositories, on pacman boxes: they travel as their files. On
  dnf boxes, what they require is installed again on the other device.

The recording reads the box's saved image, never the running box. It runs in
throwaway containers of that image and of the base image, with no network.

## How a box is built

On another device, a restored box is built again from its base image at its
first start, through its own exit. Its home is put back at once; the rest comes
at that start, in this order:

1. the baseline and the packages named with `--package`, as at any first
   start;
2. the repository files and signing keys you added;
3. the packages you added, all at once, or one by one when that fails;
4. what packages installed from files require (dnf boxes);
5. the remaining system files;
6. the box's setup script, if it has one.

Its exported apps go back into the app grid once the box is up. A package that
does not install, because a mirror is down or the exit is slow, is named when
the box comes up and tried again at every start until it installs. The next
stop saves the result as the box's own image on that device, and from then on
the box starts from that image as usual.

The **setup script** (the box dialog's **Extra setup script**, or
`kiwi-custodia set BOX --setup-script FILE`) is for what a package list cannot
express. It runs once as root after the packages whenever the box is built
from its base image: at its first start here, after a `reset`, and on another
device when it is rebuilt.

## When snapshots are taken

- After a box ran and stopped, if it changed since its last snapshot.
- When you change a box with `kiwi-custodia set` or **Edit…**: the snapshot
  follows at its next stop, or the next time the app opens.
- When the app opens: stopped boxes that changed since their last snapshot
  get one.
- When you ask: `kiwi-custodia snapshot now`, **Snapshots…** in a box's menu,
  or **Snapshot everything now** on the Snapshots page of Preferences.

The first three happen while **Snapshot automatically** is on, which it is
unless you turn it off in kiwi-proxy's snapshot settings. A running box is
saved to its image first, so the recording reads a consistent system; its
home is copied as it is.

## Before a box starts

- **A newer copy elsewhere.** When the folder holds a newer snapshot from
  another device, kiwi-custodia asks before it starts the box: restore it and
  start, start as it is, or cancel. When the box changed both here and on the
  other device, you choose which copy wins. This needs **Ask before using an
  older copy**, which is on unless you turn it off.
- **In use elsewhere.** A box that is running on another device says so in
  its row, and kiwi-custodia asks before it starts here. The folder can tell
  only as fast as your sync client carries it.

The app asks in a dialog, and `kiwi-custodia up`, `enter` and `run` ask in the
terminal. `up --restore` and `up --as-is` answer the question in advance.
Without a terminal to ask in, the command starts the box as it is and prints
a note.

## Restore a box

```bash
kiwi-custodia snapshot restore work
```

`restore` puts the newest snapshot of a box in place, or the one you name with
`--id` (`snapshot history` lists them). Its record and home are put back now;
its system is rebuilt at its next start, as described in
[How a box is built](#how-a-box-is-built). If the box is on this device, its
copy here is kept as a snapshot first, so the restore can be undone; `restore`
asks before it replaces it, and `--yes` does not ask.

A restore is refused:

- while the box is running;
- when the box's exit is not on this device. Restore the exit in Kiwi Proxy
  first, from the same folder; kiwi-custodia never makes or restores exits;
- when another box here has the same name.

In the app, boxes in the folder that are not on this device are listed under
"In your snapshot folder, not on this device", each with **Restore**.

## Commands

| Command | What it does |
|---|---|
| `kiwi-custodia snapshot list` | Lists the boxes in the folder and here, and how the copies relate. |
| `kiwi-custodia snapshot now [BOX …]` | Takes a snapshot of the boxes you name, or of every box. |
| `kiwi-custodia snapshot history BOX` | Lists the snapshots of one box. |
| `kiwi-custodia snapshot show BOX` | Says what the newest snapshot of a box carries: the packages, the files and their size. |
| `kiwi-custodia snapshot restore BOX` | Restores a box; see [Restore a box](#restore-a-box). |
| `kiwi-custodia snapshot forget BOX --yes` | Deletes every snapshot of a box from the folder, on every device that syncs it. |

## Limits

- Packages are installed again from their repositories, so the other device
  may get newer versions.
- A large program that you unpacked by hand makes the snapshot as large as the
  program. **What travels to another device** in the box dialog shows the
  sizes.
- Only boxes with dnf, apt, pacman, zypper or apk are recorded. Other images
  carry their home and the packages you named with `--package` only.
- The box's saved image stays on its device and remains the fast way to start
  it there.
