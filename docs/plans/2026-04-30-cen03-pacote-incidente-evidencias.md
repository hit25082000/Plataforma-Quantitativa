# Plano - reforco do pacote CEN-03 por incidente

Data: 2026-04-30  
Status: em execucao (solicitacao direta no chat)

## Objetivo

Reduzir erro humano na coleta CEN-03 com pacote padronizado por `incident_id`, validacao de `expected_vs_observed` por canal e gates automaticos no runner final.

## Escopo

1. Estruturar validacao do pacote CEN-03 no runner `run_ovr_stab_field_bundle.py`.
2. Exigir presenca de comparativo `expected_vs_observed` para canais obrigatorios (`hud`, `status_endpoint`, `trace_jsonl`).
3. Propagar lacunas para `manual_gaps`, `summary.md` e `summary.manifest.json`.
4. Atualizar testes unitarios do runner cobrindo casos validos e invalidos.
5. Atualizar documentacao operacional de execucao para refletir o formato esperado.

## Formato alvo (field report)

- Caminho esperado: `scenarios.CEN-03.incident_packages`.
- Cada item deve conter:
  - `incident_id`;
  - `expected_vs_observed_by_channel` com chaves `hud`, `status_endpoint`, `trace_jsonl`;
  - para cada canal, campos `expected` e `observed` nao vazios.

## Validacao planejada

- `python -m unittest distributor.tests.test_run_ovr_stab_field_bundle`
- `python scripts/run_ovr_stab_field_bundle.py --skip-stress --skip-local-qa --out-dir distributor/logs/ovr-stab-field-bundle-cen03-validation-smoke`

## Criterios de aceite

- Runner marca falha objetiva quando faltar `incident_id` ou comparativo por canal.
- Manifesto final lista gaps acionaveis por incidente/canal.
- Suite de testes do runner cobre os novos gates de validacao.
