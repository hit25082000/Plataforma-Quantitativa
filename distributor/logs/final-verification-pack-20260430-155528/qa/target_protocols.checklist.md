# OVR STAB - Checklist executavel de evidencias

Uso: preencher este checklist na mesma pasta dos artefatos locais para preparar execucao de campo.

## OVR-STAB-AUD-04 - Coleta 60s com grafico parado

- objective: Isolar jitter em cenario estavel e atribuir causa observavel por sinais de eixo/render.
- local_tooling_ready: 1
- evidence_state: pending-field
- acceptance_criteria:
  - [ ] captura de 60s registrada com resumo de variacao por frame
  - [ ] manifesto inclui sinalizacao de causa provavel: label/regressao/render
  - [ ] evidencia organizada em json/md/csv com links para logs da sessao
- manual_dependencies:
  - [ ] sessao Profit/replay com grafico parado por 60s
- notes:
  - scenario_id:
  - scenario:
  - symptom:
  - timestamps:
  - observed_state_transitions:
  - suspected_root_cause:
  - observed_signal:
  - next_action:
  - evidence_ref:
  - resultado: pass|fail|blocked

## OVR-STAB-AUD-05 - Coleta com mudanca de zoom/escala

- objective: Documentar transicoes de estado durante troca de escala e validar comportamento de congelamento/recalibracao.
- local_tooling_ready: 1
- evidence_state: pending-field
- acceptance_criteria:
  - [ ] eventos de zoom/escala anotados com timestamp e descricao
  - [ ] transicoes SUSPECT/FROZEN/RECALIBRATING aparecem na evidencia
  - [ ] trace aponta janela pre-evento e pos-evento com correlacao
- manual_dependencies:
  - [ ] acao manual de zoom/escala no grafico
- notes:
  - scenario_id:
  - scenario:
  - symptom:
  - timestamps:
  - observed_state_transitions:
  - suspected_root_cause:
  - observed_signal:
  - next_action:
  - evidence_ref:
  - resultado: pass|fail|blocked

## OVR-STAB-QA-03 - Protocolo CEN-03 de OCR degradado

- objective: Padronizar a injeção/observação de OCR ruim com explicabilidade fim-a-fim em HUD/status/trace.
- local_tooling_ready: 1
- evidence_state: pending-field
- acceptance_criteria:
  - [ ] protocolo segue passos de injeção e recuperação do CEN-03 sem ambiguidade
  - [ ] sinais esperados por canal (HUD, status endpoint, trace jsonl) são mapeados e conferidos
  - [ ] evidência registra sintomas, causa provável e ação aplicada com referência objetiva
- manual_dependencies:
  - [ ] sessão Profit/replay com capacidade de induzir OCR degradado
- notes:
  - scenario_id:
  - scenario:
  - symptom:
  - timestamps:
  - observed_state_transitions:
  - suspected_root_cause:
  - observed_signal:
  - next_action:
  - evidence_ref:
  - resultado: pass|fail|blocked

### OVR-STAB-QA-03 - protocolo padronizado de injeção/observação

- injection_protocol_steps:
  - [ ] capture_baseline_axis_stable
  - [ ] apply_ocr_degradation_injection
  - [ ] observe_status_transition_to_frozen_or_recalibrating
  - [ ] verify_last_stable_axis_preserved
  - [ ] remove_degradation_and_watch_recovery_to_stable
- operator_direct_flow:
  | step_id | operator_action | expected_result | evidence_required |
  | --- | --- | --- | --- |
  | baseline_check | Confirmar axis_status=STABLE por 5s | baseline sem jitter e confidence estavel | screenshot + trace_ref |
  | inject_degradation | Aplicar oclusao parcial no eixo ou reduzir contraste | queda de confidence/residual_px crescente | video_ref ou screenshot sequencial |
  | confirm_protection | Acompanhar transicao para FROZEN/RECALIBRATING | last_stable_axis preservado sem salto abrupto | trace_ref + status_endpoint_ref |
  | recover_signal | Remover degradacao e aguardar recuperacao | retorno para STABLE com drift controlado | screenshot pos-recuperacao + trace_ref |
- expected_signals_by_channel:
  - hud:
    - [ ] axis_status
    - [ ] axis_source
    - [ ] pending_frames
    - [ ] bad_frames
    - [ ] confidence
    - [ ] residual_px
  - status_endpoint:
    - [ ] status
    - [ ] axis_status
    - [ ] axis_source
    - [ ] bad_frames
    - [ ] pending_count
    - [ ] confidence
    - [ ] residual_px
    - [ ] last_frame
  - trace_jsonl:
    - [ ] timestamp_utc
    - [ ] frame_seq
    - [ ] axis_status
    - [ ] axis_source
    - [ ] bad_frames
    - [ ] pending_count
    - [ ] confidence
    - [ ] residual_px
    - [ ] max_error_px
    - [ ] last_stable_axis
- required_transitions:
  - [ ] STABLE->FROZEN|RECALIBRATING
  - [ ] FROZEN|RECALIBRATING->STABLE
- incident_minimum_evidence:
  - min_evidence_refs: 3
  - required_artifact_kinds:
    - [ ] screenshot
    - [ ] trace
    - [ ] log-snippet
  - required_channels_with_expected_vs_observed:
    - [ ] hud
    - [ ] status_endpoint
    - [ ] trace_jsonl
- evidence_template_required_fields:
  - [ ] incident_id
  - [ ] scenario_id
  - [ ] injection_method
  - [ ] injection_window_utc
  - [ ] symptom
  - [ ] observed_state_transitions
  - [ ] expected_signals_by_channel
  - [ ] observed_signals_by_channel
  - [ ] suspected_root_cause
  - [ ] action_taken
  - [ ] result
  - [ ] evidence_ref

#### CEN-03 - incidentes minimos por evidencia

| incident_id | transition_observed | expected_vs_observed_hud | expected_vs_observed_status_endpoint | expected_vs_observed_trace_jsonl | evidence_ref_1 | evidence_ref_2 | evidence_ref_3 | resultado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CEN-03-INC-001 | [ ] | [ ] | [ ] | [ ] |  |  |  | pass|fail|blocked |

#### CEN-03 - exemplos prontos de incidente

| incident_id | symptom | suspected_root_cause | action_taken | result | evidence_ref_example |
| --- | --- | --- | --- | --- | --- |
| CEN-03-INC-EX-001 | linhas POC/VAL congeladas durante oclusao parcial | OCR sem labels validas por contraste baixo temporario | mantido FROZEN ate remocao da oclusao | pass | artifact://ovr-stab-CEN-03-screenshot-20260430T174500Z.png, artifact://ovr-stab-CEN-03-trace-20260430T174500Z.jsonl, artifact://ovr-stab-CEN-03-log-snippet-20260430T174500Z.txt |
| CEN-03-INC-EX-002 | recuperacao lenta para STABLE apos degradacao removida | pending_count alto durante janela de revalidacao | coleta adicional de 10s e comparacao expected_vs_observed | fail | artifact://ovr-stab-CEN-03-screenshot-20260430T180000Z.png, artifact://ovr-stab-CEN-03-trace-20260430T180000Z.jsonl, artifact://ovr-stab-CEN-03-log-snippet-20260430T180000Z.txt |

## OVR-STAB-QA-04 - Protocolo multi-monitor DPI 100/125/150

- objective: Garantir alinhamento de bounds/overlay ao mover janela entre monitores com DPI distintos.
- local_tooling_ready: 1
- evidence_state: pending-field
- acceptance_criteria:
  - [ ] execucao registrada para 100%, 125% e 150%
  - [ ] cada monitor possui status pass/fail e anexo de evidencia
  - [ ] manifesto inclui observacoes sobre drift e offset em pixels
- manual_dependencies:
  - [ ] ambiente com ao menos dois monitores e perfis DPI 100/125/150
- notes:
  - scenario_id:
  - scenario:
  - symptom:
  - timestamps:
  - observed_state_transitions:
  - suspected_root_cause:
  - observed_signal:
  - next_action:
  - evidence_ref:
  - resultado: pass|fail|blocked

## OVR-STAB-QA-05 - Protocolo de carga real CEN-05

- objective: Comprovar estabilidade simultanea de backlog, taxa de publish e FPS efetivo sob carga.
- local_tooling_ready: 1
- evidence_state: pending-field
- acceptance_criteria:
  - [ ] stress.csv e summary.manifest.json anexados com resultado por cenario
  - [ ] thresholds de backlog/publish/FPS avaliados de forma objetiva e rastreavel
  - [ ] nenhum cenario com backlog crescente ou jitter persistente de publish
- manual_dependencies:
  - [ ] execucao em horario de mercado ou replay representativo de alta carga
- notes:
  - scenario_id:
  - scenario:
  - symptom:
  - timestamps:
  - observed_state_transitions:
  - suspected_root_cause:
  - observed_signal:
  - next_action:
  - evidence_ref:
  - resultado: pass|fail|blocked

## OVR-STAB-OBS-09 - Checklist estruturado de explicabilidade

- objective: Padronizar evidencias para explicar falhas sem depender de memoria operacional.
- local_tooling_ready: 1
- evidence_state: ready-local
- acceptance_criteria:
  - [ ] matriz sintoma->causa->sinal preenchida para cada incidente
  - [ ] campo de confianca da hipotese e proximo passo obrigatorios
  - [ ] bundle final possui md/json com referencias cruzadas
- manual_dependencies:
  - [ ] nenhuma
- notes:
  - scenario_id:
  - scenario:
  - symptom:
  - timestamps:
  - observed_state_transitions:
  - suspected_root_cause:
  - observed_signal:
  - next_action:
  - evidence_ref:
  - resultado: pass|fail|blocked

## OVR-STAB-QA-04 - matriz DPI

| monitor_id | dpi_percent | step_id | transition | bounds_ok | overlay_ok | drift_px | drift_band | evidence_ref |
| --- | ---: | --- | --- | --- | --- | ---: | --- | --- |
| monitor-1 | 100 | open_window_on_baseline_monitor | baseline-open | [ ] | [ ] |  | <=3.0px |  |
| monitor-2 | 125 | open_window_on_baseline_monitor | move-to-monitor | [ ] | [ ] |  | <=3.0px |  |
| monitor-3 | 150 | open_window_on_baseline_monitor | move-to-monitor | [ ] | [ ] |  | <=3.0px |  |

## OVR-STAB-QA-04 - passos de reproducao

| step_id | executed | timestamp_utc | monitor_id | dpi_percent | axis_status_before | axis_status_after | drift_px | evidence_ref |
| --- | --- | --- | --- | ---: | --- | --- | ---: | --- |
| open_window_on_baseline_monitor | [ ] |  |  |  |  |  |  |  |
| move_window_to_next_monitor | [ ] |  |  |  |  |  |  |  |
| minimize_window_on_target_monitor | [ ] |  |  |  |  |  |  |  |
| restore_window_on_target_monitor | [ ] |  |  |  |  |  |  |  |
| move_window_back_to_baseline_monitor | [ ] |  |  |  |  |  |  |  |

## OVR-STAB-QA-04 - coleta padronizada de drift

Campos obrigatorios por medicao:
- scenario_id
- step_id
- monitor_id
- dpi_percent
- timestamp_utc
- axis_status_before
- axis_status_after
- drift_px
- drift_band
- evidence_ref

## CEN-05 (carga) - contrato objetivo de thresholds

| metric | operator | threshold |
| --- | --- | ---: |
| queue_max | <= | 1 |
| backlog_growth_ratio | <= | 1.5 |
| latency_p95_ms | <= | 60.0 |
| latency_p99_ms | <= | 120.0 |
| consumer_fps | >= | 90.0 |
| publish_rate_floor_ratio | >= | 0.75 |
| publish_rate_overshoot_ratio | <= | 1.15 |
| publish_interval_jitter_cv | <= | 0.35 |

### CEN-05 - execucao operacional imediata

| step_id | executed | timestamp_utc | observed_value | threshold_contract | evidence_ref |
| --- | --- | --- | --- | --- | --- |
| run_overlay_ws_stress_regression_strict | [ ] |  |  | all_metrics_contract |  |
| attach_stress_artifacts_bundle | [ ] |  |  | stress.csv+summary.md+summary.manifest.json |  |
| verify_market_session_context | [ ] |  |  | market_open_or_representative_replay |  |
| confirm_no_backlog_growth | [ ] |  |  | backlog_growth_ratio<=1.5 |  |
| confirm_publish_band_and_fps | [ ] |  |  | floor/overshoot/fps/jitter/latency |  |

### CEN-05 - criterios mensuraveis de aceite

- [ ] `queue_max<=1` em todos os cenarios
- [ ] `backlog_growth_ratio<=1.5` em todos os cenarios
- [ ] `latency_p95_ms<=60` e `latency_p99_ms<=120` em todos os cenarios
- [ ] `consumer_fps>=90`, `publish_rate_floor_ratio>=0.75`, `publish_rate_overshoot_ratio<=1.15`
- [ ] `publish_interval_jitter_cv<=0.35` e `summary.manifest.json overall_ok=1`

## CEN-02 (zoom/escala) - roteiro operacional objetivo

- target_ids: OVR-STAB-AUD-05, OVR-STAB-QA-02
- objetivo: comprovar transicoes SUSPECT/FROZEN/RECALIBRATING com estabilizacao final.
- criterio_gate: so concluir quando todas as transicoes obrigatorias tiverem evidencia.
- comandos_executaveis:
  - `python scripts/run_ovr_stab_qa_evidence.py --strict --mode field-ready --require-ovr OVR-STAB-QA-02 --require-ovr OVR-STAB-OBS-09`
  - `python scripts/verify_ovr_stab_g8_readiness.py --qa-manifest "<out-dir>/summary.manifest.json"`
- pre-check imediato:
  - [ ] summary.manifest.json presente e nao vazio
  - [ ] feed/replay ativo e overlay com axis_status visivel
  - [ ] trace/screenshot/video habilitados antes do primeiro evento

### CEN-02 - passos operacionais

| step_id | executed | timestamp_utc | action | axis_status_before | axis_status_after | stable_reached | evidence_ref |
| --- | --- | --- | --- | --- | --- | --- | --- |
| capturar_baseline_estavel_5s | [ ] |  |  |  |  | [ ] |  |
| aplicar_zoom_in_progressivo | [ ] |  |  |  |  | [ ] |  |
| aplicar_zoom_out_progressivo | [ ] |  |  |  |  | [ ] |  |
| ajustar_escala_vertical_manual | [ ] |  |  |  |  | [ ] |  |
| aguardar_retorno_stable_pos_evento | [ ] |  |  |  |  | [ ] |  |

### CEN-02 - captura de transicoes obrigatorias

| transition_state | observed | event_timestamp_utc | pre_window_ref | post_window_ref | trigger_action | drift_px_peak | evidence_ref |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| SUSPECT | [ ] |  |  |  |  |  |  |
| FROZEN | [ ] |  |  |  |  |  |  |
| RECALIBRATING | [ ] |  |  |  |  |  |  |

### CEN-02 - evidencia minima por transicao

| transition_state | screenshot_ref | trace_ref | status_endpoint_ref | expected_vs_observed | resultado |
| --- | --- | --- | --- | --- | --- |
| SUSPECT |  |  |  |  | pass|fail|blocked |
| FROZEN |  |  |  |  | pass|fail|blocked |
| RECALIBRATING |  |  |  |  | pass|fail|blocked |

### CEN-02 - criterios objetivos de aceite

- [ ] transicoes obrigatorias observadas: SUSPECT, FROZEN e RECALIBRATING
- [ ] retorno para STABLE apos evento de zoom/escala registrado
- [ ] sem oscilacao persistente apos estabilizacao (drift_px_max <= 3.0)
- [ ] cada transicao possui evidence_ref rastreavel

### CEN-02 - contrato de qualidade automatizado

| metric | operator | threshold | evidence_observed | pass |
| --- | --- | ---: | --- | --- |
| required_transitions_count | >= | 3 |  | [ ] |
| stable_return_required | == | 1 |  | [ ] |
| drift_px_max_after_stable | <= | 3.0 |  | [ ] |
| evidence_ref_coverage_ratio | == | 1.0 |  | [ ] |

### CEN-02 - registro rapido de bloqueio

- blocked_reason:
- owner:
- eta:
- next_action:

