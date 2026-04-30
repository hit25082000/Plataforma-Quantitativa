"""Testes do consumer SHM."""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
import unittest
from multiprocessing import shared_memory
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mmap_consumer import MmapConsumer, _RingHeader, _RingSlot, _TradePayload


class _StopOnPutQueue:
    def __init__(self, stop_event: threading.Event) -> None:
        self._stop_event = stop_event
        self.items: list[str] = []
        self.maxsize = 8
        self._queue: list[str] = []

    def put_nowait(self, item: str) -> None:
        self.items.append(item)
        self._queue.append(item)
        self._stop_event.set()

    def qsize(self) -> int:
        return len(self.items)


def _write_bytes(shm: shared_memory.SharedMemory, offset: int, obj: ctypes.Structure) -> None:
    raw = ctypes.string_at(ctypes.addressof(obj), ctypes.sizeof(type(obj)))
    shm.buf[offset : offset + len(raw)] = raw


@unittest.skipUnless(os.name == "nt", "shared memory names are Windows-specific here")
class TestMmapConsumer(unittest.TestCase):
    def test_reads_trade_and_counts_gap(self) -> None:
        hdr_sz = ctypes.sizeof(_RingHeader)
        slot_sz = ctypes.sizeof(_RingSlot)
        map_size = hdr_sz + slot_sz
        shm_name = f"PQTest{os.getpid()}_{int(time.time() * 1000)}"
        shm = shared_memory.SharedMemory(name=shm_name, create=True, size=map_size)
        try:
            header = _RingHeader()
            header.magic = MmapConsumer.SHM_MAGIC
            header.version = MmapConsumer.SHM_VERSION
            header.header_size = hdr_sz
            header.slot_size = slot_sz
            header.capacity = 1
            header.write_seq = 3
            header.dropped = 2
            header.created_epoch_ms = int(time.time() * 1000)
            _write_bytes(shm, 0, header)

            trade = _TradePayload()
            trade.ticker = b"WINFUT\x00" + b"\x00" * 17
            trade.trade_date = b"2026-04-17\x00" + b"\x00" * 6
            trade.price = 123.45
            trade.qty = 7
            trade.buy_agent = 11
            trade.sell_agent = 22
            trade.trade_type = 2
            trade.trade_source = 1
            trade.reserved0 = 0
            trade.trade_number = 999
            trade.trade_flags = 1
            trade.trade_epoch_ms = 1_713_336_000_000
            trade.vwap = 123.0
            trade.net_aggression = 5

            slot = _RingSlot()
            slot.committed_seq = 3
            slot.message_type = MmapConsumer.MESSAGE_TYPE_TRADE
            slot.payload_size = ctypes.sizeof(_TradePayload)
            slot.trade = trade
            slot.trade.reserved0 = MmapConsumer._compute_slot_crc16(slot)
            _write_bytes(shm, hdr_sz, slot)

            consumer_stop = threading.Event()
            queue = _StopOnPutQueue(consumer_stop)
            consumer = MmapConsumer(shm_name, queue, map_size_bytes=map_size)
            consumer.start(loop=None)
            self.assertTrue(consumer_stop.wait(timeout=5.0), "consumer did not publish a trade")
            consumer.stop()

            self.assertEqual(len(queue.items), 1)
            payload = json.loads(queue.items[0])
            self.assertEqual(payload["type"], "trade")
            self.assertEqual(payload["ticker"], "WINFUT")
            self.assertEqual(payload["price"], 123.45)
            self.assertEqual(payload["qty"], 7)
            self.assertEqual(payload["trade_number"], 999)
            self.assertTrue(payload["is_edit"])

            metrics = consumer.metrics()
            self.assertEqual(metrics["gap_count"], 1)
            self.assertEqual(metrics["gap_messages"], 2)
            self.assertEqual(metrics["ring_dropped"], 2)
            self.assertEqual(metrics["integrity_failures"], 0)
            self.assertEqual(metrics["crc_mismatch"], 0)
            self.assertEqual(metrics["payload_mismatch"], 0)
            self.assertEqual(metrics["committed_mismatch"], 0)
        finally:
            shm.close()
            shm.unlink()

    def test_discards_trade_on_crc_mismatch(self) -> None:
        hdr_sz = ctypes.sizeof(_RingHeader)
        slot_sz = ctypes.sizeof(_RingSlot)
        map_size = hdr_sz + slot_sz
        shm_name = f"PQTestBadCrc{os.getpid()}_{int(time.time() * 1000)}"
        shm = shared_memory.SharedMemory(name=shm_name, create=True, size=map_size)
        try:
            header = _RingHeader()
            header.magic = MmapConsumer.SHM_MAGIC
            header.version = MmapConsumer.SHM_VERSION
            header.header_size = hdr_sz
            header.slot_size = slot_sz
            header.capacity = 1
            header.write_seq = 1
            header.dropped = 0
            header.created_epoch_ms = int(time.time() * 1000)
            _write_bytes(shm, 0, header)

            trade = _TradePayload()
            trade.ticker = b"WINFUT\x00" + b"\x00" * 17
            trade.trade_date = b"2026-04-19\x00" + b"\x00" * 6
            trade.price = 123.45
            trade.qty = 1
            trade.buy_agent = 1
            trade.sell_agent = 2
            trade.trade_type = 2
            trade.trade_source = 0
            trade.reserved0 = 0
            trade.trade_number = 1
            trade.trade_flags = 0
            trade.trade_epoch_ms = 1_713_336_000_000
            trade.vwap = 123.4
            trade.net_aggression = 0

            slot = _RingSlot()
            slot.committed_seq = 1
            slot.message_type = MmapConsumer.MESSAGE_TYPE_TRADE
            slot.payload_size = ctypes.sizeof(_TradePayload)
            slot.trade = trade
            slot.trade.reserved0 = 123  # CRC inválido proposital
            _write_bytes(shm, hdr_sz, slot)

            consumer_stop = threading.Event()
            queue = _StopOnPutQueue(consumer_stop)
            consumer = MmapConsumer(shm_name, queue, map_size_bytes=map_size)
            consumer.start(loop=None)
            time.sleep(0.2)
            consumer.stop()

            self.assertEqual(len(queue.items), 0)
            metrics = consumer.metrics()
            self.assertGreater(metrics["integrity_failures"], 0)
            self.assertGreater(metrics["crc_mismatch"], 0)
            self.assertEqual(metrics["payload_mismatch"], 0)
        finally:
            shm.close()
            shm.unlink()

    def test_discards_trade_on_payload_size_mismatch(self) -> None:
        hdr_sz = ctypes.sizeof(_RingHeader)
        slot_sz = ctypes.sizeof(_RingSlot)
        map_size = hdr_sz + slot_sz
        shm_name = f"PQTestBadPayload{os.getpid()}_{int(time.time() * 1000)}"
        shm = shared_memory.SharedMemory(name=shm_name, create=True, size=map_size)
        try:
            header = _RingHeader()
            header.magic = MmapConsumer.SHM_MAGIC
            header.version = MmapConsumer.SHM_VERSION
            header.header_size = hdr_sz
            header.slot_size = slot_sz
            header.capacity = 1
            header.write_seq = 1
            header.dropped = 0
            header.created_epoch_ms = int(time.time() * 1000)
            _write_bytes(shm, 0, header)

            trade = _TradePayload()
            trade.ticker = b"WINFUT\x00" + b"\x00" * 17
            trade.trade_date = b"2026-04-19\x00" + b"\x00" * 6
            trade.price = 123.45
            trade.qty = 1
            trade.buy_agent = 1
            trade.sell_agent = 2
            trade.trade_type = 2
            trade.trade_source = 0
            trade.reserved0 = 0
            trade.trade_number = 1
            trade.trade_flags = 0
            trade.trade_epoch_ms = 1_713_336_000_000
            trade.vwap = 123.4
            trade.net_aggression = 0

            slot = _RingSlot()
            slot.committed_seq = 1
            slot.message_type = MmapConsumer.MESSAGE_TYPE_TRADE
            slot.payload_size = ctypes.sizeof(_TradePayload) - 1
            slot.trade = trade
            slot.trade.reserved0 = MmapConsumer._compute_slot_crc16(slot)
            _write_bytes(shm, hdr_sz, slot)

            consumer_stop = threading.Event()
            queue = _StopOnPutQueue(consumer_stop)
            consumer = MmapConsumer(shm_name, queue, map_size_bytes=map_size)
            consumer.start(loop=None)
            time.sleep(0.2)
            consumer.stop()

            self.assertEqual(len(queue.items), 0)
            metrics = consumer.metrics()
            self.assertGreater(metrics["integrity_failures"], 0)
            self.assertEqual(metrics["crc_mismatch"], 0)
            self.assertGreater(metrics["payload_mismatch"], 0)
        finally:
            shm.close()
            shm.unlink()


if __name__ == "__main__":
    unittest.main()
