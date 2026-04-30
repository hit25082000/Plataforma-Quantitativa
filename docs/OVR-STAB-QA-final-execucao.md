# OVR-STAB QA final - execucao assistida

Status: operacional (assistido/manual)
Atualizado em: 2026-04-30

## Escopo

Automatizar preparacao e evidencias de campo para:

- `OVR-STAB-QA-02`
- `OVR-STAB-QA-03`
- `OVR-STAB-QA-04`
- `OVR-STAB-QA-05`

## Narrativa unica de progresso

- Fonte oficial publicada da frente: `progress_percent_current=30%` (conservador, gateado por `G8`).
- `40.30%` e apenas progresso tecnico auxiliar de reconciliacao local e nao substitui o percentual oficial.
- Qualquer relatorio de QA deve citar o percentual oficial e manter os `GAP-CEN-02..05` como bloqueios de campo ate evidencia real completa.

## Runner principal

```bash
python scripts/run_ovr_stab_field_qa.py
```

## Bundle final CEN-02..CEN-05 (comandos prontos)

Runner unico recomendado para fechamento do pacote de campo com coleta minima:

```bash
python scripts/run_ovr_stab_field_bundle.py --strict
```

Preflight dedicado para sessao real CEN-05 antes de abrir mercado:

```bash
python scripts/verify_cen05_preflight.py --strict
```

Modo integrado ao bundle/readiness (recomendado no pre-open imediato):

```bash
python scripts/verify_cen05_preflight.py --strict --stress-manifest "<stress-summary-manifest>" --commands-file "<commands-ready-md>" --bundle-manifest "<bundle-summary-manifest>" --readiness-manifest "<readiness-summary-manifest>" --max-age-seconds 21600
```

Saida padrao:

- `distributor/logs/cen05-preflight-<timestamp>/summary.md`
- `distributor/logs/cen05-preflight-<timestamp>/summary.manifest.json`

Interpretacao operacional:

- `preflight_ok=1`: seguir para abertura monitorada de mercado.
- `preflight_ok=0`: bloquear abertura e executar os `next_step` emitidos por check (`artifacts`, `thresholds`, `commands`, `env_doctor`).
- `operational_messages`: trilha objetiva `PREOPEN-GO`/`PREOPEN-BLOCK` para handoff direto operador -> observabilidade.
- checks adicionais de pre-open: `bundle`, `readiness`, `freshness` (janela temporal dos artefatos).
- `env_doctor` cobre precondicoes minimas de abertura: variaveis da sessao real, path de DLL (`PQ_PROFIT_DLL_PATH`), scripts locais obrigatorios e dependencias runtime basicas (`python`, `powershell`, `pytest`).
- `summary.manifest.json` agora inclui `remediation_plan` por falha de `env_doctor` com: causa, acao recomendada, comando sugerido e criterio de saida.

Saida padrao:

- `distributor/logs/ovr-stab-field-bundle-<timestamp>/summary.md`
- `distributor/logs/ovr-stab-field-bundle-<timestamp>/summary.manifest.json`
- `distributor/logs/ovr-stab-field-bundle-<timestamp>/field_execution.checklist.md`
- `distributor/logs/ovr-stab-field-bundle-<timestamp>/commands.ready.md`
- `distributor/logs/ovr-stab-field-bundle-<timestamp>/step_*.stdout.log`
- `distributor/logs/ovr-stab-field-bundle-<timestamp>/step_*.stderr.log`

O runner executa e consolida:

1. `run_overlay_ws_stress_regression.py` (CEN-05 local/stress).
2. `run_ovr_stab_qa_evidence.py --strict --mode field-ready` com foco em `OVR-STAB-QA-02..05` + `OVR-STAB-OBS-09`.
3. `verify_ovr_stab_g8_readiness.py` para classificar gaps local/campo.

Leitura recomendada da saida do checker `verify_ovr_stab_g8_readiness.py`:

1. Comecar pelo bloco curto `Executive short output` em `summary.md` (`status=PASS/FAIL` + `top_blockers`).
2. Para automacao, consumir `summary.manifest.json -> executive_summary` (sem parse de texto).
3. Em caso de `FAIL`, usar `scenario_results[*].gaps` e `field_validation.issues` para detalhamento tecnico completo.
4. Manter o manifesto completo como fonte de auditoria (`classification_counts`, `scenario_results`, `report_contract`, `field_report_validation`).

Variantes operacionais:

```bash
python scripts/run_ovr_stab_field_bundle.py --strict --field-report "<path>/field_report.json"
python scripts/run_ovr_stab_field_bundle.py --skip-stress --skip-local-qa
python scripts/run_ovr_stab_field_bundle.py --duration-scale 0.5 --frame-scale 0.75
```

Fixture realista CEN-02 (preenchimento assistido) gerado automaticamente no bundle:

- `distributor/logs/ovr-stab-field-bundle-<timestamp>/cen02.field_report.fixture.json`
- `distributor/logs/ovr-stab-field-bundle-<timestamp>/cen02.field_report.fixture.integrity.json`

Uso pratico rapido:

1. Executar `python scripts/run_ovr_stab_field_bundle.py --strict`.
2. Copiar o bloco `scenarios.CEN-02` do fixture para o `field_report` consolidado da sessao.
3. Substituir os `artifact://...` por refs reais coletadas na sessao.
4. Confirmar `integrity.ok=1` no arquivo `cen02.field_report.fixture.integrity.json`.
5. Rodar readiness final com `--field-report` apontando para o report consolidado.

Saida padrao:

- `distributor/logs/ovr-stab-field-qa-<timestamp>/summary.md`
- `distributor/logs/ovr-stab-field-qa-<timestamp>/commands.md`
- `distributor/logs/ovr-stab-field-qa-<timestamp>/qa_session.manifest.json`

## Tooling local reforcado (AUD-04/AUD-05/QA-04/OBS-09)

Executar primeiro o runner local para gerar infraestrutura de evidencias:

```bash
python scripts/run_ovr_stab_qa_evidence.py
```

Validacao estrutural automatizada (falha se artefato/checklist vier incompleto):

```bash
python scripts/run_ovr_stab_qa_evidence.py --strict --mode field-ready --require-ovr OVR-STAB-OBS-09 --require-ovr OVR-STAB-QA-04
```

Validacao endurecida da matriz CEN-04 (falha para matriz incompleta/invalida):

```bash
python scripts/run_ovr_stab_qa_evidence.py --strict --require-ovr OVR-STAB-QA-04 --require-ovr OVR-STAB-OBS-09
```

Novos artefatos obrigatorios:

- `distributor/logs/ovr-stab-qa-evidence-<timestamp>/target_protocols.manifest.json`
- `distributor/logs/ovr-stab-qa-evidence-<timestamp>/target_protocols.checklist.md`

Uso esperado:

1. Abrir `target_protocols.checklist.md`.
2. Preencher checklist de `OVR-STAB-AUD-04` (60s parado) e `OVR-STAB-AUD-05` (zoom/escala).
3. Executar matriz de `OVR-STAB-QA-04` (100/125/150) no bloco "matriz DPI".
4. Consolidar causa/sinal/proximo passo para `OVR-STAB-OBS-09`.

O runner nao falha por falta de pre-requisito externo: ele registra bloqueios em cada tarefa (`state=blocked`) com mensagem clara.

## Sessao guiada 60-120s (pregao)

Preparacao assistida sem depender de execucao automatica imediata:

```bash
powershell -ExecutionPolicy Bypass -File scripts/run-pregao-assisted-session.ps1 -DurationSec 90 -DryRun
```

Saida padrao:

- `distributor/logs/pregao-assisted-session-<timestamp>/status_snapshot.json`
- `distributor/logs/pregao-assisted-session-<timestamp>/config_snapshot.json`
- `distributor/logs/pregao-assisted-session-<timestamp>/operator_checklist.md`
- `distributor/logs/pregao-assisted-session-<timestamp>/commands.md`
- `distributor/logs/pregao-assisted-session-<timestamp>/operator_notes.md`
- `distributor/logs/pregao-assisted-session-<timestamp>/session.manifest.json`

Fluxo integrado gerado em `commands.md`:

1. `run_ovr_stab_field_qa.py` (pre-flight field QA)
2. `collect_ocr_overlay_trace_60s.py` (janela curta de trace)
3. `run-m6-m7-evidence.ps1` (referencia opcional M6/M7)

## Modo sessao manual assistida

Quando houver sessao real pronta (pregao/replay valido), executar:

```bash
python scripts/run_ovr_stab_field_qa.py --assume-manual-ready
```

## Coleta de trace para evidencia

```bash
python scripts/collect_ocr_overlay_trace_60s.py --duration-sec 60
```

Opcionalmente forcar caminho:

```bash
python scripts/collect_ocr_overlay_trace_60s.py --duration-sec 60 --trace-path "distributor/logs/ocr_overlay_trace.jsonl"
```

## Checklist operacional por tarefa

### OVR-STAB-QA-02

- aplicar zoom in/out e ajuste de eixo vertical no Profit
- observar transicoes `SUSPECT`, `RECALIBRATING`, `FROZEN`
- validar retorno para estado estavel apos confirmacao multi-frame

Roteiro operacional enxuto (execucao imediata):

1. Gerar artefatos locais: `python scripts/run_ovr_stab_qa_evidence.py`.
2. Abrir `distributor/logs/ovr-stab-qa-evidence-<timestamp>/target_protocols.checklist.md`.
3. Preencher bloco `CEN-02 - passos operacionais` para cada acao de zoom/escala.
4. Preencher bloco `CEN-02 - captura de transicoes obrigatorias` para `SUSPECT`, `FROZEN`, `RECALIBRATING`.
5. Para cada transição CEN-02, preencher pacote mínimo de evidência: `screenshot_ref`, `trace_ref`, `status_endpoint_ref`, `expected_vs_observed`.
6. Marcar aceite somente se todos os itens abaixo estiverem com evidencias:
   - transicoes obrigatorias observadas;
   - retorno para `STABLE` apos evento;
   - `drift_px_max <= 3.0` apos estabilizacao;
   - `evidence_ref` por transicao.

### OVR-STAB-QA-03

- degradar OCR (contraste baixo/oclusao parcial no eixo)
- confirmar preservacao de `last_stable_axis` (conceito: `lastStableAxis`) durante degradacao
- registrar indicadores de `confidence`, `residual_px`, `bad_frames`
- executar fluxo direto orientado ao operador: `baseline_check -> inject_degradation -> confirm_protection -> recover_signal`
- usar os exemplos `CEN-03-INC-EX-001` e `CEN-03-INC-EX-002` como referencia de preenchimento do incidente

Helper para montar `incident_packages` por incidente com `expected/observed` por canal:

```bash
python scripts/cen03_incident_packages.py --incident-id CEN-03-INC-001 --symptom "OCR degradado durante oclusao parcial" --suspected-root-cause "oclusao no eixo de preco" --action-taken "recuperacao de sinal e retorno STABLE" --transition "STABLE->FROZEN|RECALIBRATING" --transition "FROZEN|RECALIBRATING->STABLE" --evidence-ref "artifact://cen03/inc001-screenshot" --evidence-ref "artifact://cen03/inc001-trace" --evidence-ref "artifact://cen03/inc001-log" --hud-expected "axis_status=FROZEN ao degradar OCR" --hud-observed "axis_status=FROZEN com preservacao lastStableAxis" --hud-evidence-ref "artifact://cen03/inc001-hud" --status-expected "bad_frames>0 durante degradacao e queda na recuperacao" --status-observed "bad_frames=7 durante degradacao e bad_frames=0 apos recovery" --status-evidence-ref "artifact://cen03/inc001-status" --trace-expected "transicoes STABLE->FROZEN|RECALIBRATING e retorno para STABLE registradas" --trace-observed "transicoes registradas no trace com recovery concluido" --trace-evidence-ref "artifact://cen03/inc001-trace-jsonl" --out distributor/logs/cen03-incident_packages.json --field-report-out distributor/logs/cen03-field-report-fragment.json --strict
```

### OVR-STAB-QA-04

- executar em monitores/DPI: 100, 125, 150 (um registro por monitor na matriz)
- seguir passos de reprodução na ordem:
  - `open_window_on_baseline_monitor`
  - `move_window_to_next_monitor`
  - `minimize_window_on_target_monitor`
  - `restore_window_on_target_monitor`
  - `move_window_back_to_baseline_monitor`
- anexar evidencia por monitor, por passo e por DPI
- preencher a matriz DPI no `target_protocols.checklist.md` com `drift_px`, `drift_band` e `evidence_ref`
- preencher tabela de passos com `axis_status_before/after` para cada transição física

### OVR-STAB-QA-05

- elevar carga com targets/histograma ativos
- verificar responsividade da UI e ausencia de fila crescente
- coletar sinais de throughput e estabilidade
- executar validacao strict com manifesto de carga anexado

Pacote operacional imediato CEN-05 (mercado real):

1. `python scripts/run_overlay_ws_stress_regression.py --duration-scale 1.0 --frame-scale 1.0`
2. `python scripts/run_ovr_stab_qa_evidence.py --strict --mode field-ready --require-ovr OVR-STAB-QA-05 --require-ovr OVR-STAB-OBS-09 --cen05-stress-manifest "<path>/summary.manifest.json"`
3. anexar no bundle de evidencias: `stress.csv`, `summary.md`, `summary.manifest.json`, `target_protocols.manifest.json`, `target_protocols.checklist.md`

## Execucao imediata em campo (passo-a-passo)

1. Executar `python scripts/run_ovr_stab_qa_evidence.py`.
2. Abrir `distributor/logs/ovr-stab-qa-evidence-<timestamp>/target_protocols.checklist.md`.
3. Preencher `CEN-01` e `CEN-02` no bloco de checklist antes de iniciar a sessao manual.
4. Rodar sessao manual no Profit/replay e preencher `CEN-03`, `CEN-04` e `CEN-05`.
5. Para cada incidente, preencher obrigatoriamente: `symptom`, `suspected_root_cause`, `observed_signal`, `next_action`, `evidence_ref`.
6. Fechar a sessao somente quando cada cenario estiver com `resultado` definido em `pass`, `fail` ou `blocked`.

Gate operacional minimo:

- `summary.manifest.json` com `overall_ok=1`.
- `target_protocols.manifest.json` e `target_protocols.checklist.md` existentes e nao vazios.
- Matriz DPI (`100/125/150`) preenchida com `drift_px` e `evidence_ref`.
- Bloco de passos de reprodução (`mover/minimizar/restaurar/troca`) preenchido no checklist.
- Nenhum `blocked` sem `owner`, `eta` e `next_action`.

## Pendencias que exigem pregao/monitor real

- validacao conclusiva de `OVR-STAB-QA-02` com feed real
- validacao conclusiva de `OVR-STAB-QA-03` com condicao real de OCR degradado
- `OVR-STAB-QA-04` em setup multi-monitor real (100/125/150)
- `OVR-STAB-QA-05` com carga operacional real em horario de mercado

## Checklist final padronizado por cenario

### Formato obrigatorio por execucao

- scenario_id:
- ovr_ids:
- session_type: (`local-assisted` | `manual-field`)
- operator:
- date_utc:
- environment:
  - profit_version:
  - app_commit:
  - distributor_commit:
  - frontend_commit:
  - tauri_commit:
  - monitor_topology: (`single` | `multi`)
  - dpi_matrix_target: [100,125,150]
- preconditions:
  - [ ] feed/replay valido
  - [ ] overlay ativo
  - [ ] endpoints `/debug` e `/status` respondendo
  - [ ] gravacao de evidencia iniciada
- steps_executed:
- objective_acceptance:
- observed_metrics:
  - axis_status_transitions:
  - bad_frames_max:
  - pending_count_max:
  - residual_px_p95:
  - max_error_px_p95:
  - drift_px_max:
  - ws_publish_interval_ms_p95:
  - ui_frame_drop_events:
- evidence_refs:
  - summary_manifest:
  - trace_jsonl:
  - screenshot_or_video:
  - test_logs:
- result: (`pass` | `fail` | `blocked`)
- blocker_reason:
- suspected_root_cause:
- next_action:
- reviewed_by:

### Padrao unico de nomeacao de artefatos

Formato:

- `ovr-stab-<scenario_id>-<artifact_kind>-<utc_compact>.<ext>`

Exemplos obrigatorios por incidente:

- `ovr-stab-CEN-03-screenshot-20260430T174500Z.png`
- `ovr-stab-CEN-03-trace-20260430T174500Z.jsonl`
- `ovr-stab-CEN-03-log-snippet-20260430T174500Z.txt`

Regras:

- `scenario_id` deve corresponder ao bloco de checklist (`CEN-01..CEN-05`).
- `artifact_kind` permitido: `screenshot`, `video`, `trace`, `log-snippet`, `manifest-ref`.
- `utc_compact` em UTC no formato `YYYYMMDDTHHMMSSZ`.

### CEN-01 Parado (`OVR-STAB-AUD-04`, `OVR-STAB-QA-01`)

- `drift_px_max <= 2.0` por 60s.
- sem salto unico maior que `4px`.
- `axis_status=STABLE` em mais de `95%` dos frames.
- `overall_ok=1` no manifesto local.

### CEN-02 Zoom/escala (`OVR-STAB-AUD-05`, `OVR-STAB-QA-02`)

- transicao observavel `SUSPECT/RECALIBRATING -> STABLE`.
- reposicionamento apenas apos confirmacao multi-frame.
- sem oscilacao persistente apos estabilizacao (`drift_px_max <= 3.0`).
- evento de transicao com `evidence_ref` obrigatorio.
- pacote de evidência por transição obrigatório (`screenshot_ref`, `trace_ref`, `status_endpoint_ref`, `expected_vs_observed`).
- validacao automatica exige `transition_evidence` por estado (`SUSPECT`, `FROZEN`, `RECALIBRATING`) com `observed=true` e campos especificos:
  - `SUSPECT`: `trigger_action`, `observed_at_utc`
  - `FROZEN`: `freeze_duration_ms`, `observed_at_utc`
  - `RECALIBRATING`: `stable_return_ref`, `observed_at_utc`

### CEN-03 OCR ruim (`OVR-STAB-QA-03`)

- degradacao deve entrar em `FROZEN` ou `RECALIBRATING`.
- preservar `last_stable_axis` sem salto abrupto.
- registrar `confidence` baixo e/ou `residual_px` alto.
- recuperar para `STABLE` sem reposicionamento espurio.
- seguir protocolo padronizado de injeção/observação em 5 passos (`baseline -> injetar -> congelar/recalibrar -> preservar eixo -> recuperar`).
- seguir fluxo operacional direto (4 etapas) no checklist para reduzir ambiguidade de execução em campo.
- preencher template de evidência CEN-03 com `symptom`, `suspected_root_cause`, `action_taken` e sinais por canal (`HUD`, `status endpoint`, `trace JSONL`).
- exigir pacote minimo por incidente: `incident_id`, 3 `evidence_ref` (screenshot/trace/log-snippet), comparativo `expected_vs_observed` por canal.
- validar transicoes obrigatorias no incidente: `STABLE->FROZEN|RECALIBRATING` e `FROZEN|RECALIBRATING->STABLE`.

### CEN-04 Multi-monitor DPI (`OVR-STAB-QA-04`)

- evidencias individuais para `100/125/150`.
- mudanca fisica de monitor gera recalibracao controlada.
- `drift_px_max <= 3.0` apos estabilizacao em cada DPI.
- bounds e ROI coerentes em todos os monitores.

### CEN-05 Carga (`OVR-STAB-QA-05`)

- sem backlog crescente de fila durante janela de teste.
- UI responsiva sem congelamento perceptivel.
- throttle/publicacao com `ws_publish_interval_ms_p95` registrado.
- sem perda critica de atualizacao de linhas prioritarias.

Thresholds objetivos (pacote CEN-05):

- `queue_max <= 1`
- `backlog_growth_ratio <= 1.5`
- `latency_p95_ms <= 60.0`
- `latency_p99_ms <= 120.0`
- `consumer_fps >= 90.0`
- `publish_rate_floor_ratio >= 0.75`
- `publish_rate_overshoot_ratio <= 1.15`
- `publish_interval_jitter_cv <= 0.35`

## Registro de lacunas manuais

- pendencias_abertas:
  - [ ] pregao real pendente
  - [ ] replay representativo pendente
  - [ ] bancada multi-monitor fisica pendente
  - [ ] telemetria de carga real pendente
- impacto_no_gate:
  - gate_id:
  - bloqueia_aprovacao_final: (`sim` | `nao`)
- owner:
- eta:
- criterio_de_saida_da_lacuna:

## Validacoes automaticas disponiveis

Comando recomendado para pacote CEN-03:

```bash
python scripts/run_ovr_stab_qa_evidence.py --strict --require-ovr OVR-STAB-QA-03 --require-ovr OVR-STAB-OBS-09
```

O que este comando valida automaticamente:

- estrutura de artefatos (`summary.*`, `target_protocols.*` e logs por suite);
- protocolo CEN-03 no manifesto (`injection_protocol_steps`);
- mapa de sinais por canal (`HUD`, `status endpoint`, `trace JSONL`);
- template mínimo de explicabilidade (`symptom`, `root cause`, `action`, `evidence_ref`).
- pacote CEN-03 por incidente (`incident_id`) com comparativo `expected_vs_observed` por canal.
- completude mínima de trace para diagnóstico de campo:
  - sessão/evento (`event`, `event_id`, `session_id`);
  - frame (`seq`, `frame_seq`, `ts`, `timestamp_utc`, `status`);
  - `render_indicators` (`line_count_total`, `line_count_visible`, `line_count_out_of_bounds`);
  - `status_transition` (`from`, `to`, `changed`).
- contrato estrutural CEN-04:
  - matriz obrigatória com `monitor_id`, `dpi_percent`, `transition` por linha;
  - `monitor_id` único por linha da matriz;
  - `dpi_percent` inteiro válido e cobertura exata `100/125/150`;
  - `transition` restrito a `baseline-open` e `move-to-monitor`.

Formato recomendado no `field_report` para o runner consolidado:

```json
{
  "scenarios": {
    "CEN-03": {
      "incident_packages": [
        {
          "incident_id": "CEN-03-INC-001",
          "expected_vs_observed_by_channel": {
            "hud": { "expected": "axis_status=FROZEN", "observed": "axis_status=FROZEN" },
            "status_endpoint": { "expected": "bad_frames>0", "observed": "bad_frames=3" },
            "trace_jsonl": { "expected": "transition logged", "observed": "transition logged" }
          }
        }
      ]
    }
  }
}
```
