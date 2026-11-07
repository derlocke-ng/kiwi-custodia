"""kiwi-custodia — distro containers whose every byte leaves through a kiwi-proxy exit.

A *box* is one Linux distribution in a rootless Podman container with a home of
its own, joined to the sealed gateway of a kiwi-proxy exit. Install anything in
it, run its desktop apps on your desktop; the box has no route but the exit.
"""

__version__ = "0.2.2"
# The GTK application's id. The desktop entry and the icon are named after it,
# which is how GNOME on Wayland connects the window to its entry.
APP_ID = "eu.kiwinetwork.KiwiCustodia"
