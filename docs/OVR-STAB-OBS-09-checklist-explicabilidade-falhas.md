# OVR-STAB-OBS-09 - Checklist de explicabilidade por logs

Status: concluida (cobertura local com testes/mocks)
Atualizado em: 2026-04-29

## Objetivo

Garantir que cada falha de alinhamento do overlay tenha causa observável em logs/artefatos, sem depender de sessão real do Profit para validação inicial.

## Evidências mínimas exigidas

- Artefato consolidado do runner local:
  - `summary.csv`
  - `summary.md`
  - `summary.manifest.json`
- Logs por suíte:
  - `<suite>.stdout.log`
  - `<suite>.stderr.log`
- Campos rastreáveis em payload/debug:
  - `axis_status`
  - `axis_source`
  - `bad_frames`
  - `confidence`
  - `residual_px`
  - `last_frame`
  - `debug_visual`

## Matriz falha -> explicação observável

| Sintoma | Causa provável | Sinal em log/manifesto | Cobertura local |
| --- | --- | --- | --- |
| Linha oscila em gráfico parado | Eixo mudou sem confirmação robusta | `axis_status` transitando para `RECALIBRATING`/`FROZEN`; `bad_frames` crescente | Sim (parcial) |
| Linha salta após OCR ruim | Candidate rejeitado e fallback aplicado | `confidence` baixo, `residual_px` alto, manutenção de `lastStableAxis` | Sim (parcial) |
| Endpoint de controle não responde | Proxy/rotas OCR indisponíveis | falha em suíte `qa_overlay_proxy_endpoints` | Sim (parcial) |
| Y de POC/VAL/VAH incoerente | Enriquecimento eixo->pixel degradado | falha em suíte `qa_enrich_overlay_axis_health` | Sim (parcial) |
| Diferença por monitor/DPI | Ajuste físico/lógico de bounds | ausência de evidência local automatizada | Não (pendente sessão real/multi-monitor) |

## Comando padrão de coleta local

```bash
python scripts/run_ovr_stab_qa_evidence.py
```

## Critério de aceite local

- `overall_ok=1` no `summary.manifest.json`.
- OVRs com estado `partial-done` no bloco `ovr_status`.
- Existência de logs por suíte e manifestos no diretório de saída.

## Fechamento operacional sem pregão real (2026-04-29)

- Endpoints `GET /api/ocr-overlay/debug` e `GET /api/ocr-overlay/status` passam a retornar `meta` com contexto operacional mínimo:
  - `ts`, `status`, `axis_status`, `axis_source`, `frame_seq`, `last_update`.
- Erros operacionais de endpoints OCR passam a retornar envelope padronizado (`error.code`, `error.message`, `error.details`) + `meta` com diagnóstico rápido.
- `POST /api/ocr-overlay/manual-calibration` retorna erro acionável com `manual_axis_invalid_points` e preview dos pontos recebidos quando os dados são inválidos.

## Lacunas conhecidas (não cobertas localmente)

- OVR-STAB-QA-04 (multi-monitor 100/125/150%).
- Parte de OVR-STAB-QA-02 e OVR-STAB-QA-05 dependente de sessão real do Profit/telemetria de carga real.
