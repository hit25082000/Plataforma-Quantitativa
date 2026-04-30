# OCR Overlay Stable Contracts (v1)

Contrato técnico congelado para `OVR-STAB-CONTRACT-01`, alinhado ao payload de `overlay_update`.

## Modo dual (runtime atual)

O runtime publica `overlay_update` em modo dual:

- Legado no top-level (`status`, `lines`, `y_min`, `y_max`, `axis_deltas`, `axis_diagnostics`, `analysis_roi`, `analysis_sample`, `ts`).
- Estruturado nos blocos `structured` e `blocks` (mesmo conteúdo: `status`, `axis`, `lines`, `histogram`, `debug_visual`, `overlay_target`).
- Campos espelhados de compatibilidade (`axis_status`, `axis_source`, `confidence`, `residual_px`, `max_error_px`, `bad_frames`, `pending_count`, `pending_candidate`) seguem no top-level.
- Aliases aceitos no parser/UI para transição: `source` (equivalente a `axis_source`) e `pending_frames` (equivalente a `pending_count`). O emissor canônico continua publicando `axis_source` e `pending_count`.
- Para fallback de eixo, o nome canônico em logs/trace é `last_stable_axis`; `lastStableAxis` fica restrito a referência conceitual/legada em documentação operacional.
- `lines.visual_limits` publica limites obrigatórios por frame (`max_targets_per_frame`, `max_lines_per_frame`, `max_axis_labels`) para controle visual no consumidor.
- `render_indicators` é metadado de auditoria (`ocr_overlay_trace.jsonl`) e não integra o payload `overlay_update` via WebSocket.

## AxisLabel

Estrutura mínima:

- `value` (`number`): preço interpretado pelo OCR.
- `y_screen` (`number`): coordenada vertical em pixel (tela física do OCR).

Semântica:

- Cada item representa um label bruto/sanitizado de eixo.
- Ordem esperada no pipeline: crescente por `y_screen`.
- Em eixo válido de preço, `value` tende a decrescer com `y_screen` crescente.

## AxisCandidate

Estrutura mínima:

- `slope` (`number`)
- `intercept` (`number`)
- `value_per_px` (`number > 0`)
- `confidence` (`number [0..1]`)
- `labels_count` (`integer >= 0`)
- `residual_px` (`number >= 0`)
- `max_error_px` (`number >= 0`)
- `tick_valid` (`boolean`)
- `monotonic_valid` (`boolean`)

Campos de apoio aceitos:

- `inliers_count`, `value_min`, `value_max`, `y_min`, `y_max`.

Semântica:

- Representa proposta de eixo para o frame atual.
- Pode virar eixo estável apenas após validações e regras de confirmação multi-frame.

## StableAxis

Estrutura mínima:

- `slope` (`number`)
- `intercept` (`number`)
- `value_per_px` (`number > 0`)

Semântica:

- Eixo já aceito pelo `StableAxisManager` e usado para render.
- É o estado base para fallback (`last_stable_axis`) em falhas transitórias.

## OverlayLine

Estrutura mínima:

- `value` (`number`)
- `y_screen` (`number`)
- `color` (`string`)
- `chart_left` (`number`)
- `chart_right` (`number`)
- `status` (`"visible" | "clamped_top" | "clamped_bottom"`)
- `out_of_bounds` (`boolean`)

Campos opcionais:

- `label` (`string`)

Semântica:

- Linha renderizável derivada de `overlay_target` no eixo estável.
- `out_of_bounds=true` indica clamp geométrico no topo/fundo do chart.

## Trace JSONL (ocr_overlay_trace)

Contrato explícito versionado para eventos de auditoria em `docs/contracts/ocr-overlay-trace-v1.json`.

Arquivos canônicos:

- Schema: `docs/contracts/ocr-overlay-trace-v1.json`
- Fixture: `docs/contracts/fixtures/ocr-overlay-trace-demo.jsonl`

Eventos obrigatórios por contrato:

- `session_start`: `event`, `event_id`, `session_id`, `started_at`.
- `frame`: `event`, `event_id`, `session_id`, `seq`, `frame_seq`, `ts`, `timestamp_utc`, `status`, `render_indicators`, `status_transition`.

Subcampos obrigatórios de `frame`:

- `render_indicators`: `line_count_total`, `line_count_visible`, `line_count_out_of_bounds`.
- `status_transition`: `from`, `to`, `changed`.
