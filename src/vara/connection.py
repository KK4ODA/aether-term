"""
vara/connection.py — Connection state machine for Aether Term.

Tracks the lifecycle: IDLE → CONNECTING → CONNECTED → DISCONNECTING → IDLE
"""

from enum import Enum, auto


class ConnectionState(Enum):
    DISCONNECTED = auto()   # No TCP connection to modem
    MODEM_CONNECTED = auto()  # TCP link to modem established, no RF session
    INITIALIZING = auto()   # Sending MYCALL, COMPRESSION OFF, etc.
    CONNECTING = auto()     # CONNECT sent, waiting for CONNECTED/DISCONNECTED
    CONNECTED = auto()      # RF session active
    DISCONNECTING = auto()  # DISCONNECT sent, waiting for DISCONNECTED


# Human-readable labels for status bar
STATE_LABELS = {
    ConnectionState.DISCONNECTED: "DISCONNECTED",
    ConnectionState.MODEM_CONNECTED: "MODEM READY",
    ConnectionState.INITIALIZING: "INITIALIZING",
    ConnectionState.CONNECTING: "CONNECTING...",
    ConnectionState.CONNECTED: "CONNECTED",
    ConnectionState.DISCONNECTING: "DISCONNECTING...",
}

# Color names for status display
STATE_COLORS = {
    ConnectionState.DISCONNECTED: "red",
    ConnectionState.MODEM_CONNECTED: "yellow",
    ConnectionState.INITIALIZING: "yellow",
    ConnectionState.CONNECTING: "yellow",
    ConnectionState.CONNECTED: "green",
    ConnectionState.DISCONNECTING: "yellow",
}
