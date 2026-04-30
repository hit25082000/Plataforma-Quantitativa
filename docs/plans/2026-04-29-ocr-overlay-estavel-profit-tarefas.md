# Tarefas - OCR/Overlay Estavel para Profit

Fonte: plano enviado no chat em 2026-04-29
Data: 2026-04-29
Status: em andamento (reauditado com evidencias do workspace)
Conclusao estimada atual: 30% (criterio conservador, revalidado)

## Premissas

- Destino assumido: backlog local em `docs/plans/`.
- Esta frente complementa `docs/plans/2026-04-27-vp-ocr-overlay-profit-tarefas.md`.
- Engine continua responsavel apenas por dados de mercado; OCR/overlay nao entram no engine.
- OCR nunca move linha diretamente; apenas propaga `AxisCandidate`.
- Overlay desenha sempre com `lastStableAxis`.

## Escopo desta frente

- Estabilizar eixo preco->pixel contra ruido de OCR.
- Garantir congelamento controlado com `FROZEN`/`RECALIBRATING`.
- Aplicar confirmacao multi-frame para trocas de escala/zoom.
- Estabilizar linhas (deadband + EMA) sem deslocar por OCR ruim.
- Entregar fallback manual 2 pontos.
- Entregar debug operacional completo via API + painel.

## Sprints

| Sprint | Objetivo |
| --- | --- |
| S0 | Auditoria da oscilacao atual |
| S1 | `StableAxisManager` + `lastStableAxis` + rejeicao de OCR invalido |
| S2 | Regressao robusta e saneamento de labels |
| S3 | Confirmacao por multiplos frames |
| S4 | Estabilizacao visual de linhas |
| S5 | Performance (loops, throttle, filas, limites) |
| S6 | Fallback manual por 2 pontos |
| S7 | Debug/observabilidade + QA final |

## Tarefas

| ID | Camada | Tarefa | Entrega | Aceite |
| --- | --- | --- | --- | --- |
| OVR-STAB-PLAN-01 | Planejamento | Confirmar superficie real dos modulos atuais (`profit_ocr_service`, consolidator, renderer frontend, endpoints) | Mapeamento no proprio backlog | Arquivos-alvo e pontos de integracao fechados antes de codar |
| OVR-STAB-CONTRACT-01 | Contrato | Congelar `AxisLabel`, `AxisCandidate`, `StableAxis` e `OverlayLine` no contrato interno | Estruturas/tipos documentados e versionados | Campos minimos do plano presentes e com semantica fixa |
| OVR-STAB-CONTRACT-02 | Contrato | Congelar payload `overlay_update` com bloco `status`/`axis`/`lines`/`histogram` | JSON schema/fixture atualizada | `axis_status`, `axis_source`, `confidence`, `residual_px`, `bad_frames` obrigatorios |
| OVR-STAB-DIST-01 | Distributor | Garantir emissao normalizada de `overlay_target` (POC/VAL/VAH/top players/manual) | Payload normalizado no distributor | Overlay recebe `targets` sem regra de negocio extra no frontend |
| OVR-STAB-DIST-02 | Distributor | Incluir limites visuais (max linhas/histograma) na consolidacao | Controles aplicados no payload final | Nao excede limites configurados por frame publicado |
| OVR-STAB-AUD-01 | OCR | Logar cada frame OCR (labels, slope, intercept, residual, confidence, status) | Log estruturado JSONL | 60s de coleta com dados por frame |
| OVR-STAB-AUD-02 | OCR | Logar `y_screen` por linha renderizada para correlacionar com eixo | Campos por linha em debug/log | Possivel comparar salto de linha vs salto de eixo |
| OVR-STAB-AUD-03 | OCR | Criar dump unico de diagnostico `ocr_overlay_trace.jsonl` | Arquivo em `distributor/logs/` | Dump reproduzivel com metadados de sessao |
| OVR-STAB-AUD-04 | QA | Rodar coleta de 60s com grafico parado | Evidencia com sumario de variacao | Identifica se salto vem de label, regressao ou render |
| OVR-STAB-AUD-05 | QA | Rodar coleta com zoom/escala alterando durante sessao | Evidencia com transicao de estado | Mudanca de escala fica observavel no trace |
| OVR-STAB-AXIS-01 | OCR | Implementar tipo `AxisCandidate` no fluxo de OCR | Modelo em codigo + serializacao debug | Candidate inclui labels_count, residual, max_error e bounds |
| OVR-STAB-AXIS-02 | OCR | Implementar tipo `StableAxis` com `source` e `updated_at_ms` | Modelo em codigo | `to_y(price)` centralizado e reutilizado |
| OVR-STAB-AXIS-03 | OCR | Implementar `StableAxisManager` com estados `CALIBRATING/STABLE/SUSPECT/FROZEN/RECALIBRATING/MANUAL_LOCKED` | Classe operacional com estado interno | Estado muda conforme regras do plano |
| OVR-STAB-AXIS-04 | OCR | Aplicar validacao basica de candidate (`labels_count`, `confidence`, `residual_px`, `max_error_px`, monotonicidade, tick) | Filtro de aceite no manager | Candidate invalido nao move eixo |
| OVR-STAB-AXIS-05 | OCR | Implementar bootstrap de primeiro eixo estavel | Fluxo de bootstrap no manager | Sem eixo inicial nao existe render instavel |
| OVR-STAB-AXIS-06 | OCR | Persistir e reutilizar `lastStableAxis` em falha temporaria de OCR | Cache estavel no runtime | Frame ruim isolado nao altera linha |
| OVR-STAB-AXIS-07 | Distributor | Publicar `axis_status` no `overlay_update` | Payload ampliado | Frontend recebe `STABLE/SUSPECT/FROZEN/RECALIBRATING` |
| OVR-STAB-AXIS-08 | Frontend | Exibir estado de eixo no HUD/status | Status visual na UI | Operador consegue ver eixo congelado/suspeito |
| OVR-STAB-FIT-01 | OCR | Restringir OCR para ROI do eixo Y (`chart_right-90` ate `chart_right`) | ROI fixa configuravel | OCR nao roda no grafico inteiro |
| OVR-STAB-FIT-02 | OCR | Implementar preprocessamento (grayscale, resize, contrast, threshold, denoise) | Pipeline de imagem | Leitura de labels melhora sem custo excessivo |
| OVR-STAB-FIT-03 | OCR | Implementar parser conservador de preco por ativo (WINFUT/WDOFUT) | Parser com faixa min/max | Strings invalidas nao viram preco |
| OVR-STAB-FIT-04 | OCR | Validar compatibilidade de tick (`tick_size`) | Regra de tick aplicada | Label fora de tick e descartada |
| OVR-STAB-FIT-05 | OCR | Validar monotonicidade de labels por Y | Validador aplicado no sanitize | Sequencia invalida e descartada |
| OVR-STAB-FIT-06 | OCR | Implementar `sanitize_labels` (dedupe + outlier pre-filter) | Etapa antes do fit | Base de labels limpa para regressao |
| OVR-STAB-FIT-07 | OCR | Implementar `fit_axis_robust` por inliers + refit linear | Ajuste robusto em producao | Label absurda nao contamina eixo final |
| OVR-STAB-FIT-08 | OCR | Calcular `residual_px`, `max_error_px`, `confidence` e anexar no candidate | Metricas no candidate | Regras de aceite passam a ser mensuraveis |
| OVR-STAB-CONF-01 | OCR | Implementar `axis_delta_px(candidate, last_stable)` | Funcao de delta pronta | Delta pequeno atualiza por suavizacao |
| OVR-STAB-CONF-02 | OCR | Implementar thresholds `small/medium/large` e frames de confirmacao | Config aplicada no manager | Troca de escala exige N frames bons |
| OVR-STAB-CONF-03 | OCR | Implementar pendencia por candidato (`pending_candidate` + `pending_count`) | Estado de confirmacao multi-frame | Mudanca nao confirmada fica em `SUSPECT` |
| OVR-STAB-CONF-04 | OCR | Confirmar mudanca grande so apos 8 frames bons | Regra de seguranca aplicada | Zoom brusco nao causa salto imediato |
| OVR-STAB-CONF-05 | OCR | Implementar `bad_frames` + transicao para `FROZEN` e `RECALIBRATING` | Tratamento de degradacao | OCR perdido preserva ultimo eixo confiavel |
| OVR-STAB-CONF-06 | OCR | Permitir `freeze/unfreeze/recalibrate` por endpoint de controle | Hooks de controle operacional | Operador consegue forcar comportamento durante teste |
| OVR-STAB-LINE-01 | Overlay | Criar `StableLineManager` com cache por `line_id` | Gerenciador ativo no renderer | Primeira amostra inicializa sem jitter |
| OVR-STAB-LINE-02 | Overlay | Aplicar deadband de 1.5px antes de suavizacao | Regra no update de linha | Variacao minima nao move linha |
| OVR-STAB-LINE-03 | Overlay | Aplicar EMA por linha (`line_ema_alpha`) apos deadband | Suavizacao por linha | Tremedeira fina reduzida sem drift visivel |
| OVR-STAB-LINE-04 | Overlay | Aplicar clamp out-of-bounds e status visual (`out_of_bounds_top/bottom`) | Clamp no renderer | Linha fora da escala nao gera salto extremo |
| OVR-STAB-LINE-05 | Distributor/Overlay | Nao publicar/redesenhar quando delta visual < 1px | Throttle por diff visual | Menos ruido de update em grafico parado |
| OVR-STAB-LINE-06 | Frontend | Exibir status de linha (`stable/frozen/out_of_bounds/hidden`) no debug | HUD de linha | Diagnostico visual imediato por target |
| OVR-STAB-PERF-01 | Runtime | Separar loops (OCR 300-500ms, targets 5-10Hz, render 30FPS) | Loops desacoplados | OCR nao bloqueia render |
| OVR-STAB-PERF-02 | Runtime | Implementar filas `maxsize=1` para OCR/targets e descarte de frame antigo | Queues limitadas | Sem backlog crescente |
| OVR-STAB-PERF-03 | Distributor | Aplicar throttle WS minimo de 100ms + publish only on change | Politica de publish consolidada | Cliente recebe apenas alteracoes relevantes |
| OVR-STAB-PERF-04 | Overlay | Limitar `max_targets` e `max_histogram_levels` | Limites de seguranca aplicados | UI continua responsiva com carga alta |
| OVR-STAB-PERF-05 | Overlay | Coalescer/agrupar niveis VP quando escala comprimida | Reducao de barras densas | Histograma continua legivel em escala apertada |
| OVR-STAB-PERF-06 | Overlay | Skip render quando nao houver diff real de estado | Curto-circuito de render | Menos custo em periodo estavel |
| OVR-STAB-PERF-07 | Tauri | Implementar loop de bounds 1-2Hz (move/resize/minimize/DPI/monitor) | Monitoramento da janela Profit | Mudanca fisica entra em `RECALIBRATING` |
| OVR-STAB-PERF-08 | Tauri | Corrigir coordenadas fisicas vs logicas em multi-monitor/DPI | Ajuste de posicionamento | Overlay nao desloca em 100/125/150% |
| OVR-STAB-PERF-09 | QA | Medir CPU/FPS/latencia com VP+POC/VAL/VAH+players+histograma | Relatorio de performance | Sem travamento e com FPS estavel |
| OVR-STAB-MAN-01 | Frontend/Tauri | Criar modo "Calibracao manual" com captura de 2 cliques | Fluxo UI pronto | Usuario seleciona ponto A/B com feedback |
| OVR-STAB-MAN-02 | Frontend/Tauri | Capturar preco informado para ponto A/B e validar entrada | Formulario + validacao | Dados invalidos sao bloqueados |
| OVR-STAB-MAN-03 | OCR | Implementar calculo de eixo manual por 2 pontos | `StableAxis(source=manual)` | Eixo manual consistente e reutilizavel |
| OVR-STAB-MAN-04 | OCR | Travar estado em `MANUAL_LOCKED` enquanto manual ativo | Regras de bloqueio OCR | OCR automatico nao sobrescreve eixo manual |
| OVR-STAB-MAN-05 | API | Expor `POST /api/ocr-overlay/manual-calibration` | Endpoint funcional | Payload aplica eixo manual em runtime |
| OVR-STAB-MAN-06 | Frontend | Botao para voltar ao modo OCR automatico | Acao de unlock | Sistema sai de `MANUAL_LOCKED` com seguranca |
| OVR-STAB-OBS-01 | API | Expor `GET /api/ocr-overlay/debug` | Endpoint debug completo | Retorna axis/ocr/chart/targets/status |
| OVR-STAB-OBS-02 | API | Expor `GET /api/ocr-overlay/status` | Endpoint leve de status | Pode ser consultado a 1Hz sem custo alto |
| OVR-STAB-OBS-03 | API | Expor `POST /api/ocr-overlay/recalibrate` | Controle de recalibracao | Forca transicao controlada de estado |
| OVR-STAB-OBS-04 | API | Expor `POST /api/ocr-overlay/freeze` e `/unfreeze` | Controle de congelamento | Operador congela/descongela explicitamente |
| OVR-STAB-OBS-05 | API | Expor `POST /api/ocr-overlay/config` para tunning runtime | Configuracao aplicada | Thresholds ajustaveis sem restart |
| OVR-STAB-OBS-06 | Frontend | Criar painel visual "OCR Overlay Debug" | Painel com metricas chave | Mostra status, labels, residual, bad/pending, slope/intercept |
| OVR-STAB-OBS-07 | Frontend | Adicionar modo debug visual (labels OCR, regressao, ROI, bounds) | Overlay de depuracao | Erros de alinhamento ficam visiveis no grafico |
| OVR-STAB-OBS-08 | Runtime | Exportar JSONL de frames OCR e indicadores de render | Export local em logs | Qualquer salto fica rastreavel pos-sessao |
| OVR-STAB-OBS-09 | QA | Fechar checklist de explicabilidade de falhas via logs | Documento de diagnostico | Cada falha de alinhamento tem causa observavel |
| OVR-STAB-QA-01 | QA | Teste grafico parado por 60s | Evidencia com variacao max por linha | Oscilacao <= 1-2px e sem saltos absurdos |
| OVR-STAB-QA-02 | QA | Teste zoom/eixo vertical no Profit | Evidencia de transicao de estado | Congela em `SUSPECT/RECALIBRATING` e reposiciona apos confirmacao |
| OVR-STAB-QA-03 | QA | Teste OCR propositalmente ruim (contraste/cobertura parcial) | Evidencia de degradacao controlada | Entra em `FROZEN` e preserva `lastStableAxis` |
| OVR-STAB-QA-04 | QA | Teste multi-monitor (100/125/150%) | Evidencia por monitor e DPI | Bounds e overlay seguem corretos |
| OVR-STAB-QA-05 | QA | Teste carga com muitos targets/histograma | Evidencia de throughput e estabilidade | UI responsiva e sem fila crescente |

## Dependencias principais

| Tarefa | Depende de |
| --- | --- |
| OVR-STAB-CONTRACT-01 | OVR-STAB-PLAN-01 |
| OVR-STAB-CONTRACT-02 | OVR-STAB-CONTRACT-01 |
| OVR-STAB-DIST-01 | OVR-STAB-CONTRACT-02 |
| OVR-STAB-AUD-01 | OVR-STAB-PLAN-01 |
| OVR-STAB-AUD-03 | OVR-STAB-AUD-01, OVR-STAB-AUD-02 |
| OVR-STAB-AXIS-03 | OVR-STAB-AXIS-01, OVR-STAB-AXIS-02 |
| OVR-STAB-AXIS-04 | OVR-STAB-AXIS-03, OVR-STAB-FIT-08 |
| OVR-STAB-AXIS-06 | OVR-STAB-AXIS-03, OVR-STAB-AXIS-05 |
| OVR-STAB-CONF-02 | OVR-STAB-CONF-01 |
| OVR-STAB-CONF-03 | OVR-STAB-CONF-02 |
| OVR-STAB-CONF-05 | OVR-STAB-CONF-03 |
| OVR-STAB-LINE-03 | OVR-STAB-LINE-01, OVR-STAB-LINE-02 |
| OVR-STAB-LINE-05 | OVR-STAB-LINE-03 |
| OVR-STAB-PERF-03 | OVR-STAB-LINE-05, OVR-STAB-PERF-01 |
| OVR-STAB-PERF-05 | OVR-STAB-PERF-04 |
| OVR-STAB-PERF-08 | OVR-STAB-PERF-07 |
| OVR-STAB-MAN-03 | OVR-STAB-MAN-01, OVR-STAB-MAN-02 |
| OVR-STAB-MAN-04 | OVR-STAB-MAN-03 |
| OVR-STAB-MAN-06 | OVR-STAB-MAN-04 |
| OVR-STAB-OBS-06 | OVR-STAB-OBS-01, OVR-STAB-OBS-02 |
| OVR-STAB-OBS-07 | OVR-STAB-OBS-06 |
| OVR-STAB-QA-01 | OVR-STAB-AXIS-06, OVR-STAB-LINE-05 |
| OVR-STAB-QA-02 | OVR-STAB-CONF-05, OVR-STAB-PERF-07 |
| OVR-STAB-QA-03 | OVR-STAB-FIT-08, OVR-STAB-CONF-05 |
| OVR-STAB-QA-04 | OVR-STAB-PERF-08 |
| OVR-STAB-QA-05 | OVR-STAB-PERF-09, OVR-STAB-PERF-04, OVR-STAB-PERF-05 |

## Gates de aprovacao

| Gate | Condicao |
| --- | --- |
| G0 - Backlog | Tarefas aprovadas pelo humano |
| G1 - Contrato | `OVR-STAB-CONTRACT-*` e `OVR-STAB-DIST-01/02` aprovados |
| G2 - Eixo estavel base | `OVR-STAB-AXIS-*` + `OVR-STAB-FIT-*` aprovados |
| G3 - Troca controlada de eixo | `OVR-STAB-CONF-*` aprovado |
| G4 - Estabilidade visual | `OVR-STAB-LINE-*` aprovado |
| G5 - Performance | `OVR-STAB-PERF-*` aprovado |
| G6 - Fallback manual | `OVR-STAB-MAN-*` aprovado |
| G7 - Observabilidade | `OVR-STAB-OBS-*` aprovado |
| G8 - QA final | `OVR-STAB-QA-01..05` aprovados com evidencia |

## Ordem sugerida de execucao

1. Fechar contrato e normalizacao (`OVR-STAB-CONTRACT-*`, `OVR-STAB-DIST-*`).
2. Executar auditoria S0 e gerar `ocr_overlay_trace.jsonl`.
3. Entregar `StableAxisManager` + regras basicas de aceite.
4. Entregar regressao robusta e parser/validadores de label.
5. Entregar confirmacao multi-frame e estados de degradacao.
6. Entregar `StableLineManager` e throttle por diff visual.
7. Entregar loops/fila/limites de performance + bounds/DPI.
8. Entregar fallback manual e controles de estado.
9. Entregar endpoints/painel debug e fechar QA de campo.

## Prioridade maxima (ataque inicial)

1. `OVR-STAB-AXIS-03`
2. `OVR-STAB-AXIS-06`
3. `OVR-STAB-AXIS-04`
4. `OVR-STAB-LINE-02`
5. `OVR-STAB-LINE-03`

## Regra de retorno

SEMPRE RETORNE AO LER ESTE ARQUIVO A PORCENTAGEM DE PROGRESSO JA FEITO.

## Reconciliacao de progresso (2026-04-29)

### Criterio conservador (explicito)

- Universo auditado: 67 tarefas unicas `OVR-STAB-*` da tabela principal.
- Pontuacao:
  - Concluida com evidencia em codigo + teste/contrato: `1.0`
  - Parcial com evidencia incompleta (faltando QA real, UI final ou cobertura integral): `0.5`
  - Sem evidencia suficiente: `0.0`
- Formula: `progresso = (soma dos pontos / 67) * 100`.
- Resultado reconciliado (reauditoria 2026-04-29): `20.5 / 67 = 30.59%` -> **30%** (arredondado para baixo para evitar inflar).

### Reauditoria complementar (workspace atual)

- Revalidados artefatos locais de QA em `distributor/logs/ovr-stab-qa-evidence-20260429-161246/` (`summary.md`, `summary.csv`, `summary.manifest.json`).
- Revalidados guias/checklists operacionais em `docs/OVR-STAB-QA-final-execucao.md` e `docs/OVR-STAB-OBS-09-checklist-explicabilidade-falhas.md`.
- Resultado da reauditoria: **sem ganho de pontos no criterio conservador** (evidencia nova reforca itens parciais, mas nao converte pendencias de campo em concluidas).

### Tarefas auditadas com evidencia

Concluidas (`1.0`):
- `OVR-STAB-CONTRACT-01`
- `OVR-STAB-AXIS-03`
- `OVR-STAB-AXIS-06`
- `OVR-STAB-LINE-02`
- `OVR-STAB-LINE-03`
- `OVR-STAB-CONF-06`
- `OVR-STAB-MAN-03`
- `OVR-STAB-MAN-04`
- `OVR-STAB-MAN-05`
- `OVR-STAB-OBS-01`
- `OVR-STAB-OBS-02`
- `OVR-STAB-OBS-09`

Parciais (`0.5`):
- `OVR-STAB-CONTRACT-02`
- `OVR-STAB-AXIS-04`
- `OVR-STAB-AXIS-07`
- `OVR-STAB-OBS-07`
- `OVR-STAB-OBS-08`
- `OVR-STAB-AUD-03`
- `OVR-STAB-QA-01`
- `OVR-STAB-QA-02`
- `OVR-STAB-QA-03`
- `OVR-STAB-QA-05`

Sem evidencia suficiente nesta reconciliacao (`0.0`):
- Demais tarefas da tabela nao listadas acima.

## Proximo lote prioritario (max 10, atualizado)

1. `OVR-STAB-QA-04` - fechar evidencia real multi-monitor/DPI 100/125/150 (principal gap sem cobertura local).
2. `OVR-STAB-AUD-04` - coleta de 60s com grafico parado em sessao Profit real, com rastreabilidade de causa.
3. `OVR-STAB-AUD-05` - coleta com mudanca de zoom/escala e validacao de transicoes de estado no trace.
4. `OVR-STAB-OBS-06` - painel visual "OCR Overlay Debug" com metricas completas de operacao.
5. `OVR-STAB-OBS-09` - promover checklist de explicabilidade de parcial para completo com evidencias de campo.
6. `OVR-STAB-QA-05` - fechar teste de carga real com limites finais de linhas/histograma e sem backlog crescente.
7. `OVR-STAB-OBS-08` - consolidar export JSONL final (padrao unico de sessao + indicadores de render em todas as rotas).
8. `OVR-STAB-OBS-02` - fechar endpoint leve de status em regime 1Hz com criterio de custo.
9. `OVR-STAB-AXIS-04` - completar validacoes faltantes de candidate (monotonicidade/tick/max_error) com cobertura de regressao.
10. `OVR-STAB-OBS-07` - fechar parte frontend do debug visual (labels OCR, regressao, ROI, bounds) com aceite de campo.

## Evidencias usadas na reconciliacao

- `distributor/profit_ocr_service.py`
- `distributor/websocket_server.py`
- `distributor/tests/test_profit_ocr_service.py`
- `distributor/tests/test_websocket_vp_overlay_endpoints.py`
- `frontend/src/pages/OverlayPage.tsx`
- `docs/contracts/ocr-overlay-stable-types-v1.md`
- `docs/contracts/overlay-update-v1.json`
- `docs/OVR-STAB-OBS-09-checklist-explicabilidade-falhas.md`
- `scripts/run_ovr_stab_qa_evidence.py`

Validacao do ciclo:
- `python -m compileall distributor/profit_ocr_service.py` OK
- `python -m unittest distributor.tests.test_websocket_vp_overlay_endpoints distributor.tests.test_vp_overlay_consolidator distributor.tests.test_vp_ocr_enrich` OK (12 testes)
- `python -m compileall distributor/profit_ocr_service.py distributor/tests/test_profit_ocr_service.py` OK
- `python -m unittest distributor.tests.test_profit_ocr_service distributor.tests.test_websocket_vp_overlay_endpoints distributor.tests.test_vp_ocr_enrich` OK (9 testes)
- `cargo check --manifest-path app/src-tauri/Cargo.toml` OK
- `npm run build --prefix frontend` OK
- `python -m compileall distributor/profit_ocr_service.py distributor/websocket_server.py distributor/tests/test_profit_ocr_service.py distributor/tests/test_websocket_vp_overlay_endpoints.py` OK
- `python -m unittest distributor.tests.test_profit_ocr_service distributor.tests.test_websocket_vp_overlay_endpoints` OK (18 testes)
- `python -m unittest distributor.tests.test_run_ovr_stab_qa_evidence` OK
- `python scripts/run_ovr_stab_qa_evidence.py` OK (artefatos consolidados de evidência local)
