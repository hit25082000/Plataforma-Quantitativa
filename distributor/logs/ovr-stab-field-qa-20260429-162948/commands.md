# Command checklist per session

## 1) Pre-flight probes

python scripts/run_ovr_stab_field_qa.py --base-url http://127.0.0.1:8000 --trace-path "C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ocr_overlay_trace.jsonl" --out-dir "C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-field-qa-20260429-162948"

## 2) Trace window capture (60s)

python scripts/collect_ocr_overlay_trace_60s.py --duration-sec 60 --trace-path "C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ocr_overlay_trace.jsonl" --summary-out "C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-field-qa-20260429-162948\trace_window.summary.json"

## 3) Optional local suites (mocked)

python scripts/run_ovr_stab_qa_evidence.py

## 4) Session notes template

- registrar ativo, horario, monitor/DPI, cenario, resultado e anexos
- preencher o arquivo qa_session.manifest.json desta pasta
