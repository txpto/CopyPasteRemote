"""CopyPasteRemote Windows client (agent) package.

Only :mod:`cpr_client.clipboard_win`, :mod:`cpr_client.hotkeys` and
:mod:`cpr_client.tray` touch Windows-only APIs, and they import their native
dependencies lazily, so the rest of the package (config, packaging, serializer,
transport, agent) imports and unit-tests cleanly on any platform.
"""

from cpr_shared.version import __version__

__all__ = ["__version__"]
