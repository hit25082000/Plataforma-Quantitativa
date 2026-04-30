# CEN-04 Drift Worksheet (Execucao fisica multi-monitor)

## Artifacts naming padrao

- session_slug: `ovr-stab-field-bundle-<YYYYMMDD-HHMMSS>`
- scenario_id: `CEN-04`
- monitor_tag: `monitor-<N>-dpi-<100|125|150>`
- step_id: `open_window_on_baseline_monitor|move_window_to_next_monitor|minimize_window_on_target_monitor|restore_window_on_target_monitor|move_window_back_to_baseline_monitor`
- evidence_ref (recomendado): `CEN-04/<monitor_tag>/<step_id>/<artifact_kind>-<UTC>.{png|jsonl|log}`
- artifact_kind suportado: `screenshot|ocr_trace|overlay_log|window_bounds`

## Matriz de medicao por monitor

| monitor_id | dpi_percent | baseline_ref | final_ref | max_drift_px | pass_drift_lte_3px |
| --- | ---: | --- | --- | ---: | --- |
| monitor-1 | 100 |  |  |  | [ ] |
| monitor-2 | 125 |  |  |  | [ ] |
| monitor-3 | 150 |  |  |  | [ ] |

## Drift por passo (preencher durante execucao fisica)

| step_seq | step_id | timestamp_utc | monitor_id | dpi_percent | axis_status_before | axis_status_after | drift_px | bounds_ok | overlay_ok | evidence_ref | notes |
| ---: | --- | --- | --- | ---: | --- | --- | ---: | --- | --- | --- | --- |
| 1 | open_window_on_baseline_monitor |  | monitor-1 | 100 |  |  |  | [ ] | [ ] |  |  |
| 2 | move_window_to_next_monitor |  | monitor-2 | 125 |  |  |  | [ ] | [ ] |  |  |
| 3 | minimize_window_on_target_monitor |  | monitor-2 | 125 |  |  |  | [ ] | [ ] |  |  |
| 4 | restore_window_on_target_monitor |  | monitor-2 | 125 |  |  |  | [ ] | [ ] |  |  |
| 5 | move_window_back_to_baseline_monitor |  | monitor-3 | 150 |  |  |  | [ ] | [ ] |  |  |

## Gate CEN-04

- [ ] cobertura DPI concluida para 100/125/150
- [ ] todas as linhas com `evidence_ref` preenchido no padrao definido
- [ ] `bounds_ok` e `overlay_ok` marcados em todas as linhas
- [ ] `drift_px <= 3.0` em todos os passos e monitores medidos

## Pendencias manuais

- [ ] consolidar refs finais no `field_execution.checklist.md`
- [ ] anexar artefatos fisicos ao pacote de evidencia CEN-04
