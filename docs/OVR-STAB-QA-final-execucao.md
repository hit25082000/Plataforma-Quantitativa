# OVR-STAB QA final - execucao assistida

Status: operacional (assistido/manual)
Atualizado em: 2026-04-29

## Escopo

Automatizar preparacao e evidencias de campo para:

- `OVR-STAB-QA-02`
- `OVR-STAB-QA-03`
- `OVR-STAB-QA-04`
- `OVR-STAB-QA-05`

## Runner principal

```bash
python scripts/run_ovr_stab_field_qa.py
```

Saida padrao:

- `distributor/logs/ovr-stab-field-qa-<timestamp>/summary.md`
- `distributor/logs/ovr-stab-field-qa-<timestamp>/commands.md`
- `distributor/logs/ovr-stab-field-qa-<timestamp>/qa_session.manifest.json`

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

### OVR-STAB-QA-03

- degradar OCR (contraste baixo/oclusao parcial no eixo)
- confirmar preservacao de `lastStableAxis` durante degradacao
- registrar indicadores de `confidence`, `residual_px`, `bad_frames`

### OVR-STAB-QA-04

- executar em monitores/DPI: 100, 125, 150
- mover janela entre monitores e validar bounds/overlay
- anexar evidencia por monitor e DPI

### OVR-STAB-QA-05

- elevar carga com targets/histograma ativos
- verificar responsividade da UI e ausencia de fila crescente
- coletar sinais de throughput e estabilidade

## Pendencias que exigem pregao/monitor real

- validacao conclusiva de `OVR-STAB-QA-02` com feed real
- validacao conclusiva de `OVR-STAB-QA-03` com condicao real de OCR degradado
- `OVR-STAB-QA-04` em setup multi-monitor real (100/125/150)
- `OVR-STAB-QA-05` com carga operacional real em horario de mercado
