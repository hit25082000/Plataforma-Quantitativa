# OVR-STAB-OBS-09 - Checklist de explicabilidade por logs

Status: concluida (cobertura local com testes/mocks)
Atualizado em: 2026-04-30

## Objetivo

Garantir que cada falha de alinhamento do overlay tenha causa observável em logs/artefatos, sem depender de sessão real do Profit para validação inicial.

## Narrativa unica de progresso

- Fonte oficial publicada da frente: `progress_percent_current=30%` (criterio conservador).
- `40.30%` permanece apenas como progresso tecnico auxiliar de reconciliacao e nao altera status oficial.
- Enquanto existirem `GAP-CEN-02..05`, o fechamento permanece bloqueado no gate de campo `G8`.

## Evidências mínimas exigidas

- Artefato consolidado do runner local:
  - `summary.csv`
  - `summary.md`
  - `summary.manifest.json`
- Logs por suíte:
  - `<suite>.stdout.log`
  - `<suite>.stderr.log`
- Campos rastreáveis em payload/debug:
  - `axis_status`
  - `axis_source`
  - `bad_frames`
  - `confidence`
  - `residual_px`
  - `last_frame`
  - `debug_visual`

## Matriz falha -> explicação observável

| Sintoma | Causa provável | Sinal em log/manifesto | Cobertura local |
| --- | --- | --- | --- |
| Linha oscila em gráfico parado | Eixo mudou sem confirmação robusta | `axis_status` transitando para `RECALIBRATING`/`FROZEN`; `bad_frames` crescente | Sim (parcial) |
| Linha salta após OCR ruim | Candidate rejeitado e fallback aplicado | `confidence` baixo, `residual_px` alto, manutenção de `last_stable_axis` | Sim (parcial) |
| Endpoint de controle não responde | Proxy/rotas OCR indisponíveis | falha em suíte `qa_overlay_proxy_endpoints` | Sim (parcial) |
| Y de POC/VAL/VAH incoerente | Enriquecimento eixo->pixel degradado | falha em suíte `qa_enrich_overlay_axis_health` | Sim (parcial) |
| Diferença por monitor/DPI | Ajuste físico/lógico de bounds | ausência de evidência local automatizada | Não (pendente sessão real/multi-monitor) |

## Rastreabilidade operacional obrigatoria (incidente)

Campos minimos por incidente:

- `scenario_id`
- `symptom`
- `suspected_root_cause`
- `observed_signal`
- `next_action`
- `evidence_ref`
- `resultado` (`pass` | `fail` | `blocked`)

Regra de aceite por incidente:

- sem `evidence_ref`, o incidente fica `blocked`;
- sem `observed_signal`, a causa fica classificada como hipotese nao validada;
- sem `next_action`, o incidente nao pode ser encerrado.

## Comando padrão de coleta local

```bash
python scripts/run_ovr_stab_qa_evidence.py
```

Validação estrita de completude de trace (sessão/evento/render/status transition):

```bash
python scripts/run_ovr_stab_qa_evidence.py --strict --require-ovr OVR-STAB-OBS-09
```

## Leitura diagnóstica rápida (90 segundos)

1. Abrir `summary.manifest.json` e confirmar:
   - `trace_completeness_validation_ok=true`
   - `target_protocols_validation_ok=true`
   - `integrity_report.ok=true`
2. Se `trace_completeness_validation_ok=false`, inspecionar `trace_completeness_validation_errors` e corrigir antes de seguir para campo.
3. No trace JSONL, validar presença mínima por frame:
   - `event_id`, `frame_seq`, `timestamp_utc`, `status`,
   - `render_indicators.line_count_total/visible/out_of_bounds`,
   - `status_transition.from/to/changed`.
4. Confirmar transições operacionais do eixo (`SUSPECT`, `FROZEN`, `RECALIBRATING`) no bloco de checklist CEN-02.

## Template estruturado de explicabilidade (automatizavel)

O runner agora gera:

- `target_protocols.manifest.json` com objetivos, criterios e dependencias por alvo (`OVR-STAB-AUD-04`, `OVR-STAB-AUD-05`, `OVR-STAB-QA-04`, `OVR-STAB-OBS-09`).
- `target_protocols.checklist.md` com campos obrigatorios de evidencias (`scenario`, `timestamps`, `observed_state_transitions`, `suspected_root_cause`, `next_action`) e matriz DPI 100/125/150.

Regra operacional:

- sem sessao de campo, preencher os blocos locais e manter estado `pending-field`;
- com sessao de campo, anexar referencia objetiva (`evidence_ref`) por linha de monitor/DPI e por incidente.

## Critério de aceite local

- `overall_ok=1` no `summary.manifest.json`.
- OVRs com estado `partial-done` no bloco `ovr_status`.
- Existência de logs por suíte e manifestos no diretório de saída.

## Criterio mensuravel por cenario (execucao imediata)

- `CEN-01`: `drift_px_max<=2.0` por 60s e `axis_status=STABLE` em >=95% dos frames.
- `CEN-02`: transicao `SUSPECT/RECALIBRATING -> STABLE` observada e sem salto persistente >3px.
- `CEN-03`: evidencia de degradacao (`confidence` baixo ou `residual_px` alto) e recuperacao controlada para `STABLE`.
- `CEN-04`: cobertura completa `100/125/150`, com `drift_px` e `evidence_ref` em cada linha da matriz.
- `CEN-05`: sem backlog crescente, latencia controlada e com banda de publicacao/FPS dentro do contrato.

## CEN-03 - Protocolo padronizado (injecao/observacao)

Passos obrigatorios:

1. `capture_baseline_axis_stable`
2. `apply_ocr_degradation_injection`
3. `observe_status_transition_to_frozen_or_recalibrating`
4. `verify_last_stable_axis_preserved`
5. `remove_degradation_and_watch_recovery_to_stable`

Fluxo direto orientado ao operador (dry-run):

1. `baseline_check`
2. `inject_degradation`
3. `confirm_protection`
4. `recover_signal`

Mapeamento de sinais esperados por canal:

| Canal | Sinais obrigatorios |
| --- | --- |
| HUD | `axis_status`, `axis_source`, `pending_frames`, `bad_frames`, `confidence`, `residual_px` |
| Status endpoint | `status`, `axis_status`, `axis_source`, `bad_frames`, `pending_count`, `confidence`, `residual_px`, `last_frame` |
| Trace JSONL | `timestamp_utc`, `frame_seq`, `axis_status`, `axis_source`, `bad_frames`, `pending_count`, `confidence`, `residual_px`, `max_error_px`, `last_stable_axis` |

Template minimo de evidencia CEN-03:

- `incident_id`
- `scenario_id`
- `injection_method`
- `injection_window_utc`
- `symptom`
- `observed_state_transitions`
- `expected_signals_by_channel`
- `observed_signals_by_channel`
- `suspected_root_cause`
- `action_taken`
- `result`
- `evidence_ref`

Pacote minimo por incidente CEN-03:

- minimo de `3` evidencias rastreaveis (`screenshot`, `trace`, `log-snippet`);
- comparativo `expected vs observed` para `HUD`, `status endpoint` e `trace JSONL`;
- transicoes obrigatorias: `STABLE->FROZEN|RECALIBRATING` e `FROZEN|RECALIBRATING->STABLE`.

Exemplos praticos de incidente:

- `CEN-03-INC-EX-001`: congelamento controlado com preservacao de eixo estavel e recuperacao em `pass`.
- `CEN-03-INC-EX-002`: recuperacao lenta apos degradacao removida, classificado como `fail` para triagem.

## Fechamento operacional sem pregão real (2026-04-29)

- Endpoints `GET /api/ocr-overlay/debug` e `GET /api/ocr-overlay/status` passam a retornar `meta` com contexto operacional mínimo:
  - `ts`, `status`, `axis_status`, `axis_source`, `frame_seq`, `last_update`.
- Erros operacionais de endpoints OCR passam a retornar envelope padronizado (`error.code`, `error.message`, `error.details`) + `meta` com diagnóstico rápido.
- `POST /api/ocr-overlay/manual-calibration` retorna erro acionável com `manual_axis_invalid_points` e preview dos pontos recebidos quando os dados são inválidos.

## Lacunas conhecidas (não cobertas localmente)

- OVR-STAB-QA-04 (multi-monitor 100/125/150%).
- Parte de OVR-STAB-QA-02 e OVR-STAB-QA-05 dependente de sessão real do Profit/telemetria de carga real.

## Matriz de explicabilidade por cenario (rastreavel)

| scenario_id | sintoma | causa_hipotese | sinal_observavel_objetivo | threshold_objetivo | evidence_ref | resultado |
| --- | --- | --- | --- | --- | --- | --- |
| CEN-01 | oscilacao em grafico parado | ruido OCR/filtro insuficiente | `axis_status`, `drift_px_max`, `bad_frames` | `drift_px_max<=2.0` | obrigatorio | pass/fail/blocked |
| CEN-02 | salto apos zoom | troca de escala sem confirmacao suficiente | transicao `SUSPECT/RECALIBRATING -> STABLE` | sem salto persistente `>3.0px` | obrigatorio | pass/fail/blocked |
| CEN-03 | salto com OCR ruim | fallback mal aplicado | `confidence`, `residual_px`, `last_stable_axis` | preservacao de eixo estavel | obrigatorio | pass/fail/blocked |
| CEN-04 | desloco por DPI/monitor | conversao fisico/logico inconsistente | `bounds`, `roi`, `axis_status` por DPI | cobertura 100/125/150 completa | obrigatorio | pass/fail/blocked |
| CEN-05 | degradacao sob carga | throttling/filas inadequadas | fila, intervalo de publicacao, latencia e responsividade | `queue_max<=1`, `backlog_growth_ratio<=1.5`, `latency_p95_ms<=60`, `latency_p99_ms<=120`, `consumer_fps>=90` | obrigatorio | pass/fail/blocked |

## Criterio de aceite de explicabilidade

- `overall_ok=1` nao e suficiente isoladamente.
- aceite exige cobertura de `CEN-01..CEN-05` com `evidence_ref` preenchido.
- nenhuma linha critica pode ficar `blocked` sem owner/ETA.
- campos minimos por incidente: `axis_status`, `axis_source`, `bad_frames`, `confidence`, `residual_px`, `pending_count`.
- para `CEN-05`, exigir validacao strict do runner de evidencias com manifesto de carga (`--cen05-stress-manifest`).

## Sessao manual pendente (obrigatorio quando blocked)

- scenario_id:
- motivo_bloqueio_manual:
- dependencia_externa:
- owner:
- data_planejada:
- risco_se_nao_executar:
- mitigacao_temporaria:
