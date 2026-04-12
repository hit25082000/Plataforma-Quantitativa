# Roadmap

**Current Milestone:** M6 - Zero-Copy IPC
**Status:** Planning

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

**Shared Memory Producer (C++)** - PLANNED

- Substituir `ZmqPublisher` por writer de Memory-Mapped File
- Lock-Free Ring Buffer (SPSC) com atomics para produtor/consumidor
- Estruturas de dados binárias (não JSON) no buffer compartilhado
- Fallback gracioso: manter ZMQ como canal secundário durante migração

**Shared Memory Consumer (Python)** - PLANNED

- Reader Python via `mmap` / `ctypes` para ler o ring buffer
- Adapter que expõe a mesma interface do `ZmqConsumer` atual
- Zero deserialização JSON: leitura direta de structs do buffer

**Shared Memory Consumer (Tauri/Rust)** - PLANNED

- Reader Rust opcional para Tauri ler direto da memória compartilhada
- Bypass do distributor Python para dados de baixa latência no overlay

**Validação de Concorrência** - PLANNED

- Testes de stress: 1M+ mensagens/segundo sem perda
- Validação de ordering guarantees do ring buffer
- Benchmark comparativo ZMQ vs SHM

---

## M7 - HFT OS Tuning + Segurança (Fase 2 — Mês 2)

**Goal:** Isolar cores de CPU para threads críticas e implementar gestão segura de credenciais.
**Target:** Zero context switching nas threads da Profit DLL; chaves nunca em plaintext no repo.

### Features

**CPU Pinning (C++)** - PLANNED

- `SetThreadAffinityMask` para vincular thread da Profit DLL a core isolado
- `SetProcessPriorityBoost` + `REALTIME_PRIORITY_CLASS` para engine
- Afinidade separada para thread de publicação (SHM writer)

**Otimizações de Memória** - PLANNED

- NUMA-aware allocation via Windows `VirtualAllocExNuma`
- Cache prefetching (`_mm_prefetch`) em hot paths do DOM/T&T
- Huge Pages (2MB) para o ring buffer compartilhado

**Gestão de Segredos (AWS KMS)** - PLANNED

- Integração com AWS KMS SDK para leitura de chaves
- Migração de `.env` → KMS para: API OpenAI, credenciais Profit, tokens de corretora
- IP Allowlist para serviços externos
- Auditoria de acesso a segredos

---

## M8 - Copiloto IA Conversacional (Fase 3 — Mês 3)

**Goal:** Interação por voz entre trader e IA com latência < 500ms, com acesso ao estado do mercado via Function Calling.
**Target:** Trader faz pergunta por voz → IA consulta dados em tempo real → responde por voz.

### Features

**WebRTC / Realtime API Bridge** - PLANNED

- Conexão frontend → OpenAI Realtime API (`gpt-4o-realtime-preview`) via WebRTC
- Alternativa avaliada: Cartesia Sonic / ElevenLabs para TTS de ultra-baixa latência
- Configuração de VAD (`silence_duration_ms`, `turn_detection`) para barge-in

**Function Calling Schema** - PLANNED

- Schema de funções expondo o motor C++ para a IA:
  - `analyze_order_book`: desequilíbrio de agressão atual
  - `get_current_signal`: estado das regras R1-R6
  - `get_wall_status`: muralhas ativas no DOM
  - `get_vwap_position`: posição relativa à VWAP institucional
- Bridge: IA invoca função → Tauri/Python consulta SHM/estado → retorna resultado

**UI do Copiloto** - PLANNED

- Botão push-to-talk / modo always-listening no frontend
- Indicador visual de estado (ouvindo / processando / falando)
- Histórico de interações recentes em painel lateral

---

## M9 - RAG em Tempo Real (Fase 4 — Mês 4)

**Goal:** Pipeline de memória contextual que converte fluxo de mercado em embeddings pesquisáveis, injetados automaticamente no contexto da IA.
**Target:** Busca vetorial em janelas de 5min de T&T em < 10ms.

### Features

**Streaming Pipeline** - PLANNED

- Redpanda (ou Kafka) consumindo do SHM ring buffer
- Tópicos: `trades`, `dom-snapshots`, `alerts`, `signals`
- Janelas de tempo configuráveis (1min, 5min, 15min)

**Embedding Engine** - PLANNED

- Conversão de janelas de mercado (T&T, agressão, DOM) em vetores
- Modelo de embedding otimizado para dados financeiros tabulares
- Atualização contínua (a cada janela fechada)

**Banco Vetorial** - PLANNED

- Pinecone ou Vectara para armazenamento e busca de embeddings
- Índices por ativo e tipo de evento
- TTL automático para dados > 1 pregão

**Context Engine (Injeção de Contexto)** - PLANNED

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
