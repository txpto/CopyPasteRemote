"""CopyPasteRemote orchestrator (server) package.

The server is the "director de orquesta": it authenticates machines, keeps the
pool registry, stores one encrypted clipboard payload per mailbox/slot and
notifies machines in real time over a WebSocket channel.
"""

from cpr_shared.version import __version__

__all__ = ["__version__"]
