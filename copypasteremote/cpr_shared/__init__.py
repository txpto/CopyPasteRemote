"""Shared library used by both the CopyPasteRemote server and client.

This package contains code that must behave *identically* on the orchestrator
(which usually runs on a modern Linux/Windows VM) and on the Windows clients
(which may run as old as Windows 7 x64 with Python 3.8).  Keep it dependency
light and avoid anything that is not available on Python 3.8.
"""

from .version import __version__, PROTOCOL_VERSION

__all__ = ["__version__", "PROTOCOL_VERSION"]
