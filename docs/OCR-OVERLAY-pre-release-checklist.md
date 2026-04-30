# OCR Overlay pre-release checklist

## Sanity automatizado

```bash
python scripts/run_ocr_overlay_prerelease_sanity.py
```

Saida padrao:

- `logs/pre-release/ocr-overlay-prerelease-<timestamp>/report.md`
- `logs/pre-release/ocr-overlay-prerelease-<timestamp>/report.manifest.json`

## Checklist executavel pre-installer

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-installer-readiness.ps1
```

Saida padrao:

- `logs/pre-release/installer-readiness-<timestamp>/report.md`
- `logs/pre-release/installer-readiness-<timestamp>/report.manifest.json`

## Criticos de empacotamento

- `app/src-tauri/resources/profit_ocr_service.py` presente e sincronizado com `distributor/profit_ocr_service.py`
- `app/src-tauri/resources/ocr_overlay_audit.py` presente e sincronizado com `distributor/ocr_overlay_audit.py`
- `app/src-tauri/tauri.conf.json` contem recursos criticos em `bundle.resources`
- sem artefatos `__pycache__/*.pyc` em `app/src-tauri/resources/`

## Contratos, fixtures e QA

- contrato: `docs/contracts/vp-overlay-v1.json`
- fixture: `docs/contracts/fixtures/vp-overlay-demo.json`
- scripts QA:
  - `scripts/run_ovr_stab_qa_evidence.py`
  - `scripts/run_ovr_stab_field_qa.py`
  - `scripts/collect_ocr_overlay_trace_60s.py`
  - `scripts/sync-profit-ocr-to-tauri-resources.ps1`
- testes QA:
  - `distributor/tests/test_profit_ocr_service.py`
  - `distributor/tests/test_ocr_overlay_audit.py`
  - `distributor/tests/test_vp_overlay_contract.py`
  - `distributor/tests/test_websocket_vp_overlay_endpoints.py`
  - `distributor/tests/test_vp_ocr_enrich.py`

## Gate de release

- `overall_ok=1`: apto para seguir para build/release
- `warn>0`: revisar manualmente antes de promover
- `fail>0`: bloqueante para release
