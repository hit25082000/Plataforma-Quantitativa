"""Configuration for Sync Monitor (BOVA11 only)."""

TICKERS = ["BOVA11"]
POLL_INTERVAL_SEC = 3
SYNC_BAND_PCT = 0.50  # todos dentro de ±0.50% = in_sync (evita OUT OF SYNC em variação intraday normal, ex. -0.18%)
# Leituras consecutivas necessárias para mudar estado (evita alternância IN SYNC <-> OUT OF SYNC)
SYNC_HYSTERESIS_COUNT = 2
ZMQ_PUB_PORT = 5557
