# OCR Overlay Pre-Release Sanity Report

- generated_at: `2026-04-29 16:26:38`
- overall_ok: `1`
- ok: `33`
- warn: `0`
- fail: `0`

| check_id | status | detail |
| --- | --- | --- |
| presence:app/src-tauri/resources/profit_ocr_service.py | ok | resource presente |
| presence:app/src-tauri/resources/ocr_overlay_audit.py | ok | resource presente |
| presence:app/src-tauri/resources/engine.exe | ok | resource presente |
| presence:app/src-tauri/resources/distributor.exe | ok | resource presente |
| presence:app/src-tauri/resources/ProfitDLL.dll | ok | resource presente |
| presence:app/src-tauri/resources/ProfitDLL64.dll | ok | resource presente |
| presence:app/src-tauri/resources/libzmq-mt-4_3_5.dll | ok | resource presente |
| presence:app/src-tauri/resources/sounds/wall.wav | ok | resource presente |
| presence:app/src-tauri/resources/sounds/breakout.wav | ok | resource presente |
| presence:docs/contracts/vp-overlay-v1.json | ok | contract presente |
| presence:docs/contracts/fixtures/vp-overlay-demo.json | ok | fixture presente |
| presence:scripts/run_ovr_stab_qa_evidence.py | ok | qa-script presente |
| presence:scripts/run_ovr_stab_field_qa.py | ok | qa-script presente |
| presence:scripts/collect_ocr_overlay_trace_60s.py | ok | qa-script presente |
| presence:scripts/sync-profit-ocr-to-tauri-resources.ps1 | ok | qa-script presente |
| presence:distributor/tests/test_profit_ocr_service.py | ok | qa-test presente |
| presence:distributor/tests/test_ocr_overlay_audit.py | ok | qa-test presente |
| presence:distributor/tests/test_vp_overlay_contract.py | ok | qa-test presente |
| presence:distributor/tests/test_websocket_vp_overlay_endpoints.py | ok | qa-test presente |
| presence:distributor/tests/test_vp_ocr_enrich.py | ok | qa-test presente |
| sync:distributor/profit_ocr_service.py->app/src-tauri/resources/profit_ocr_service.py | ok | conteudo sincronizado |
| sync:distributor/ocr_overlay_audit.py->app/src-tauri/resources/ocr_overlay_audit.py | ok | conteudo sincronizado |
| bundle:resources/profit_ocr_service.py | ok | entrada registrada |
| bundle:resources/profit_ocr_service.exe | ok | entrada registrada |
| bundle:resources/engine.exe | ok | entrada registrada |
| bundle:resources/distributor.exe | ok | entrada registrada |
| bundle:resources/ProfitDLL.dll | ok | entrada registrada |
| bundle:resources/ProfitDLL64.dll | ok | entrada registrada |
| bundle:resources/libzmq-mt-4_3_5.dll | ok | entrada registrada |
| bundle:resources/sounds/wall.wav | ok | entrada registrada |
| bundle:resources/sounds/breakout.wav | ok | entrada registrada |
| bundle:resources/ocr_overlay_audit.py | ok | audit script empacotado |
| hygiene:pycache | ok | sem artefatos pycache em resources |
