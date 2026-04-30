# OVR STAB - G8 readiness validator

## Executive short output

- status: `FAIL`
- g8_ready: `0`
- top_blockers: `CEN-01:GAP-CEN-01-LOCAL:evidencia local insuficiente (ovr_status.OVR-STAB-QA-01.state=missing); CEN-02:GAP-CEN-02-LOCAL:evidencia local insuficiente (ovr_status.OVR-STAB-QA-02.state=missing); CEN-03:GAP-CEN-03-LOCAL:evidencia local insuficiente (ovr_status.OVR-STAB-QA-03.state=missing)`
- recommendation: `Bloquear promocao e tratar top blockers antes do proximo gate.`

- g8_ready: `0`
- qa_manifest: `distributor\tests\fixtures\qa_manifest.sample.json`
- stress_manifest: `distributor\tests\fixtures\stress_manifest.sample.json`
- field_report: `distributor\tests\fixtures\field_report_real_integration.json`
- field_report_issues: `none`

| scenario | status | classification | local_validation | field_validation | gaps |
| --- | --- | --- | --- | --- | --- |
| CEN-01 | FAIL | FALSE_NEGATIVE_RISK | 0 (ovr_status.OVR-STAB-QA-01.state=missing) | 1 (pass=true) | GAP-CEN-01-LOCAL |
| CEN-02 | FAIL | FALSE_NEGATIVE_RISK | 0 (ovr_status.OVR-STAB-QA-02.state=missing) | 1 (CEN-02:SUSPECT:missing_transition|acao:registrar evento SUSPECT no transition_evidence com evidencias completas,CEN-02:FROZEN:missing_transition|acao:registrar evento FROZEN no transition_evidence com evidencias completas,CEN-02:RECALIBRATING:missing_transition|acao:registrar evento RECALIBRATING no transition_evidence com evidencias completas) | GAP-CEN-02-LOCAL |
| CEN-03 | FAIL | CONFIRMED_NOT_READY | 0 (ovr_status.OVR-STAB-QA-03.state=missing) | 0 (CEN-03.incident_packages_missing_or_empty|acao:corrigir incident_packages (canais hud/status_endpoint/trace_jsonl, transicoes e evidence_ref) e reenviar report,CEN-03.incident_packages_missing_or_empty|acao:corrigir incident_packages (canais hud/status_endpoint/trace_jsonl, transicoes e evidence_ref) e reenviar report) | GAP-CEN-03-LOCAL,GAP-CEN-03-FIELD |
| CEN-04 | FAIL | CONFIRMED_NOT_READY | 0 (ovr_status.OVR-STAB-QA-04.state=missing) | 0 (CEN-04:missing_monitor_dpi_matrix|acao:preencher monitor_dpi_matrix com 100/125/150) | GAP-CEN-04-LOCAL,GAP-CEN-04-FIELD |
| CEN-05 | FAIL | FALSE_NEGATIVE_RISK | 0 (stress_gate_ok=0) | 1 (pass=true) | GAP-CEN-05-LOCAL |

## Diagnosis and next action

- CEN-01 | FALSE_NEGATIVE_RISK | campo indica pronto, mas validacao local falhou (risco de falso negativo)
  - next_action: auditar gate local (ovr_status.OVR-STAB-QA-01.state=missing) e alinhar regra com evidencia real confirmada de CEN-01
- CEN-02 | FALSE_NEGATIVE_RISK | campo indica pronto, mas validacao local falhou (risco de falso negativo)
  - next_action: auditar gate local (ovr_status.OVR-STAB-QA-02.state=missing) e alinhar regra com evidencia real confirmada de CEN-02
- CEN-03 | CONFIRMED_NOT_READY | local e campo convergem para falha (ovr_status.OVR-STAB-QA-03.state=missing; CEN-03.incident_packages_missing_or_empty|acao:corrigir incident_packages (canais hud/status_endpoint/trace_jsonl, transicoes e evidence_ref) e reenviar report,CEN-03.incident_packages_missing_or_empty|acao:corrigir incident_packages (canais hud/status_endpoint/trace_jsonl, transicoes e evidence_ref) e reenviar report)
  - next_action: tratar causa raiz de CEN-03, repetir validacao local e anexar evidence_ref de campo
- CEN-04 | CONFIRMED_NOT_READY | local e campo convergem para falha (ovr_status.OVR-STAB-QA-04.state=missing; CEN-04:missing_monitor_dpi_matrix|acao:preencher monitor_dpi_matrix com 100/125/150)
  - next_action: tratar causa raiz de CEN-04, repetir validacao local e anexar evidence_ref de campo
- CEN-05 | FALSE_NEGATIVE_RISK | campo indica pronto, mas validacao local falhou (risco de falso negativo)
  - next_action: auditar gate local (stress_gate_ok=0) e alinhar regra com evidencia real confirmada de CEN-05

## Gap details

- CEN-01 | GAP-CEN-01-LOCAL | FAIL | evidencia local insuficiente (ovr_status.OVR-STAB-QA-01.state=missing)
- CEN-02 | GAP-CEN-02-LOCAL | FAIL | evidencia local insuficiente (ovr_status.OVR-STAB-QA-02.state=missing)
- CEN-03 | GAP-CEN-03-LOCAL | FAIL | evidencia local insuficiente (ovr_status.OVR-STAB-QA-03.state=missing)
- CEN-03 | GAP-CEN-03-FIELD | FAIL | field-report invalido: CEN-03.incident_packages_missing_or_empty|acao:corrigir incident_packages (canais hud/status_endpoint/trace_jsonl, transicoes e evidence_ref) e reenviar report,CEN-03.incident_packages_missing_or_empty|acao:corrigir incident_packages (canais hud/status_endpoint/trace_jsonl, transicoes e evidence_ref) e reenviar report
- CEN-04 | GAP-CEN-04-LOCAL | FAIL | evidencia local insuficiente (ovr_status.OVR-STAB-QA-04.state=missing)
- CEN-04 | GAP-CEN-04-FIELD | FAIL | field-report invalido: CEN-04:missing_monitor_dpi_matrix|acao:preencher monitor_dpi_matrix com 100/125/150
- CEN-05 | GAP-CEN-05-LOCAL | FAIL | manifesto ausente ou gate inválido
