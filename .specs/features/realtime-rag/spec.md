# Real-time RAG Architecture (Memória Estruturada) Specification

## Problem Statement

A IA e as análises da plataforma não possuem memória contínua dos eventos do pregão. Quando o trader pergunta "teve absorção nos últimos 5 minutos?", a IA não tem como saber — o estado do motor C++ é instantâneo (snapshot), sem histórico semântico. Os dados passam pelo sistema e são descartados após o broadcast via WebSocket. Sem uma camada de memória estruturada, a IA não consegue correlacionar eventos temporais, detectar padrões recorrentes ou fundamentar respostas em contexto histórico recente.

## Goals

- [ ] Busca vetorial em janelas de 5min de histórico de fluxo em < 10ms
- [ ] Pipeline de streaming contínuo: SHM → Redpanda → Embeddings → Banco Vetorial
- [ ] Context Engine injeta contexto de mercado antes de cada resposta da IA
- [ ] Retenção de dados: 1 pregão completo (6-8 horas); TTL automático

## Out of Scope

- Análise histórica multi-dia (apenas intraday, 1 pregão)
- Treinamento de modelos de embedding customizados (usa pré-treinados)
- Persistência permanente de embeddings (descartados ao fim do pregão)
- Dashboard de analytics sobre os dados vetoriais

---

## User Stories

### P1: Streaming Pipeline (SHM → Redpanda) ⭐ MVP

**User Story**: As a platform, I want market events to flow from shared memory into a streaming platform so that they can be processed, windowed, and consumed by multiple downstream services.

**Why P1**: Sem ingestão, não há dados para embeddings — é a fundação do pipeline.

**Acceptance Criteria**:

1. WHEN engine writes a trade/DOM/alert to the ring buffer THEN a Redpanda producer SHALL ingest the event into the appropriate topic within < 1ms
2. WHEN events arrive in Redpanda THEN they SHALL be partitioned by asset and event type (topics: `trades`, `dom-snapshots`, `alerts`, `signals`)
3. WHEN Redpanda is unavailable THEN the SHM consumer SHALL continue operating normally (RAG degrades gracefully, core trading unaffected)
4. WHEN system starts THEN Redpanda SHALL auto-create topics with retention = 8 hours

**Independent Test**: Rodar engine + Redpanda producer por 10 minutos; consumir do topic `trades` com `rpk consume`; validar ordering e completeness.

---

### P1: Embedding Engine ⭐ MVP

**User Story**: As a context engine, I want market event windows converted to vector embeddings so that the AI can semantically search recent market history.

**Why P1**: Sem embeddings, não há busca vetorial — o RAG não funciona.

**Acceptance Criteria**:

1. WHEN a time window closes (e.g., 5min bucket) THEN embedding engine SHALL generate a vector from the aggregated events (trades, DOM deltas, signals)
2. WHEN embedding is generated THEN it SHALL be stored in the vector database with metadata (asset, timestamp, window_start, window_end, event_types)
3. WHEN embedding model processes a window THEN latency SHALL be < 100ms per window
4. WHEN window contains no events (e.g., leilão) THEN system SHALL skip embedding generation

**Independent Test**: Gerar embeddings de 1 hora de dados simulados; buscar "forte agressão vendedora"; validar que retorna as janelas com maior delta negativo de agressão.

---

### P2: Context Engine (Injeção pré-resposta)

**User Story**: As an AI copilot, I want relevant market context automatically injected into my prompt before answering so that my responses are grounded in recent market reality.

**Why P2**: Diferencia o copiloto de um chatbot genérico, mas a funcionalidade core de voz funciona sem isso.

**Acceptance Criteria**:

1. WHEN trader asks a question THEN Context Engine SHALL perform vector search with the question as query (top-K=5 windows)
2. WHEN results are retrieved THEN they SHALL be formatted and injected as system context for the AI (< 2000 tokens)
3. WHEN search returns no relevant results THEN Context Engine SHALL inject only the current real-time state (via Function Calling)
4. WHEN total context exceeds token limit THEN oldest/least-relevant windows SHALL be pruned

**Independent Test**: Perguntar "como estava o fluxo 5 minutos atrás?" → resposta deve citar dados coerentes com o que o painel mostrava naquele momento.

---

### P2: Views Materializadas

**User Story**: As a data pipeline, I want materialized views that cross-reference streaming data with structured state so that the AI gets pre-computed aggregations instead of raw events.

**Why P2**: Reduz carga computacional no momento da consulta; melhora qualidade do contexto.

**Acceptance Criteria**:

1. WHEN Redpanda receives events THEN Materialize (or SQL engine) SHALL maintain live aggregations: VWAP running, aggression delta, wall count, top brokers
2. WHEN Context Engine queries THEN it SHALL prefer materialized views over raw event scan
3. WHEN materialized view lags > 1 second THEN system SHALL log warning and fall back to direct query

**Independent Test**: Consultar materialized view de "top 5 corretoras agressoras últimos 5min" e comparar com cálculo manual dos eventos.

---

### P3: TTL e cleanup automático

**User Story**: As a system, I want automatic cleanup of old embeddings and events so that resources don't grow unboundedly during long trading sessions.

**Why P3**: Nice-to-have para estabilidade, mas sistema funciona sem isso no curto prazo.

**Acceptance Criteria**:

1. WHEN an embedding is older than 8 hours THEN vector database SHALL delete it automatically
2. WHEN Redpanda retention window expires THEN old events SHALL be purged
3. WHEN cleanup runs THEN it SHALL NOT impact query latency of active embeddings

---

## Edge Cases

- WHEN embedding model API is down THEN system SHALL queue windows for retry and log; AI continues with real-time-only context
- WHEN market has a flash crash (100+ trades/second spike) THEN pipeline SHALL handle burst without dropping events (Redpanda buffering)
- WHEN trader asks about a period before the system started THEN AI SHALL say "Não tenho dados anteriores ao início da sessão"
- WHEN two assets are being monitored THEN embeddings SHALL be namespaced by asset (no cross-contamination)
- WHEN system restarts mid-pregão THEN embeddings from before restart SHALL still be queryable (persisted in vector DB)

---

## Success Criteria

- [ ] Busca vetorial retorna resultados em < 10ms (p95)
- [ ] Pipeline end-to-end (event → embedding → queryable) em < 5 segundos
- [ ] Context Engine melhora relevância percebida das respostas da IA (A/B qualitativo)
- [ ] Zero impacto no latência do trading core (IPC, alertas) quando RAG está ativo
