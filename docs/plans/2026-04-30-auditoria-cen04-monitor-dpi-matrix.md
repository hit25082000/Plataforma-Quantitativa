# Plano - auditoria automatica CEN-04 monitor_dpi_matrix

## Objetivo

Adicionar um validador isolado para `monitor_dpi_matrix` e `drift_steps` (CEN-04), com saida acionavel para operador, testes unitarios e referencia no pack final.

## Etapas

1. Criar script dedicado `scripts/check_cen04_monitor_dpi_matrix.py` com:
   - validacao de contrato de `monitor_dpi_matrix` e `drift_steps`;
   - diagnostico acionavel (`issues` com acao);
   - geracao de `summary.md` + `summary.manifest.json`.
2. Integrar o script no bundle de campo (`scripts/run_ovr_stab_field_bundle.py`) para executar check isolado e incluir artifact na saida final.
3. Integrar referencia no pack final (`scripts/run_final_verification_pack.py`) para apontar explicitamente o comando/entrada CEN-04 no passo de readiness.
4. Adicionar testes unitarios em `distributor/tests` cobrindo:
   - caso PASS;
   - falhas de cobertura DPI/steps;
   - saida acionavel para operador.
5. Rodar os testes alvo e ajustar regressao.
