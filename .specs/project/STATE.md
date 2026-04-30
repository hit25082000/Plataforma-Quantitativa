# State

**Last Updated:** 2026-04-29
**Latest Update:** 2026-04-29 (reauditoria complementar OCR overlay estável) — o plano `docs/plans/2026-04-29-ocr-overlay-estavel-profit-tarefas.md` foi reauditado com artefatos locais recentes (`ovr-stab-qa-evidence`, checklist QA final e checklist OBS-09), mantendo critério conservador (`done=1`, `partial=0.5`, `not-evidenced=0`) e progresso oficial em **28%** (`19.0/67`), sem incremento por ausência de novas evidências de campo conclusivas.
**Current Work:** M9 em andamento. Streaming e Context Engine operacionais com vector store local + backends cloud opcionais (Pinecone/Vectara); views materializadas com backend memory/sqlite e rotina de evidência contínua em pregão entregue e robustecida. Na frente VP Sato + OCR overlay, o foco imediato está em fechar QA de campo (especialmente multi-monitor/DPI), consolidar observabilidade final e converter itens hoje parciais para concluídos com aceite operacional.

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
- 2026-04-29 (VP OCR overlay Sato): `python scripts/check_vp_sato_overlay.py --json` OK com `ok=true`, `overlay_ok=true` e `ocr_ok=true` após separar o gate demo/overlay do ramo Profit real; OCR respondeu `status=ok`, `axis_labels=3` e `chart_rect` válido.
- 2026-04-29 (VP OCR overlay Sato settings cap): `frontend/src/components/Settings/SettingsPanel.tsx` passou a aceitar `max_visible_histogram_levels` até 2000; `rtk npm run build --prefix frontend` e a suíte do overlay continuaram OK.
- 2026-04-29 (VP OCR overlay Sato QA visual): `frontend/src/pages/OverlayPage.tsx` passou a expor `align Npx` no `StatusBadge`, e `scripts/check_vp_sato_overlay.py` agora registra `vp_alignment_ok` como gate visual; `npm run build --prefix frontend` permaneceu OK.
- 2026-04-29 (VP OCR overlay Sato): `rtk python -m unittest distributor.tests.test_vp_overlay_consolidator distributor.tests.test_vp_ocr_enrich distributor.tests.test_message_router_vp_tape distributor.tests.test_websocket_vp_tape_endpoints distributor.tests.test_message_router_ui_aggregator distributor.tests.test_websocket_vp_overlay_endpoints distributor.tests.test_vp_overlay_contract` OK; `rtk npm run build --prefix frontend` OK.
- 2026-04-29 (VP OCR overlay Sato render debug): `frontend/src/pages/OverlayPage.tsx` passou a expor `render ms`, contagem visível de histograma e médias no `StatusBadge`; `rtk npm run build --prefix frontend` OK.
- 2026-04-29 (VP OCR overlay Sato observability): `frontend/src/pages/OverlayPage.tsx` passou a expor contagem OCR visível no `StatusBadge`; `rtk npm run build --prefix frontend` OK.
- 2026-04-29 (VP OCR overlay Sato histogram coalescing): `frontend/src/pages/OverlayPage.tsx` passou a coalescer histogramas densos antes do render; `rtk npm run build --prefix frontend` OK.
- 2026-04-29 (VP OCR overlay Sato histogram observability): `frontend/src/pages/OverlayPage.tsx` passou a expor contagem de merges do histograma no `StatusBadge`; `rtk npm run build --prefix frontend` OK.
- 2026-04-29 (VP OCR overlay Sato avg dedupe): `frontend/src/pages/OverlayPage.tsx` passou a deduplicar top avg por preço no overlay antes do render; `rtk npm run build --prefix frontend` OK.
- 2026-04-29 (VP OCR overlay Sato avg compact labels): `frontend/src/pages/OverlayPage.tsx` passou a compactar labels densos de médias no overlay; `rtk npm run build --prefix frontend` OK.
- 2026-04-29 (VP OCR overlay Sato legenda): `frontend/src/pages/OverlayPage.tsx` passou a mostrar níveis visíveis e merges na legenda do VP; `rtk npm run build --prefix frontend` OK.
- 2026-04-29 (VP OCR overlay Sato backend observability): `distributor/vp_overlay_consolidator.py` e `distributor/websocket_server.py` passaram a expor cache/emit/skipped do consolidator no debug e no `/health`; `python -m compileall distributor/vp_overlay_consolidator.py distributor/websocket_server.py` OK.
- 2026-04-29 (VP OCR overlay Sato health coverage): `distributor/tests/test_websocket_vp_overlay_endpoints.py` passou a cobrir os contadores do consolidator em `/health`; `python -m compileall distributor/tests/test_websocket_vp_overlay_endpoints.py` OK.
- 2026-04-29 (VP OCR overlay Sato QA-03 parcial): sessão real com app + Profit abertos mostrou `route_avg_ms` estável (~3.3 ms) e backlog baixo/oscillante; o coletor HTTP conseguiu ler `/health`, mas `vp_overlay/debug` e `vp_overlay/last` permaneceram vazios nesta janela e o WS externo do coletor retornou `403`.
- 2026-04-29 (VP OCR overlay estável - debug/trace OCR): `distributor/profit_ocr_service.py` passou a expor `GET /debug`, manter `last_frame` por iteração e opcionalmente gravar `ocr_overlay_trace.jsonl`; `python -m compileall distributor/profit_ocr_service.py distributor/tests/test_profit_ocr_service.py` OK e `python -m unittest distributor.tests.test_profit_ocr_service distributor.tests.test_websocket_vp_overlay_endpoints distributor.tests.test_vp_ocr_enrich` OK (9 testes).
- 2026-04-29 (VP OCR overlay estável - controles do eixo): `distributor/profit_ocr_service.py` passou a expor `POST /freeze`, `POST /unfreeze` e `POST /manual_calibration`; `app/src-tauri/src/commands.rs`, `app/src-tauri/src/lib.rs` e `frontend/src/pages/OverlayPage.tsx` passaram a consumir/expor esses controles e a mostrar `axis_status`/`axis_source`/`bad_frames` no HUD; `cargo check --manifest-path app/src-tauri/Cargo.toml` e `npm run build --prefix frontend` OK.
- 2026-04-28 (VP OCR overlay Sato frontend store): `rtk python -m unittest distributor.tests.test_vp_overlay_consolidator distributor.tests.test_vp_ocr_enrich distributor.tests.test_message_router_vp_tape distributor.tests.test_websocket_vp_tape_endpoints distributor.tests.test_message_router_ui_aggregator` OK; `rtk npm run build --prefix frontend` OK após registrar `vp_overlay` no store/frontend.
- 2026-04-28 (VP OCR overlay Sato store cleanup): `clearMarketData()` limpa `vpOverlay` e `overlayLastUpdateTs`, evitando snapshot velho ao trocar de ativo.
- 2026-04-28 (VP OCR overlay Sato endpoints): `rtk python -m unittest distributor.tests.test_websocket_vp_overlay_endpoints distributor.tests.test_vp_overlay_consolidator distributor.tests.test_vp_overlay_contract distributor.tests.test_vp_ocr_enrich distributor.tests.test_websocket_vp_tape_endpoints` OK.
- 2026-04-28 (VP OCR overlay Sato settings): `rtk npm run build --prefix frontend` OK após persistir `vp_overlay.histogram_visible` no painel de configurações.
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
