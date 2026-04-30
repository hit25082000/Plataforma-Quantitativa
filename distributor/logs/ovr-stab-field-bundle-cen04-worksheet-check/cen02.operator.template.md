# CEN-02 Operator Template (field-ready)

Use este template durante a sessao real para preencher evidencias minimas de zoom/escala.

## Contexto operacional
- scenario_id: CEN-02
- session_id: <preencher>
- symbol: <preencher>
- operator: <preencher>
- started_at_utc: <preencher>

## Checklist minimo pre-execucao
- [ ] overlay com axis_status visivel (HUD ou endpoint)
- [ ] captura de screenshot habilitada
- [ ] captura de trace jsonl habilitada
- [ ] marcador de logs para inicio da sessao

## Passos de execucao
| step_id | executed | timestamp_utc | action | axis_status_before | axis_status_after | stable_reached | evidence_ref | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capturar_baseline_estavel_5s | [ ] |  |  |  |  | [ ] |  |  |
| aplicar_zoom_in_progressivo | [ ] |  |  |  |  | [ ] |  |  |
| aplicar_zoom_out_progressivo | [ ] |  |  |  |  | [ ] |  |  |
| ajustar_escala_vertical_manual | [ ] |  |  |  |  | [ ] |  |  |
| aguardar_retorno_stable_pos_evento | [ ] |  |  |  |  | [ ] |  |  |

## Transicoes obrigatorias
| transition_state | observed | event_timestamp_utc | pre_window_ref | post_window_ref | trigger_action | drift_px_peak | evidence_ref |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| SUSPECT | [ ] |  |  |  |  |  |  |
| FROZEN | [ ] |  |  |  |  |  |  |
| RECALIBRATING | [ ] |  |  |  |  |  |  |

## Criterios minimos de aceite
- [ ] transicoes obrigatorias observadas com evidence_ref
- [ ] retorno para STABLE confirmado no fim da sessao
- [ ] drift_px_max apos retorno STABLE <= 3.0
- [ ] nenhuma transicao marcada sem referencia rastreavel

## Bloqueios
- blocked_reason:
- owner:
- eta:
- next_action:
