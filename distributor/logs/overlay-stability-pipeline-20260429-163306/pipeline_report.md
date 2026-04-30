# Overlay Stability Pipeline Report

- overall_ok: `0`
- total_steps: `4`
- failed_steps: `2`

| step | status | exit_code | manifest_ok | elapsed_s | manifest_path |
| --- | --- | ---: | ---: | ---: | --- |
| ovr_stab_qa_evidence | ok | 0 | 1 | 12.665 | C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\overlay-stability-pipeline-20260429-163306\steps\ovr_stab_qa_evidence\summary.manifest.json |
| ovr_stab_field_qa | fail | 0 | 0 | 6.553 | C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\overlay-stability-pipeline-20260429-163306\steps\ovr_stab_field_qa\qa_session.manifest.json |
| ocr_overlay_prerelease_sanity | fail | 2 | 0 | 0.236 | C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\overlay-stability-pipeline-20260429-163306\steps\ocr_overlay_prerelease_sanity\report.manifest.json |
| overlay_ws_stress_regression | ok | 0 | 1 | 6.52 | C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\overlay-stability-pipeline-20260429-163306\steps\overlay_ws_stress_regression\summary.manifest.json |

## Failures

- `ovr_stab_field_qa`: manifest_overall_ok=0
- `ocr_overlay_prerelease_sanity`: manifest ausente; exit_code=2; manifest_overall_ok=0
