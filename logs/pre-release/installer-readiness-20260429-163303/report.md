# Installer Readiness Report (Overlay Stable)

- generated_at: 2026-04-29 16:33:05
- overall_ok: 0
- ok: 14
- warn: 0
- fail: 1

## Blockers

- preflight:overlay-sanity

## Checks

| check_id | status | detail |
| --- | --- | --- |
| preflight:overlay-sanity | fail | run_ocr_overlay_prerelease_sanity.py reportou bloqueios (exit=2) |
| presence:scripts/build-installer.ps1 | ok | script presente |
| presence:scripts/sync-profit-ocr-to-tauri-resources.ps1 | ok | script presente |
| presence:scripts/run_ocr_overlay_prerelease_sanity.py | ok | script presente |
| build-installer:sync-profit-ocr | ok | sincronizacao OCR para Tauri resources |
| build-installer:copy-engine | ok | copia de engine.exe para resources |
| build-installer:copy-distributor | ok | copia de distributor.exe para resources |
| build-installer:copy-ocr-service-exe | ok | copia de profit_ocr_service.exe para resources |
| build-installer:copy-profitdll64 | ok | copia/validacao de ProfitDLL64.dll |
| bundle:resources/profit_ocr_service.py | ok | entrada declarada em bundle.resources |
| bundle:resources/ocr_overlay_audit.py | ok | entrada declarada em bundle.resources |
| bundle:resources/profit_ocr_service.exe | ok | entrada declarada em bundle.resources |
| bundle:resources/engine.exe | ok | entrada declarada em bundle.resources |
| bundle:resources/distributor.exe | ok | entrada declarada em bundle.resources |
| bundle:resources/ProfitDLL64.dll | ok | entrada declarada em bundle.resources |
