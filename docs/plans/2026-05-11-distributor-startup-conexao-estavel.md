# Plano — Distributor/startup/conexão estável

**Data:** 2026-05-11  
**Escopo:** engine Profit DLL, distributor FastAPI/WebSocket, Tauri lifecycle, frontend status/conexão.  
**Objetivo:** o app deve iniciar, conectar, manter feed ativo, reconectar quando possível e mostrar erro útil quando depender de ação externa.

## Critério de pronto

Este plano só fecha quando todos os gates abaixo passarem:

- `run-dev.ps1` sobe o app sem duplicar engine/distributor/OCR.
- `/health` responde como liveness mesmo durante boot.
- `/ready` só fica OK quando os consumers estão vivos e o pipeline está aceitando eventos.
- UI separa claramente: `INICIALIZANDO`, `AGUARDANDO FEED`, `CONECTADO`, `DESCONECTADO`.
- Troca de ativo não quebra o startup e tem retry limitado com mensagem objetiva.
- Perda temporária de ZMQ/SHM/WebSocket não derruba o distributor.
- Sessão de 30 minutos em pregão/replay mantém atualização ou degrada com motivo rastreável.
- Bundle de evidência gera logs suficientes para localizar causa-raiz sem adivinhação.

## Premissas operacionais

- Tauri é o dono principal do lifecycle em uso normal.
- `scripts/run-dev.ps1` deve preparar ambiente, buildar/copiar artefatos e iniciar Tauri; só inicia distributor/OCR por flags explícitas.
- Portas canônicas: `8000` distributor, `5555` ZMQ mercado, `5556` engine controle, `5557` ZMQ sync, `5558` OCR.
- Estado visual não deve depender só de “porta respondeu”; deve depender de camadas.
- Falha de Profit/DLL/login/pregão deve ser classificada separadamente de falha local de distributor.

## S0 — Congelar a superfície de estabilização

**Meta:** evitar que a correção cresça para overlay, indicadores ou UI extra.

Tarefas:

- Registrar o estado atual do worktree antes de mexer.
- Separar mudanças já existentes em blocos: startup, distributor readiness, engine/5556, statusbar, overlay/OCR.
- Não adicionar novos indicadores nem mudar contrato visual fora da statusbar/conexão.
- Manter logs e mensagens voltados para diagnóstico, não para copy final.

Gate:

- Lista de arquivos tocados por este plano e motivo de cada grupo.

## S1 — Diagnóstico reprodutível do erro atual

**Meta:** transformar “não para de dar erro” em um pacote único de evidência.

Tarefas:

- Criar/ajustar um coletor de diagnóstico de startup que leia:
  - processos `engine.exe`, `python.exe`, `distributor.exe`, `profit_ocr_service`.
  - listeners nas portas `8000`, `5555`, `5556`, `5557`, `5558`.
  - `runtime-bootstrap.log`.
  - `profit_engine.log`.
  - `engine_stderr.log`.
  - `distributor_stdout.log`.
  - `distributor_stderr.log`.
  - `/health`, `/ready`, `/debug/status`, `/ipc-state`.
- O coletor deve gerar `summary.json` com `ok`, `root_symptom`, `likely_layer`, `next_action`.
- Rodar o coletor antes e depois de cada slice.

Gate:

```powershell
python scripts/collect_startup_diagnostics.py --out-dir distributor/logs/startup-diagnostics-<timestamp>
```

Resultado esperado:

- Falha classificada como uma das camadas: `port_conflict`, `engine_not_started`, `profit_login_market`, `subscribe_failed`, `distributor_bootstrap`, `ipc_fallback`, `feed_stale`, `frontend_state`.

## S2 — Lifecycle único e portas sem conflito

**Meta:** eliminar start duplo e processo órfão.

Tarefas:

- Garantir que o fluxo padrão seja:
  1. limpar listeners antigos;
  2. carregar `.env`/KMS/aliases;
  3. buildar/copiar engine e DLLs;
  4. sincronizar recursos Tauri;
  5. iniciar Tauri;
  6. Tauri inicia/valida distributor e engine.
- Manter `-StartDistributor` e `-StartOcr` apenas como modo legado/diagnóstico.
- No Tauri, se houver processo existente, validar camada funcional antes de aceitar como “já rodando”.
- Quando uma porta estiver ocupada, reportar PID/processo e camada afetada.
- Revisar `docs/PORTS.md` junto com `scripts/run-dev.ps1`, `start_distributor.ps1` e `commands.rs`.

Gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1
```

Resultado esperado:

- Sem bind duplicado.
- Sem `engine.exe` residual segurando `5556`.
- Sem distributor antigo em `8000` com rotas incompletas.

## S3 — Contrato de startup do engine

**Meta:** engine só vira “pronto” quando a sessão Profit e a assinatura estiverem utilizáveis.

Tarefas:

- Separar status do engine em:
  - `process_started`.
  - `dll_loaded`.
  - `activation_ok`.
  - `login_ok`.
  - `market_connected`.
  - `subscribed`.
  - `control_port_ready`.
- `spawn_engine` deve falhar com motivo de camada, não com mensagem genérica.
- `5556` aberto não pode mascarar erro de login/assinatura.
- `set_active_asset` deve usar retry limitado e manter último motivo retornado pelo engine.
- Normalizar ativo/bolsa em todos os pontos: `WINFUT/F`, `TESTE/SIM`.
- Confirmar que build Debug/Release e cópia para `app/src-tauri/resources` ficam consistentes.

Gates:

```powershell
.\app\src-tauri\resources\engine.exe --run-seconds=35
```

```powershell
python scripts/run_m6_m7_evidence.py --python-exe python --engine engine/build/Release/engine.exe --workdir engine/build/Release --hft-duration-seconds 60 --session-seconds 60 --session-min-observed-trades 1
```

Resultado esperado:

- Ativação/login/market/subscription classificados.
- `subscribe_ticker_ret=0` e `subscribe_offer_book_ret=0` quando há sessão válida.

## S4 — Contrato de readiness do distributor

**Meta:** distributor vivo não significa feed pronto.

Tarefas:

- Consolidar `startup_state` como fonte única para `/health`, `/ready`, `/debug/status`, `/ipc-state`.
- `/health`: processo HTTP vivo e métricas disponíveis.
- `/ready`: consumers vivos, bootstrap finalizado e pipeline aceitando eventos.
- `feed_live`: evento de mercado recente dentro de `DISTRIBUTOR_FEED_LIVE_STALE_MS`.
- Background tasks devem marcar erro e não morrer silenciosamente.
- `ZmqConsumer` e `MmapConsumer` devem reconectar/revalidar sem matar o servidor.
- Fallback SHM→ZMQ deve ser explícito e visível.

Gates:

```powershell
python -m unittest distributor.tests.test_websocket_vp_overlay_endpoints
```

```powershell
python -m unittest distributor.tests.test_mmap_consumer distributor.tests.test_zmq_consumer_allowlist
```

Resultado esperado:

- `/ready` retorna `503` enquanto inicializa e `200` só quando o pipeline está pronto.
- `/health` continua disponível durante falha recuperável.

## S5 — Frontend sem falso desconectado

**Meta:** a UI deve refletir a camada certa, sem assustar quando está só aguardando feed.

Tarefas:

- Statusbar deve consumir `/health`, `/ready`, `/debug/status`.
- `DESCONECTADO` só quando o distributor HTTP estiver inacessível.
- `INICIALIZANDO DISTRIBUTOR` quando HTTP está vivo, mas `/ready` ainda não.
- `AGUARDANDO FEED` quando pipeline está pronto, mas ainda sem evento recente.
- `CONECTADO` quando há feed recente.
- Mensagem de erro deve carregar `last_error` quando existir.
- `useTauriStartup` deve tratar readiness como progressivo, sem travar a UI por falta temporária de feed.

Gates:

```powershell
rtk npm run build --prefix frontend
```

```powershell
rtk npm run typecheck --prefix frontend
```

Resultado esperado:

- Sem `DESCONECTADO` se `/health` está OK.
- Sem “conectado” falso se nenhum evento chegou.

## S6 — Recuperação automática e limites

**Meta:** manter conectado sem loop infinito opaco.

Tarefas:

- Definir política única de retry:
  - distributor HTTP: retry curto para boot.
  - engine 5556: retry com respawn controlado.
  - ZMQ/SHM: reconnect interno com backoff.
  - WebSocket frontend: reconnect contínuo com estado visual.
- Registrar cada transição: `attempt`, `ready`, `fallback`, `degraded`, `recovered`, `failed`.
- Evitar respawn concorrente de engine/distributor.
- Quando o erro depender de Profit fechado, login inválido ou fora de pregão, mostrar esse motivo e parar respawn agressivo.

Gate:

```powershell
python scripts/collect_startup_diagnostics.py --stress-reconnect --duration-seconds 180 --out-dir distributor/logs/startup-reconnect-<timestamp>
```

Resultado esperado:

- Recuperação sem multiplicar processos.
- Falha final com motivo útil quando recuperação não é possível.

## S7 — Evidência contínua de atualização

**Meta:** provar que conecta e continua atualizando.

Tarefas:

- Criar sessão assistida que valide:
  - `/health`.
  - `/ready`.
  - `/debug/status.feed_live`.
  - incremento de `messages_received_total`.
  - incremento de `messages_sent_total`.
  - atualização de Times & Trades/VP quando aplicável.
- Rodar smoke curto em modo local e janela longa em pregão/replay.
- Gerar `summary.json` com contadores antes/depois, falhas HTTP, lag máximo e motivo de parada.

Gates:

```powershell
python scripts/run_startup_connection_evidence.py --base-url http://127.0.0.1:8000 --duration-seconds 300 --interval-seconds 2 --out-dir distributor/logs/startup-connection-evidence-<timestamp>
```

```powershell
python scripts/run_startup_connection_evidence.py --base-url http://127.0.0.1:8000 --duration-seconds 1800 --interval-seconds 5 --require-feed-live --out-dir distributor/logs/startup-connection-evidence-live-<timestamp>
```

Resultado esperado:

- `overall_ok=1`.
- Sem queda contínua de `/health`.
- Sem travar em `initializing`.
- Sem backlog crescente sem recuperação.

## S8 — Testes de regressão mínimos

**Meta:** impedir que o mesmo problema volte.

Tarefas:

- Cobrir `startup_state`.
- Cobrir `/health`, `/ready`, `/debug/status`, `/ipc-state`.
- Cobrir reconexão ZMQ.
- Cobrir fallback SHM→ZMQ.
- Cobrir statusbar para quatro estados.
- Cobrir `useTauriStartup` para credenciais ausentes, distributor lento, engine lento e troca de ativo lenta.
- Cobrir comando Tauri de readiness com payload `503` preservado.

Gates:

```powershell
python -m unittest discover -s distributor/tests -p "test_*.py"
```

```powershell
rtk cargo test --manifest-path app/src-tauri/Cargo.toml
```

```powershell
rtk npm run build --prefix frontend
```

## S9 — Fechamento operacional

**Meta:** deixar um procedimento simples para uso real.

Tarefas:

- Atualizar `STATE.md` com o resultado validado.
- Atualizar `docs/PORTS.md` se houver ajuste de porta/lifecycle.
- Registrar comandos oficiais:
  - dev normal.
  - diagnóstico.
  - evidência curta.
  - evidência live.
- Registrar o que fazer quando:
  - Profit estiver fechado.
  - login/ativação falhar.
  - fora de pregão.
  - porta ocupada.
  - feed sem novos eventos.

Gate final:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1
python scripts/run_startup_connection_evidence.py --base-url http://127.0.0.1:8000 --duration-seconds 300 --interval-seconds 2 --out-dir distributor/logs/startup-final-smoke
```

## Ordem de execução recomendada

1. S1 diagnóstico atual.
2. S2 lifecycle/portas.
3. S3 engine e 5556.
4. S4 distributor readiness.
5. S5 frontend status.
6. S6 recuperação.
7. S7 evidência contínua.
8. S8 regressão.
9. S9 documentação/estado.

## Prioridade prática

P0:

- Diagnóstico atual.
- Lifecycle único.
- Readiness real do distributor.
- Engine pronto por sessão/assinatura, não só por processo/porta.

P1:

- Reconnect ZMQ/SHM robusto.
- Statusbar sem falso desconectado.
- Evidência curta e live.

P2:

- Refinos de mensagens.
- Runbook final.
- Cobertura ampliada.
