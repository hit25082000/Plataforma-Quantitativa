"""Standalone Sync Monitor: polls prices, publishes sync status on ZMQ PUB :5557."""

import json
import logging
import sys
import time
from datetime import datetime, timezone

import zmq

from config import (
    POLL_INTERVAL_SEC,
    SYNC_BAND_PCT,
    SYNC_HYSTERESIS_COUNT,
    TICKERS,
    ZMQ_PUB_PORT,
)
from price_fetcher import fetch_prices
from sync_calculator import calculate_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    addr = f"tcp://*:{ZMQ_PUB_PORT}"
    sock.bind(addr)
    logger.info("Sync monitor ZMQ PUB bound to %s", addr)

    # Histerese: só muda para OUT OF SYNC após N leituras fora da banda; só volta a IN SYNC após N leituras dentro
    last_in_sync: bool | None = None
    consecutive_other: int = 0  # leituras consecutivas do valor oposto ao atual

    try:
        while True:
            try:
                prices = fetch_prices(TICKERS)
                if not prices:
                    logger.warning("Fetch returned no prices for %s (check yfinance/BOVA11.SA)", TICKERS)
                result = calculate_sync(prices, SYNC_BAND_PCT)
                raw_in_sync = result["in_sync"]

                if last_in_sync is None:
                    last_in_sync = raw_in_sync
                    consecutive_other = 0
                elif raw_in_sync != last_in_sync:
                    consecutive_other += 1
                    if consecutive_other >= SYNC_HYSTERESIS_COUNT:
                        last_in_sync = raw_in_sync
                        consecutive_other = 0
                else:
                    consecutive_other = 0

                in_sync_to_send = last_in_sync
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                msg = {
                    "topic": "sync",
                    "in_sync": in_sync_to_send,
                    "variations": result["variations"],
                    "ts": ts,
                }
                raw = json.dumps(msg)
                sock.send_string(raw)
                logger.info("sync published: in_sync=%s variations=%s", in_sync_to_send, result["variations"])
            except Exception as e:
                logger.warning("Sync cycle failed (will retry): %s", e)
            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        ctx.term()
        logger.info("Sync monitor stopped")


if __name__ == "__main__":
    main()
