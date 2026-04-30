# Field execution checklist (CEN-02..CEN-05)

## CEN-02 Zoom/Escala
- [ ] SUSPECT observado com evidence_ref
- [ ] FROZEN observado com evidence_ref
- [ ] RECALIBRATING observado com evidence_ref
- [ ] retorno para STABLE com drift_px_max <= 3.0

## CEN-03 OCR degradado
- [ ] executar fluxo direto: baseline_check -> inject_degradation -> confirm_protection -> recover_signal
- [ ] transicao STABLE->FROZEN|RECALIBRATING registrada
- [ ] preservacao de lastStableAxis confirmada
- [ ] transicao FROZEN|RECALIBRATING->STABLE registrada
- [ ] incidente preenchido com 3 evidencias (screenshot/trace/log-snippet)
- [ ] cada canal (hud/status_endpoint/trace_jsonl) contem expected/observed + evidence_ref
- [ ] exemplo CEN-03-INC-EX-001/002 usado como referencia de preenchimento

### CEN-03 Template operacional por incidente

| incident_id | transition_stable_to_protection | transition_recovery_to_stable | symptom | suspected_root_cause | action_taken | result |
| --- | --- | --- | --- | --- | --- | --- |
| CEN-03-INC-001 | [ ] | [ ] |  |  |  | pass|fail|blocked |

| incident_id | channel | expected | observed | evidence_ref |
| --- | --- | --- | --- | --- |
| CEN-03-INC-001 | hud |  |  |  |
| CEN-03-INC-001 | status_endpoint |  |  |  |
| CEN-03-INC-001 | trace_jsonl |  |  |  |

| incident_id | evidence_ref_1 | evidence_ref_2 | evidence_ref_3 |
| --- | --- | --- | --- |
| CEN-03-INC-001 |  |  |  |

## CEN-04 Multi-monitor 100/125/150
- [ ] usar versao curta abaixo para execucao de bancada
- [ ] preencher worksheet dedicado `cen04_drift_worksheet.md` (drift por passo)

### CEN-04 Execucao curta (bancada multi-monitor)

| monitor_id | dpi_percent | transicao | bounds_ok | overlay_ok | drift_px | evidence_ref |
| --- | ---: | --- | --- | --- | ---: | --- |
| monitor-1 | 100 | baseline-open | [ ] | [ ] |  |  |
| monitor-2 | 125 | move-to-monitor | [ ] | [ ] |  |  |
| monitor-3 | 150 | move-to-monitor | [ ] | [ ] |  |  |

| step_id | executed | timestamp_utc | monitor_id | dpi_percent | axis_status_before | axis_status_after | drift_px | evidence_ref |
| --- | --- | --- | --- | ---: | --- | --- | ---: | --- |
| open_window_on_baseline_monitor | [ ] |  | monitor-1 | 100 |  |  |  |  |
| move_window_to_next_monitor | [ ] |  | monitor-2 | 125 |  |  |  |  |
| minimize_window_on_target_monitor | [ ] |  | monitor-2 | 125 |  |  |  |  |
| restore_window_on_target_monitor | [ ] |  | monitor-2 | 125 |  |  |  |  |
| move_window_back_to_baseline_monitor | [ ] |  | monitor-3 | 150 |  |  |  |  |

#### Criterios de aceite instantaneos (CEN-04)
- [ ] cobertura DPI exata: 100/125/150
- [ ] `bounds_ok` e `overlay_ok` marcados para todos os DPIs
- [ ] `drift_px <= 3.0` em todas as linhas da matriz
- [ ] cada linha com `evidence_ref` preenchido

## CEN-05 Carga real
- [ ] stress.csv anexado
- [ ] summary.manifest.json do stress com gate.ok=true
- [ ] thresholds validados (latencia/fps/backlog/publish/jitter)
