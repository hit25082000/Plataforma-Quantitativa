# Shared Memory IPC (Zero-Copy) Specification

## Problem Statement

O IPC atual usa ZeroMQ (TCP) com serialização JSON, exigindo: (1) serialização de structs C++ para JSON string, (2) cópia do payload para o buffer de rede do ZMQ, (3) cópia no socket do subscriber Python, (4) deserialização JSON para dict Python. Cada etapa adiciona latência de ~0.5-2ms. Para HFT tick-by-tick na B3, essa cadeia é o principal gargalo entre a captura na Profit DLL e o consumo downstream.

## Goals

- [ ] Latência IPC produtor→consumidor < 10μs (atualmente ~1-5ms com ZMQ+JSON) — validar no hardware alvo com `SHM_QPC_DIAG=1` (p99 `write_trade`) + benchmark P3
- [ ] Zero cópias de dados entre engine C++ e consumidores Python/Rust
- [ ] Zero perda de mensagens sob throughput de 100k+ mensagens/segundo — `scripts/benchmark_ipc_zmq_vs_shm.py --stress --stress-rate 100000`
- [x] Migração transparente: sistema funciona com ZMQ como fallback durante transição

## Out of Scope

- IPC entre máquinas diferentes (apenas single-machine)
- Persistência de mensagens em disco (ring buffer é volátil)
- Suporte a múltiplos produtores (apenas SPSC: 1 engine → N consumidores via leituras independentes)

---

## User Stories

### P1: Ring Buffer SPSC no Engine C++ ⭐ MVP

**User Story**: As a platform developer, I want the C++ engine to write market data to a lock-free ring buffer in shared memory so that consumers can read without serialization or network overhead.

**Why P1**: É o alicerce de toda a evolução v2. Sem ring buffer lock-free, não há zero-copy.

**Acceptance Criteria**:

1. WHEN Profit DLL callback fires a trade event THEN engine SHALL write the trade struct directly to the ring buffer (binary, no JSON)
2. WHEN ring buffer is full THEN engine SHALL overwrite the oldest entry (circular) and increment a `dropped` counter (no blocking)
3. WHEN consumer reads an entry THEN consumer SHALL access the same physical memory page without any memcpy or deserialization
4. WHEN engine starts THEN engine SHALL create a named shared memory region via `CreateFileMapping` with configurable size (default: 64MB)

**Independent Test**: Escrever 1M trades no ring buffer via engine standalone, ler com processo Python separado, validar que todos os campos estão corretos e latência < 10μs p99.

---

### P1: Consumer Python via mmap ⭐ MVP

**User Story**: As a distributor, I want to read market data from shared memory using Python's `mmap` + `ctypes` so that I maintain the same downstream interface (WebSocket broadcast) without ZeroMQ.

**Why P1**: O distributor Python é o hub central — sem consumer SHM, a cadeia não fecha.

**Acceptance Criteria**:

1. WHEN a new entry appears in the ring buffer THEN Python consumer SHALL detect it via atomic sequence number (polling or event)
2. WHEN Python consumer reads a trade struct THEN it SHALL map to a Python dataclass/dict via `ctypes.Structure` (zero JSON parsing)
3. WHEN Python consumer starts THEN it SHALL open the named shared memory created by the engine (`OpenFileMapping`)
4. WHEN engine is not running THEN Python consumer SHALL retry with backoff and log warnings (graceful degradation)

**Independent Test**: Rodar engine produzindo trades reais da Profit DLL; rodar distributor lendo via SHM; verificar que `MessageRouter` recebe dados idênticos aos do ZMQ consumer atual.

---

### P2: Fallback ZMQ durante migração

**User Story**: As a trader, I want the system to automatically fall back to ZeroMQ if shared memory is unavailable so that my trading session is never interrupted.

**Why P2**: Garante zero downtime durante a fase de migração; permite rollback seguro.

**Acceptance Criteria**:

1. WHEN shared memory region is not found THEN consumer SHALL fall back to ZMQ subscriber transparently
2. WHEN fallback occurs THEN system SHALL log a warning and emit a `ipc_fallback` event to the frontend
3. WHEN shared memory becomes available again THEN consumer SHALL NOT auto-switch (requer restart)

**Independent Test**: Iniciar distributor sem engine rodando; verificar que conecta via ZMQ; verificar log de fallback.

---

### P2: Consumer Rust (Tauri direto)

**User Story**: As a frontend developer, I want Tauri to optionally read market data directly from shared memory (bypassing the Python distributor) so that the overlay can update with minimal latency.

**Why P2**: Para o overlay OCR, a cadeia Engine→Python→WS→Frontend adiciona latência desnecessária.

**Acceptance Criteria**:

1. WHEN Tauri app starts and SHM is available THEN Tauri SHALL open the shared memory region via Rust `windows-sys` crate
2. WHEN new data arrives in ring buffer THEN Tauri SHALL emit Tauri events to the frontend webview
3. WHEN SHM reader fails THEN Tauri SHALL fall back to WebSocket connection with the distributor

**Independent Test**: Rodar overlay com Tauri lendo SHM direto; comparar latência de atualização vs. caminho via WebSocket.

---

### P3: Benchmark automatizado

**User Story**: As a developer, I want automated benchmarks comparing ZMQ vs SHM latency so that I can validate the improvement quantitativamente.

**Why P3**: Importante para documentação e decisões futuras, mas não bloqueia funcionalidade.

**Acceptance Criteria**:

1. [x] WHEN benchmark suite runs THEN it SHALL measure p50, p95, p99 latency for both ZMQ and SHM paths
2. [x] WHEN benchmark completes THEN it SHALL output CSV with results and summary comparison

---

## Edge Cases

- WHEN ring buffer wraps around (circular) THEN consumer SHALL detect via sequence number gap and skip stale entries
- WHEN consumer reads slower than producer THEN system SHALL NOT block the producer; consumer sees a gap in sequence numbers
- WHEN engine crashes mid-write THEN consumer SHALL detect incomplete entry via CRC16-CCITT (`TradePayload.reserved0`) or sequence mismatch and skip it
- WHEN multiple consumers read simultaneously THEN each SHALL maintain its own read cursor independently
- WHEN system runs for > 8 hours continuously THEN ring buffer SHALL NOT leak memory or degrade performance

---

## Success Criteria

- [ ] Latência IPC p99 < 10μs medida com `QueryPerformanceCounter` — instrumentação engine: `SHM_QPC_DIAG=1` (p99 de `write_trade` no stderr ao encerrar o writer)
- [ ] Zero perda de trades em sessão de 6 horas de pregão (9h-17h B3)
- [ ] Throughput sustentado de 100k mensagens/segundo sem backpressure — verificação automatizada: `--stress` (contador `dropped` do header)
- [x] Distributor Python funciona identicamente via SHM ou ZMQ (interface transparente)
