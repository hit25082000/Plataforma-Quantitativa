# Plano - SHM nao ativado e backlog ZMQ

## Diagnostico observado
- O `/health` atual responde, mas degradado: `ipc_mode=zmq`, `backlog=20000/20000`, `route_avg_ms=725ms`, `dropped_dom=609`, `dropped_low_priority=16204`.
- O engine segue recebendo trades: `q_trade=0`, `q_normal` baixo e `realtime_trades_received` subindo.
- O leitor Tauri loga apenas `aguardando mapping ... Local\PQMarketDataV1`; nao ha evidencia de abertura do mapping.
- O `engine` so cria SHM quando `SHM_ENABLED=1`.
- `app/src-tauri/src/commands.rs::spawn_engine` nao injeta `SHM_ENABLED=1`.
- `scripts/run-dev.ps1` tambem nao define `SHM_ENABLED=1` nem `IPC_MODE=shm`.
- `distributor/config.py` usa `IPC_MODE=zmq` por default.

## Causa raiz
A correcao anterior manteve o leitor SHM do Tauri vivo, mas o writer SHM do engine nao esta sendo ativado no caminho normal do app.

Resultado:
1. Tauri fica esperando um mapping que nunca nasce.
2. Frontend continua dependendo do WebSocket do distributor.
3. Distributor roda em ZMQ e satura sob carga.
4. A fila chega ao limite (`20000/20000`) e a UI para de receber dados recentes.

## Plano de correcao
1. Em `spawn_engine`, definir por default:
   - `SHM_ENABLED=1`
   - `SHM_MAPPING_NAME=Local\PQMarketDataV1`
   - `SHM_SIZE_MB=64`
   mantendo override por variavel de ambiente quando ja existir.
2. Em `spawn_distributor`, definir `IPC_MODE=shm`, `SHM_MAPPING_NAME` e `SHM_SIZE_MB` no processo gerenciado pelo Tauri.
3. Ajustar `useTauriStartup` para, se `/health` ja estiver ok mas `ipc_mode=zmq`, reiniciar/subir distributor depois do engine ou ao menos emitir estado correto e nao tratar ZMQ saturado como pronto.
4. Ajustar `scripts/run-dev.ps1` para:
   - setar `SHM_ENABLED=1` antes do Tauri spawnar o engine;
   - evitar iniciar distributor antes do engine em modo SHM, ou iniciar distributor com `IPC_MODE=shm` apenas depois do mapping existir.
5. Adicionar log objetivo no Tauri reader ao abrir SHM:
   - mapping aberto;
   - `capacity`;
   - `slot_size`;
   - primeiro `write_seq` visto.
6. Validar com `/health`:
   - `ipc_mode=shm`;
   - `backlog` proximo de 0;
   - `route_avg_ms` abaixo de 5ms;
   - `integrity_failures_total=0`;
   - UI sem `SEM ATUALIZACAO` durante trades ativos.

## Validacao operacional
- Reiniciar stack.
- Confirmar no log do engine: `shm_enabled=1` e `shm_write_seq` subindo.
- Confirmar no Tauri: `pq:ipc-transport mode=shm`.
- Confirmar no `/health`: `ipc_mode=shm`, `backlog < 100`, `route_avg_ms < 5`.
- Rodar monitor por 2 minutos em pregão ativo sem timeout de `/health`.
