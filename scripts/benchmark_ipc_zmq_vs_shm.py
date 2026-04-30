#!/usr/bin/env python3
"""
P3 benchmark: one-way producer→consumer latency for ZMQ (JSON/TCP) vs SHM ring (binary).

Windows required for SHM path (named file mapping). ZMQ runs on all platforms.

Outputs a CSV with per-sample rows and a trailing SUMMARY section (percentiles).

`--stress` uses a Python producer (mmap writes can be slow wall-clock); outputs include
both `achieved_rate` (configured duration) and `achieved_rate_effective`
(measured producer wall-clock).
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import platform
import traceback
from multiprocessing import shared_memory
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "distributor") not in sys.path:
    sys.path.insert(0, str(_ROOT / "distributor"))

from mmap_consumer import (  # noqa: E402
    MmapConsumer,
    _RingHeader,
    _RingSlot,
    _TradePayload,
    _mapping_candidates,
)


def _memory_barrier() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.ntdll.RtlMemoryFence()
    except AttributeError:
        pass


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


def _compute_slot_crc16(message_type: int, payload_size: int, trade: _TradePayload) -> int:
    trade_raw = ctypes.string_at(ctypes.addressof(trade), ctypes.sizeof(_TradePayload))
    trade_copy = _TradePayload.from_buffer_copy(trade_raw)
    trade_copy.reserved0 = 0
    prefix = int(message_type).to_bytes(4, byteorder="little", signed=False) + int(payload_size).to_bytes(
        4, byteorder="little", signed=False
    )
    trade_bytes = ctypes.string_at(ctypes.addressof(trade_copy), ctypes.sizeof(_TradePayload))
    return _crc16_ccitt(prefix + trade_bytes)


def _percentile_ns(sorted_ns: List[int], p: float) -> float:
    if not sorted_ns:
        return 0.0
    n = len(sorted_ns)
    if n == 1:
        return float(sorted_ns[0])
    idx = (n - 1) * p
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    w = idx - lo
    return sorted_ns[lo] * (1.0 - w) + sorted_ns[hi] * w


def _struct_bytes(obj: ctypes.Structure) -> bytes:
    return ctypes.string_at(ctypes.addressof(obj), ctypes.sizeof(type(obj)))


@dataclass
class BenchStats:
    path: str
    latencies_ns: List[int]

    def summary(self) -> dict:
        s = sorted(self.latencies_ns)
        n = len(s)
        if n == 0:
            return {
                "path": self.path,
                "count": 0,
                "p50_ns": 0,
                "p95_ns": 0,
                "p99_ns": 0,
                "mean_ns": 0.0,
            }
        mean = sum(s) / n
        return {
            "path": self.path,
            "count": n,
            "p50_ns": int(round(_percentile_ns(s, 0.50))),
            "p95_ns": int(round(_percentile_ns(s, 0.95))),
            "p99_ns": int(round(_percentile_ns(s, 0.99))),
            "mean_ns": mean,
        }


def _zero_shm(shm: shared_memory.SharedMemory, size: int) -> None:
    bs = 1024 * 1024
    z = b"\x00" * bs
    buf = shm.buf
    left = size
    while left > 0:
        chunk = z if left >= bs else b"\x00" * left
        start = size - left
        buf[start : start + len(chunk)] = chunk
        left -= len(chunk)


def _bench_mapping_name(mapping_name: str) -> str:
    candidates = _mapping_candidates(mapping_name)
    return candidates[-1] if candidates else mapping_name


def _unique_run_mapping_name(mapping_name: str) -> str:
    base = _bench_mapping_name(mapping_name)
    suffix = f"{os.getpid()}_{int(time.time() * 1000)}"
    return f"{base}_{suffix}"


def _init_shm_mapping(shm: shared_memory.SharedMemory, map_size: int) -> None:
    slot_sz = ctypes.sizeof(_RingSlot)
    hdr_sz = ctypes.sizeof(_RingHeader)
    capacity = (map_size - hdr_sz) // slot_sz
    if capacity <= 0:
        raise SystemExit("map too small for ring")
    _zero_shm(shm, map_size)
    h = _RingHeader()
    h.magic = MmapConsumer.SHM_MAGIC
    h.version = MmapConsumer.SHM_VERSION
    h.header_size = hdr_sz
    h.slot_size = slot_sz
    h.capacity = capacity
    h.write_seq = 0
    h.dropped = 0
    h.created_epoch_ms = int(time.time() * 1000)
    shm.buf[:hdr_sz] = _struct_bytes(h)


def _read_header_copy(shm: shared_memory.SharedMemory) -> _RingHeader:
    raw = bytes(shm.buf[: ctypes.sizeof(_RingHeader)])
    return _RingHeader.from_buffer_copy(raw)


def _write_trade_slot(shm: shared_memory.SharedMemory, send_ns: int, seq: int) -> None:
    hdr_sz = ctypes.sizeof(_RingHeader)
    slot_sz = ctypes.sizeof(_RingSlot)

    hh = _read_header_copy(shm)
    cap = int(hh.capacity)
    next_seq = int(hh.write_seq) + 1
    idx = (next_seq - 1) % cap
    offset = hdr_sz + idx * slot_sz

    trade = _TradePayload()
    trade.ticker = b"BENCH\x00" + b"\x00" * 18
    trade.trade_date = b"\x00" * 16
    trade.price = 0.0
    trade.qty = 1
    trade.buy_agent = 0
    trade.sell_agent = 0
    trade.trade_type = 0
    trade.trade_source = 0
    trade.reserved0 = 0
    trade.trade_number = seq & 0xFFFFFFFF
    trade.trade_flags = 0
    trade.trade_epoch_ms = send_ns
    trade.vwap = 0.0
    trade.net_aggression = 0

    slot = _RingSlot()
    slot.committed_seq = 0
    slot.message_type = MmapConsumer.MESSAGE_TYPE_TRADE
    slot.payload_size = ctypes.sizeof(_TradePayload)
    trade.reserved0 = _compute_slot_crc16(slot.message_type, slot.payload_size, trade)
    slot.trade = trade

    shm.buf[offset : offset + slot_sz] = _struct_bytes(slot)
    _memory_barrier()
    slot.committed_seq = next_seq
    shm.buf[offset : offset + slot_sz] = _struct_bytes(slot)
    _memory_barrier()

    hh.write_seq = next_seq
    if next_seq > cap:
        hh.dropped = next_seq - cap
    shm.buf[:hdr_sz] = _struct_bytes(hh)


def _read_slot(shm: shared_memory.SharedMemory, header: _RingHeader, seq: int) -> _RingSlot:
    hdr_sz = ctypes.sizeof(_RingHeader)
    slot_sz = int(header.slot_size)
    cap = int(header.capacity)
    idx = (seq - 1) % cap
    offset = hdr_sz + idx * slot_sz
    raw = bytes(shm.buf[offset : offset + ctypes.sizeof(_RingSlot)])
    return _RingSlot.from_buffer_copy(raw)


def bench_shm(mapping_name: str, map_size: int, total_messages: int, warmup: int) -> BenchStats:
    if sys.platform != "win32":
        raise SystemExit("SHM benchmark requires Windows")

    run_mapping_name = _unique_run_mapping_name(mapping_name)
    latencies: List[int] = []
    err: List[BaseException] = []
    consumer_done = threading.Event()
    mapping_ready = threading.Event()
    can_produce = threading.Event()
    can_consume = threading.Event()
    can_produce.set()

    def producer() -> None:
        try:
            shm = shared_memory.SharedMemory(name=run_mapping_name, create=True, size=map_size)
            _init_shm_mapping(shm, map_size)
            mapping_ready.set()
            for i in range(total_messages):
                if not can_produce.wait(timeout=120.0):
                    break
                can_produce.clear()
                t0 = time.perf_counter_ns()
                _write_trade_slot(shm, t0, i + 1)
                can_consume.set()
            consumer_done.wait(timeout=60.0)
            shm.close()
        except BaseException as e:
            err.append(e)
            mapping_ready.set()

    def consumer() -> None:
        shm: Optional[shared_memory.SharedMemory] = None
        try:
            if not mapping_ready.wait(timeout=30.0):
                return
            shm = shared_memory.SharedMemory(name=run_mapping_name, create=False)
            next_seq = 1
            while next_seq <= total_messages:
                if err:
                    break
                if not can_consume.wait(timeout=120.0):
                    break
                can_consume.clear()
                hh = _read_header_copy(shm)
                slot = _read_slot(shm, hh, next_seq)
                if int(slot.committed_seq) != int(next_seq):
                    err.append(RuntimeError(f"shm seq mismatch want={next_seq} got={slot.committed_seq}"))
                    break
                if int(slot.message_type) != MmapConsumer.MESSAGE_TYPE_TRADE:
                    err.append(RuntimeError("shm expected trade"))
                    break
                if int(slot.payload_size) != ctypes.sizeof(_TradePayload):
                    err.append(
                        RuntimeError(
                            f"shm payload_size mismatch want={ctypes.sizeof(_TradePayload)} got={slot.payload_size}"
                        )
                    )
                    break
                expected_crc = int(slot.trade.reserved0) & 0xFFFF
                got_crc = _compute_slot_crc16(int(slot.message_type), int(slot.payload_size), slot.trade)
                if got_crc != expected_crc:
                    err.append(RuntimeError(f"shm crc mismatch want={expected_crc} got={got_crc}"))
                    break
                t1 = time.perf_counter_ns()
                send_ns = int(slot.trade.trade_epoch_ms)
                if next_seq > warmup:
                    latencies.append(t1 - send_ns)
                next_seq += 1
                can_produce.set()
            if shm is not None:
                shm.close()
        except BaseException as e:
            err.append(e)
        finally:
            consumer_done.set()

    t_prod = threading.Thread(target=producer, daemon=True)
    t_cons = threading.Thread(target=consumer, daemon=True)
    t_cons.start()
    t_prod.start()
    t_prod.join(timeout=120.0)
    t_cons.join(timeout=120.0)
    if err:
        raise err[0]
    return BenchStats("shm", latencies)


def bench_zmq(bind_url: str, total_messages: int, warmup: int) -> BenchStats:
    import zmq

    latencies: List[int] = []
    ctx = zmq.Context()
    ready = threading.Barrier(2)
    can_produce = threading.Event()
    can_consume = threading.Event()
    can_produce.set()

    def producer() -> None:
        sock = ctx.socket(zmq.PUB)
        sock.bind(bind_url)
        time.sleep(0.05)
        ready.wait()
        for i in range(total_messages):
            if not can_produce.wait(timeout=120.0):
                break
            can_produce.clear()
            t0 = time.perf_counter_ns()
            payload = json.dumps({"type": "trade", "bench_send_ns": t0, "seq": i + 1})
            sock.send_string(payload)
            can_consume.set()
        sock.close(linger=0)

    def consumer() -> None:
        sock = ctx.socket(zmq.SUB)
        sock.connect(bind_url)
        sock.setsockopt_string(zmq.SUBSCRIBE, "")
        time.sleep(0.05)
        ready.wait()
        for _ in range(total_messages):
            if not can_consume.wait(timeout=120.0):
                break
            can_consume.clear()
            raw = sock.recv_string()
            t1 = time.perf_counter_ns()
            obj = json.loads(raw)
            seq = int(obj.get("seq", 0))
            t0 = int(obj.get("bench_send_ns", 0))
            if seq > warmup:
                latencies.append(t1 - t0)
            can_produce.set()
        sock.close(linger=0)

    tp = threading.Thread(target=producer, daemon=True)
    tc = threading.Thread(target=consumer, daemon=True)
    tp.start()
    tc.start()
    tp.join(timeout=120.0)
    tc.join(timeout=120.0)
    ctx.term()
    return BenchStats("zmq", latencies)


def bench_shm_stress(
    mapping_name: str,
    map_size: int,
    target_rate: int,
    duration_sec: float,
) -> dict:
    """SPSC stress: producer paced at target_rate msg/s; consumer spins; reports ring dropped."""
    if sys.platform != "win32":
        raise SystemExit("SHM stress requires Windows")
    if target_rate <= 0 or duration_sec <= 0:
        raise SystemExit("invalid stress parameters")

    run_mapping_name = _unique_run_mapping_name(mapping_name)
    written_box: List[int] = [0]
    producer_elapsed_box: List[float] = [0.0]
    final_header_box: List[Optional[_RingHeader]] = [None]
    crc_mismatch_box: List[int] = [0]
    payload_mismatch_box: List[int] = [0]
    err: List[BaseException] = []
    producer_done = threading.Event()
    consumer_ready = threading.Event()
    mapping_ready = threading.Event()

    def producer() -> None:
        try:
            shm = shared_memory.SharedMemory(name=run_mapping_name, create=True, size=map_size)
            _init_shm_mapping(shm, map_size)
            mapping_ready.set()
            consumer_ready.wait(timeout=30.0)
            start = time.perf_counter()
            total = max(1, int(target_rate * duration_sec + 0.999999))
            for seq in range(1, total + 1):
                next_deadline = start + seq / float(target_rate)
                while time.perf_counter() < next_deadline:
                    pass
                _write_trade_slot(shm, int(time.perf_counter_ns()), seq)
            written_box[0] = total
            producer_elapsed_box[0] = max(0.0, time.perf_counter() - start)
            final_header_box[0] = _read_header_copy(shm)
            producer_done.set()
            shm.close()
        except BaseException as e:
            err.append(e)
            mapping_ready.set()
        finally:
            producer_done.set()

    def consumer() -> None:
        try:
            if not mapping_ready.wait(timeout=30.0):
                return
            shm = shared_memory.SharedMemory(name=run_mapping_name, create=False)
            consumer_ready.set()
            next_seq = 1
            while True:
                if err:
                    break
                if producer_done.is_set() and next_seq > written_box[0]:
                    break
                hh = _read_header_copy(shm)
                w = int(hh.write_seq)
                if w < next_seq:
                    if producer_done.is_set() and next_seq > written_box[0]:
                        break
                    time.sleep(0)
                    continue
                slot = _read_slot(shm, hh, next_seq)
                if int(slot.committed_seq) != next_seq:
                    time.sleep(0)
                    continue
                if int(slot.message_type) != MmapConsumer.MESSAGE_TYPE_TRADE:
                    time.sleep(0)
                    continue
                if int(slot.payload_size) != ctypes.sizeof(_TradePayload):
                    payload_mismatch_box[0] += 1
                    next_seq += 1
                    continue
                expected_crc = int(slot.trade.reserved0) & 0xFFFF
                got_crc = _compute_slot_crc16(int(slot.message_type), int(slot.payload_size), slot.trade)
                if got_crc != expected_crc:
                    crc_mismatch_box[0] += 1
                    next_seq += 1
                    continue
                next_seq += 1
            shm.close()
        except BaseException as e:
            err.append(e)

    tp = threading.Thread(target=producer, daemon=True)
    tc = threading.Thread(target=consumer, daemon=True)
    tc.start()
    tp.start()
    join_timeout = max(120.0, duration_sec * 3.0 + 30.0)
    tp.join(timeout=join_timeout)
    tc.join(timeout=join_timeout)
    if err:
        raise err[0]

    hh = final_header_box[0]
    if hh is None:
        raise RuntimeError("stress did not capture final SHM header")
    dropped = int(hh.dropped)
    capacity = int(hh.capacity)
    final_write = int(hh.write_seq)

    written = written_box[0]
    return {
        "target_rate": target_rate,
        "duration_sec": duration_sec,
        "written": written,
        "producer_elapsed_sec": round(float(producer_elapsed_box[0]), 6),
        "final_write_seq": final_write,
        "ring_dropped_counter": dropped,
        "ring_capacity": capacity,
        "crc_mismatch": int(crc_mismatch_box[0]),
        "payload_mismatch": int(payload_mismatch_box[0]),
    }


def bench_shm_session(
    mapping_name: str,
    map_size: int,
    duration_sec: float,
    poll_sleep_s: float = 0.0005,
) -> dict:
    """Long-session reader-only diagnostics: gaps and dropped observed in ring header."""
    if sys.platform != "win32":
        raise SystemExit("SHM session diagnostics requires Windows")
    if duration_sec <= 0:
        raise SystemExit("invalid session duration")

    shm = None
    last_err: Optional[BaseException] = None
    for candidate in _mapping_candidates(mapping_name):
        try:
            shm = shared_memory.SharedMemory(name=candidate, create=False)
            break
        except BaseException as exc:
            last_err = exc
            shm = None
    if shm is None:
        if last_err is not None:
            raise last_err
        raise FileNotFoundError(mapping_name)
    header0 = _read_header_copy(shm)
    initial_write_seq = int(header0.write_seq)
    initial_dropped = int(header0.dropped)
    started_at = time.perf_counter()
    next_seq = initial_write_seq + 1 if initial_write_seq > 0 else 1
    gap_count = 0
    gap_messages = 0
    last_write_seq = 0
    last_dropped = 0
    observed_trades = 0
    committed_mismatch = 0
    crc_mismatch = 0
    payload_mismatch = 0
    try:
        while (time.perf_counter() - started_at) < duration_sec:
            hh = _read_header_copy(shm)
            write_seq = int(hh.write_seq)
            capacity = int(hh.capacity)
            last_write_seq = write_seq
            last_dropped = int(hh.dropped)
            if write_seq <= 0 or capacity <= 0:
                time.sleep(poll_sleep_s)
                continue
            floor_seq = write_seq - capacity + 1
            if next_seq < floor_seq:
                lost = floor_seq - next_seq
                if lost > 0:
                    gap_messages += lost
                gap_count += 1
                next_seq = floor_seq
            if next_seq > write_seq:
                time.sleep(poll_sleep_s)
                continue
            slot = _read_slot(shm, hh, next_seq)
            committed_seq = int(slot.committed_seq)
            if committed_seq != next_seq:
                if committed_seq > next_seq:
                    lost = committed_seq - next_seq
                    if lost > 0:
                        gap_messages += lost
                    gap_count += 1
                    next_seq = committed_seq
                else:
                    committed_mismatch += 1
                    time.sleep(poll_sleep_s)
                continue
            if int(slot.message_type) != MmapConsumer.MESSAGE_TYPE_TRADE:
                next_seq += 1
                continue
            if int(slot.payload_size) != ctypes.sizeof(_TradePayload):
                payload_mismatch += 1
                next_seq += 1
                continue
            expected_crc = int(slot.trade.reserved0) & 0xFFFF
            got_crc = _compute_slot_crc16(int(slot.message_type), int(slot.payload_size), slot.trade)
            if got_crc != expected_crc:
                crc_mismatch += 1
                next_seq += 1
                continue
            observed_trades += 1
            next_seq += 1
    finally:
        shm.close()

    elapsed_sec = time.perf_counter() - started_at
    ring_dropped_delta = max(0, int(last_dropped) - int(initial_dropped))
    write_seq_delta = max(0, int(last_write_seq) - int(initial_write_seq))
    observed_ratio = (float(observed_trades) / float(write_seq_delta)) if write_seq_delta > 0 else 0.0
    return {
        "duration_sec": round(elapsed_sec, 3),
        "initial_write_seq": int(initial_write_seq),
        "initial_ring_dropped_counter": int(initial_dropped),
        "observed_trades": observed_trades,
        "last_write_seq": last_write_seq,
        "write_seq_delta": write_seq_delta,
        "ring_dropped_counter": last_dropped,
        "ring_dropped_delta": ring_dropped_delta,
        "gap_count": gap_count,
        "gap_messages": gap_messages,
        "committed_mismatch": committed_mismatch,
        "crc_mismatch": crc_mismatch,
        "payload_mismatch": payload_mismatch,
        "next_seq": next_seq,
        "observed_ratio": round(observed_ratio, 6),
        "loss_detected": int((ring_dropped_delta > 0) or (gap_messages > 0)),
    }


def evaluate_stress_result(
    row: dict,
    max_dropped: int,
    max_crc_mismatch: int,
    max_payload_mismatch: int,
    min_achieved_rate: float,
    min_achieved_rate_ratio: float,
) -> dict:
    max_allowed = max(0, int(max_dropped))
    max_crc = max(0, int(max_crc_mismatch))
    max_payload = max(0, int(max_payload_mismatch))
    min_rate = max(0.0, float(min_achieved_rate))
    min_ratio = max(0.0, float(min_achieved_rate_ratio))
    dropped = int(row.get("ring_dropped_counter", 0))
    crc_mismatch = int(row.get("crc_mismatch", 0))
    payload_mismatch = int(row.get("payload_mismatch", 0))
    target_rate = float(row.get("target_rate", 0))
    achieved_effective = float(row.get("achieved_rate_effective", row.get("achieved_rate", 0.0)))
    achieved_ratio = (achieved_effective / target_rate) if target_rate > 0 else 0.0
    ok = int(
        dropped <= max_allowed
        and crc_mismatch <= max_crc
        and payload_mismatch <= max_payload
        and achieved_effective >= min_rate
        and achieved_ratio >= min_ratio
    )
    return {
        "max_ring_dropped_allowed": max_allowed,
        "max_crc_mismatch_allowed": max_crc,
        "max_payload_mismatch_allowed": max_payload,
        "min_achieved_rate_allowed": round(min_rate, 4),
        "min_achieved_rate_ratio_allowed": round(min_ratio, 4),
        "achieved_rate_ratio": round(achieved_ratio, 6),
        "stress_ok": ok,
    }


def evaluate_session_result(
    row: dict,
    max_gap_messages: int,
    max_ring_dropped: int,
    max_committed_mismatch: int,
    max_crc_mismatch: int,
    max_payload_mismatch: int,
    min_observed_trades: int,
) -> dict:
    max_gap = max(0, int(max_gap_messages))
    max_dropped = max(0, int(max_ring_dropped))
    max_mismatch = max(0, int(max_committed_mismatch))
    max_crc = max(0, int(max_crc_mismatch))
    max_payload = max(0, int(max_payload_mismatch))
    min_observed = max(0, int(min_observed_trades))
    gap_messages = int(row.get("gap_messages", 0))
    ring_dropped = int(row.get("ring_dropped_delta", row.get("ring_dropped_counter", 0)))
    committed_mismatch = int(row.get("committed_mismatch", 0))
    crc_mismatch = int(row.get("crc_mismatch", 0))
    payload_mismatch = int(row.get("payload_mismatch", 0))
    observed_trades = int(row.get("observed_trades", 0))
    ok = int(
        gap_messages <= max_gap
        and ring_dropped <= max_dropped
        and committed_mismatch <= max_mismatch
        and crc_mismatch <= max_crc
        and payload_mismatch <= max_payload
        and observed_trades >= min_observed
    )
    return {
        "max_gap_messages_allowed": max_gap,
        "max_ring_dropped_allowed": max_dropped,
        "max_committed_mismatch_allowed": max_mismatch,
        "max_crc_mismatch_allowed": max_crc,
        "max_payload_mismatch_allowed": max_payload,
        "min_observed_trades_allowed": min_observed,
        "session_ok": ok,
    }


def write_kv_csv(path: Path, section_name: str, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    section = (section_name or "").strip().upper() or "STRESS"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "metric", "value"])
        for k, v in row.items():
            w.writerow([section, k, v])


def write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, shm_stats: Optional[BenchStats], zmq_stats: BenchStats) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "path", "seq", "latency_ns"])
        if shm_stats:
            for i, ns in enumerate(shm_stats.latencies_ns, start=1):
                w.writerow(["sample", "shm", i, ns])
        for i, ns in enumerate(zmq_stats.latencies_ns, start=1):
            w.writerow(["sample", "zmq", i, ns])
        w.writerow([])
        w.writerow(["section", "path", "count", "p50_ns", "p95_ns", "p99_ns", "mean_ns"])
        rows = []
        if shm_stats:
            rows.append(shm_stats.summary())
        rows.append(zmq_stats.summary())
        for s in rows:
            w.writerow(
                [
                    "SUMMARY",
                    s["path"],
                    s["count"],
                    s["p50_ns"],
                    s["p95_ns"],
                    s["p99_ns"],
                    f'{s["mean_ns"]:.2f}',
                ]
            )
        if len(rows) == 2:
            s0, s1 = rows[0], rows[1]
            ratio = (s1["p50_ns"] / s0["p50_ns"]) if s0["p50_ns"] else 0.0
            w.writerow([])
            w.writerow(["COMPARE", "zmq_p50_over_shm_p50", "", f"{ratio:.4f}", "", "", ""])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stress", action="store_true", help="Run SHM throughput stress (Windows) instead of latency bench")
    ap.add_argument(
        "--session",
        action="store_true",
        help="Run long-session SHM diagnostics (reader-only): tracks gaps and dropped counters",
    )
    ap.add_argument("--stress-rate", type=int, default=100_000)
    ap.add_argument("--stress-seconds", type=float, default=3.0)
    ap.add_argument("--stress-max-dropped", type=int, default=0)
    ap.add_argument("--stress-max-crc-mismatch", type=int, default=0)
    ap.add_argument("--stress-max-payload-mismatch", type=int, default=0)
    ap.add_argument("--stress-min-achieved-rate", type=float, default=0.0)
    ap.add_argument("--stress-min-achieved-rate-ratio", type=float, default=0.0)
    ap.add_argument("--stress-fail-on-drop", action="store_true")
    ap.add_argument("--session-seconds", type=float, default=6 * 60 * 60)
    ap.add_argument("--session-max-gap-messages", type=int, default=0)
    ap.add_argument("--session-max-ring-dropped", type=int, default=0)
    ap.add_argument("--session-max-committed-mismatch", type=int, default=0)
    ap.add_argument("--session-max-crc-mismatch", type=int, default=0)
    ap.add_argument("--session-max-payload-mismatch", type=int, default=0)
    ap.add_argument("--session-min-observed-trades", type=int, default=0)
    ap.add_argument("--session-fail-on-loss", action="store_true")
    ap.add_argument("--messages", type=int, default=50_000)
    ap.add_argument("--warmup", type=int, default=500)
    ap.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "distributor" / "logs" / "ipc_benchmark_last.csv",
    )
    ap.add_argument("--zmq-url", type=str, default="tcp://127.0.0.1:37591")
    ap.add_argument("--shm-name", type=str, default="Local\\PQBenchIpcV1")
    ap.add_argument("--shm-mb", type=int, default=8)
    ap.add_argument("--zmq-only", action="store_true")
    args = ap.parse_args()
    started_at = time.time()
    manifest = {
        "started_at_epoch_s": started_at,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "args": {
            "stress": bool(args.stress),
            "session": bool(args.session),
            "stress_rate": int(args.stress_rate),
            "stress_seconds": float(args.stress_seconds),
            "stress_max_dropped": int(args.stress_max_dropped),
            "stress_max_crc_mismatch": int(args.stress_max_crc_mismatch),
            "stress_max_payload_mismatch": int(args.stress_max_payload_mismatch),
            "stress_min_achieved_rate": float(args.stress_min_achieved_rate),
            "stress_min_achieved_rate_ratio": float(args.stress_min_achieved_rate_ratio),
            "stress_fail_on_drop": bool(args.stress_fail_on_drop),
            "session_seconds": float(args.session_seconds),
            "session_max_gap_messages": int(args.session_max_gap_messages),
            "session_max_ring_dropped": int(args.session_max_ring_dropped),
            "session_max_committed_mismatch": int(args.session_max_committed_mismatch),
            "session_max_crc_mismatch": int(args.session_max_crc_mismatch),
            "session_max_payload_mismatch": int(args.session_max_payload_mismatch),
            "session_min_observed_trades": int(args.session_min_observed_trades),
            "session_fail_on_loss": bool(args.session_fail_on_loss),
            "messages": int(args.messages),
            "warmup": int(args.warmup),
            "zmq_url": args.zmq_url,
            "shm_name": args.shm_name,
            "shm_mb": int(args.shm_mb),
            "zmq_only": bool(args.zmq_only),
        },
    }

    if args.stress:
        if sys.platform != "win32":
            raise SystemExit("--stress requires Windows SHM")
        map_size = max(8, args.shm_mb) * 1024 * 1024
        row = bench_shm_stress(args.shm_name, map_size, args.stress_rate, args.stress_seconds)
        row["achieved_rate"] = round(row["written"] / args.stress_seconds, 2) if args.stress_seconds else 0.0
        producer_elapsed = float(row.get("producer_elapsed_sec", 0.0))
        row["achieved_rate_effective"] = round(row["written"] / producer_elapsed, 2) if producer_elapsed > 0 else 0.0
        row.update(
            evaluate_stress_result(
                row,
                args.stress_max_dropped,
                args.stress_max_crc_mismatch,
                args.stress_max_payload_mismatch,
                args.stress_min_achieved_rate,
                args.stress_min_achieved_rate_ratio,
            )
        )
        write_kv_csv(args.out, "STRESS", row)
        manifest.update({"mode": "stress", "result": row, "finished_at_epoch_s": time.time()})
        write_manifest(args.out.with_suffix(".manifest.json"), manifest)
        print(row)
        if args.stress_fail_on_drop and int(row.get("stress_ok", 0)) == 0:
            raise SystemExit(2)
        return
    if args.session:
        if sys.platform != "win32":
            raise SystemExit("--session requires Windows SHM")
        map_size = max(8, args.shm_mb) * 1024 * 1024
        session_exception: Optional[BaseException] = None
        try:
            row = bench_shm_session(args.shm_name, map_size, args.session_seconds)
        except BaseException as exc:  # noqa: BLE001
            session_exception = exc
            row = {
                "duration_sec": 0.0,
                "initial_write_seq": 0,
                "initial_ring_dropped_counter": 0,
                "observed_trades": 0,
                "last_write_seq": 0,
                "write_seq_delta": 0,
                "ring_dropped_counter": 0,
                "ring_dropped_delta": 0,
                "gap_count": 0,
                "gap_messages": 0,
                "committed_mismatch": 0,
                "crc_mismatch": 0,
                "payload_mismatch": 0,
                "next_seq": 1,
                "observed_ratio": 0.0,
                "loss_detected": 0,
                "session_error": f"{type(exc).__name__}: {exc}",
            }
        row.update(
            evaluate_session_result(
                row,
                max_gap_messages=args.session_max_gap_messages,
                max_ring_dropped=args.session_max_ring_dropped,
                max_committed_mismatch=args.session_max_committed_mismatch,
                max_crc_mismatch=args.session_max_crc_mismatch,
                max_payload_mismatch=args.session_max_payload_mismatch,
                min_observed_trades=args.session_min_observed_trades,
            )
        )
        if session_exception is not None:
            row["session_ok"] = 0
        write_kv_csv(args.out, "SESSION", row)
        manifest.update({"mode": "session", "result": row, "finished_at_epoch_s": time.time()})
        write_manifest(args.out.with_suffix(".manifest.json"), manifest)
        print(row)
        if session_exception is not None:
            traceback.print_exception(session_exception)
            raise SystemExit(1)
        if args.session_fail_on_loss and int(row.get("session_ok", 0)) == 0:
            raise SystemExit(2)
        return

    if args.warmup >= args.messages:
        raise SystemExit("--warmup must be < --messages")

    z_stats = bench_zmq(args.zmq_url, args.messages, args.warmup)
    s_stats: Optional[BenchStats] = None
    if sys.platform == "win32" and not args.zmq_only:
        map_size = max(8, args.shm_mb) * 1024 * 1024
        s_stats = bench_shm(args.shm_name, map_size, args.messages, args.warmup)

    write_csv(args.out, s_stats, z_stats)
    manifest.update(
        {
            "mode": "latency",
            "result": {
                "shm": s_stats.summary() if s_stats else None,
                "zmq": z_stats.summary(),
            },
            "finished_at_epoch_s": time.time(),
        }
    )
    write_manifest(args.out.with_suffix(".manifest.json"), manifest)


if __name__ == "__main__":
    main()
