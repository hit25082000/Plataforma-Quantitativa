# Tarefas - VP Sato + OCR Overlay no grafico do Profit

Fonte: `C:\Users\luiz.domingues\Downloads\plano_vp_ocr_overlay_profit.md`
Data: 2026-04-27
Status: Em implementacao (continuacao 2026-04-29)
Conclusao estimada atual: ~93%

Continuacao 2026-04-27: `vp_ocr_enrich.enrich_vp_overlay_payload` (health OCR + bloco `axis`), broadcast/to_thread no router; snapshot inicial `/ws/vp-overlay`, `/api/vp-overlay/last` e debug enriquecidos; `health.last_trade_age_ms` no consolidador; metrica `vp_overlay_client_queue_dropped` no ConnectionManager e `/health`; `debug_state.last_overlay_publish_age_sec`.

Continuacao 2026-04-28 (overlay Tauri): HUD VP — selector **Período VP (engine)** (`day` / `week` / `manual`) via `set_vp_period` + `vp_period` em `read_config`; bloco **Saude / OCR** com `health` do stream `vp_overlay` (`data_status`, `ocr_confidence`, `axis_stale_ms`, `last_trade_age_ms`); linha de debug **ov commit ms / Hz** no `StatusBadge` (intervalo entre commits React do overlay).

Continuacao 2026-04-28 (frontend store): `vp_overlay` agora tambem entra no store compartilhado do frontend via `useWebSocket`, para debug/UI reaproveitarem o payload consolidado sem depender apenas da janela dedicada.
Continuacao 2026-04-28 (frontend store cleanup): `clearMarketData()` tambem limpa `vpOverlay` e `overlayLastUpdateTs`, evitando snapshot velho ao trocar de ativo.
Continuacao 2026-04-29 (settings cap): o painel de configuracao do overlay passou a aceitar `max_visible_histogram_levels` ate 2000, alinhado ao renderer e ao contrato do `vp_overlay`.
Continuacao 2026-04-29 (QA visual): o overlay passou a expor um indicador de alinhamento `align Npx` no `StatusBadge`, e o smoke `scripts/check_vp_sato_overlay.py` passou a registrar `vp_alignment_ok` como parte do gate do overlay.

Validado em 2026-04-29: `rtk python -m unittest distributor.tests.test_vp_overlay_consolidator distributor.tests.test_vp_ocr_enrich distributor.tests.test_message_router_vp_tape distributor.tests.test_websocket_vp_tape_endpoints distributor.tests.test_message_router_ui_aggregator distributor.tests.test_websocket_vp_overlay_endpoints distributor.tests.test_vp_overlay_contract` OK; `rtk npm run build --prefix frontend` OK.
Validado em 2026-04-29: `python scripts/check_vp_sato_overlay.py --json` permaneceu coerente no ramo overlay/demonstrativo e agora reporta `vp_alignment_ok`; a ausência do OCR ao vivo neste momento mantém o check geral dependente do serviço externo, mas o frontend/build ficaram verdes.
Validado em 2026-04-28: `VpOverlayConsolidator.debug_state()` passou a expor `last_trade_age_ms`, `ocr_confidence` e `data_status` do último payload para debug/telemetria.
Validado em 2026-04-28: o overlay Tauri já expõe selector de `vp_period` (`day|week|manual`), bloco `Saude / OCR` e linha de debug `ov commit ms / Hz` no `StatusBadge`.
Validado em 2026-04-28: `rtk python -m unittest distributor.tests.test_vp_overlay_consolidator distributor.tests.test_vp_ocr_enrich distributor.tests.test_message_router_vp_tape distributor.tests.test_websocket_vp_tape_endpoints distributor.tests.test_message_router_ui_aggregator` OK; `rtk npm run build --prefix frontend` OK.
Validado em 2026-04-28: o payload `vp_overlay` também ficou disponível no store/frontend compartilhado.
Validado em 2026-04-28: `clearMarketData()` tambem limpa `vpOverlay` e `overlayLastUpdateTs`, evitando snapshot velho ao trocar de ativo.
Validado em 2026-04-28: `distributor.tests.test_vp_overlay_contract` cobre schema `docs/contracts/vp-overlay-v1.json` e fixture `docs/contracts/fixtures/vp-overlay-demo.json`.
Validado em 2026-04-28: `VpOverlayConsolidator` passou a ignorar campos volateis de health no hash de identidade, preservando coalescing idempotente.
Validado em 2026-04-28: `distributor.tests.test_websocket_vp_overlay_endpoints` cobre `/api/vp-overlay/debug`, `/api/vp-overlay/last`, `/api/vp-overlay/reset` e snapshot demo persistido.
Validado em 2026-04-28: `frontend/src/components/Settings/SettingsPanel.tsx` persiste `vp_overlay.histogram_visible` junto aos demais toggles do overlay.

## Premissas

- Destino assumido: backlog local em `docs/plans/`.
- Nenhuma implementacao deve comecar antes da aprovacao humana deste backlog.
- A Engine C++ e a fonte da verdade para VP, players, POC, VAL, VAH, absorcao e preco medio.
- OCR mapeia apenas preco para pixel; nao calcula mercado.
- Overlay apenas desenha payload pronto; nao decide ranking nem semantica de player.
- Performance e alinhamento visual sao gates de entrega, nao tarefas opcionais.
- `todos/` fica reservado para achados de review, conforme `CLAUDE.md`.

## Guardrails obrigatorios


| Area        | Regra                                                                                     |
| ----------- | ----------------------------------------------------------------------------------------- |
| Engine      | `on_trade()` deve atualizar acumuladores O(1) e nunca ordenar top players no hot path     |
| Engine      | Snapshot `vp_overlay` deve ser gerado por dirty flag, throttle ou mudanca critica         |
| Distributor | `/ws/vp-overlay` nao pode manter fila ilimitada por cliente lento                         |
| OCR         | Captura continua deve usar ROI do eixo Y, nao full-screen                                 |
| Overlay     | Render deve usar canvas/batch draw, nao centenas de componentes React por tick            |
| Exibicao    | Linha desenhada com OCR de baixa confianca deve ser ocultada ou marcada como descalibrada |
| Labels      | POC, VAL e VAH tem prioridade sobre medias de players                                     |


## Performance budget


| Camada                                | Meta de aceite                      |
| ------------------------------------- | ----------------------------------- |
| Engine `on_trade()`                   | < 100 us medio                      |
| Engine build snapshot VP/Tape/Top Avg | < 5 ms                              |
| Publicacao `vp_overlay`               | 4 a 10 Hz                           |
| OCR eixo Y                            | 2 a 8 Hz                            |
| Overlay render                        | ate 30 FPS, sob demanda             |
| Latencia dado -> overlay              | < 300 ms aceitavel                  |
| Fila WS por cliente                   | maximo 1 payload pendente           |
| CPU OCR                               | ROI do eixo Y, sem loop full-screen |


## Execution Plan

### Sprint 0: Contrato e fixtures (Sequencial)

```text
PLAN-01 -> CONTRACT-01 -> CONTRACT-02 -> FIX-01 -> FIX-02
```

### Sprint 1: Engine - semantica correta de players (Sequencial com testes por etapa)

```text
FIX-01 -> ENG-ABS-01 -> ENG-ABS-02 -> ENG-REG-01 -> ENG-HOLD-01 -> ENG-HOLD-02
```

### Sprint 2: Engine - medias, snapshot e performance (Paralelo apos semantica)

```text
ENG-HOLD-02 -> ENG-AVG-01 -> ENG-AVG-02 -> ENG-AVG-03
ENG-HOLD-02 -> ENG-PUB-01 -> ENG-PUB-02 -> ENG-PERF-01
```

### Sprint 3: Distributor - consolidacao e WebSocket dedicado

```text
CONTRACT-02 + ENG-PUB-02 -> DIST-01 -> DIST-02 -> DIST-03 -> DIST-04
DIST-02 -> DIST-DBG-01
```

### Sprint 4: OCR - mapeamento robusto preco -> pixel

```text
OCR-01 -> OCR-02 -> OCR-03 -> OCR-04 -> OCR-05
OCR-03 -> OCR-DPI-01
```

### Sprint 5: Overlay Renderer - MVP visual correto

```text
DIST-03 + OCR-04 -> OVR-01 -> OVR-02 -> OVR-03 -> OVR-04 -> OVR-05
```

### Sprint 6: Overlay avancado e configuracao

```text
OVR-05 -> OVR-AVG-01 [P]
OVR-05 -> OVR-HIST-01 [P]
OVR-05 -> UI-01 -> UI-02
```

### Sprint 7: Observabilidade, replay e QA final

```text
ENG-PERF-01 + DIST-04 + OCR-05 + OVR-HIST-01 + UI-02 -> OBS-01 -> QA-01 -> QA-02 -> QA-03 -> QA-FINAL
```

## Tarefas

### PLAN-01: Confirmar superficie atual do fluxo VP/Tape/OCR

**Prioridade**: P1 - Critico
**What**: Mapear os arquivos atuais que produzem `volume_profile`, `tape_intelligence`, OCR e overlay oficial.
**Where**: `engine/src`, `distributor`, `frontend/src`, `app/src-tauri`, `docs/plans/`
**Depends on**: None
**Reuses**: Backlogs VP Sato v1.1 e correcao v1 ja existentes em `docs/plans/`.

**Done when**:

- Arquivo oficial do overlay confirmado.
- Publisher atual de VP/Tape confirmado.
- Servico OCR atual confirmado.
- Pontos de configuracao atuais confirmados.
- Decisoes registradas neste plano antes de codificar.

**Verify**:

- Buscar referencias de `volume_profile`, `tape_intelligence`, `profit_ocr` e overlay oficial.
- Confirmar que nao existe componente legado sendo usado como alvo de implementacao.

---

### CONTRACT-01: Congelar JSON schema `vp_overlay`

**Prioridade**: P1 - Critico
**What**: Criar contrato versionado para o payload consolidado `vp_overlay`.
**Where**: `docs/contracts/vp-overlay-v1.json`
**Depends on**: PLAN-01
**Reuses**: Contratos atuais de `volume_profile` e `tape_intelligence`.

**Done when**:

- Schema contem `type`, `version`, `symbol`, `scope`, `sequence`, `updated_at`.
- Schema contem `poc`, `val`, `vah`, `levels`, `top_player_avg_lines`, `display` e `health`.
- Schema diferencia `holder.method` entre `passive_buy_absorption` e `passive_sell_absorption`.
- Schema limita campos de exibicao para o overlay nao inferir regra de negocio.

**Verify**:

- Validar payload demo contra o schema.
- Confirmar que OCR nao aparece como fonte de dados de mercado no contrato.

---

### CONTRACT-02: Criar payload demo estatico

**Prioridade**: P1 - Critico
**What**: Criar fixture JSON de `vp_overlay` para desenhar POC/VAL/VAH, medias e histograma sem Engine aberta.
**Where**: `docs/contracts/fixtures/vp-overlay-demo.json`
**Depends on**: CONTRACT-01
**Reuses**: Exemplo de payload do plano original.

**Done when**:

- Fixture contem POC laranja, VAL/VAH vermelhas, 2+ medias de top players e `levels`.
- Fixture contem `display` com toggles principais.
- Fixture contem `health.data_status=ok`.
- Fixture usa precos e volumes consistentes para validacao visual.

**Verify**:

- Fixture valida contra `docs/contracts/vp-overlay-v1.json`.
- Overlay demo consegue desenhar sem depender de stream real.

---

### FIX-01: Criar fixtures de trades para absorcao passiva

**Prioridade**: P1 - Critico
**What**: Criar fixture deterministica para validar agressao separada de absorcao.
**Where**: `engine/tests/fixtures/vp_overlay_absorption_trades.json`
**Depends on**: CONTRACT-01
**Reuses**: Fixtures existentes de VP/T&T quando aplicavel.

**Done when**:

- Fixture contem venda agressora absorvida por comprador na regiao da VAL.
- Fixture contem compra agressora absorvida por vendedor na regiao da VAH.
- Fixture contem player dominante na POC por volume total.
- Resultado esperado esta documentado junto da fixture.

**Verify**:

- Teste automatizado consegue calcular `val_holder` por `buy_absorption`.
- Teste automatizado consegue calcular `vah_holder` por `sell_absorption`.

---

### FIX-02: Criar fixture de medias dos top players

**Prioridade**: P1 - Alto
**What**: Criar trades sinteticos com notional conhecido para medias buy/sell/total.
**Where**: `engine/tests/fixtures/vp_overlay_player_avg_trades.json`
**Depends on**: CONTRACT-01
**Reuses**: Padrao de fixtures do engine.

**Done when**:

- Fixture permite calcular `buy_avg_price` manualmente.
- Fixture permite calcular `sell_avg_price` manualmente.
- Fixture cobre filtro `min_contracts`.
- Fixture cobre limite `max_lines`.

**Verify**:

- Teste compara medias calculadas com resultado esperado.
- Teste confirma que player abaixo de `min_contracts` nao vira linha.

---

### ENG-ABS-01: Expandir `PlayerPriceStats`

**Prioridade**: P1 - Critico
**What**: Separar acumuladores de agressao e absorcao por player/preco.
**Where**: `engine/src/tape_intelligence.`* ou modulo equivalente
**Depends on**: FIX-01
**Reuses**: Estruturas atuais de T&T Intelligence.

**Done when**:

- Existem campos `buy_aggression`, `sell_aggression`, `buy_absorption`, `sell_absorption`.
- Campos de volume total e notional permanecem consistentes.
- Reset de periodo limpa todos os acumuladores novos.

**Verify**:

- Rodar teste unitario da fixture de absorcao.
- Confirmar que volume total nao duplica ao adicionar acumuladores.

---

### ENG-ABS-02: Classificar absorcao por trade

**Prioridade**: P1 - Critico
**What**: Atualizar processamento de trade para creditar agressor e passivo nos players corretos.
**Where**: `engine/src/tape_intelligence.`*
**Depends on**: ENG-ABS-01
**Reuses**: Campos `buy_agent`, `sell_agent`, `trade_type`, `qty`, `price`.

**Done when**:

- Sell aggression incrementa `sell_aggression` do vendedor.
- Sell aggression incrementa `buy_absorption` do comprador.
- Buy aggression incrementa `buy_aggression` do comprador.
- Buy aggression incrementa `sell_absorption` do vendedor.
- Tipo desconhecido nao afirma holder.

**Verify**:

- Fixture de absorcao passa.
- Teste confirma que agressor nao e usado como holder por engano.

---

### ENG-REG-01: Agregar regioes POC/VAL/VAH por ticks

**Prioridade**: P1 - Critico
**What**: Implementar agregacao por regiao configuravel ao redor dos anchors.
**Where**: `engine/src/volume_profile.`*, `engine/src/tape_intelligence.*`
**Depends on**: ENG-ABS-02
**Reuses**: `tick_size`, `poc`, `val`, `vah` atuais.

**Done when**:

- Config aceita `poc_region_ticks`, `val_region_ticks`, `vah_region_ticks`.
- Funcao retorna lista de precos da regiao sem duplicar nivel.
- Agregacao soma players em todos os ticks da regiao.
- Regiao respeita tick size do ativo.

**Verify**:

- Teste com VAL +/- 2 ticks soma corretamente.
- Teste com regiao na borda do range nao acessa nivel inexistente.

---

### ENG-HOLD-01: Calcular holders de VAL e VAH por absorcao

**Prioridade**: P1 - Critico
**What**: Selecionar `val_holder` por `buy_absorption` e `vah_holder` por `sell_absorption`.
**Where**: `engine/src/tape_intelligence.`*
**Depends on**: ENG-REG-01
**Reuses**: Rankings top players atuais, se existirem.

**Done when**:

- `val_holder` usa somente compradores passivos na regiao da VAL.
- `vah_holder` usa somente vendedores passivos na regiao da VAH.
- `poc_player` continua por maior volume total na regiao da POC.
- Payload nao usa texto "segurou" quando evidencia minima nao existe.

**Verify**:

- Fixture confirma holder correto na VAL.
- Fixture confirma holder correto na VAH.
- Fixture com volume insuficiente retorna `unconfirmed` ou baixa confianca.

---

### ENG-HOLD-02: Calcular confidence e estado `unconfirmed`

**Prioridade**: P1 - Alto
**What**: Adicionar criterio objetivo de confianca para holder.
**Where**: `engine/src/tape_intelligence.`*, config de engine/distributor
**Depends on**: ENG-HOLD-01
**Reuses**: Config padrao `holder_detection`.

**Done when**:

- Config aceita `min_absorption_contracts`.
- Config aceita `min_participation_pct`.
- Config aceita `confirmation_seconds` e `rejection_ticks`, se aplicavel ao estado atual.
- Holder abaixo do minimo sai como `unconfirmed` ou `low_confidence`.

**Verify**:

- Teste com contratos abaixo do minimo nao afirma holder.
- Teste com participacao dominante calcula confidence maior.

---

### ENG-AVG-01: Criar `PlayerSessionStats`

**Prioridade**: P1 - Alto
**What**: Adicionar acumulador por player no escopo ativo para qty e notional.
**Where**: `engine/src/tape_intelligence.`*
**Depends on**: FIX-02
**Reuses**: IDs de player ja resolvidos no publisher.

**Done when**:

- Acumula `buy_qty`, `sell_qty`, `total_qty`.
- Acumula `buy_notional`, `sell_notional`, `total_notional`.
- Mantem `last_trade_ts`.
- Reset de periodo limpa estatisticas por player.

**Verify**:

- Fixture de medias confirma acumuladores por player.
- Teste confirma ausencia de divisao por zero.

---

### ENG-AVG-02: Calcular medias buy/sell/total

**Prioridade**: P1 - Alto
**What**: Calcular preco medio por lado sem arredondamento visual prematuro.
**Where**: `engine/src/tape_intelligence.`*
**Depends on**: ENG-AVG-01
**Reuses**: `tick_size` e precos inteiros atuais.

**Done when**:

- `buy_avg_price = buy_notional / buy_qty`.
- `sell_avg_price = sell_notional / sell_qty`.
- `total_avg_price = total_notional / total_qty`.
- Saida respeita unidade de preco usada no projeto.

**Verify**:

- Teste compara medias com calculo manual da fixture.
- Teste cobre player com apenas compra ou apenas venda.

---

### ENG-AVG-03: Selecionar top player avg lines no snapshot

**Prioridade**: P1 - Alto
**What**: Gerar `top_player_avg_lines` somente durante build de snapshot.
**Where**: `engine/src/tape_intelligence.`*, publisher de payload
**Depends on**: ENG-AVG-02
**Reuses**: Config `top_player_avg`.

**Done when**:

- Suporta `top_total_volume`, `top_buy_volume`, `top_sell_volume`, `top_net_volume`.
- Respeita `max_lines`.
- Respeita `min_contracts`.
- Nao ordena todos os players a cada trade.
- Labels ficam prontos para o overlay desenhar.

**Verify**:

- Fixture confirma ordenacao por modo.
- Teste de performance confirma selecao fora do hot path.

---

### ENG-PUB-01: Implementar dirty flag e throttle de snapshot

**Prioridade**: P1 - Critico
**What**: Publicar snapshot de overlay por intervalo ou mudanca critica, nao por trade.
**Where**: publisher C++ atual de VP/Tape
**Depends on**: ENG-HOLD-02, ENG-AVG-03
**Reuses**: Debounce atual de `tape_intelligence`, se existir.

**Done when**:

- `on_trade()` apenas atualiza estado e marca dirty.
- `publish_interval_ms` controla frequencia normal.
- Mudanca de POC/VAL/VAH forca publish.
- Mudanca de holder/top avg relevante forca publish.
- Reset de periodo forca publish.

**Verify**:

- Teste de carga confirma 4 a 10 snapshots/s.
- Teste confirma publish imediato quando POC muda.

---

### ENG-PUB-02: Emitir payload base para `vp_overlay`

**Prioridade**: P1 - Critico
**What**: Publicar dados suficientes para o Distributor consolidar ou repassar `vp_overlay`.
**Where**: publisher C++ atual, ZMQ/SHM conforme fluxo existente
**Depends on**: ENG-PUB-01
**Reuses**: Payloads `volume_profile` e `tape_intelligence`.

**Done when**:

- Payload contem POC/VAL/VAH com players e labels.
- Payload contem `top_player_avg_lines`.
- Payload contem `levels` no formato leve necessario ao histograma.
- Payload contem `sequence` monotona.
- Payload valida contra o contrato ou subset esperado pelo Distributor.

**Verify**:

- Capturar payload real e validar campos obrigatorios.
- Confirmar que payload nao cresce sem limite durante sessao longa.

---

### ENG-PERF-01: Medir custo de hot path e snapshot

**Prioridade**: P1 - Gate de performance
**What**: Adicionar medicao para `on_trade()`, build snapshot, JSON dump e send.
**Where**: `engine/src`, logs/metricas existentes
**Depends on**: ENG-PUB-02
**Reuses**: Diagnosticos HFT/QPC ja existentes quando aplicavel.

**Done when**:

- Medicao de `on_trade()` disponivel.
- Medicao de build snapshot disponivel.
- Medicao de serializacao/envio disponivel.
- Percentis ou medias sao registrados em evidencia.

**Verify**:

- `on_trade()` < 100 us medio em fixture de carga.
- Build snapshot < 5 ms em fixture representativa.
- Sem ordenacao de top players no callback de trade.

---

### DIST-01: Criar `VpOverlayConsolidator`

**Prioridade**: P1 - Critico
**What**: Criar consolidator que une ultimo VP, T&T, top avg, config e OCR mapping.
**Where**: `distributor`
**Depends on**: CONTRACT-02, ENG-PUB-02
**Reuses**: `MessageRouter`, managers WebSocket e enrich OCR atuais.

**Done when**:

- Mantem cache por ticker de VP.
- Mantem cache por ticker de T&T/players.
- Mantem cache por ticker de top avg.
- Mantem ultimo axis mapping valido.
- Retorna `vp_overlay` mesmo se VP e Tape chegarem em ordem diferente.

**Verify**:

- Teste com VP antes de Tape usa ultimo Tape valido.
- Teste com Tape antes de VP usa ultimo VP valido.
- Teste sem dados minimos nao publica payload enganoso.

---

### DIST-02: Implementar throttle e mudanca critica no consolidator

**Prioridade**: P1 - Critico
**What**: Controlar frequencia de publicacao do `vp_overlay` no Distributor.
**Where**: `distributor`
**Depends on**: DIST-01
**Reuses**: Config `publish_interval_ms`.

**Done when**:

- Publicacao normal respeita 4 a 10 Hz.
- Mudanca de POC/VAL/VAH passa pelo throttle como evento critico.
- Mudanca de holder/top avg relevante publica sem atraso perceptivel.
- Payload repetido sem mudanca nao e rebroadcastado sem necessidade.

**Verify**:

- Teste unitario mede coalescing temporal.
- Teste confirma publish em mudanca de anchor.

---

### DIST-03: Criar WebSocket `/ws/vp-overlay`

**Prioridade**: P1 - Critico
**What**: Expor canal dedicado para o overlay consumir payload consolidado.
**Where**: `distributor/websocket_server.py` ou modulo equivalente
**Depends on**: DIST-02
**Reuses**: Padrao de `/ws/volume-profile` e `/ws/tape-intelligence`.

**Done when**:

- Endpoint `/ws/vp-overlay` aceita multiplos clientes.
- Novo cliente recebe ultimo snapshot valido quando disponivel.
- Canal nao depende do `/ws` principal.
- Reconnect nao perde estado consolidado.

**Verify**:

- Teste WebSocket conecta, recebe snapshot e reconecta.
- Teste confirma que `/ws` principal nao fica sobrecarregado por overlay.

---

### DIST-04: Implementar backpressure por cliente

**Prioridade**: P1 - Critico
**What**: Manter no maximo um `vp_overlay` pendente por cliente lento.
**Where**: manager WebSocket do `distributor`
**Depends on**: DIST-03
**Reuses**: Estrutura atual de clients WebSocket.

**Done when**:

- Cliente lento substitui payload pendente pelo mais recente.
- Nao ha fila ilimitada por conexao.
- Metrica de dropped/coalesced updates e registrada.
- Desconexao limpa estado do cliente.

**Verify**:

- Teste simula cliente lento e confirma fila maxima 1.
- Teste confirma contador de updates descartados.

---

### DIST-DBG-01: Criar endpoints de debug `vp-overlay`

**Prioridade**: P2 - Alto
**What**: Expor diagnostico operacional do consolidator e ultimo payload.
**Where**: `distributor`
**Depends on**: DIST-02
**Reuses**: Padroes atuais de endpoints `/api/*/status` ou `/health`.

**Done when**:

- `GET /api/vp-overlay/debug?symbol=WINFUT` retorna estado dos caches.
- `GET /api/vp-overlay/last?symbol=WINFUT` retorna ultimo payload.
- `POST /api/vp-overlay/reset` limpa estado controladamente.
- `POST /api/vp-overlay/demo` injeta fixture demo.
- Debug mostra `last_trade_age_ms`, `last_overlay_publish_age_ms`, OCR confidence e contadores visiveis.

**Verify**:

- Testes HTTP cobrem endpoints principais.
- Demo permite validar overlay sem Engine aberta.

---

### OCR-01: Confirmar contrato do axis mapping

**Prioridade**: P1 - Critico
**What**: Garantir saida OCR contendo bounds, slope/intercept, confidence e status.
**Where**: `app/src-tauri/resources/profit_ocr_service.py`, `distributor`
**Depends on**: PLAN-01
**Reuses**: Status atual do OCR.

**Done when**:

- Saida contem `chart_bounds`.
- Saida contem `price_min`, `price_max`, `slope`, `intercept`.
- Saida contem `confidence`.
- Saida contem status `ok`, `stale`, `low_confidence`, `window_not_found`, `axis_not_found` ou equivalente.

**Verify**:

- Endpoint/status atual retorna campos necessarios.
- Estado low confidence nao e tratado como OK.

---

### OCR-02: Capturar apenas ROI do eixo Y

**Prioridade**: P1 - Performance
**What**: Reduzir captura continua para eixo Y e pequenas ROIs de validacao.
**Where**: `app/src-tauri/resources/profit_ocr_service.py`
**Depends on**: OCR-01
**Reuses**: `find_profit_window` e chart bounds atuais.

**Done when**:

- Loop OCR nao usa captura full-screen continua.
- ROI do eixo Y e calculada a partir do chart bounds.
- Captura de bounds tem frequencia separada da leitura do eixo.
- Logs indicam tamanho da ROI capturada.

**Verify**:

- Medir `capture_ms` antes/depois.
- Confirmar CPU controlada com Profit aberto.

---

### OCR-03: Aplicar regressao, histerese e smoothing

**Prioridade**: P1 - Critico
**What**: Estabilizar `slope/intercept` e rejeitar outliers do eixo.
**Where**: `app/src-tauri/resources/profit_ocr_service.py`
**Depends on**: OCR-02
**Reuses**: Labels atuais do eixo.

**Done when**:

- Exige minimo de labels validos.
- Rejeita outliers de OCR.
- Calcula regressao linear com score/confidence.
- Aplica histerese em `price_min/price_max`.
- Aplica EMA no y calculado ou no mapping.

**Verify**:

- Teste/smoke com labels ruidosos nao salta linhas abruptamente.
- Mudanca real de zoom recalibra em tempo aceitavel.

---

### OCR-04: Implementar fallback para ultimo eixo valido

**Prioridade**: P1 - Exibicao correta
**What**: Usar ultimo axis mapping valido por tempo limitado e sinalizar stale.
**Where**: OCR service, distributor, overlay
**Depends on**: OCR-03
**Reuses**: Config `axis_stale_timeout_ms`, `hide_when_axis_invalid`.

**Done when**:

- Low confidence usa ultimo eixo valido por ate `axis_stale_timeout_ms`.
- Apos timeout, overlay oculta ou marca descalibrado.
- Payload informa `axis_stale_ms`.
- Overlay nao desenha linha como confiavel com eixo invalido.

**Verify**:

- Simular falha OCR e confirmar que linhas nao ficam erradas indefinidamente.
- Confirmar aviso visual quando estado estiver stale/low confidence.

---

### OCR-05: Expor botao/acao de recalibracao OCR

**Prioridade**: P2 - Alto
**What**: Disponibilizar comando operacional para forcar recalibracao do eixo.
**Where**: Tauri/distributor/UI conforme arquitetura atual
**Depends on**: OCR-04
**Reuses**: Comandos/config atuais.

**Done when**:

- Existe acao `Recalibrar OCR`.
- Acao invalida mapping atual e solicita nova leitura.
- UI mostra resultado da recalibracao.
- Falha retorna mensagem operacional clara.

**Verify**:

- Mover/zoomar Profit e acionar recalibracao.
- Confirmar linhas voltam ao Y correto.

---

### OCR-DPI-01: Validar coordenadas fisicas/logicas em DPI e multi-monitor

**Prioridade**: P1 - Gate de exibicao
**What**: Padronizar conversao de coordenadas entre captura/OCR e WebView/UI.
**Where**: `app/src-tauri/src`, OCR service, overlay
**Depends on**: OCR-03
**Reuses**: Correcoes de DPI existentes.

**Done when**:

- Captura/OCR usa coordenadas fisicas.
- Overlay/UI usa coordenadas logicas quando necessario.
- Conversao entre fisico/logico e explicita.
- Monitor secundario e scaling diferente nao deslocam linhas.

**Verify**:

- Validar DPI 100%, 125%, 150%.
- Validar Profit em monitor secundario.
- Validar janela maximizada/restaurada e movida entre monitores.

---

### OVR-01: Criar renderer canvas 2D para overlay

**Prioridade**: P1 - Critico
**What**: Criar ou adaptar renderer leve para desenhar em canvas dentro da janela overlay.
**Where**: `frontend/src` e/ou overlay Tauri oficial
**Depends on**: DIST-03, OCR-04
**Reuses**: Overlay oficial atual.

**Done when**:

- Canvas cobre chart bounds corretos.
- Render e acionado por `requestAnimationFrame`.
- React nao renderiza uma arvore por linha/barra.
- Renderer limpa e redesenha em batch.

**Verify**:

- Smoke com payload demo desenha sem travar UI.
- `render_ms` fica dentro do budget com payload demo.

---

### OVR-02: Implementar `price_to_y` no overlay

**Prioridade**: P1 - Exibicao correta
**What**: Converter preco para coordenada Y usando `slope * price + intercept`.
**Where**: renderer do overlay
**Depends on**: OVR-01
**Reuses**: Axis mapping OCR.

**Done when**:

- Preco maior aparece mais acima no canvas.
- Precos fora do range sao filtrados antes do desenho.
- Conversao considera chart bounds e DPI conforme contrato.
- Baixa confianca do OCR altera estado visual.

**Verify**:

- Fixture demo posiciona POC entre VAL e VAH corretamente.
- Teste visual confirma VAH acima da POC e VAL abaixo da POC.

---

### OVR-03: Desenhar POC/VAL/VAH do MVP

**Prioridade**: P1 - Critico
**What**: Desenhar as tres linhas principais com cores e labels corretos.
**Where**: renderer do overlay
**Depends on**: OVR-02
**Reuses**: Payload `poc`, `val`, `vah` de `vp_overlay`.

**Done when**:

- POC e linha laranja com espessura maior.
- VAL e linha vermelha.
- VAH e linha vermelha.
- Labels usam texto pronto do payload.
- Estado low confidence aparece cinza ou `nao confirmado`.

**Verify**:

- Demo local exibe tres linhas no Y esperado.
- Labels POC/VAL/VAH ficam legiveis com fundo semitransparente.

---

### OVR-04: Implementar filtro de range visivel

**Prioridade**: P1 - Performance
**What**: Ignorar linhas e levels fora de `chart_bounds`.
**Where**: renderer do overlay
**Depends on**: OVR-03
**Reuses**: `chart_bounds` do OCR.

**Done when**:

- Elementos acima de `chart_top - margem` nao sao desenhados.
- Elementos abaixo de `chart_bottom + margem` nao sao desenhados.
- Contador `visible_levels_count` existe para debug.
- Desenho nao itera trabalho visual inutil apos filtragem.

**Verify**:

- Payload com precos fora do range nao quebra render.
- Debug mostra contagem visivel menor que total quando aplicavel.

---

### OVR-05: Implementar prioridade e colisao de labels

**Prioridade**: P1 - Exibicao correta
**What**: Evitar labels ilegiveis quando linhas ficam proximas.
**Where**: renderer do overlay
**Depends on**: OVR-03
**Reuses**: Prioridade definida no plano original.

**Done when**:

- POC tem prioridade maxima.
- VAL e VAH ficam acima de medias de players.
- Label secundario pode ser deslocado.
- Label de menor prioridade pode ser ocultado.
- Labels nunca ficam empilhados ilegivelmente.

**Verify**:

- Fixture com POC/VAL/VAH proximos mantem labels principais legiveis.
- Contador `label_collisions_count` aparece no debug.

---

### OVR-AVG-01: Desenhar linhas de preco medio dos top players

**Prioridade**: P2 - Alto
**What**: Desenhar medias buy/sell/total com estilo leve e limite visual.
**Where**: renderer do overlay
**Depends on**: OVR-05, ENG-AVG-03
**Reuses**: `top_player_avg_lines` do payload.

**Done when**:

- Linhas de media usam stroke fino.
- Linhas podem ser dashed conforme payload.
- Maximo de linhas respeita `display.max_avg_lines`.
- Labels curtos sao exibidos sem poluir POC/VAL/VAH.
- Toggle desliga medias sem parar calculo.

**Verify**:

- Demo com 6 medias permanece legivel.
- Toggle remove linhas imediatamente.

---

### OVR-HIST-01: Desenhar histograma VP performatico

**Prioridade**: P2 - Alto
**What**: Desenhar barras horizontais de VP apenas para levels visiveis.
**Where**: renderer do overlay
**Depends on**: OVR-04
**Reuses**: `levels` e `display.max_histogram_width_px`.

**Done when**:

- Modo inicial `total` funciona.
- Width usa volume relativo ao maior volume visivel.
- Limita `max_visible_histogram_levels`.
- Agrupa levels quando zoom estiver denso, se necessario.
- Toggle desliga histograma sem parar stream.

**Verify**:

- Testar payload com 50, 300 e 1000 levels.
- Render permanece fluido e dentro do budget.

---

### UI-01: Criar painel de controle `VP Overlay`

**Prioridade**: P2 - Alto
**What**: Expor controles operacionais para reduzir ruido visual e calibrar.
**Where**: `frontend/src`, `app/src-tauri`, config conforme padrao atual
**Depends on**: OVR-05
**Reuses**: Settings/config store atual.

**Done when**:

- Toggle `Ativo`.
- Toggle histograma.
- Toggle POC.
- Toggle VAL/VAH.
- Toggle labels.
- Toggle medias dos top players.
- Toggle linhas esticadas.
- Controle dia atual/dia anterior/manual.
- Status OCR mostra confidence e ultimo update.

**Verify**:

- Cada toggle altera exibicao sem reiniciar app.
- Status OCR muda quando OCR fica stale/low confidence.

---

### UI-02: Persistir configuracao `vp_overlay`

**Prioridade**: P2 - Alto
**What**: Persistir preferenciais de display e thresholds operacionais.
**Where**: `config.json`, comandos Tauri/distributor
**Depends on**: UI-01
**Reuses**: `read_config`/`write_config` atuais.

**Done when**:

- Config salva `vp_overlay.enabled`.
- Config salva toggles de exibicao.
- Config salva `max_lines` e `min_contracts`.
- Config salva modo de top players.
- Config e reidratada no startup.

**Verify**:

- Alterar config pela UI, reiniciar app e confirmar persistencia.
- Confirmar que default nao polui visualmente o grafico.

---

### OBS-01: Adicionar metricas de VP Overlay

**Prioridade**: P1 - Gate operacional
**What**: Expor metricas para diagnosticar atraso, desalinhamento e excesso de render.
**Where**: Engine, Distributor, OCR, Overlay debug
**Depends on**: ENG-PERF-01, DIST-04, OCR-04, OVR-05
**Reuses**: `/health` e paineis de debug atuais.

**Done when**:

- Engine expoe trades processados, snapshot build ms e send ms.
- Distributor expoe publish count, clients, dropped updates e last age.
- OCR expoe confidence, stale ms, capture ms, ocr ms e fit ms.
- Overlay expoe render ms, FPS, visible levels/lines e label collisions.

**Verify**:

- `/health` ou debug mostra metricas principais.
- Sessao real permite identificar gargalo por camada.

---

### QA-01: Validar contrato e fixtures

**Prioridade**: P1 - Gate
**What**: Garantir que todos os payloads de demo/teste seguem o contrato.
**Where**: `docs/contracts`, testes automatizados
**Depends on**: CONTRACT-02, FIX-01, FIX-02
**Reuses**: Ferramentas de teste existentes.

**Done when**:

- Schema `vp_overlay` valida demo.
- Fixture de absorcao valida holders esperados.
- Fixture de medias valida top avg esperado.

**Verify**:

- Rodar testes de contrato/fixtures.
- Registrar comando e resultado neste arquivo.

---

### QA-02: Validar alinhamento visual OCR/Overlay

**Prioridade**: P1 - Gate de exibicao
**What**: Confirmar que POC/VAL/VAH aparecem no preco correto do Profit.
**Where**: Profit real, OCR, overlay
**Depends on**: OCR-DPI-01, OVR-03
**Reuses**: Payload demo e stream real.

**Done when**:

- POC alinha no eixo do Profit.
- VAL alinha no eixo do Profit.
- VAH alinha no eixo do Profit.
- Zoom/escala recalibra sem travar.
- OCR low confidence nao deixa linha errada como confiavel.

**Verify**:

- Registrar prints/video em DPI 100%, 125%, 150%.
- Registrar teste com Profit movido/redimensionado.

---

### QA-03: Validar performance em fluxo real ou replay

**Prioridade**: P1 - Gate de performance
**What**: Executar sessao longa ou replay para confirmar ausencia de freeze/fila crescente.
**Where**: scripts de evidencia, Engine, Distributor, OCR, Overlay
**Depends on**: OBS-01, OVR-HIST-01
**Reuses**: Evidenciadores existentes quando aplicavel.

**Done when**:

- Engine nao serializa payload pesado por trade.
- `/ws/vp-overlay` fica entre 4 e 10 Hz em fluxo normal.
- Cliente lento nao cria fila crescente.
- Overlay render permanece responsivo.
- OCR nao usa CPU excessiva por captura full-screen.

**Verify**:

- Rodar replay deterministico ou sessao real de pelo menos 30 min.
- Registrar CPU, latencia, FPS, dropped updates e memoria.

---

### QA-FINAL: Validacao final antes da entrega ao cliente

**Prioridade**: P1 - Gate de entrega
**What**: Executar checklist completo do plano antes de declarar a feature pronta.
**Where**: evidencias locais, Profit real, Engine, Distributor, OCR, Overlay
**Depends on**: QA-01, QA-02, QA-03, UI-02, DIST-DBG-01, OCR-05
**Reuses**: Definition of Done do plano original.

**Done when**:

- VP aparece no grafico do Profit via overlay.
- POC aparece em laranja no preco correto.
- VAL e VAH aparecem em vermelho no preco correto.
- POC mostra player dominante e contratos.
- VAL mostra quem segurou fundo usando absorcao passiva.
- VAH mostra quem segurou alta usando absorcao passiva.
- Linhas de preco medio dos top players aparecem sem poluir.
- Usuario consegue limitar medias e desligar histograma/labels.
- OCR recalibra com zoom, escala e movimento do Profit.
- OCR sem confianca oculta ou marca overlay descalibrado.
- Engine, Distributor e Overlay continuam responsivos em sessao real.
- Replay confirma numeros contra T&T/Profit.

**Verify**:

- Consolidar evidencias de contrato, replay, performance e prints/video.
- Atualizar status deste backlog com porcentagem real.

## Dependencias


| Tarefa      | Depende de                                      |
| ----------- | ----------------------------------------------- |
| CONTRACT-01 | PLAN-01                                         |
| CONTRACT-02 | CONTRACT-01                                     |
| FIX-01      | CONTRACT-01                                     |
| FIX-02      | CONTRACT-01                                     |
| ENG-ABS-01  | FIX-01                                          |
| ENG-ABS-02  | ENG-ABS-01                                      |
| ENG-REG-01  | ENG-ABS-02                                      |
| ENG-HOLD-01 | ENG-REG-01                                      |
| ENG-HOLD-02 | ENG-HOLD-01                                     |
| ENG-AVG-01  | FIX-02                                          |
| ENG-AVG-02  | ENG-AVG-01                                      |
| ENG-AVG-03  | ENG-AVG-02                                      |
| ENG-PUB-01  | ENG-HOLD-02, ENG-AVG-03                         |
| ENG-PUB-02  | ENG-PUB-01                                      |
| ENG-PERF-01 | ENG-PUB-02                                      |
| DIST-01     | CONTRACT-02, ENG-PUB-02                         |
| DIST-02     | DIST-01                                         |
| DIST-03     | DIST-02                                         |
| DIST-04     | DIST-03                                         |
| DIST-DBG-01 | DIST-02                                         |
| OCR-02      | OCR-01                                          |
| OCR-03      | OCR-02                                          |
| OCR-04      | OCR-03                                          |
| OCR-05      | OCR-04                                          |
| OCR-DPI-01  | OCR-03                                          |
| OVR-01      | DIST-03, OCR-04                                 |
| OVR-02      | OVR-01                                          |
| OVR-03      | OVR-02                                          |
| OVR-04      | OVR-03                                          |
| OVR-05      | OVR-03                                          |
| OVR-AVG-01  | OVR-05, ENG-AVG-03                              |
| OVR-HIST-01 | OVR-04                                          |
| UI-01       | OVR-05                                          |
| UI-02       | UI-01                                           |
| OBS-01      | ENG-PERF-01, DIST-04, OCR-04, OVR-05            |
| QA-01       | CONTRACT-02, FIX-01, FIX-02                     |
| QA-02       | OCR-DPI-01, OVR-03                              |
| QA-03       | OBS-01, OVR-HIST-01                             |
| QA-FINAL    | QA-01, QA-02, QA-03, UI-02, DIST-DBG-01, OCR-05 |


## Gates de aprovacao


| Gate                        | Condicao                                                   |
| --------------------------- | ---------------------------------------------------------- |
| G0 - Backlog                | Tarefas aprovadas por humano                               |
| G1 - Contrato               | CONTRACT-01, CONTRACT-02, FIX-01, FIX-02 e QA-01 aprovados |
| G2 - Engine correta         | ENG-ABS, ENG-REG, ENG-HOLD, ENG-AVG e ENG-PUB aprovados    |
| G3 - Performance Engine     | ENG-PERF-01 dentro do budget                               |
| G4 - Distributor resiliente | DIST-01 a DIST-04 aprovados sem fila crescente             |
| G5 - OCR confiavel          | OCR-01 a OCR-DPI-01 aprovados em DPI/multi-monitor         |
| G6 - MVP visual             | OVR-01 a OVR-05 e QA-02 aprovados                          |
| G7 - Visual completo        | OVR-AVG-01, OVR-HIST-01, UI-01 e UI-02 aprovados           |
| G8 - Operacional            | OBS-01 e QA-03 aprovados em replay/sessao real             |
| G9 - Entrega                | QA-FINAL aprovado com evidencias                           |


## Ordem sugerida de execucao

1. Aprovar este backlog.
2. Congelar contrato e fixtures antes de mexer no engine.
3. Corrigir semantica de agressao vs absorcao.
4. Implementar medias dos top players fora do hot path.
5. Implementar dirty flag, throttle e metricas do engine.
6. Criar `VpOverlayConsolidator` e `/ws/vp-overlay` com coalescing.
7. Fortalecer OCR com ROI, confidence, fallback e DPI.
8. Criar renderer canvas com POC/VAL/VAH primeiro.
9. Adicionar medias, histograma e controles de UI.
10. Rodar contrato, replay, DPI, performance e QA final.

## Pergunta obrigatoria antes da execucao

Antes de implementar, confirmar com o humano:

```text
Para cada fase/tarefa, quais ferramentas devo usar?

MCPs disponiveis no projeto:
- cursor-app-control
- cursor-ide-browser
- plugin-stripe-stripe
- plugin-supabase-supabase
- plugin-vercel-vercel

Skills relevantes disponiveis:
- tlc-spec-driven
- observabilidade_tempo_real
- playwright-skill
```

## Regra de retorno

SEMPRE RETORNE AO LER ESTE ARQUIVO A PORCENTAGEM DE PROGRESSO JA FEITO.
