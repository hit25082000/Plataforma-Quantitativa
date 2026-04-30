# CEN-02..CEN-05 command bundle

## 1) Gerar evidencias locais + checklist de campo

python scripts/run_ovr_stab_qa_evidence.py --strict --mode field-ready --require-ovr OVR-STAB-QA-02 --require-ovr OVR-STAB-QA-03 --require-ovr OVR-STAB-QA-04 --require-ovr OVR-STAB-QA-05 --require-ovr OVR-STAB-OBS-09 --cen05-stress-manifest "<stress-summary-manifest>"

## 2) Executar stress de carga CEN-05

python scripts/run_overlay_ws_stress_regression.py --duration-scale 1.0 --frame-scale 1.0

## 3) Rodar pacote estrito orientado ao operador para CEN-03

python scripts/run_ovr_stab_qa_evidence.py --strict --mode field-ready --require-ovr OVR-STAB-QA-03 --require-ovr OVR-STAB-OBS-09 --cen05-stress-manifest "<stress-summary-manifest>"

## 4) Validar prontidao consolidada G8 (CEN-01..05)

python scripts/verify_ovr_stab_g8_readiness.py --strict --qa-manifest "<qa-summary-manifest>" --stress-manifest "<stress-summary-manifest>" --field-report "<field-report.json>"

## 5) Preencher pacote dedicado CEN-02 (operador)

preencher `cen02.operator.template.md` e validar campos minimos com `cen02.minimum_checks.json`

## Referencias desta execucao

- qa_manifest: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-qa-evidence-final-pass\summary.manifest.json`
- stress_manifest: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\overlay-ws-stress-regression-final-pass\summary.manifest.json`
- readiness_manifest: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-g8-readiness-20260430-145632\summary.manifest.json`
- cen04_drift_worksheet: `distributor\logs\ovr-stab-field-bundle-cen03-validation-smoke\cen04_drift_worksheet.md`
- cen02_operator_template: `distributor\logs\ovr-stab-field-bundle-cen03-validation-smoke\cen02.operator.template.md`
- cen02_minimum_checks: `distributor\logs\ovr-stab-field-bundle-cen03-validation-smoke\cen02.minimum_checks.json`
