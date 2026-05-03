# Roadmap

**Current Milestone:** M9 - RAG em Tempo Real
**Status:** In Progress (fase 2 evoluída em código: pipeline local + injeção de contexto + fallback local→cloud opcional em Pinecone/Vectara + views materializadas com backend memory/sqlite; pendente: validação operacional contínua em pregão e eventual migração para engine SQL dedicado)
**Overlay VP/OCR (stability track):** In Progress (slice de robustez aplicado: retenção de último estado válido, anti-oscilação, freeze resiliente e cadência 500ms; pendente validação live de campo).

---

## M1 - Data Foundation — COMPLETE

**Goal:** C++ capturando dados reais da Profit DLL, snapshot do livro em memória, publicando via ZeroMQ.

### Features

**Integração Profit DLL** - COMPLETE
**DOM Snapshot Engine** - COMPLETE
**T&T Stream Processor** - COMPLETE

---

## M2 - Rule Engine — COMPLETE

**Goal:** 6 regras event-driven operando sobre processadores de dados.

### Features

**Event Framework** - COMPLETE
**R1: Saldo de Agressão** - COMPLETE
**R2: Muralhas (≥500 lotes)** - COMPLETE
**R3: VWAP Institucional** - COMPLETE
**R4: Renovação / Iceberg** - COMPLETE
**R5: Convergência + IFR** - COMPLETE
**R6: Absorção** - COMPLETE

---

## M3 - Distribution Layer — COMPLETE

**Goal:** API Python servindo alertas em tempo real via WebSocket.

### Features

**ZeroMQ Consumer** - COMPLETE
**WebSocket Server** - COMPLETE
**Message Router + CandleMacd + FlowTracker** - COMPLETE

---

## M4 - Frontend Core — COMPLETE

**Goal:** Interface React com alertas em tempo real, heatmap, painel de agressão.

### Features

**Alert Feed Tático** - COMPLETE
**Heatmap do Livro** - COMPLETE
**Painel de Agressão Dinâmico** - COMPLETE
**MACD Chart** - COMPLETE
**Agent 007 Panel** - COMPLETE

---

## M5 - Desktop & Polish — COMPLETE

**Goal:** Aplicação desktop instalável com overlay e experiência completa.

### Features

**Tauri Desktop App** - COMPLETE
**Overlay Profit (OCR)** - COMPLETE
**Instalador .exe (NSIS)** - COMPLETE

---

## M6 - Zero-Copy IPC (Fase 1 — Mês 1)

**Goal:** Substituir ZeroMQ por Memória Compartilhada com Lock-Free Ring Buffer, eliminando serialização e cópias de buffer.
**Target:** Fluxo Profit DLL → Python/Tauri via `CreateFileMapping`/`MapViewOfFile` sem cópia intermediária.
**Métrica:** Latência IPC < 10μs (atualmente ~1-5ms com ZMQ + JSON).

### Features

**Shared Memory Producer (C++)** - COMPLETE

- Writer de Memory-Mapped File (`SharedMemoryRingWriter`) integrado ao fluxo de publicação
- Lock-Free Ring Buffer (SPSC) com `MemoryBarrier` / sequência por slot
- Estruturas binárias no buffer compartilhado (trade)
- ZMQ mantido como fallback durante migração

**Shared Memory Consumer (Python)** - COMPLETE

- Reader via `mmap` / `ctypes` (`MmapConsumer`) com fallback SHM→ZMQ no startup
- Interface alinhada ao `ZmqConsumer` para o distributor
- Sem JSON no caminho SHM→router (conversão JSON apenas na borda WebSocket)

**Shared Memory Consumer (Tauri/Rust)** - COMPLETE

- Leitor SHM no app Tauri com fallback WebSocket + evento `ipc_fallback`

**Validação de Concorrência** - COMPLETE

- Testes de stress: 1M+ mensagens/segundo sem perda
- Validação de ordering guarantees do ring buffer
- Validação de integridade por slot (`payload_size` + CRC16-CCITT em `reserved0`) no consumer Python/Tauri e evidência automatizada
- **Benchmark comparativo ZMQ vs SHM** - COMPLETE (`scripts/benchmark_ipc_zmq_vs_shm.py`, CSV p50/p95/p99; `--stress` para pacing 100k msg/s e leitura de `dropped`)

---

## M7 - HFT OS Tuning + Segurança (Fase 2 — Mês 2)

**Goal:** Isolar cores de CPU para threads críticas e implementar gestão segura de credenciais.
**Target:** Zero context switching nas threads da Profit DLL; chaves nunca em plaintext no repo.

### Features

**CPU Pinning (C++)** - COMPLETE

- `SetThreadAffinityMask` para vincular thread da Profit DLL a core isolado
- `SetProcessPriorityBoost` + `HIGH_PRIORITY_CLASS` para engine
- Afinidade separada para thread de publicação (SHM writer)
- Modo de índice de core com priorização de núcleo físico (`HFT_CORE_INDEX_MODE=physical|logical`) para evitar siblings SMT quando possível
- Diagnóstico de jitter com `QueryPerformanceCounter` (`HFT_QPC_DIAG`, `HFT_QPC_SAMPLE_EVERY`, `HFT_QPC_MAX_SAMPLES`) para callbacks Profit e loop publisher
- Execução controlada para benchmark (`engine.exe --run-seconds=<N>`) com dump de percentis p50/p95/p99/p999/max
- Ferramenta de evidência automatizada (`scripts/benchmark_hft_qpc.py` e `scripts/run-hft-qpc-evidence.ps1`) para baseline vs pinning

**Otimizações de Memória** - COMPLETE

- Shared memory writer com tentativa de Huge Pages (`SHM_LARGE_PAGES` / `SHM_LARGE_PAGES_STRICT`) e fallback
- Preferência de node NUMA no mapping SHM (`SHM_NUMA_NODE`) via API NUMA quando disponível
- Cache prefetching (`HFT_PREFETCH`, `SHM_PREFETCH_NEXT_SLOT`) em hot paths do DOM/T&T + writer SHM
- Orquestração unificada de evidência (`scripts/run_m6_m7_evidence.py` + `scripts/run-m6-m7-evidence.ps1`) para matriz HFT + sessão IPC com resumo consolidado
- Controle de duração total por fase (`--hft-total-seconds`, `--session-total-seconds`) com divisão automática por janela para execuções longas contínuas

**Gestão de Segredos (AWS KMS)** - COMPLETE

- Scan de segredos no pre-commit entregue (`scripts/scan_secrets.py`, `.githooks/pre-commit`, `scripts/install-git-hooks.ps1`)
- Integração inicial com AWS KMS/Secrets Manager no startup do distributor (`distributor/aws_kms_bootstrap.py`; `AWS_KMS_SECRET_MAP`; retry 3x + backoff + erro claro)
- Bootstrapping opcional de KMS nos launchers (`scripts/load_kms_secrets.py`, `scripts/run-dev.ps1`, `scripts/run-dev2.ps1`) para propagar segredos ao engine/distributor em dev
- Engine aceita aliases `PROFIT_DLL_*` além de `PROFIT_*` para credenciais
- Allowlist de endpoint AWS por IP/CIDR (`AWS_KMS_ALLOWED_IPS`) no bootstrap para restringir resolução DNS do Secrets Manager
- Auditoria de acesso a segredos em JSONL (`AWS_KMS_AUDIT_LOG_PATH`) sem persistir valores sensíveis
- Chat do Agent007 com hardening de egress por IP/CIDR (`AGENT007_ALLOWED_IPS`/`OPENROUTER_ALLOWED_IPS`), auditoria JSONL (`AGENT007_AUDIT_LOG_PATH`) e métricas em `/health` (`agent007_chat_metrics`)
- **Migração `.env` → KMS** - COMPLETE (`scripts/migrate_env_to_kms.py`, `scripts/migrate-env-to-kms.ps1`): ferramenta de migração assistida com `--dry-run`, geração automática do `AWS_KMS_SECRET_MAP` e auditoria JSONL sem expor valores
- **Allowlist ZMQ egress** - COMPLETE (`ZMQ_ALLOWED_IPS` no `zmq_consumer.py`): validação IP/CIDR antes de `zmq.connect()` com fallback seguro
- Pipeline de auditoria centralizado (KMS + Agent007) com métricas no `/health` (`security_audit_metrics`) e controles de retenção/rotação (`SECURITY_AUDIT_RETENTION_DAYS`, `SECURITY_AUDIT_PRUNE_INTERVAL_S`, `SECURITY_AUDIT_DAILY_ROTATE`)

---

## M8 - Copiloto IA Conversacional (Fase 3 — Mês 3)

**Goal:** Interação por voz entre trader e IA com latência < 500ms, com acesso ao estado do mercado via Function Calling.
**Target:** Trader faz pergunta por voz → IA consulta dados em tempo real → responde por voz.

### Features

**WebRTC / Realtime API Bridge** - COMPLETE

- Endpoint `POST /api/voice/session` no distributor: gera `client_secret` (ephemeral key) via OpenAI Realtime API sem proxy de áudio
- Endpoint `POST /api/voice/function-call`: bridge IA → Agent007 state para Function Calling
- Endpoint `GET /api/voice/status`: feature flag + métricas de sessões
- Módulo `distributor/voice_realtime.py` com `create_realtime_session()` e `execute_function_call()`
- `OPENAI_REALTIME_API_KEY` lê de `OPENAI_API_KEY` (já injetado pelo KMS do M7)
- Feature flag `VOICE_FUNCTIONS_ENABLED` (default 1); desabilitado exibe botão inativo com tooltip

**Function Calling Schema** - COMPLETE

- 4 funções registradas na sessão Realtime API:
  - `analyze_order_book`: desequilíbrio de agressão + inversões recentes + urgência
  - `get_current_signal`: sinal verde/vermelho/neutro + Weis + MACD
  - `get_wall_status`: muralhas ativas no DOM (≥500 lotes)
  - `get_vwap_position`: preço vs VWAP + distância
- Bridge: IA invoca função → frontend POST /api/voice/function-call → Agent007.get_snapshot() → retorno via Data Channel

**UI do Copiloto** - COMPLETE

- Componente `VoiceCopilotPanel` com botão push-to-talk animado (anel pulsante por estado)
- Visualizador de amplitude (barras de onda sonora em tempo real)
- Badge de status com indicador colorido (idle/connecting/listening/thinking/speaking/error)
- Histórico de transcrições com bolhas de chat (usuário/IA), auto-scroll
- Toast de erro inline com mensagem descritiva
- Acessado via botão "🎙 Copiloto" na StatusBar (painel lateral slide-over, consistente com Agent007)
- Hook `useVoiceCopilot.ts`: ciclo completo WebRTC, PTT, amplitude loop, timeout de sessão, cleanup

---

## M9 - RAG em Tempo Real (Fase 4 — Mês 4) — IN PROGRESS

**Goal:** Pipeline de memória contextual que converte fluxo de mercado em embeddings pesquisáveis, injetados automaticamente no contexto da IA.
**Target:** Busca vetorial em janelas de 5min de T&T em < 10ms.

### Features

**Streaming Pipeline** - IN PROGRESS

- Ingestão de eventos no distributor com agregação em janelas temporais (default 5 min)
- Publicação best-effort em Redpanda/Kafka (`RAG_REDPANDA_BROKERS`, `RAG_TOPIC_PREFIX`) com degrade gracioso se broker/lib indisponível
- Tópicos lógicos mapeados: `trades`, `dom-snapshots`, `alerts`, `signals`

- Redpanda (ou Kafka) consumindo do SHM ring buffer
- Tópicos: `trades`, `dom-snapshots`, `alerts`, `signals`
- Janelas de tempo configuráveis (1min, 5min, 15min)

**Embedding Engine** - IN PROGRESS

- Embedding heurístico de janelas de mercado (trade/dom/signal/alert) sem dependência externa obrigatória
- Vetorização automática no fechamento das janelas e métricas de pipeline no `/health`

- Conversão de janelas de mercado (T&T, agressão, DOM) em vetores
- Modelo de embedding otimizado para dados financeiros tabulares
- Atualização contínua (a cada janela fechada)

**Banco Vetorial** - IN PROGRESS

- Índice vetorial local em memória com TTL configurável (`RAG_VECTOR_TTL_SECONDS`)
- Busca por similaridade cosseno com filtro por ativo (ticker)
- Persistência cloud opcional via Pinecone/Vectara (`RAG_VECTOR_CLOUD_*`, `RAG_PINECONE_*`, `RAG_VECTARA_*`) com fallback local-first e degrade gracioso

- Pinecone ou Vectara para armazenamento e busca de embeddings
- Índices por ativo e tipo de evento
- TTL automático para dados > 1 pregão

**Context Engine (Injeção de Contexto)** - IN PROGRESS

- Injeção automática de contexto RAG no endpoint `/api/agent007/chat`
- Endpoint de diagnóstico `/api/rag/status` + métricas RAG em `/health`
- Views materializadas de suporte (`/api/rag/views`) com backend configurável (`memory`/`sqlite`): VWAP running, delta de agressão, muralhas e top corretoras por lote, com warning/fallback por lag
- Evidência operacional contínua automatizada em pregão (`scripts/run_m9_rag_operational_evidence.py`, wrapper `scripts/run-m9-rag-operational-evidence.ps1`) com gates de saúde RAG/Views, **warm-up obrigatório**, watchdog de disponibilidade HTTP e rerun automático por tentativa

- Antes de responder, IA faz busca vetorial no estado do mercado
- Unifica: regras ativas + histórico de fluxo + padrões similares passados
- Views materializadas (Materialize ou SQL) para dados estruturados

---

## Future Considerations

- Backtesting e replay de sessões gravadas
- Suporte a Cedro e outras fontes de dados além da Profit DLL
- Dashboard de performance (win rate por tipo de alerta)
- Modo multi-monitor / layout customizável pelo trader
- Alertas remotos via Telegram / Discord
- Múltiplos ativos simultâneos com abas
- IA com personalidade configurável (agressivo, conservador, neutro)
- Integração com corretoras para execução assistida (semi-auto)
