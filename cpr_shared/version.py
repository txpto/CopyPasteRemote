"""Single source of truth for version numbers.

``__version__`` is the application version (semantic versioning).
``PROTOCOL_VERSION`` is bumped only when the wire protocol between client and
server changes in a backwards-incompatible way; the server rejects clients that
speak a different *major* protocol version.
"""

__version__ = "1.0.0"

# Wire-protocol version. Format: "MAJOR.MINOR".
# MAJOR mismatch  -> incompatible, server refuses the client.
# MINOR mismatch  -> compatible, newer side degrades gracefully.
PROTOCOL_VERSION = "1.0"
