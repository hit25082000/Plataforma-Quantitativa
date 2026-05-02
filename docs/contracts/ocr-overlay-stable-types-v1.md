# OCR Overlay Stable Contracts (v1)

Contrato técnico congelado para `OVR-STAB-CONTRACT-01`, alinhado ao payload de `overlay_update`.

## Modo dual (runtime atual)

O runtime publica `overlay_update` em modo dual:

- Legado no top-level (`status`, `lines`, `y_min`, `y_max`, `axis_deltas`, `axis_diagnostics`, `analysis_roi`, `analysis_sample`, `ts`).
- Estruturado no bloco `structured` (`status`, `axis`, `lines`, `histogram`, `debug_visual`, `overlay_target`).
- Campos espelhados de compatibilidade (`axis_status`, `axis_source`, `confidence`, `residual_px`, `max_error_px`, `bad_frames`, `pending_count`, `pending_candidate`) seguem no top-level.

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
