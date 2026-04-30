# Sequencia de comandos (pregao assistido)

## 1) Pre-flight field QA
python scripts/run_ovr_stab_field_qa.py --base-url http://127.0.0.1:8000 --trace-path "C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ocr_overlay_trace.jsonl" --out-dir "distributor\logs\pregao-assisted-session-dryrun-check\field_qa_probe" --assume-manual-ready

## 2) Janela curta de trace
python scripts/collect_ocr_overlay_trace_60s.py --duration-sec 60 --trace-path "C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ocr_overlay_trace.jsonl" --summary-out "distributor\logs\pregao-assisted-session-dryrun-check\trace_window.summary.json"

## 3) Opcional: baseline consolidado M6/M7
powershell -ExecutionPolicy Bypass -File scripts/run-m6-m7-evidence.ps1 -OutDir "distributor\logs\pregao-assisted-session-dryrun-check\m6_m7_reference" -HftDurationSeconds 60 -SessionSeconds 60 -FailOnAny:$false
