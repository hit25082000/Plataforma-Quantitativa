# Plano - Travamento de Times & Trades / "SEM ATUALIZACAO"

## Diagnostico observado
- O engine esta recebendo trades em tempo real: `events(trade)` continua subindo e `realtime_trades_received` acompanha o fluxo.
- As filas internas do engine estao saudaveis no momento observado: `q_trade=0`, `q_normal` baixo e `trade_latency_ms(avg)` perto de poucos ms.
- O `/health` do distributor nao respondeu dentro de 5s em tentativas repetidas.
- Ha conexoes `CLOSE_WAIT` na porta `8000`, indicando que o distributor ficou preso ou atrasado para drenar/fechar conexoes.
- Logs anteriores do mesmo pipeline mostram backlog alto no distributor, drops de DOM e resgate de mensagens trade-like.

## Hipotese principal
O app Tauri inicia o leitor SHM antes do engine existir. Se o mapeamento `Local\PQMarketDataV1` ainda nao existe, `shared_memory_ipc::start_reader` emite fallback para WebSocket e encerra a thread. Quando o engine sobe depois, o leitor SHM nao tenta reconectar.

Resultado: a UI passa a depender do distributor/WebSocket para trades. Sob carga, o distributor fica saturado e o frontend deixa de receber trades, causando `SEM ATUALIZACAO: SEM NEGOCIOS RECENTES`, mesmo com o Profit recebendo Times & Trades.

## Plano de correcao
1. Alterar `app/src-tauri/src/shared_memory_ipc.rs` para manter o leitor SHM vivo quando o mapping ainda nao existir.
2. Implementar retry com backoff curto ate o mapping aparecer, sem emitir fallback definitivo no primeiro `mapping_not_found`.
3. Emitir `pq:ipc-transport` como `shm` assim que o mapping for aberto com header valido, fechando o WebSocket principal no frontend como ja ocorre hoje.
4. Se o mapping ficar invalido ou o engine reiniciar, reabrir o mapping em loop em vez de encerrar permanentemente.
5. Reduzir risco no distributor movendo a classificacao/drop de mensagens para fora do event loop ou limitando callbacks `call_soon_threadsafe` sob pressao, para o `/health` continuar respondendo durante rajadas.

## Validacao
- Iniciar app sem engine, depois iniciar engine pelas Configuracoes.
- Confirmar no frontend que o transporte troca para `shm`.
- Confirmar que `lastMarketEventTs` segue atualizando enquanto `events(trade)` sobe.
- Confirmar que `/health` responde em menos de 1s durante fluxo.
- Confirmar ausencia de `SEM ATUALIZACAO: SEM NEGOCIOS RECENTES` durante trades ativos no Profit.

## Ordem sugerida
1. Corrigir retry/reconexao SHM no Tauri.
2. Validar fluxo real com Profit.
3. Em seguida, tratar saturacao do distributor como melhoria separada se o `/health` continuar instavel.
