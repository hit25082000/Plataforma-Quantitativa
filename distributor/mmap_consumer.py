"""Shared-memory market consumer compatible with ZmqConsumer API."""

import asyncio
import ctypes
import json
import logging
from multiprocessing import shared_memory
import threading
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

POLL_SLEEP_S = 0.0005
MMAP_LOOP_BATCH_MAX = 128
MMAP_LOOP_BATCH_FLUSH_S = 0.008


def _crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    crc = init & 0xFFFF
    for b in data:
        crc ^= (b & 0xFF) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def _mapping_candidates(mapping_name: str) -> list[str]:
    """Windows mmap tagname can reject explicit namespace prefixes; try normalized names too."""
    raw = (mapping_name or "").strip()
    if not raw:
        return [raw]
    candidates = [raw]
    if "\\" in raw:
        normalized = raw.split("\\", 1)[1]
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


class _TradePayload(ctypes.Structure):
    _fields_ = [
        ("ticker", ctypes.c_char * 24),
        ("trade_date", ctypes.c_char * 16),
        ("price", ctypes.c_double),
        ("qty", ctypes.c_int64),
        ("buy_agent", ctypes.c_int32),
        ("sell_agent", ctypes.c_int32),
        ("trade_type", ctypes.c_uint8),
        ("trade_source", ctypes.c_uint8),
        ("reserved0", ctypes.c_uint16),
        ("trade_number", ctypes.c_uint32),
        ("trade_flags", ctypes.c_uint32),
        ("trade_epoch_ms", ctypes.c_int64),
        ("vwap", ctypes.c_double),
        ("net_aggression", ctypes.c_int64),
    ]


class _RingHeader(ctypes.Structure):
    _fields_ = [
        ("magic", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("header_size", ctypes.c_uint32),
        ("slot_size", ctypes.c_uint32),
        ("capacity", ctypes.c_uint64),
        ("write_seq", ctypes.c_uint64),
        ("dropped", ctypes.c_uint64),
        ("created_epoch_ms", ctypes.c_uint64),
        ("reserved", ctypes.c_uint64 * 8),
    ]


class _RingSlot(ctypes.Structure):
    _fields_ = [
        ("committed_seq", ctypes.c_uint64),
        ("message_type", ctypes.c_uint32),
        ("payload_size", ctypes.c_uint32),
        ("trade", _TradePayload),
    ]


class MmapConsumer:
    """Reads lock-free ring buffer in shared memory and pushes JSON strings."""

    SHM_MAGIC = 0x504D4853
    SHM_VERSION = 1
    MESSAGE_TYPE_TRADE = 1

    @classmethod
    def probe_mapping(cls, mapping_name: str, map_size_bytes: int) -> tuple[bool, str]:
        """Best-effort startup probe used by fallback logic."""
        last_err = "mapping_not_found"
        for candidate in _mapping_candidates(mapping_name):
            try:
                shm = shared_memory.SharedMemory(name=candidate, create=False)
            except FileNotFoundError:
                last_err = "mapping_not_found"
                continue
            except OSError as exc:
                last_err = f"mapping_open_failed:{exc}"
                continue

            try:
                header = _RingHeader.from_buffer_copy(shm.buf[: ctypes.sizeof(_RingHeader)])
                if header.magic != cls.SHM_MAGIC:
                    last_err = f"invalid_magic:{header.magic}"
                    continue
                if header.version != cls.SHM_VERSION:
                    last_err = f"invalid_version:{header.version}"
                    continue
                if int(header.capacity) <= 0:
                    last_err = "invalid_capacity"
                    continue
                return True, "ok"
            finally:
                shm.close()
        return False, last_err

    def __init__(
        self,
        mapping_name: str,
        queue: asyncio.Queue[str],
        map_size_bytes: int,
        dom_soft_limit_pct: int = 70,
    ) -> None:
        self._mapping_name = mapping_name
        self._queue = queue
        self._map_size_bytes = map_size_bytes
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._shm: Optional[shared_memory.SharedMemory] = None
        self._header: Optional[_RingHeader] = None
        self._slots_offset = ctypes.sizeof(_RingHeader)
        self._next_seq = 1
        self._dropped_count = 0
        self._rescued_trades = 0
        self._evicted_dom = 0
        self._gap_count = 0
        self._gap_messages = 0
        self._ring_dropped_last = 0
        self._integrity_failures = 0
        self._crc_mismatch = 0
        self._payload_mismatch = 0
        self._committed_mismatch = 0
        safe_pct = max(1, min(int(dom_soft_limit_pct), 99))
        maxsize = max(int(getattr(queue, "maxsize", 0)), 0)
        self._dom_soft_limit = int(maxsize * safe_pct / 100) if maxsize > 0 else 0

    @staticmethod
    def _decode_cstr(raw: bytes) -> str:
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

    @staticmethod
    def _iso_ts(epoch_ms: int) -> str:
        if epoch_ms <= 0:
            return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _message_type(self, raw: str) -> str:
        try:
            msg = json.loads(raw)
            if isinstance(msg, dict):
                return str(msg.get("type", ""))
        except json.JSONDecodeError:
            return ""
        return ""

    def _evict_one_dom_snapshot(self) -> bool:
        q = self._queue._queue  # type: ignore[attr-defined]
        for idx, item in enumerate(q):
            if "dom_snapshot" not in item:
                continue
            if self._message_type(item) == "dom_snapshot":
                del q[idx]
                self._evicted_dom += 1
                return True
        return False

    def _put_msg(self, raw: str) -> None:
        msg_type = self._message_type(raw)
        is_dom = msg_type == "dom_snapshot"
        is_trade_like = msg_type in ("trade", "flow_inversion")
        is_vp_ti = msg_type in ("volume_profile", "tape_intelligence")
        if is_dom and self._dom_soft_limit > 0 and self._queue.qsize() >= self._dom_soft_limit:
            self._dropped_count += 1
            return
        try:
            self._queue.put_nowait(raw)
        except asyncio.QueueFull:
            if is_dom:
                self._dropped_count += 1
                return
            if (is_trade_like or is_vp_ti) and self._evict_one_dom_snapshot():
                try:
                    self._queue.put_nowait(raw)
                    self._rescued_trades += 1
                    return
                except asyncio.QueueFull:
                    pass
            logger.warning("Market queue full, discarding non-dom message")

    def _put_trade_raw(self, raw: str) -> None:
        """Fast path for SHM trade payloads (avoids JSON parse on event loop)."""
        try:
            self._queue.put_nowait(raw)
        except asyncio.QueueFull:
            if self._evict_one_dom_snapshot():
                try:
                    self._queue.put_nowait(raw)
                    self._rescued_trades += 1
                    return
                except asyncio.QueueFull:
                    pass
            logger.warning("Market queue full, discarding trade message")

    def _put_trade_batch(self, batch: list[str]) -> None:
        for raw in batch:
            self._put_trade_raw(raw)

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._loop = loop
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("MMAP consumer started, mapping=%s", self._mapping_name)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def metrics(self) -> dict[str, int]:
        return {
            "dropped_dom": self._dropped_count,
            "rescued_trade_like": self._rescued_trades,
            "evicted_dom": self._evicted_dom,
            "gap_count": self._gap_count,
            "gap_messages": self._gap_messages,
            "ring_dropped": self._ring_dropped_last,
            "integrity_failures": self._integrity_failures,
            "crc_mismatch": self._crc_mismatch,
            "payload_mismatch": self._payload_mismatch,
            "committed_mismatch": self._committed_mismatch,
        }

    @staticmethod
    def _compute_slot_crc16(slot: _RingSlot) -> int:
        trade_raw = ctypes.string_at(ctypes.addressof(slot.trade), ctypes.sizeof(_TradePayload))
        trade = _TradePayload.from_buffer_copy(trade_raw)
        trade.reserved0 = 0
        trade_bytes = ctypes.string_at(ctypes.addressof(trade), ctypes.sizeof(_TradePayload))
        slot_prefix = int(slot.message_type).to_bytes(4, byteorder="little", signed=False) + int(
            slot.payload_size
        ).to_bytes(4, byteorder="little", signed=False)
        return _crc16_ccitt(slot_prefix + trade_bytes)

    def _open_mapping_with_retry(self) -> bool:
        backoff_s = 0.5
        while not self._stop_event.is_set():
            opened = False
            for candidate in _mapping_candidates(self._mapping_name):
                try:
                    self._shm = shared_memory.SharedMemory(name=candidate, create=False)
                    opened = True
                    break
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    logger.warning("Shared memory open failed (%s): %s", candidate, exc)
            if opened and self._shm is not None:
                self._header = _RingHeader.from_buffer_copy(self._shm.buf[: ctypes.sizeof(_RingHeader)])
                if self._header.magic != self.SHM_MAGIC or self._header.version != self.SHM_VERSION:
                    logger.warning("MMAP header mismatch: magic=%s version=%s", self._header.magic, self._header.version)
                    self._shm.close()
                    self._shm = None
                else:
                    return True
            else:
                logger.warning("Shared memory not found (%s). Retrying...", self._mapping_name)
            time.sleep(backoff_s)
            backoff_s = min(backoff_s * 1.5, 3.0)
        return False

    def _read_slot(self, idx: int) -> _RingSlot:
        assert self._shm is not None
        assert self._header is not None
        slot_size = int(self._header.slot_size)
        start = self._slots_offset + idx * slot_size
        end = start + ctypes.sizeof(_RingSlot)
        raw = bytes(self._shm.buf[start:end])
        return _RingSlot.from_buffer_copy(raw)

    def _run(self) -> None:
        if not self._open_mapping_with_retry():
            return
        assert self._header is not None
        loop = self._loop
        pending: list[str] = []
        last_flush = time.monotonic()
        try:
            while not self._stop_event.is_set():
                assert self._shm is not None
                self._header = _RingHeader.from_buffer_copy(self._shm.buf[: ctypes.sizeof(_RingHeader)])
                write_seq = int(self._header.write_seq)
                capacity = int(self._header.capacity)
                self._ring_dropped_last = int(self._header.dropped)
                if write_seq <= 0 or capacity <= 0:
                    time.sleep(POLL_SLEEP_S)
                    continue
                if self._next_seq < (write_seq - capacity + 1):
                    lost = (write_seq - capacity + 1) - self._next_seq
                    if lost > 0:
                        self._gap_messages += int(lost)
                    self._gap_count += 1
                    self._next_seq = write_seq - capacity + 1
                if self._next_seq > write_seq:
                    time.sleep(POLL_SLEEP_S)
                    continue

                idx = int((self._next_seq - 1) % capacity)
                slot = self._read_slot(idx)
                if int(slot.committed_seq) != self._next_seq:
                    if int(slot.committed_seq) > self._next_seq:
                        lost = int(slot.committed_seq) - self._next_seq
                        if lost > 0:
                            self._gap_messages += int(lost)
                        self._gap_count += 1
                        self._next_seq = int(slot.committed_seq)
                    else:
                        self._committed_mismatch += 1
                        time.sleep(POLL_SLEEP_S)
                    continue
                if int(slot.message_type) != self.MESSAGE_TYPE_TRADE:
                    self._next_seq += 1
                    continue
                if int(slot.payload_size) != ctypes.sizeof(_TradePayload):
                    self._integrity_failures += 1
                    self._payload_mismatch += 1
                    self._next_seq += 1
                    continue
                expected_crc16 = int(slot.trade.reserved0) & 0xFFFF
                got_crc16 = self._compute_slot_crc16(slot)
                if got_crc16 != expected_crc16:
                    self._integrity_failures += 1
                    self._crc_mismatch += 1
                    self._next_seq += 1
                    continue

                trade = slot.trade
                payload = {
                    "topic": "market",
                    "type": "trade",
                    "ticker": self._decode_cstr(bytes(trade.ticker)),
                    "price": float(trade.price),
                    "qty": int(trade.qty),
                    "buy_agent": int(trade.buy_agent),
                    "sell_agent": int(trade.sell_agent),
                    "trade_type": int(trade.trade_type),
                    "trade_number": int(trade.trade_number),
                    "trade_date": self._decode_cstr(bytes(trade.trade_date)),
                    "trade_source": "history" if int(trade.trade_source) == 1 else "realtime",
                    "is_edit": bool(int(trade.trade_flags) & 0x1),
                    "vwap": float(trade.vwap),
                    "net_aggression": int(trade.net_aggression),
                    "ts": self._iso_ts(int(trade.trade_epoch_ms)),
                }
                raw = json.dumps(payload)
                pending.append(raw)
                now = time.monotonic()
                should_flush = (
                    len(pending) >= MMAP_LOOP_BATCH_MAX
                    or (now - last_flush) >= MMAP_LOOP_BATCH_FLUSH_S
                )
                if should_flush:
                    batch = pending
                    pending = []
                    last_flush = now
                    if loop is not None:
                        loop.call_soon_threadsafe(self._put_trade_batch, batch)
                    else:
                        self._put_trade_batch(batch)
                self._next_seq += 1
        finally:
            if pending:
                if loop is not None:
                    loop.call_soon_threadsafe(self._put_trade_batch, pending)
                else:
                    self._put_trade_batch(pending)
            if self._shm is not None:
                self._shm.close()
                self._shm = None
            logger.info("MMAP consumer stopped")
