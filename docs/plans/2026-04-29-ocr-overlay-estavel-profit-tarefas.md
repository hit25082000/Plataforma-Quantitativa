# Plano Principal - OCR/Overlay Estavel para Profit (executivo)

Fonte: plano enviado no chat em 2026-04-29  
Data-base: 2026-04-29  
Status: em andamento (consolidacao executiva)  
Conclusao estimada oficial: **30%**  
`progress_percent_current`: **30**  
`progress_last_reconciled_at`: 2026-04-30 16:19 UTC-4

## Narrativa oficial (fonte unica)

- Este arquivo e a fonte oficial de progresso e backlog.
- O progresso publicado permanece em **30%** por regra conservadora.
- `progresso_tecnico_aux = 40.30% (27.0/67)` fica apenas como referencia interna, sem efeito de gate.
- Estado de prontidao consolidado: **NAO-PRONTO** enquanto `G8` estiver bloqueado por evidencias de campo.

## Status atual consolidado

### Gates (executivo)

| Gate | Status |
| --- | --- |
| G0 - Backlog | PASS |
| G1 - Contrato | PARTIAL |
| G2 - Eixo estavel base | PARTIAL |
| G3 - Troca controlada de eixo | PARTIAL |
| G4 - Estabilidade visual | PARTIAL |
| G5 - Performance | PARTIAL |
| G6 - Fallback manual | PASS |
| G7 - Observabilidade | PARTIAL |
| G8 - QA final | FAIL |

### Decisao operacional

- `g8_ready=false` (bloqueado por lacunas de campo `CEN-02..CEN-05`).
- Nenhuma promocao artificial de progresso sem fechamento de campo com `evidence_ref`.

## Evidencias essenciais (deduplicadas)

### 1) Contratos e compatibilidade

- `docs/contracts/ocr-overlay-stable-types-v1.md`
- `docs/contracts/overlay-update-v1.json`
- `docs/contracts/fixtures/overlay-update-demo.json`
- `frontend/src/utils/overlayUpdateCompat.ts`

### 2) Runtime/backend/tauri

- `distributor/profit_ocr_service.py`
- `distributor/websocket_server.py`
- `distributor/ocr_overlay_audit.py`
- `app/src-tauri/src/commands.rs`
- `app/src-tauri/src/lib.rs`

### 3) Frontend overlay/manual/debug

- `frontend/src/pages/OverlayPage.tsx`
- `frontend/src/hooks/useProfitOverlay.ts`
- `frontend/src/utils/overlayRenderDiff.ts`

### 4) Scripts e governanca de readiness

- `scripts/run_overlay_ws_stress_regression.py`
- `scripts/run_ovr_stab_qa_evidence.py`
- `scripts/verify_ovr_stab_g8_readiness.py`
- `scripts/run_ovr_stab_field_bundle.py`

### 5) Resultado sintetico de validacoes locais

- Suites criticas backend/frontend/tauri e harness locais em PASS nas rodadas consolidadas.
- Readiness final permanece `FAIL` por ausencia de evidencias fisicas obrigatorias.

## Rastreabilidade minima dos bloqueios (P1)

| Gap | Cenario | Bloqueio |
| --- | --- | --- |
| `GAP-CEN-04-MULTI-MONITOR` | CEN-04 | matriz fisica `100/125/150` com `evidence_ref` |
| `GAP-CEN-02-REAL-SESSION` | CEN-02 | transicoes reais completas `SUSPECT/FROZEN/RECALIBRATING -> STABLE` |
| `GAP-CEN-03-REAL-OCR-DEGRADATION` | CEN-03 | incidente real com evidencias de degradacao/recuperacao |
| `GAP-CEN-05-LOAD-REAL` | CEN-05 | carga em horario de mercado com bundle final real |

## Proximos passos (curtos e objetivos)

1. Executar `CEN-04` em bancada real e anexar matriz completa com `evidence_ref`.
2. Executar `CEN-02` em sessao real e comprovar transicoes obrigatorias.
3. Executar `CEN-03` real com template de explicabilidade fechado.
4. Executar `CEN-05` em horario de mercado com `stress.csv` + `summary.manifest.json`.
5. Reexecutar readiness estrito com field report consolidado.
6. Atualizar `progress_percent_current` apenas se `g8_ready=true`.

## Backlog final enxuto

### P1 (bloqueia G8)

1. `GAP-CEN-04-MULTI-MONITOR`
2. `GAP-CEN-02-REAL-SESSION`
3. `GAP-CEN-03-REAL-OCR-DEGRADATION`
4. `GAP-CEN-05-LOAD-REAL`

### P2 (nao desbloqueia G8 sozinho)

1. `OVR-STAB-CONTRACT-02` (promover parcial -> concluido)
2. `OVR-STAB-OBS-06`
3. `OVR-STAB-OBS-07`
4. `OVR-STAB-LINE-06`
5. Preencher `owner`/`eta` reais para todos os gaps abertos

## Regra de retorno

SEMPRE RETORNAR AO LER ESTE ARQUIVO A PORCENTAGEM DE PROGRESSO JA FEITO: **30%**.

## Evidencias locais recentes (2026-04-30)

- Runner ajustado para maior clareza de saida em `scripts/run_final_verification_pack.py`:
  - adiciona `executed` por etapa
  - marca etapas nao executadas com `skipped_reason`
  - publica contadores (`required_failed_count`, `strict_failed_count`, `skipped_*`)
- Regressao corrigida em `scripts/verify_ovr_stab_g8_readiness.py` (`issues` inicializado em `_validate_cen02_transition_evidence`).

### Rodadas executadas

1. `python scripts/run_final_verification_pack.py --smoke`
   - saida: `distributor/logs/final-verification-pack-20260430-155447/summary.manifest.json`
   - resultado: `overall_ok=true`
2. `python scripts/run_final_verification_pack.py --continue-on-failure` (rodada intermediaria)
   - saida: `distributor/logs/final-verification-pack-20260430-155528/summary.manifest.json`
   - resultado: `overall_ok=false` (regressao em readiness identificada e corrigida)
3. `python scripts/run_final_verification_pack.py --continue-on-failure` (apos correcao)
   - saida: `distributor/logs/final-verification-pack-20260430-155710/summary.manifest.json`
   - resultado: `overall_ok=true` e `required_ok=true`
4. `python scripts/run_final_verification_pack.py --continue-on-failure` (triagem full desta sessao)
   - saida: `distributor/logs/final-verification-pack-20260430-153815/summary.manifest.json`
   - resultado: `overall_ok=true` e `required_ok=true`
   - observacao: warnings nao bloqueantes em `step_02_frontend_tests.stderr.log` (`Warning: The current testing environment is not configured to support act(...)`)

### Estado consolidado de prontidao

- Pack local final: **PASS** (full local).
- Readiness G8 sem field report: `g8_ready=false`
  - evidencia: `distributor/logs/ovr-stab-g8-readiness-20260430-155749/summary.manifest.json`
- Decisao de gate permanece: **NAO-PRONTO para campo/producao** ate fechamento dos gaps de evidencia de campo.

### Atualizacao tecnica CEN-04/CEN-05 (2026-04-30 15:54 UTC-4)

- Endurecido contrato de readiness/preflight com `contract_version=1.1` e secoes `report_contract` em:
  - `scripts/verify_ovr_stab_g8_readiness.py`
  - `scripts/verify_cen05_preflight.py`
  - `scripts/run_ovr_stab_field_bundle.py`
- `verify_ovr_stab_g8_readiness.py` agora emite issues CEN-04 em formato acionavel (`issue|acao:...`) para acelerar triagem de campo.
- `verify_cen05_preflight.py` bloqueia readiness sem contrato minimo (`classification`, `diagnosis`, `next_action`, `diagnostics`) com status `READINESS_CONTRACT_INVALID`.
- `run_ovr_stab_field_bundle.py` adiciona `preopen_contract_check` no gate estrito para impedir bundle "verde" com preflight incompleto.
- Progresso executivo mantido em **30%** (sem promocao).

### Atualizacao tecnica CEN-02 (2026-04-30 16:02 UTC-4)

- Endurecida validacao de transicoes CEN-02 em:
  - `scripts/run_ovr_stab_field_bundle.py`
  - `scripts/verify_ovr_stab_g8_readiness.py`
- Regras adicionadas para reduzir erro operacional no `field_report`:
  - rejeita `transition_state` desconhecido e duplicado;
  - aceita aliases seguros de `observed` (`true/1/sim`) para evitar falso negativo por preenchimento textual;
  - aceita `event_timestamp_utc` como fallback de `observed_at_utc` em `SUSPECT/FROZEN`.
- Gate estrito do bundle agora publica `strict_gate_diagnostics` no manifesto para facilitar triagem quando `strict_ok=false`.

### Testes focados executados (CEN-02)

1. `python -m pytest distributor/tests/test_run_ovr_stab_field_bundle.py distributor/tests/test_verify_ovr_stab_g8_readiness.py`
   - resultado: `44 passed`

### Lacunas manuais finais (sem mudanca de gate)

- Mantidos bloqueios de campo: `GAP-CEN-02-REAL-SESSION`, `GAP-CEN-03-REAL-OCR-DEGRADATION`, `GAP-CEN-04-MULTI-MONITOR`, `GAP-CEN-05-LOAD-REAL`.
- `progress_percent_current` mantido em **30%**.

### Atualizacao tecnica field-report G8 (2026-04-30 16:19 UTC-4)

- Revisados validadores de `CEN-02/03/04/05` em:
  - `scripts/verify_ovr_stab_g8_readiness.py`
  - `scripts/run_ovr_stab_field_bundle.py`
- Acrescentado contrato explicito de `CEN-05` no field-report (session_type/result/evidence_ref) como gate estrito.
- Mensagens de gaps agora padronizadas em formato acionavel (`issue|acao:...`) para reduzir ambiguidade operacional no fechamento de G8.
- Incluidas integracoes com fixtures locais incompleto/completo para validar strict end-to-end em:
  - `distributor/tests/test_verify_ovr_stab_g8_readiness.py`
  - `distributor/tests/test_run_ovr_stab_field_bundle.py`
- Progresso executivo preservado em **30%** (sem promocao).

### Sincronizacao operacional (2026-04-30 16:19 UTC-4)

- Referencia principal de pack local permanece:
  - `distributor/logs/final-verification-pack-20260430-155710/summary.manifest.json`
  - `required_ok=true`, `overall_ok=true`, `required_failed_count=0`, `skipped_required_count=0`.
- Alinhamento de fluxo validado:
  1. `run_final_verification_pack.py` consolida backend/frontend/tauri/stress/qa e executa readiness como etapa opcional sem `field_report`;
  2. `verify_ovr_stab_g8_readiness.py` permanece gate de prontidao real de `G8` (com `--strict` para bloquear promocao quando `g8_ready=false`).
- Sem promocao de progresso: estado executivo continua **30%** ate `g8_ready=true` com evidencias de campo completas.

## Impedimentos para decisao (curto e explicito)

- **Gate final G8**: `g8_ready` continua bloqueado sem `field_report` valido de campo (CEN-02..CEN-05).
- **Preopen CEN-05**: `PREOPEN_BLOCKED` nas rodadas `preopen` por `COMMANDS_FILE_MISSING`, `BUNDLE_MANIFEST_MISSING`, `READINESS_G8_OR_CEN05_FAILED`, `ENVIRONMENT_NOT_READY`, `FRESHNESS_WINDOW_EXCEEDED`.
- **Ambiente real**: faltam variaveis operacionais (`PROFIT_DLL_USER`, `PROFIT_DLL_PASSWORD`, `PQ_PROFIT_DLL_PATH`) no host de execucao real.
- **Decisao necessaria**: manter `NAO-PRONTO` e priorizar fechamento de evidencia de campo (sem inflar `%`).

## Proximos passos operacionais objetivos (ordem de execucao)

1. Preparar host real com variaveis `PROFIT_DLL_*` e validar acesso.
2. Executar `python scripts/run_ovr_stab_field_bundle.py --strict` em janela real para gerar `commands.ready.md` + `summary.manifest.json`.
3. Reexecutar `python scripts/verify_ovr_stab_g8_readiness.py --strict` com evidencias atualizadas de campo.
4. Reexecutar `python scripts/verify_cen05_preflight.py --strict` imediatamente antes da abertura para remover `PREOPEN_BLOCKED`.
5. Atualizar este plano mantendo `progress_percent_current=30` enquanto `g8_ready=false`; promover somente apos `g8_ready=true`.

### Atualizacao tecnica CEN-03 (2026-04-30 16:54 UTC-4)

- Reforcada consistencia do helper de incidentes em `scripts/cen03_incident_packages.py`:
  - novo `build_incident_evidence_index()` com indexacao por `incident_id`;
  - bloqueio strict para `incident_id` duplicado;
  - `validate_cen03_incident_packages()` agora publica `incident_evidence_index` no resultado.
- Integracao do mesmo contrato nos fluxos estritos:
  - `scripts/run_ovr_stab_field_bundle.py` agora inclui `cen03_incident_evidence_index` no `summary.manifest.json` e resume cobertura por `incident_id` em `manual_gaps`.
  - `scripts/verify_ovr_stab_g8_readiness.py` passa a anexar `incident_evidence_index` na secao `field_validation` de `CEN-03`.

### Testes focados executados (CEN-03 incident_id)

1. `python -m pytest distributor/tests/test_cen03_incident_packages.py::TestCen03IncidentPackages::test_build_incident_evidence_index_returns_indexed_channels distributor/tests/test_cen03_incident_packages.py::TestCen03IncidentPackages::test_build_incident_evidence_index_rejects_duplicate_incident_id distributor/tests/test_run_ovr_stab_field_bundle.py::TestRunOvrStabFieldBundle::test_main_skip_stress_removes_stress_from_strict_gate distributor/tests/test_run_ovr_stab_field_bundle.py::TestRunOvrStabFieldBundle::test_main_strict_fails_when_cen03_channel_contract_is_incomplete distributor/tests/test_verify_ovr_stab_g8_readiness.py::TestVerifyOvrStabG8Readiness::test_scenario_result_cen03_requires_incident_package_contract distributor/tests/test_verify_ovr_stab_g8_readiness.py::TestVerifyOvrStabG8Readiness::test_main_integration_diagnostics_with_field_failures`
   - resultado: `6 passed`

### Pendencias de campo remanescentes (sem mudanca de gate)

- `GAP-CEN-03-REAL-OCR-DEGRADATION`: falta incidente real completo com evidencias operacionais finais.
- Mantidos `GAP-CEN-02-REAL-SESSION`, `GAP-CEN-04-MULTI-MONITOR`, `GAP-CEN-05-LOAD-REAL`.
- `progress_percent_current` permanece em **30%**.
