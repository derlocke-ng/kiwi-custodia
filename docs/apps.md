# Apps in the app grid

The desktop apps you install in a box can go into your app grid, next to your
other apps. They then start like any other app, but run in the box and go out
through its exit. A box can also have an entry of its own, which opens a
terminal in it. This page says how both work.

## List a box's apps

```bash
kiwi-custodia apps work
```

`apps` reads the desktop files that the box's packages installed in
`/usr/share/applications` and `/usr/local/share/applications`, and lists each
app's id and name. The id is the desktop file's name without `.desktop`. A `*`
marks the apps that are in your app grid already. `--all` also lists apps
that hide themselves from menus. The box must be running, so `apps` starts it
when it is stopped.

In the app, **Applications…** in a box's menu shows the same list. It starts
the box first if it is stopped. Each app has a button that opens it and a
button that adds it to the app grid or removes it.

## Put an app into the app grid

```bash
kiwi-custodia export work org.example.App
kiwi-custodia export work org.example.App --rm     # take it out again
```

`export` writes an entry into your app grid named after the app and the box,
for example "Firefox (work)", so that the same app from two boxes can be told
apart. The entry:

- runs `kiwi-custodia run <box> -- <the app's command>`, so it starts the box
  when it is stopped;
- shows the app's own icon, copied from the box, or Kiwi Custodia's icon
  when the box has none;
- keeps the app's category and whether it runs in a terminal;
- tells the desktop which window belongs to it, so the dock shows the running
  app under its entry.

The desktop cannot hand files to an app in a box, so the entry opens the app
without files, even when you open a file with it.

When you delete a box, its apps leave the app grid. When a box is restored
from a snapshot on another device, its apps go back into the app grid there
once it is up; see [Snapshots](snapshots.md).

## The box's own entry

A box can have an entry of its own in the app grid, named after the box. It
opens a terminal with a shell in the box and starts the box when it is
stopped. A right click on it offers **Stop**. Its icon is the box's icon in
the box's colour; see [Colours](boxes.md#colours).

The entry is off by default. Turn it on with **Show in the app grid** in the
box dialog, `kiwi-custodia new … --desktop-entry`, or
`kiwi-custodia set BOX --desktop-entry`; `--no-desktop-entry` turns it off.

`kiwi-custodia desktop sync` rewrites the entry of every box and removes
entries of boxes that no longer exist. The installer runs it after an install
or update, so that these entries point to the new install. It does not rewrite
the entries of apps you exported; if the install moved, export them again.

## Files

| Path | What it is |
|---|---|
| `~/.local/share/applications/eu.kiwinetwork.KiwiCustodia.box-<box>-<app>.desktop` | An app you exported. |
| `~/.local/share/applications/eu.kiwinetwork.KiwiCustodia.enter-<id8>.desktop` | A box's own entry. |
| `~/.local/share/icons/hicolor/<size>/apps/kc-<box>-<icon>.*` | The icons of the apps you exported. |
| `~/.local/share/kiwi-custodia/icons/<id>-<colour>.svg` | A box's icon in its colour. |

`<box>` is the box's name, `<id>` its id, and `<id8>` the first 8 characters
of its id.
