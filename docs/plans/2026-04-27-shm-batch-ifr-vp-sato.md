# Plano - SHM lento apos alguns minutos, IFR e VP Sato parados

## Diagnostico
- A correcao anterior ativou `SHM_ENABLED=1` e `IPC_MODE=shm`, mas o payload SHM atual carrega somente `trade`.
- Em `frontend/src/hooks/useWebSocket.ts`, quando chega `pq:ipc-transport` com `mode=shm`, o WebSocket principal e fechado. Isso evita duplicidade de trades, mas tambem corta mensagens derivadas do distributor, incluindo `macd_signal` usado pelo IFR.
- `fetchWarmMacdSnapshot` hoje roda no `onopen` do WebSocket principal. Em modo SHM, esse `onopen` deixa de acontecer depois que o WS e fechado.
- `distributor/mmap_consumer.py` so reconstrui mensagens `market/trade`. Como `distributor/main.py` troca o consumidor principal para SHM, ele deixa de receber do ZMQ do engine os eventos `volume_profile` e `tape_intelligence` que alimentam VP Sato.
- `app/src-tauri/src/shared_memory_ipc.rs` emite um evento Tauri por trade (`pq:market-message`). Mesmo com batch no store React, a ponte Tauri/WebView ainda recebe eventos unitarios e pode acumular atraso apos alguns minutos de fluxo intenso.

## Causa raiz provavel
O modo SHM atual foi aplicado como substituto total do WebSocket/ZMQ, mas ele ainda nao e semanticamente equivalente ao stream antigo:
1. SHM entrega trades brutos.
2. ZMQ ainda entrega VP Sato/Tape/DOM/daily.
3. Distributor calcula IFR a partir dos trades, mas o frontend deixa de ouvir o WS onde esse IFR e publicado.
4. O frontend recebe trades SHM sem batching na ponte nativa.

## Plano de correcao
1. Batching no reader SHM do Tauri:
   - Acumular trades por janela curta (ex.: 16 ms) ou limite de lote (ex.: 200 trades).
   - Emitir `pq:market-message` como `ws_batch` quando houver mais de uma mensagem.
   - Manter emissao unica apenas para lote unitario.
2. Ajustar `useWebSocket` para aceitar batches vindos do Tauri:
   - Processar `topic=ws_batch` no listener `pq:market-message`.
   - Manter o WebSocket principal aberto mesmo com `ipcTransportMode=shm`.
   - Ignorar `market/trade` vindos do WebSocket quando SHM estiver ativo, evitando duplicidade no Times & Trades.
   - Continuar processando pelo WS: `macd_signal`, `flow_inversion`, `broker_snapshot`, `alert`, `daily`, `dom_snapshot` e demais derivados.
3. Restaurar VP Sato/Tape em modo SHM:
   - Criar consumidor ZMQ auxiliar filtrado no distributor quando `IPC_MODE=shm`.
   - Esse consumidor deve descartar `trade` e aceitar pelo menos `volume_profile`, `tape_intelligence` e `daily`.
   - Roteamento continua passando por `MessageRouter`, preservando enriquecimento OCR e broadcasts para `/ws/volume-profile` e `/ws/tape-intelligence`.
4. Restaurar warm-up IFR em modo SHM:
   - Ao receber `pq:ipc-transport mode=shm`, chamar `fetchWarmMacdSnapshot`.
   - Garantir que `sync_ifr_series_to_distributor` continue rodando apos distributor pronto.
5. Diagnostico/health:
   - Expor no `/health` metricas do consumidor auxiliar ZMQ quando ativo.
   - Logar lotes SHM: quantidade emitida, dropped/gap, write_seq observado.

## Validacao
1. Subir stack limpa.
2. Confirmar `/health`:
   - `ipc_mode=shm`
   - `backlog` baixo
   - consumidor SHM vivo
   - consumidor auxiliar ZMQ vivo em modo filtrado
3. Validar Times & Trades por 10 minutos:
   - sem queda progressiva de taxa visual
   - sem crescimento continuo de backlog
4. Validar IFR:
   - warm-up inicial aparece
   - troca 42R/16R/30m reidrata e volta a emitir `macd_signal`
5. Validar VP Sato/Tape:
   - `volume_profile` e `tape_intelligence` chegam nos WebSockets dedicados
   - overlay recebe atualizacoes sem depender de demo

## Guardrail
- Nao voltar `IPC_MODE` global para `zmq`; isso mascara a regressao de VP/IFR, mas reabre o backlog que motivou a correcao anterior.
- Nao fechar o WebSocket principal em modo SHM; apenas suprimir `trade` duplicado vindo dele.
