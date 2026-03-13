"""Configuration for the M3 Distribution Layer."""

import os

ZMQ_ADDRESS = "tcp://localhost:5555"
WS_PORT = int(os.environ.get("WS_PORT", "8000"))
WS_HOST = "127.0.0.1"  # apenas localhost (single machine)
DOM_THROTTLE_MS = 100  # máx 10 dom_snapshots/s para o frontend
MARKET_QUEUE_MAXSIZE = 1000  # descarta se frontend não consumir
