# Plano - G8 readiness com triagem automática

Data: 2026-04-30  
Status: auxiliar incorporado ao plano principal (encerrado nesta rodada)

## Vinculo de governanca

- Narrativa oficial de progresso e backlog foi consolidada em `docs/plans/2026-04-29-ocr-overlay-estavel-profit-tarefas.md`.
- Este arquivo permanece somente como registro auxiliar de desenho da triagem automatica de `G8`.
- Qualquer atualizacao de status/gaps/prioridade deve ocorrer apenas no plano principal para evitar duplicacao.

## Objetivo

Expandir `scripts/verify_ovr_stab_g8_readiness.py` para:

- gerar ranking de gaps com priorizacao pratica por impacto/esforco;
- emitir recomendacao operacional com template de `owner` e `eta`;
- manter artefatos de saida legiveis (`summary.md`) e estruturados (`summary.manifest.json`);
- cobrir comportamento novo com testes unitarios.

## Escopo de implementacao

1. **Modelo de triagem**
   - Definir score por gap com base em:
     - impacto (bloqueio de gate, risco operacional, abrangencia);
     - esforco estimado (baixo/medio/alto via heuristica por gap/scenario).
   - Ordenar gaps por prioridade pratica (maior impacto e menor esforco primeiro).

2. **Recomendacao operacional**
   - Incluir recomendacao por item com template:
     - `owner_suggested` (papel: QA / Runtime / Frontend / OCR / Platform);
     - `eta_template` (ex.: `D+1`, `D+2`, `D+5`);
     - `runbook_hint` (acao concreta curta para execucao).

3. **Artefatos**
   - Atualizar `summary.md` com secao:
     - "Gap triage ranking (impact x effort)";
     - "Operational recommendations".
   - Atualizar `summary.manifest.json` com:
     - `gap_triage_ranking` (lista ordenada com score e rationale);
     - `operational_recommendations` (owner/eta template por gap).

4. **Testes**
   - Expandir `distributor/tests/test_verify_ovr_stab_g8_readiness.py` para cobrir:
     - calculo e ordenacao do ranking;
     - mapeamento owner/eta por tipo de gap;
     - renderizacao das novas secoes no markdown;
     - persistencia dos novos campos no manifesto final.

## Arquivos-alvo

- `scripts/verify_ovr_stab_g8_readiness.py`
- `distributor/tests/test_verify_ovr_stab_g8_readiness.py`

## Validacao planejada

- `python -m unittest distributor.tests.test_verify_ovr_stab_g8_readiness`
- `python scripts/verify_ovr_stab_g8_readiness.py --out-dir "distributor/logs/ovr-stab-g8-readiness-triage-smoke"`

## Criterios de aceite

- Ranking de gaps aparece no `summary.md` com ordem deterministica.
- Manifesto JSON inclui ranking e recomendacoes operacionais.
- Testes unitarios novos e existentes da suite do verificador passam.
- Em `--strict`, comportamento de exit code atual e preservado.
