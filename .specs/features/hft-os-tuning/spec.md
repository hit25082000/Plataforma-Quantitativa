# HFT Hardware & OS Optimizations Specification

## Problem Statement

O Windows realiza troca de contexto (context switching) de processos livremente, limpando caches L1/L2 do processador e gerando latência imprevisível (jitter) nas threads críticas do engine C++. A thread da Profit DLL e o rule engine competem por cores com processos do sistema, browsers, e o próprio Tauri. Sem isolamento, a latência tick-by-tick varia de < 1ms a > 10ms dependendo da carga do SO. Para HFT, previsibilidade importa mais que velocidade média.

## Goals

- [ ] Jitter de latência < 1μs em 99.9% dos ticks (atualmente ~1-10ms de variação)
- [ ] Threads críticas (Profit DLL callbacks + rule engine) isoladas em cores dedicados
- [ ] Ring buffer SHM alocado em Huge Pages (2MB) para eliminar TLB misses
- [ ] Prefetching de cache em hot paths do DOM e T&T

## Out of Scope

- Modificações no kernel do Windows (apenas configurações user-space)
- Driver de rede customizado (kernel bypass / DPDK)
- Suporte a Linux ou outras plataformas
- Overclocking ou configurações de BIOS automatizadas

---

## User Stories

### P1: CPU Pinning para threads críticas ⭐ MVP

**User Story**: As a platform, I want critical engine threads pinned to dedicated CPU cores so that the OS never preempts them for background tasks.

**Why P1**: Maior impacto em redução de jitter; relativamente simples de implementar.

**Acceptance Criteria**:

1. WHEN engine starts THEN it SHALL set thread affinity for Profit DLL callback thread to a specific core via `SetThreadAffinityMask`
2. WHEN engine starts THEN it SHALL set thread affinity for event dispatcher/rule engine thread to a separate dedicated core
3. WHEN engine starts THEN it SHALL elevate process priority to `HIGH_PRIORITY_CLASS` (not REALTIME, to avoid starving other processes)
4. WHEN configured cores are not available (e.g., 2-core machine) THEN engine SHALL fall back to default scheduling and log warning

**Independent Test**: Rodar engine com pinning ativado; medir jitter de latência do callback Profit DLL com `QueryPerformanceCounter` por 1 hora; comparar com baseline sem pinning.

---

### P1: SHM Ring Buffer com Huge Pages ⭐ MVP

**User Story**: As a platform, I want the shared memory ring buffer allocated using 2MB Huge Pages so that TLB misses are minimized for the most frequently accessed memory region.

**Why P1**: O ring buffer é o hot path mais acessado do sistema; Huge Pages eliminam TLB misses.

**Acceptance Criteria**:

1. WHEN engine creates the SHM region THEN it SHALL attempt allocation with `MEM_LARGE_PAGES` via `VirtualAlloc`
2. WHEN Huge Pages are unavailable (privilege not granted) THEN system SHALL fall back to regular pages and log warning
3. WHEN ring buffer is allocated THEN it SHALL be aligned to 2MB boundary

**Independent Test**: Alocar ring buffer com Huge Pages; medir TLB miss rate via `perf` counters (ou VTune) vs. regular pages.

---

### P2: Cache Prefetching nos hot paths

**User Story**: As a developer, I want explicit cache prefetching in the DOM snapshot and T&T processing code so that cache misses are minimized during high-throughput periods.

**Why P2**: Melhoria mensurável mas incremental; depende de profiling para validar.

**Acceptance Criteria**:

1. WHEN DOM snapshot processes a price level update THEN code SHALL prefetch the next N price levels via `_mm_prefetch(_MM_HINT_T0)`
2. WHEN T&T stream processes a trade THEN code SHALL prefetch the next ring buffer slot
3. WHEN prefetch is added THEN benchmark SHALL show measurable improvement in cache hit rate

**Independent Test**: Profile com VTune antes/depois; comparar L1/L2 cache miss rate.

---

### P2: NUMA-aware Memory Allocation

**User Story**: As a platform, I want memory allocated on the same NUMA node as the pinned CPU cores so that cross-node memory access doesn't add latency.

**Why P2**: Relevante apenas em sistemas multi-socket ou com topologia NUMA complexa (Ryzen CCX).

**Acceptance Criteria**:

1. WHEN engine allocates critical data structures (DOM, T&T accumulators, ring buffer) THEN it SHALL use `VirtualAllocExNuma` with the NUMA node of the pinned core
2. WHEN NUMA information is unavailable THEN system SHALL fall back to default allocation

**Independent Test**: Em máquina com NUMA (Ryzen 7+), medir latência de acesso a memória com e sem NUMA-aware allocation.

---

### P3: Configuração de "Trading Mode" no Profit

**User Story**: As a trader, I want a "Trading Mode" toggle in settings that enables all HFT optimizations (CPU pinning, priority boost, Huge Pages) with one click.

**Why P3**: UX convenience; otimizações individuais já funcionam.

**Acceptance Criteria**:

1. WHEN trader enables "Trading Mode" THEN system SHALL activate all HFT optimizations and show confirmation
2. WHEN "Trading Mode" is disabled THEN system SHALL revert to default scheduling

---

## Edge Cases

- WHEN user's CPU has fewer cores than required for pinning THEN system SHALL use shared cores and log recommendation for hardware upgrade
- WHEN "Lock Pages in Memory" privilege is not granted (required for Huge Pages) THEN system SHALL fall back and show one-time setup instruction
- WHEN another high-priority process (e.g., antivirus) runs on the pinned core THEN performance SHALL degrade gracefully (not crash)
- WHEN engine runs for > 8 hours THEN CPU pinning SHALL NOT cause thermal throttling issues (cores rotate if needed)
- WHEN system has hyperthreading enabled THEN pinning SHALL target physical cores, not logical cores sharing the same execution unit

---

## Success Criteria

- [ ] Jitter de latência < 1μs p99.9 em sessão de 6 horas com CPU pinning
- [ ] TLB miss rate reduzido em > 80% com Huge Pages (medido via perf counters)
- [ ] Zero impacto funcional: todas as regras R1-R6 continuam operando corretamente
- [ ] Fallback gracioso em hardware que não suporta as otimizações
