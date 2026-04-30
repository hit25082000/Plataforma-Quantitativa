# State

**Last Updated:** 2026-04-24
**Latest Update:** 2026-04-24 (M9 — reteste da rodada longa executado) — nova execução de 30 min com rerun automático (3 tentativas) repetiu o padrão de falha (`attempt-01` watchdog por queda de `/health`; `attempt-02/03` warm-up sem amostras HTTP), mantendo `overall_ok=0`.
**Current Work:** M9 em andamento. Streaming e Context Engine operacionais com vector store local + backends cloud opcionais (Pinecone/Vectara); views materializadas com backend memory/sqlite e rotina de evidência contínua em pregão entregue e robustecida. Próximos passos: nova rodada longa em pregão ativo com estabilidade de `/health` para fechar `overall_ok=1` e, depois, evolução opcional para engine SQL dedicado (Materialize) quando necessário.

---

## Recent Decisions (Last 60 days)

### AD-013: Views materializadas com backend SQL opcional (2026-04-24)

**Decision:** Adicionar backend SQL local (`sqlite`) para views materializadas do RAG, selecionável por configuração (`RAG_VIEWS_BACKEND`), mantendo backend em memória como default e fallback.
**Reason:** Evoluir a etapa de views materializadas do M9 para caminho SQL sem introduzir dependência obrigatória de infraestrutura externa nesta fase.
**Trade-off:** SQLite local simplifica adoção imediata, mas não substitui engine SQL streaming dedicado; Materialize segue como opção de evolução posterior.
**Impact:** `distributor/realtime_rag.py`, `distributor/config.py`, `distributor/tests/test_realtime_rag.py`.

### AD-012: M9 fase 2 com cloud opcional e views locais (2026-04-23)

**Decision:** Introduzir persistência vetorial cloud opcional (Pinecone via REST) em modo mirror/fallback sem bloquear o caminho local, e adicionar views materializadas intraday em memória para agregados estruturados consumidos pelo contexto da IA.
**Reason:** Avança os itens pendentes do M9 (persistência entre restart + agregados prontos para consulta) preservando latência e tolerância a falhas no core de trading.
**Trade-off:** Sem dependência obrigatória de cloud, com cobertura inicial Pinecone/Vectara; views ainda locais (não SQL/Materialize).
**Impact:** `distributor/realtime_rag.py`, `distributor/config.py`, `distributor/websocket_server.py`, `distributor/tests/test_realtime_rag.py`.

### AD-011: M9 fase inicial local-first com degrade gracioso (2026-04-23)

**Decision:** Entregar primeiro o RAG intraday dentro do distributor (janela+embedding+vetor em memória) e manter Redpanda/Kafka como publicação opcional best-effort, sem bloquear o fluxo de trading quando indisponível.
**Reason:** Permite iniciar contexto histórico da IA imediatamente com baixo risco operacional e sem acoplar o core a infraestrutura externa já no primeiro incremento.
**Trade-off:** Vetor local não persiste restart; relevância semântica inicial é heurística (não usa embedding cloud dedicado).
**Impact:** `distributor/realtime_rag.py`, `distributor/message_router.py`, `distributor/websocket_server.py`, `distributor/agent_007_chat.py`, `distributor/config.py`, `distributor/requirements.txt`, testes novos `distributor/tests/test_realtime_rag.py`.

### AD-010: Fallback SHM→ZMQ no startup e transporte SHM no Tauri (2026-04-16)

**Decision:** Com `IPC_MODE=shm`, o distributor faz probe do mapping com timeout; se SHM não estiver válido/disponível, usa `ZmqConsumer` até **restart** (sem auto-switch de volta). O app Tauri abre o mesmo mapping e emite `pq:market-message`; se SHM falhar, sinaliza `pq:ipc-fallback` e a UI volta ao WebSocket do distributor. O launcher de baseline (`scripts/run-dev2.ps1`) agora espera o mapping SHM antes de iniciar o distributor. O helper de evidência (`scripts/run-ipc-evidence.ps1`) escolhe automaticamente o mapping real para `session` quando `ShmName` não é informado.
**Reason:** Migração sem downtime; critérios P2 do spec (fallback + evento + leitor Rust).
**Trade-off:** Leitor Tauri SHM cobre o que o ring publica como trade no caminho atual; DOM/sync continuam dependentes do distributor/ZMQ até evolução do layout/engine.
**Impact:** `distributor/config.py` (`SHM_FALLBACK_PROBE_*`), `distributor/main.py`, `distributor/websocket_server.py` (`/ipc-state`, primeiro frame WS em fallback), `app/src-tauri` (`shared_memory_ipc.rs`, `spawn_distributor` → `/ipc-state`), `frontend` (`useWebSocket.ts`, `messages.ts`), `engine/README.md` (operacional).

### AD-005: Substituir ZeroMQ por Memória Compartilhada (2026-04-12)

**Decision:** Migrar IPC de ZeroMQ (TCP + JSON) para Memory-Mapped Files com Lock-Free Ring Buffer (SPSC).
**Reason:** ZMQ exige serialização JSON e cópias de buffer de rede, adicionando ~1-5ms de latência. SHM com ring buffer lock-free reduz para microssegundos e elimina cópias.
**Trade-off:** Complexidade significativamente maior (atomics, memory ordering, validação de concorrência); perda da portabilidade de rede do ZMQ; ZMQ será mantido como fallback durante migração.
**Impact:** Requer reescrever `ZmqPublisher` (C++) e `ZmqConsumer` (Python); novo reader Rust no Tauri; structs binárias no lugar de JSON.

### AD-006: OpenAI Realtime API para Copiloto de Voz (2026-04-12)

**Decision:** Usar OpenAI Realtime API (`gpt-4o-realtime-preview`) via WebRTC para interação voz-para-voz com o trader.
**Reason:** Latência nativa de 200-500ms fala-para-fala; VAD embutido com suporte a barge-in; Function Calling integrado para consultar o motor C++.
**Trade-off:** Custo por minuto de áudio; dependência de terceiro para feature crítica; alternativas (Cartesia Sonic, ElevenLabs) serão avaliadas para TTS.
**Impact:** Frontend precisa de componente WebRTC; bridge de Function Calling conectando IA → Tauri/Python → SHM/estado do motor.

### AD-007: Pipeline RAG com Redpanda + Banco Vetorial (2026-04-12)

**Decision:** Implementar RAG em tempo real com Redpanda para streaming e Pinecone/Vectara para busca vetorial.
**Reason:** A IA precisa de contexto contínuo do mercado (janelas de 5min) para respostas fundamentadas; embedding de dados tabulares financeiros permite busca semântica de padrões.
**Trade-off:** Infraestrutura adicional (Redpanda broker); custo de banco vetorial cloud; complexidade de pipeline de embeddings.
**Impact:** Novo componente de streaming entre SHM e banco vetorial; Context Engine como middleware antes de cada resposta da IA.

### AD-008: CPU Pinning e otimizações de SO Windows (2026-04-12)

**Decision:** Implementar afinidade de CPU, NUMA-aware allocation e Huge Pages para threads críticas.
**Reason:** Context switching do Windows limpa caches L1/L2 e introduz jitter inaceitável para HFT; isolar cores garante latência previsível.
**Trade-off:** Reduz cores disponíveis para outras aplicações; configuração por máquina pode variar; requer hardware recomendado (i7+/Ryzen 7+).
**Impact:** Mudanças no `main.cpp` do engine (afinidade de thread); Huge Pages requerem privilégio de Lock Pages in Memory no Windows.

### AD-009: AWS KMS para gestão de segredos (2026-04-12)

**Decision:** Migrar todas as chaves sensíveis (.env, credenciais) para AWS KMS.
**Reason:** Chaves em plaintext no repo/env são risco de segurança inaceitável quando há chaves de API da OpenAI e credenciais de corretora.
**Trade-off:** Dependência de AWS; latência de leitura de segredos no startup; custo mensal marginal do KMS.
**Impact:** SDK AWS no Python e possivelmente no Rust; IP Allowlist nos serviços externos.

---

## Active Blockers

_Nenhum blocker ativo._

---

## Lessons Learned

### L-001: EventQueue com mutex e condition_variable é gargalo potencial (2026-04-12)

**Context:** Análise do `event_bus.h` revelou que o engine usa `std::queue<Event>` com `std::mutex` e `std::condition_variable`.
**Problem:** Mutex cria contenção quando produtor (Profit DLL callbacks) e consumidor (dispatcher/rules) competem pela fila.
**Solution:** Ring buffer SPSC lock-free (com atomics `memory_order_release/acquire`) eliminará a contenção.
**Prevents:** Latência imprevisível por contenção de lock em cenários de alto throughput.

---

## Preferences

**Model Guidance Shown:** 2026-04-12

---

## Validation

- 2026-04-24 (M9 operacional contínuo 30min c/ rerun — reteste): `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run-m9-rag-operational-evidence.ps1 -BaseUrl http://127.0.0.1:8000 -Ticker WINFUT -DurationSeconds 1800 -IntervalSeconds 5 -WarmupSeconds 60 -WarmupMinOkSamples 3 -WatchdogConsecutiveHttpFailures 8 -MaxAttempts 3 -RerunBackoffSeconds 10 -SqlitePath distributor/logs/rag_views_pregao.sqlite3 -ExpectViewsBackend sqlite -MaxHttpFailures 400 -MaxLagMs 600000 -MinViewsIngestedDelta 50` concluído com `overall_ok=0` em `distributor/logs/m9-rag-operational-evidence-20260424-122034/summary.json` (attempt-01 `watchdog_health_drop`; attempt-02/03 `warmup_not_ready`)
- 2026-04-24 (M9 operacional contínuo 30min c/ rerun): `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run-m9-rag-operational-evidence.ps1 -BaseUrl http://127.0.0.1:8000 -Ticker WINFUT -DurationSeconds 1800 -IntervalSeconds 5 -WarmupSeconds 60 -WarmupMinOkSamples 3 -WatchdogConsecutiveHttpFailures 8 -MaxAttempts 3 -RerunBackoffSeconds 10 -SqlitePath distributor/logs/rag_views_pregao.sqlite3 -ExpectViewsBackend sqlite -MaxHttpFailures 400 -MaxLagMs 600000 -MinViewsIngestedDelta 50` concluído com `overall_ok=0` em `distributor/logs/m9-rag-operational-evidence-20260424-112314/summary.json` (attempt-01 `watchdog_health_drop`; attempt-02/03 `warmup_not_ready`)
- 2026-04-24 (M9 evidenciador robusto): `python -m compileall scripts/run_m9_rag_operational_evidence.py` OK
- 2026-04-24 (M9 evidenciador robusto smoke): `python scripts/run_m9_rag_operational_evidence.py --base-url http://127.0.0.1:65534 --ticker WINFUT --duration-seconds 5 --interval-seconds 1 --timeout-seconds 0.8 --warmup-seconds 3 --warmup-min-ok-samples 1 --max-attempts 2 --rerun-backoff-seconds 1 --out-dir tmp/m9-rag-watchdog-smoke` executado com rerun automático (2 tentativas)
- 2026-04-24 (M9 operacional contínuo 30min): `python scripts/run_m9_rag_operational_evidence.py --base-url http://127.0.0.1:8000 --ticker WINFUT --duration-seconds 1800 --interval-seconds 5 --expect-views-backend sqlite --max-http-failures 400 --max-lag-ms 600000 --min-views-ingested-delta 50 --sqlite-path distributor/logs/rag_views_pregao.sqlite3` concluído com `overall_ok=0` (sem fluxo novo; `sqlite_min_lag_ms=1037035`) em `distributor/logs/m9-rag-operational-evidence-20260424-104115/summary.json`
- 2026-04-24 (M9 operacional contínuo 30min): execução anterior da mesma janela concluída com `overall_ok=0` em `distributor/logs/m9-rag-operational-evidence-20260424-101022/summary.json`
- 2026-04-24 (M9 operacional contínuo): `python scripts/run_m9_rag_operational_evidence.py --base-url http://127.0.0.1:8000 --ticker WINFUT --duration-seconds 60 --interval-seconds 5 --expect-views-backend sqlite --max-http-failures 20 --max-lag-ms 300000 --min-views-ingested-delta 1 --sqlite-path distributor/logs/rag_views_pregao.sqlite3` OK (`overall_ok=1`)
- 2026-04-24 (M9 operacional contínuo): `python -m compileall scripts/run_m9_rag_operational_evidence.py` OK
- 2026-04-24 (M9 views SQL pregão smoke): execução em ambiente de pregão com `run-dev2.ps1` + `RAG_ENABLED=1` + `RAG_VIEWS_BACKEND=sqlite` OK; evidência em `distributor/logs/rag-views-sqlite-evidence-pregao-20260424-095525/summary.json` (`ok=true`, `trades_rows=18547`, `walls_rows=250`)
- 2026-04-24 (M9 views SQL restart): `python scripts/run_rag_views_sqlite_evidence.py --out-dir distributor/logs/rag-views-sqlite-evidence-20260424` OK (`summary.json` com `ok=true`)
- 2026-04-24 (M9 views SQL restart): `python -m unittest distributor.tests.test_realtime_rag` OK (9 testes, incluindo persistência sqlite entre restart)
- 2026-04-24 (M9 views SQL restart): `python -m compileall scripts/run_rag_views_sqlite_evidence.py distributor/tests/test_realtime_rag.py` OK
- 2026-04-24 (M9 views SQL): `python -m unittest distributor.tests.test_realtime_rag` OK (8 testes, incluindo backend sqlite)
- 2026-04-24 (M9 views SQL): `python -m compileall distributor/realtime_rag.py distributor/config.py distributor/tests/test_realtime_rag.py` OK
- 2026-04-24 (M6/M7 pregão ativo final): `python scripts/run_m6_m7_evidence.py --python-exe python --out-dir distributor/logs/m6-m7-evidence-pregao-ativo-final-20260424-093456 --engine engine/build/Release/engine.exe --workdir engine/build/Release --hft-duration-seconds 120 --hft-startup-grace-seconds 10 --hft-windows 1 --hft-runs pinned --hft-enable-shm-qpc --matrix-shm-large-pages 0 --matrix-shm-numa-nodes -1 --session-seconds 120 --session-windows 1 --session-min-observed-trades 1 --session-fail-on-loss` OK (`overall_ok=1`)
- 2026-04-24 (HFT QPC smoke): `python scripts/benchmark_hft_qpc.py --engine engine/build/Release/engine.exe --workdir engine/build/Release --duration-seconds 120 --runs pinned --enable-shm-qpc --out tmp/hft_qpc_recheck.csv` OK
- 2026-04-24 (engine login+subscribe smoke): `engine/build/Release/engine.exe --run-seconds=35` OK (`Login:0`, `Subscribe startup OK`)
- 2026-04-23 (M9 fase 2b): `python -m unittest distributor.tests.test_realtime_rag` OK (7 testes)
- 2026-04-23 (M9 fase 2b): `python -m unittest distributor.tests.test_agent_007_chat distributor.tests.test_agent_007 distributor.tests.test_realtime_rag` OK (17 testes)
- 2026-04-23 (M9 fase 2b): `python -m compileall distributor/realtime_rag.py distributor/config.py distributor/tests/test_realtime_rag.py` OK
- 2026-04-23 (M9 fase 2): `python -m unittest distributor.tests.test_realtime_rag` OK (6 testes)
- 2026-04-23 (M9 fase 2): `python -m unittest distributor.tests.test_agent_007_chat distributor.tests.test_agent_007` OK (10 testes)
- 2026-04-23 (M9 fase 2): `python -m compileall distributor/realtime_rag.py distributor/websocket_server.py distributor/config.py distributor/tests/test_realtime_rag.py` OK
- 2026-04-23 (M9): `python -m unittest distributor.tests.test_realtime_rag distributor.tests.test_agent_007_chat` OK (8 testes)
- 2026-04-23 (M9): `python -m unittest distributor.tests.test_voice_realtime distributor.tests.test_agent_007` OK (31 testes)
- 2026-04-23 (M9): `python -m compileall distributor/realtime_rag.py distributor/main.py distributor/message_router.py distributor/websocket_server.py distributor/agent_007_chat.py` OK
- 2026-04-21: `python -m unittest distributor.tests.test_mmap_consumer distributor.tests.test_benchmark_ipc_zmq_vs_shm distributor.tests.test_run_m6_m7_evidence distributor.tests.test_security_audit distributor.tests.test_aws_kms_bootstrap distributor.tests.test_agent_007_chat` OK
- 2026-04-21: `python -m unittest distributor.tests.test_egress_allowlist distributor.tests.test_agent_007_chat distributor.tests.test_aws_kms_bootstrap` OK
- 2026-04-21: `cargo check --manifest-path app/src-tauri/Cargo.toml` OK
- 2026-04-21: `npm run build --prefix frontend` OK
- 2026-04-21: `frontend/node_modules/.bin/tsc.cmd --noEmit -p frontend/tsconfig.json` OK
- 2026-04-21: `python -m unittest distributor.tests.test_run_m6_m7_evidence` OK
- 2026-04-21: `python -m unittest distributor.tests.test_migrate_env_to_kms distributor.tests.test_zmq_consumer_allowlist distributor.tests.test_run_m6_m7_evidence distributor.tests.test_mmap_consumer distributor.tests.test_benchmark_ipc_zmq_vs_shm distributor.tests.test_security_audit distributor.tests.test_aws_kms_bootstrap distributor.tests.test_agent_007_chat distributor.tests.test_egress_allowlist` OK (83 testes)
- 2026-04-21: `python -m compileall scripts/migrate_env_to_kms.py` OK
- 2026-04-21 (M8): `python -m unittest distributor.tests.test_voice_realtime` OK (22 testes)
- 2026-04-21 (M8): `npm run build --prefix frontend` OK (c/ VoiceCopilotPanel + useVoiceCopilot)
- 2026-04-21 (M8): `frontend/node_modules/.bin/tsc.cmd --noEmit -p frontend/tsconfig.json` OK
