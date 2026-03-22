"""Configuration for Sync Monitor (Bovespa reference basket, yfinance .SA)."""

# ZMQ PUB: ver ../docs/PORTS.md (5557; não usar para HTTP)

TICKERS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "B3SA3", "ABEV3"]
POLL_INTERVAL_SEC = 3
SYNC_BAND_PCT = 0.50  # todos dentro de ±0.50% = in_sync (evita OUT OF SYNC em variação intraday normal, ex. -0.18%)
# Leituras consecutivas necessárias para mudar estado (evita alternância IN SYNC <-> OUT OF SYNC)
SYNC_HYSTERESIS_COUNT = 2
ZMQ_PUB_PORT = 5557
