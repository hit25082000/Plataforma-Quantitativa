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
- [ ] exemplo CEN-03-INC-EX-001/002 usado como referencia de preenchimento

## CEN-04 Multi-monitor 100/125/150
- [ ] usar versao curta abaixo para execucao de bancada

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
