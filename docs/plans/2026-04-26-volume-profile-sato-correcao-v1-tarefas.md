# Tarefas - Correcao VP Sato v1

Fonte: `Plano_Correcao_VP_Sato_v1.docx`
Data: 2026-04-26
Status: implementacao de codigo concluida; QA operacional (QA-P1, QA-FALLBACK, QA-FINAL) pendente
Conclusao estimada atual: 93% (automatizado OK; restante = evidencias com app/Profit)

## Andamento

- BUG-01, BUG-02, BUG-03, INC-01, BUG-04, BUG-05, BUG-06, INC-02, DIV-01 e DIV-02 estao implementados ou resolvidos na arvore atual.
- `engine/tests/trade_reconciler_tests.cpp` + alvo CMake `trade_reconciler_tests` cobrem limite e reentrada de chave apos poda (BUG-06).
- Verificacao local 2026-04-26: `volume_profile_tests` + `trade_reconciler_tests` passam; `frontend` `npm run typecheck` e `npm run build` passam.
- BUG-03: trade com tipo desconhecido deixa de criar entrada vazia em `levels_` (payload sem nivel fantasma).
- QA-P1, QA-FALLBACK e QA-FINAL seguem pendentes por dependerem de validacao operacional com app, Profit/OCR e evidencias locais.
- `ProfitOverlayView.tsx` nao existe mais em `frontend/src/components/Overlay`; o overlay oficial e `OverlayPage.tsx`.
- `player_name` e `player_id` sao enriquecidos no publisher via cache `agent_name_cache_`, antes do payload chegar ao frontend.
- INC-02: `write_config` aceita `vp_fallback_price_top_clear` / `vp_fallback_price_bot_clear` para apagar precos do JSON; apos persistir, o backend emite `pq:config-saved` para todas as janelas Tauri; `OverlayPage` escuta com `listen` (nao depende de `window` entre janelas).
- Verificacao local agregada: `scripts/verify-vp-sato-correcao-v1.ps1` (engine `volume_profile_tests` + `trade_reconciler_tests`, `cargo build` em `app/src-tauri`, `npm run typecheck` e `npm run build` no `frontend`).
- 2026-04-26 (re-run): `volume_profile_tests` + `trade_reconciler_tests` + `cargo build` (src-tauri) + `npm run typecheck`/`build` (frontend) passaram; QA manual inalterada.
- Verificacao: na raiz do repo, `npm run verify:vp-sato` (equivale a `scripts/verify-vp-sato-correcao-v1.ps1`); requer `engine\\build\\Debug\\volume_profile_tests.exe` e `trade_reconciler_tests.exe` ja compilados.

## Verificacao automatizada (parcial)

| Cobertura | Como |
| --- | --- |
| BUG-03 (tipo 0, somas) | `volume_profile_tests` (`test_unknown_trade_type_does_not_accumulate`) |
| BUG-04 (POC/VAL/VAH) | `test_value_area_asymmetric_regression`, `test_value_area_price_ordering_multi_levels` |
| BUG-06 (limite `seen_`, reentrada) | `trade_reconciler_tests` |
| QA-FINAL item build | `verify-vp-sato-correcao-v1.ps1` (sem app em runtime) |

## Premissas

- Destino assumido: backlog local em `docs/plans/`.
- Este arquivo converte o plano de correcao em tarefas executaveis e verificaveis.
- Nenhuma implementacao deve comecar antes da aprovacao humana deste backlog.
- Itens P1 bloqueiam demonstracao ao cliente.
- `todos/` fica reservado para achados de review, conforme `CLAUDE.md`.

## Execution Plan

### Sprint 1: Bloqueadores P1 (Sequencial com paralelismo limitado)

```text
BUG-01 -> BUG-02 -> QA-P1
BUG-03 -> INC-01 -> QA-P1
```

### Sprint 2: Qualidade P2

```text
BUG-04 [P]
BUG-05 [P] -> DIV-02
BUG-06 [P]
```

### Sprint 3: Funcionalidade incompleta P2

```text
BUG-02 -> INC-02 -> QA-FALLBACK
```

### Sprint 4: Divida tecnica e documentacao P3

```text
INC-01 -> DIV-01
BUG-05 -> DIV-02
```

## Tarefas

### BUG-01: Manter VP e T&T conectados em modo SHM

**Prioridade**: P1 - Critico
**What**: Ajustar `useWebSocket` para abrir `/ws/volume-profile` e `/ws/tape-intelligence` sempre, independente de `IPC_MODE=shm`.
**Where**: `frontend/src/hooks/useWebSocket.ts`
**Depends on**: None
**Reuses**: Fluxo atual de `connectVp()`, `connectTape()` e `connect()`.

**Done when**:

- [x] `connectVp()` roda fora da condicional de SHM.
- [x] `connectTape()` roda fora da condicional de SHM.
- [x] Apenas a conexao principal de trades `/ws` fica condicional ao transporte SHM.
- [x] Nenhuma conexao duplicada e criada em modo nao-SHM.

**Verify**:

- [ ] Iniciar app com `IPC_MODE=shm`.
- [ ] Confirmar no DevTools que `/ws/volume-profile` esta aberto.
- [ ] Confirmar no DevTools que `/ws/tape-intelligence` esta aberto.
- [ ] Confirmar que VP exibe dados apos o primeiro trade.

---

### BUG-02: Tornar falha de OCR visivel e reduzir fallback silencioso

**Prioridade**: P1 - Critico
**What**: Aumentar tolerancia do OCR, registrar falhas estruturadas e exibir alerta visual claro quando o overlay operar em fallback.
**Where**: `distributor/vp_ocr_enrich.py`, `frontend/src/pages/OverlayPage.tsx`
**Depends on**: None
**Reuses**: Status atual do OCR, `axis_labels`, `axis_diagnostics`, `chart_rect` e indicador de fallback ja exibido no header.

**Done when**:

- [x] Timeout de consulta ao OCR sobe de `0.2s` para `0.8s`.
- [x] Falhas do OCR geram log com `chart_rect`, labels lidos e `axis_diagnostics`.
- [x] UI mostra aviso visual vermelho claro quando fallback estiver ativo.
- [x] Fallback manual depende de configuracao explicita, como `vp_fallback_mode`.
- [x] Atualizacao continua de posicao fica bloqueada ou estabilizada durante fallback para evitar deriva.

**Verify**:

- [ ] Desligar OCR e confirmar log com causa da falha.
- [ ] Confirmar alerta visual de fallback ativo no overlay.
- [ ] Com OCR ativo, mover janela do Profit e confirmar alinhamento do histograma.
- [ ] Confirmar no `/status` que `axis_labels >= 2` no cenario normal.

---

### BUG-03: Ignorar tipo de trade desconhecido no VP

**Prioridade**: P1 - Critico
**What**: Trocar o `else` generico por classificacao explicita de compra e venda no acumulador do Volume Profile.
**Where**: `engine/src/volume_profile.cpp`
**Depends on**: None
**Reuses**: Constantes existentes de `TRADE_TYPE_BUY_AGGRESSION` e `TRADE_TYPE_SELL_AGGRESSION`.

**Done when**:

- [x] `BUY_AGGRESSION` incrementa somente `bid_vol`.
- [x] `SELL_AGGRESSION` incrementa somente `ask_vol`.
- [x] Tipos desconhecidos nao incrementam `bid_vol` nem `ask_vol`.
- [x] Tipo desconhecido gera log de debug ou diagnostico equivalente.

**Verify**:

- [ ] Injetar trade de tipo `0` via fixture.
- [ ] Confirmar que `bid_vol` e `ask_vol` nao aumentam com tipo desconhecido.
- [ ] Confirmar que `sum(bid_vol + ask_vol) <= total_vol`.
- [ ] Rodar fixture existente de VP/T&T e comparar volumes antes/depois.

---

### INC-01: Resolver nome legivel da corretora nos badges T&T

**Prioridade**: P1 - Critico
**What**: Resolver `player_name` a partir do ID de agente e publicar nome legivel no payload `tape_intelligence`.
**Where**: `engine/src/tape_intelligence.cpp`, `frontend/src/pages/OverlayPage.tsx`, `docs/contracts/*`
**Depends on**: BUG-03
**Reuses**: Campos atuais `buy_agent`, `sell_agent`, payload `tape_intelligence` e funcoes da ProfitDLL para nome de agente.

**Done when**:

- [x] Publisher possui cache `agent_name_cache_` aplicado ao payload `tape_intelligence`.
- [x] Primeira ocorrencia de um agente resolve nome via bridge da ProfitDLL.
- [x] Payload inclui `player_id` e `player_name`.
- [x] Frontend exibe `player_name` quando disponivel.
- [x] Frontend usa fallback `ID:XXXXX` quando nome vier vazio.
- [x] Contrato JSON/documentacao reflete `player_name`.

**Verify**:

- [ ] Confirmar payload ZMQ com `player_name` nao vazio em mercado aberto.
- [ ] Confirmar badges exibindo nomes como corretoras em vez de `0` ou ID cru.
- [ ] Rodar por 30 min e verificar tamanho estavel do cache.
- [ ] Simular nome vazio e confirmar fallback `ID:XXXXX`.

---

### QA-P1: Validar entrega minima dos bloqueadores

**Prioridade**: P1 - Critico
**What**: Executar validacao integrada dos quatro bloqueadores de Sprint 1.
**Where**: `docs/plans/`, evidencias locais de QA
**Depends on**: BUG-01, BUG-02, BUG-03, INC-01
**Reuses**: Checklist final do plano.

**Done when**:

- [ ] VP e T&T carregam dados em modo SHM.
- [ ] OCR funciona em modo automatico sem fallback em tela padrao.
- [ ] Fallback exibe aviso visual claro.
- [ ] `bid_vol + ask_vol <= total_vol` em todos os niveis testados.
- [ ] Badges exibem nome legivel da corretora.

**Verify**:

- [ ] Registrar evidencias de rede, overlay e payload.
- [ ] Comparar badges com Times & Trades do Profit.
- [ ] Registrar resultado no plano antes de demonstrar ao cliente.

---

### BUG-04: Corrigir expansao alternada da Value Area

**Prioridade**: P2 - Alto
**What**: Ajustar `compute_value_area()` para alternar expansao cima/baixo e preservar `VAL <= POC <= VAH`.
**Where**: `engine/src/volume_profile.cpp`
**Depends on**: BUG-03
**Reuses**: Testes e fixtures existentes do Volume Profile.

**Done when**:

- [x] Loop usa flag `expand_up` alternando a cada iteracao.
- [x] Quando um lado esgota, algoritmo continua pelo lado disponivel.
- [x] Retorno usa `min/max` para evitar inversao de `VAL` e `VAH`.
- [x] Teste de regressao cobre distribuicao assimetrica conhecida (`test_value_area_asymmetric_regression` em `engine/tests/volume_profile_tests.cpp`).

**Verify**:

- [ ] Criar fixture sintetica com volumes conhecidos.
- [ ] Comparar `poc`, `vah` e `val` com calculo manual.
- [ ] Confirmar `vah > poc > val` quando houver niveis suficientes.

---

### BUG-05: Corrigir ou remover canvas legado com Y invertido

**Prioridade**: P2 - Alto
**What**: Tomar decisao arquitetural sobre `ProfitOverlayView.tsx`: deletar se estiver orfao ou corrigir `lineY()` se for mantido.
**Where**: `frontend/src/components/Overlay/ProfitOverlayView.tsx`
**Depends on**: None
**Reuses**: `OverlayPage.tsx` como componente oficial.

**Done when**:

- [x] Confirmado se existe import, rota ou lazy load ativo para `ProfitOverlayView.tsx`.
- [x] Se orfao, arquivo removido.
- [x] Se mantido, `lineY()` usa convencao correta de canvas: preco maior gera Y menor.
- [x] Comentario curto documenta que Y cresce para baixo no canvas.

**Verify**:

- [ ] Se removido, build completo nao reporta import quebrado.
- [ ] Se mantido, VAH renderiza acima da POC e VAL abaixo da POC.

---

### BUG-06: Limitar crescimento de memoria do TradeReconciler

**Prioridade**: P2 - Alto
**What**: Adicionar poda ao mapa `seen_` para impedir crescimento indefinido durante sessoes longas.
**Where**: `engine/src/trade_reconciler.cpp`
**Depends on**: None
**Reuses**: Estrutura atual de deduplicacao de trades.

**Done when**:

- [x] Definido limite `kMaxSeen` ou equivalente.
- [x] `seen_` remove entradas antigas ao atingir o limite.
- [x] Duplicatas recentes continuam rejeitadas apos poda.
- [x] Diagnostico expoe tamanho atual de `seen_` quando aplicavel.

**Verify**:

- [x] Simular 100k+ trades sequenciais (teste `trade_reconciler_tests`).
- [x] Confirmar que `seen_` nao excede o limite definido.
- [ ] Confirmar que memoria do `engine.exe` estabiliza.
- [ ] Confirmar que deduplicacao segue funcionando apos poda.

---

### INC-02: Criar UI para calibracao manual de fallback

**Prioridade**: P2 - Medio
**What**: Expor configuracao manual de `vp_fallback_price_top` e `vp_fallback_price_bot` na interface.
**Where**: `distributor/profit_ocr_service.py`, `app/src-tauri/src/commands.rs`, `frontend`
**Depends on**: BUG-02
**Reuses**: `config.json`, comandos `read_config`/`write_config` e fluxo atual de sincronizacao com distributor.

**Done when**:

- [x] Painel de configuracoes possui secao `Calibracao Manual`.
- [x] UI possui campos numericos para `Preco Topo` e `Preco Base`.
- [x] Botao `Salvar` persiste valores no `config.json`.
- [x] Valores ativos aparecem na UI quando fallback estiver ativo.
- [x] Reinicio da aplicacao preserva valores.

**Verify**:

- [ ] Desligar OCR e confirmar que modo fallback e detectado.
- [ ] Informar precos manuais e confirmar alinhamento do histograma.
- [ ] Reiniciar app e confirmar persistencia no `config.json`.

---

### QA-FALLBACK: Validar fluxo completo de fallback manual

**Prioridade**: P2 - Medio
**What**: Validar experiencia operacional quando o OCR falha e o operador usa calibracao manual.
**Where**: Overlay, distributor e `config.json`
**Depends on**: BUG-02, INC-02
**Reuses**: Checklist final do plano.

**Done when**:

- [ ] Fallback automatico silencioso nao mascara desalinhamento.
- [ ] Operador consegue configurar topo/base pela UI.
- [ ] Overlay informa claramente que esta em fallback.
- [ ] Histograma permanece alinhado apos aplicar calibracao.

**Verify**:

- [ ] Testar com OCR desligado.
- [ ] Testar com Profit movido/redimensionado.
- [ ] Testar restart da aplicacao.
- [ ] Registrar evidencia visual.

---

### DIV-01: Padronizar documentacao para `volume_profile`

**Prioridade**: P3 - Baixo
**What**: Atualizar documentacao e contratos para usar `volume_profile` como nome canonico do topico/payload.
**Where**: `docs/plans/*`, `docs/contracts/*`, PRD v1.1, `docs/PORTS.md`
**Depends on**: INC-01
**Reuses**: Nome ja usado no codigo.

**Done when**:

- [x] Docs nao tratam `vp_profile` como topico ZMQ ativo.
- [x] Contratos usam `volume_profile`.
- [x] `docs/PORTS.md` lista o topico correto.
- [x] Referencias historicas, se mantidas, deixam claro que `vp_profile` e nome antigo.

**Verify**:

- [x] Buscar `vp_profile` nos docs e confirmar que nao aparece como nome canonico de topico.
- [x] Buscar `volume_profile` e confirmar consistencia entre docs e codigo.

---

### DIV-02: Remover ou registrar dependencia Tauri legada

**Prioridade**: P3 - Baixo
**What**: Resolver referencia a `get_overlay_calibration` em componente legado.
**Where**: `frontend/src/components/Overlay/ProfitOverlayView.tsx`, `app/src-tauri/src/commands.rs`
**Depends on**: BUG-05
**Reuses**: Decisao tomada em BUG-05.

**Done when**:

- [x] Se `ProfitOverlayView.tsx` foi removido, nao resta chamada a `get_overlay_calibration`.
- [x] Se componente foi mantido, comando Tauri esta registrado e testado.
- [x] Build completo nao falha por import ou invoke inexistente.

**Verify**:

- [x] Rodar busca por `get_overlay_calibration`.
- [x] Rodar build do frontend/Tauri conforme comando padrao do projeto.
- [ ] Confirmar overlay oficial funcionando via `OverlayPage.tsx`.

---

### QA-FINAL: Validacao final antes da entrega

**Prioridade**: P1 - Gate de entrega
**What**: Executar checklist completo de validacao do plano antes de declarar a entrega pronta.
**Where**: Evidencias locais, overlay, engine, distributor e documentacao
**Depends on**: QA-P1, BUG-04, BUG-05, BUG-06, QA-FALLBACK, DIV-01, DIV-02
**Reuses**: Checklist final do `Plano_Correcao_VP_Sato_v1.docx`.

**Done when**:

- [ ] VP e T&T funcionam em modo SHM.
- [ ] OCR automatico funciona em tela padrao.
- [ ] Fallback mostra aviso claro.
- [ ] Badges exibem corretora legivel.
- [ ] Memoria do `engine.exe` fica estavel em sessao longa.
- [ ] Calibracao manual funciona e persiste.
- [ ] CPU do overlay fica abaixo de 3% em idle com mercado aberto.
- [ ] Alinhamento validado em DPI 100%, 125% e 150%.
- [ ] Build completo passa sem erros.

**Verify**:

- [ ] Registrar evidencias de rede, payload, overlay e memoria.
- [ ] Validar badges POC, FUNDO e TOPO com mercado real.
- [ ] Consolidar resultado no documento de entrega.

## Dependencias

| Tarefa | Depende de |
| --- | --- |
| INC-01 | BUG-03 |
| QA-P1 | BUG-01, BUG-02, BUG-03, INC-01 |
| BUG-04 | BUG-03 |
| INC-02 | BUG-02 |
| QA-FALLBACK | BUG-02, INC-02 |
| DIV-01 | INC-01 |
| DIV-02 | BUG-05 |
| QA-FINAL | QA-P1, BUG-04, BUG-05, BUG-06, QA-FALLBACK, DIV-01, DIV-02 |

## Gates de aprovacao

| Gate | Condicao |
| --- | --- |
| G0 - Backlog | Tarefas aprovadas por humano |
| G1 - P1 | BUG-01, BUG-02, BUG-03, INC-01 e QA-P1 concluidos |
| G2 - P2 Calculo/Robustez | BUG-04, BUG-05 e BUG-06 concluidos |
| G3 - Fallback Manual | INC-02 e QA-FALLBACK concluidos |
| G4 - Limpeza/Docs | DIV-01 e DIV-02 concluidos |
| G5 - Entrega | QA-FINAL aprovado com evidencias |

## Ordem sugerida de execucao

1. Aprovar este backlog.
2. Corrigir P1 em Sprint 1.
3. Executar `QA-P1` antes de qualquer demonstracao.
4. Corrigir P2 de calculo, robustez e memoria.
5. Implementar fallback manual com UI.
6. Fechar documentacao e limpeza.
7. Executar `QA-FINAL` e consolidar evidencias.

## Regra de retorno

SEMPRE RETORNE AO LER ESTE ARQUIVO A PORCENTAGEM DE PROGRESSO JA FEITO.
