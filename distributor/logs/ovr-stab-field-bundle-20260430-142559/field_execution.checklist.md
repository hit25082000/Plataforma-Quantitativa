# Field execution checklist (CEN-02..CEN-05)

## CEN-02 Zoom/Escala
- [ ] SUSPECT observado com evidence_ref
- [ ] FROZEN observado com evidence_ref
- [ ] RECALIBRATING observado com evidence_ref
- [ ] retorno para STABLE com drift_px_max <= 3.0

## CEN-03 OCR degradado
- [ ] transicao STABLE->FROZEN|RECALIBRATING registrada
- [ ] preservacao de lastStableAxis confirmada
- [ ] transicao FROZEN|RECALIBRATING->STABLE registrada
- [ ] incidente preenchido com 3 evidencias (screenshot/trace/log-snippet)

## CEN-04 Multi-monitor 100/125/150
- [ ] matriz DPI preenchida para 100/125/150
- [ ] passos open/move/minimize/restore/move-back registrados
- [ ] drift_px_max <= 3.0 por DPI

## CEN-05 Carga real
- [ ] stress.csv anexado
- [ ] summary.manifest.json do stress com gate.ok=true
- [ ] thresholds validados (latencia/fps/backlog/publish/jitter)
