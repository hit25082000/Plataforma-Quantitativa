# Plano — UI Snapshot Aggregator no Distributor (anti-travamento)

## Objetivo
Reduzir travamento sob mercado ativo limitando taxa de atualização visual no `/ws` sem perder eventos críticos.

## Escopo
- Camada `distributor` apenas.
- Agregação/throttle para mensagens de mercado visuais no `MessageRouter`.
- Sem alterar protocolo da engine C++ neste ciclo.

## Estratégia
1. **Configurar taxa de snapshot UI**
   - Adicionar `UI_SNAPSHOT_INTERVAL_MS` no `distributor/config.py` (default `50` ms, ~20 FPS).

2. **Criar agregador no `MessageRouter`**
   - Manter um buffer de “último estado visual” por tipo de mensagem descartável (`dom_snapshot`, `daily`, e demais market não críticos).
   - Implementar flush por janela (`UI_SNAPSHOT_INTERVAL_MS`) enviando apenas o snapshot mais novo para `/ws`.
   - Preservar envio imediato para:
     - `topic=alert`
     - `type in (trade, flow_inversion, volume_profile, tape_intelligence, broker_snapshot, macd_signal, agent007_state, sync)`

3. **Garantir semântica de descarte**
   - Se chegar novo snapshot dentro da janela, substituir o anterior (latest-wins).
   - Nunca crescer fila interna de agregação (estado único por chave/tipo).

4. **Observabilidade mínima**
   - Expor contadores no `MessageRouter.metrics()`:
     - `ui_aggregated_count`
     - `ui_flushed_count`
     - `ui_replaced_count`
   - Incluir no log periódico do router.

5. **Testes**
   - Criar/ajustar testes em `distributor/tests/` validando:
     - `dom_snapshot` em alta frequência resulta em 1 envio por janela.
     - alertas continuam imediatos.
     - `volume_profile` e `tape_intelligence` continuam dedicados e sem atraso.

6. **Validação**
   - Rodar suíte focal:
     - `python -m pytest distributor/tests/test_message_router_vp_tape.py`
     - novo teste do agregador.
   - Rodar `ReadLints` nos arquivos alterados.

## Critérios de aceite
- Em burst de `dom_snapshot`, o número de frames enviados no `/ws` cai para taxa máxima configurada.
- Nenhum atraso introduzido para alertas e eventos críticos.
- Testes focalizados verdes.
