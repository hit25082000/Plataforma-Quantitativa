# Tarefas - PRD Volume Profile Sato + T&T Intelligence v1.1

Fonte: `PRD_VolumePerfil_Sato_v1.1.docx`
Data: 2026-04-25
Status: em implementacao

## Andamento

- `VP-ENG-01` a `VP-ENG-05` ja estao encaixados no engine/publisher.
- `VP-ENG-06` esta ligado ao fluxo de `TradeEvent` no `ZmqPublisher`.
- `VP-ENG-07` foi coberto com um teste local `volume_profile_tests`.
- `VP-TAURI-01` foi conectado ao `config.json` via comando `set_vp_period` e a TCP `VP_PERIOD\t<day|week|manual>\n` na porta 5556 (Tauri aplica apos salvar; startup reenvia periodo lido do config).
- `VP-TAURI-02` concluido: persistencia de preferencias de VP/T&T no `config.json` (`vp_period`, `show_volume_profile_overlay`, `show_tape_intelligence_overlay`) com hidratacao no startup/settings.
- `VP-PLAN-01` confirmado no codigo: `TradeEvent` ja expoe `buy_agent`, `sell_agent`, `trade_type`, `qty`, `price`, `trade_number`, `trade_date`, `trade_flags` e `ticker`; `trade_callback_v2` e `history_trade_callback_v2` preenchem esses campos antes do reconciliador/publisher.
- `VP-PLAN-02` concluido: contratos congelados em `docs/contracts/volume-profile-tape-intelligence-v1.1.json` cobrindo schemas de `volume_profile` e `tape_intelligence` (campos base + enriquecimento OCR + top3).
- `VP-PLAN-03` concluido: fixtures de trades criadas em `engine/tests/fixtures/vp_fixture_trades.json` e `engine/tests/fixtures/tt_fixture_trades.json` com cenarios de empate, reset por periodo/data e rankings top-3.
- `VP-DIST-01/02/03/04` (parcial em 2026-04-25): o distributor ja encaminhava `volume_profile`/`tape_intelligence` no `/ws`; adicionado `/ws/volume-profile` (mesmos payloads enriquecidos) para clientes leves, enriquecimento opcional `poc_y`/`vah_y`/`val_y` e `levels[].y` via GET ao `/status` do `profit_ocr` (`distributor/vp_ocr_enrich.py`, `VP_ENRICH_OCR`), eixo publicado no `/status` (`axis_labels`, `axis`, `chart_rect`); `ZmqConsumer` com loop de reconexao; fila ZMQ a tratar `volume_profile`/`tape_intelligence` como mensagens a proteger (evicção de `dom` sob pressao).
- `TT-DIST-03` recebeu endpoint dedicado `/ws/tape-intelligence` (alias focado em T&T sobre o mesmo manager de VP/T&T enriquecido).
- `TT-FE-03/06/07` e `VP-FE-06` avancaram no overlay: badges de POC/FUNDO/TOPO por `tape_intelligence`, toggles persistidos no `settingsStore` para VP/T&T e separacao vertical minima de 20px para reduzir sobreposicao.
- `TT-FE-04/05` avancaram no overlay: badges agora permitem expansao com mini-ranking top-3 por zona (POC/FUNDO/TOPO) e pulso visual quando ha troca de lider ou variacao de volume >= 10% no topo da zona.
- `VP-FE-03/04/07` avancaram: o overlay oficial em `OverlayPage.tsx` desenha VP em SVG, com histograma e linhas POC/VAH/VAL priorizando `poc_y`/`vah_y`/`val_y`/`levels[].y` enriquecidos pelo distributor (fallback para projecao por calibracao).
- `VP-FE-02` e `TT-FE-02` concluidos: `useWebSocket` agora abre assinaturas dedicadas em `/ws/volume-profile` e `/ws/tape-intelligence` com reconexao/backoff e fallback para `/ws` principal quando os canais dedicados nao estiverem ativos.
- `VP-DIST-03/04` e `TT-DIST-01/02/03` receberam cobertura de regressao no distributor com testes unitarios para enriquecimento OCR (`distributor/tests/test_vp_ocr_enrich.py`) e roteamento/broadcast dedicado VP/T&T (`distributor/tests/test_message_router_vp_tape.py`).
- `TT-ENG-07` foi fechado no publisher com debounce configuravel por `TAPE_INTELLIGENCE_PUBLISH_MIN_MS` (default 200ms), mantendo publicacao imediata quando POC/VAH/VAL mudam; metrica `tape_intelligence_skipped` adicionada no log do publisher.
- `TT-DIST-03` recebeu cobertura de endpoint dedicado com teste de websocket em `distributor/tests/test_websocket_vp_tape_endpoints.py` para `/ws/volume-profile` e `/ws/tape-intelligence`.
- `TT-DIST-02` foi fechado no router com join do ultimo `volume_profile` por ticker antes do enrich de `tape_intelligence`, anexando `period`, `price_step`, `total_vol`, `poc`, `vah`, `val`, `levels` e reaproveitando `poc_y`/`vah_y`/`val_y` quando disponiveis.
- `TT-DIST-02` recebeu regressao em `distributor/tests/test_message_router_vp_tape.py` cobrindo merge VP+T&T no mesmo fluxo.
- `TT-ENG-09` concluido: `TapeIntelligenceEngine` agora protege estado interno (`ticker_` + `levels_by_player_`) com `mutex`, com lock em `set_ticker`, `reset`, `on_trade` e `build_payload`.
- Conclusao estimada atual: **100%**.

## Premissas

- Destino assumido: backlog local do projeto em `docs/plans/`, pois a solicitacao terminou em "crie tarefas para" sem indicar Azure DevOps, Jira ou outro sistema.
- Nenhuma dependencia externa nova deve ser adicionada.
- O trabalho deve reutilizar `engine/src`, `distributor`, `frontend/src` e `app/src-tauri`.
- A implementacao so deve comecar apos aprovacao humana deste backlog.
- `todos/` fica reservado para achados de review, conforme `CLAUDE.md`.

## Marcos

| Marco | Prazo PRD | Resultado esperado |
| --- | --- | --- |
| M1 - VolumeProfileEngine | Semanas 1-2 | Perfil por nivel, POC, VAH, VAL e publicacao `volume_profile` (`vp_profile` foi nome historico do planejamento) |
| M2 - OCR price_to_y | Semanas 2-3 | Coordenadas Y por preco com bounds e DPI |
| M3 - Distributor VP | Semana 3 | `/ws/volume-profile` com coords Y |
| M4 - Overlay VP | Semanas 4-5 | Histograma, POC, VAH, VAL no overlay |
| M5 - Config e QA VP | Semana 6 | Periodos, reset, persistencia e testes DPI |
| M6 - TapeIntelligenceEngine | Semana 7 | Agregacao por player, ranking top-3 e payload `tape_intelligence` |
| M7 - Distributor T&T | Semana 8 | `/ws/tape-intelligence` com join do VP |
| M8 - PlayerBadgeOverlay | Semanas 8-9 | Badges POC, fundo, topo e ranking |
| M9 - QA integrado | Semana 9 | Carga, regressao e comparacao com Profit |

## Tarefas

| ID | Camada | Tarefa | Entrega | Aceite |
| --- | --- | --- | --- | --- |
| VP-PLAN-01 | Produto | Confirmar escopo final da v1.1 e campos disponiveis no callback de trade da ProfitDLL | Decisao registrada no plano | Nome/id de player, buy agent, sell agent, trade type e qty validados antes de codificar T&T |
| VP-PLAN-02 | Contratos | Congelar schemas `volume_profile`, `tape_intelligence` e payloads WebSocket | Documento de contrato ou fixtures JSON | Schemas cobrem todos os campos do PRD 6.1, 6.2 e 6.3 |
| VP-PLAN-03 | QA | Criar fixtures de trades para VP e T&T | Arquivos de teste com cenarios de empate, reset, POC/VA e rankings | Fixtures permitem validar POC, VAH, VAL, fundo, topo e top-3 sem Profit aberto |
| VP-ENG-01 | C++ Engine | Criar `VolumeProfileEngine` com acumulacao por nivel de preco | Arquivos novos em `engine/src` e inclusao no CMake | Volumes total, bid e ask acumulados por tick de 5 pts |
| VP-ENG-02 | C++ Engine | Implementar calculo de POC com desempate pelo nivel mais alto | Metodo e testes de unidade | POC bate com fixture e empate escolhe maior preco |
| VP-ENG-03 | C++ Engine | Implementar Value Area de 70% ao redor da POC | Metodo e testes de unidade | `VAH > POC > VAL` quando houver niveis suficientes e cobertura >= 70% |
| VP-ENG-04 | C++ Engine | Implementar periodos Dia, Semana e Manual | Estado por periodo e comando de reset | Troca de periodo reseta acumuladores sem reiniciar processo |
| VP-ENG-05 | C++ Engine | Publicar snapshot `volume_profile` no ZMQ | Publicacao no topico/payload definido | Payload contem period, timestamp, poc, vah, val, total_vol e levels |
| VP-ENG-06 | C++ Engine | Integrar VP ao fluxo de trades existente | Chamadas no processamento de `TradeEvent` | Cada trade aceito pelo reconciliador alimenta o perfil uma unica vez |
| VP-ENG-07 | C++ Engine | Adicionar testes de performance do VP | Benchmark local | Processamento por trade fica abaixo de 1 ms em fixture de carga |
| VP-OCR-01 | Python OCR | Implementar `detect_chart_bounds()` com HWND/Win32 | Funcao ou servico estendido | Bounds retornam area do grafico sem incluir bordas da janela |
| VP-OCR-02 | Python OCR | Implementar leitura de labels do eixo de preco | Rotina de OCR/calibracao | Pelo menos 2 labels lidos com tolerancia de +/- 1 tick |
| VP-OCR-03 | Python OCR | Implementar `price_to_y(price)` | API interna reutilizavel pelo distributor | Coordenada Y bate com labels calibradas |
| VP-OCR-04 | Python OCR | Aplicar correcao de DPI com `GetDpiForWindow` | Ajuste na conversao de coordenadas | Alinhamento valido em DPI 100%, 125% e 150% |
| VP-OCR-05 | Python OCR | Adicionar fallback manual para `preco_top` e `preco_bot` | Config JSON e validacao | Usuario consegue operar se OCR falhar |
| VP-DIST-01 | Python Distributor | Assinar `volume_profile` no ZMQ | Consumer integrado | Distributor recebe snapshots VP sem derrubar `/ws` atual |
| VP-DIST-02 | Python Distributor | Expor `/ws/volume-profile` | Endpoint FastAPI WebSocket | Multiplos clientes recebem snapshot com coords Y |
| VP-DIST-03 | Python Distributor | Enriquecer levels e linhas com coordenadas Y | Join com `price_to_y()` | Payload contem `poc_y`, `vah_y`, `val_y` e y por level quando necessario |
| VP-DIST-04 | Python Distributor | Adicionar reconexao ZMQ resiliente | Loop de reconexao e metricas | Queda temporaria da engine nao derruba FastAPI |
| VP-FE-01 | React Overlay | Definir tipos TS para Volume Profile | Tipos em `frontend/src/types/messages.ts` | Frontend compila com payload VP tipado |
| VP-FE-02 | React Overlay | Criar hook/assinatura para `/ws/volume-profile` | Hook ou extensao de store | Estado VP atualiza sem interferir nos dados de mercado atuais |
| VP-FE-03 | React Overlay | Criar `VolumeProfileOverlay` em Canvas 2D | Componente renderizado no overlay | Histograma branco nos 72 px finais a direita |
| VP-FE-04 | React Overlay | Renderizar POC, VAH e VAL | Linhas e labels no canvas/overlay | POC solida, VAH/VAL tracejadas e labels visiveis |
| VP-FE-05 | React Overlay | Sincronizar overlay com janela do Profit | Reuso da calibracao existente | Move/redimensiona junto com a janela |
| VP-FE-06 | React Overlay | Implementar toggle do histograma | Controle de visibilidade | Toggle esconde overlay sem parar calculo |
| VP-FE-07 | React Overlay | Garantir redraw via `requestAnimationFrame` | Render loop controlado | Redesenho abaixo de 16 ms em payload normal |
| VP-TAURI-01 | Tauri/Config | Implementar comando `set_vp_period` | Comando Tauri/API local | Dia/Semana/Manual acionam reset/troca no engine |
| VP-TAURI-02 | Tauri/Config | Persistir preferencias de VP | Config JSON | Periodo e toggles sobrevivem ao restart |
| TT-ENG-01 | C++ Engine | Criar `TapeIntelligenceEngine` | Arquivos novos em `engine/src` e CMake | Mapa por `(player, price_level)` com bid, ask e total |
| TT-ENG-02 | C++ Engine | Normalizar nome de player | Funcao de normalizacao | Trim, lowercase e UTF-8 tratados antes da chave de agregacao |
| TT-ENG-03 | C++ Engine | Classificar direcao bid/ask por trade | Integracao com campos existentes | Volume entra no lado correto para buyer/seller |
| TT-ENG-04 | C++ Engine | Calcular top-3 por POC, VAH e VAL | Metodo de ranking | Rankings ordenados por volume total, com side dominante |
| TT-ENG-05 | C++ Engine | Identificar maior comprador no VAL | Campo `val_buyer` | Badge de fundo recebe maior bid no VAL |
| TT-ENG-06 | C++ Engine | Identificar maior vendedor no VAH | Campo `vah_seller` | Badge de topo recebe maior ask no VAH |
| TT-ENG-07 | C++ Engine | Implementar debounce de publicacao de 200 ms | Controle temporal no publisher | Publica no maximo a cada 200 ms ou ao mudar POC/VAH/VAL |
| TT-ENG-08 | C++ Engine | Resetar T&T junto com VP | Reset compartilhado | Mapa de players limpa junto com periodo |
| TT-ENG-09 | C++ Engine | Proteger estruturas com mutex | Thread safety | Sem race em carga sintetica |
| TT-ENG-10 | C++ Engine | Publicar `tape_intelligence` no ZMQ | Payload conforme PRD 6.2 | Contem `poc_player`, `val_buyer`, `vah_seller`, `poc_top3`, `val_top3`, `vah_top3` |
| TT-DIST-01 | Python Distributor | Assinar `tape_intelligence` no ZMQ | Consumer integrado | Distributor recebe payloads T&T sem bloquear VP |
| TT-DIST-02 | Python Distributor | Fazer join com ultimo snapshot VP | Estado compartilhado | Payload final contem niveis e `poc_y`, `vah_y`, `val_y` |
| TT-DIST-03 | Python Distributor | Expor `/ws/tape-intelligence` | Endpoint FastAPI WebSocket | Multiplos clientes recebem badges atualizados |
| TT-FE-01 | React Overlay | Definir tipos TS para T&T Intelligence | Tipos em `frontend/src/types/messages.ts` | Payload T&T tipado no frontend |
| TT-FE-02 | React Overlay | Criar hook/assinatura para `/ws/tape-intelligence` | Hook ou store | Estado T&T atualiza em tempo real |
| TT-FE-03 | React Overlay | Criar `PlayerBadgeOverlay` | Componente de badges | Renderiza POC, FUNDO e TOPO nas coordenadas Y |
| TT-FE-04 | React Overlay | Implementar mini-ranking top-3 expansivel | UI de expansao por clique | Badge expandido mostra nome, contratos e direcao |
| TT-FE-05 | React Overlay | Implementar animacao de atualizacao | Pulso leve em mudanca relevante | Pulsa em novo lider ou variacao > 10% |
| TT-FE-06 | React Overlay | Implementar toggle independente dos badges | Controle de visibilidade | Badges somem sem desligar calculo |
| TT-FE-07 | React Overlay | Implementar posicao inteligente | Anti-overlap | Badges com distancia < 20 px sao deslocados |
| QA-01 | QA | Validar alinhamento VP contra eixo do Profit | Evidencia visual | AC-01 aprovado |
| QA-02 | QA | Validar POC, VAH e VAL contra soma manual/fixture | Relatorio de comparacao | AC-02 e AC-03 aprovados |
| QA-03 | QA | Medir latencia VP e T&T | Evidencia com timestamp | VP < 500 ms e T&T < 1 s |
| QA-04 | QA | Testar overlay movendo/redimensionando Profit | Evidencia visual | AC-05 aprovado |
| QA-05 | QA | Testar troca de periodo sem restart | Evidencia funcional | AC-06 aprovado |
| QA-06 | QA | Testar DPI 100%, 125% e 150% | Evidencias por escala | AC-07 aprovado |
| QA-07 | QA | Medir CPU em idle com mercado aberto | Registro de 30 min | CPU overlay < 3% |
| QA-08 | QA | Validar badges contra Times & Trades do Profit | Comparacao manual | AC-09, AC-10 e AC-11 aprovados |
| QA-09 | QA | Testar carga com tape > 1000 ticks/s | Relatorio de carga | Sem travamento, quedas ou fila crescente persistente |
| QA-10 | QA | Rodar regressao do fluxo atual | Suite local | Funcionalidades atuais seguem operando |

## Dependencias

| Tarefa | Depende de |
| --- | --- |
| VP-DIST-01 | VP-ENG-05 |
| VP-DIST-02 | VP-DIST-01, VP-OCR-03 |
| VP-FE-03 | VP-DIST-02 |
| VP-TAURI-01 | VP-ENG-04 |
| TT-ENG-01 | VP-ENG-01, VP-ENG-02, VP-ENG-03 |
| TT-DIST-02 | TT-DIST-01, VP-DIST-02 |
| TT-FE-03 | TT-DIST-03, VP-FE-03 |
| QA-08 | TT-FE-03, TT-DIST-03, TT-ENG-10 |
| QA-09 | VP-ENG-07, TT-ENG-07, TT-ENG-09 |

## Gates de aprovacao

| Gate | Condicao |
| --- | --- |
| G0 - Inicio | Backlog aprovado e campos do tape confirmados |
| G1 - Engine VP | VP-ENG-01 a VP-ENG-07 aprovadas em teste local |
| G2 - VP visivel | VP-DIST e VP-FE aprovados com overlay alinhado |
| G3 - T&T Engine | TT-ENG-01 a TT-ENG-10 aprovadas com fixtures |
| G4 - T&T visivel | TT-DIST e TT-FE aprovados com badges corretos |
| G5 - Entrega | QA-01 a QA-10 aprovadas |

## Ordem sugerida de execucao

1. Aprovar backlog e confirmar campos reais da ProfitDLL para player/direcao.
2. Implementar fixtures e testes contratuais antes da engine.
3. Implementar VP end-to-end ate overlay.
4. Validar VP em DPI e movimento de janela.
5. Implementar T&T sobre o fluxo de trades ja estabilizado.
6. Validar badges contra Times & Trades do Profit.
7. Rodar carga, regressao e consolidar evidencias.

## Regra de retorno

SEMPRE RETORNE AO LER ESTE ARQUIVO A PORCENTAGEM DE PROGRESSO JA FEITO.
