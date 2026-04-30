# CEN-05 preflight validator

- preflight_ok: `0`
- stress_manifest: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\overlay-ws-stress-regression-final-pass\summary.manifest.json`
- commands_file: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-field-bundle-cen02-final-check\commands.ready.md`
- bundle_manifest: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-field-bundle-cen02-final-check\summary.manifest.json`
- readiness_manifest: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-g8-readiness-20260430-152029\summary.manifest.json`

| check | status | details | next_step |
| --- | --- | --- | --- |
| artifacts | PASS | artefatos presentes em C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\overlay-ws-stress-regression-final-pass | nenhum |
| thresholds | PASS | stress gate aprovado (overall_ok=true e gate.ok=true) | nenhum |
| commands | FAIL | commands.ready.md ausente | gerar bundle de campo: python scripts/run_ovr_stab_field_bundle.py --strict |
| bundle | FAIL | bundle summary.manifest.json ausente | executar: python scripts/run_ovr_stab_field_bundle.py --strict |
| readiness | FAIL | readiness nao aprovado para G8/CEN-05 (C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-g8-readiness-20260430-152029\summary.manifest.json) | reexecutar verify_ovr_stab_g8_readiness.py com evidencias de campo atualizadas |
| environment | FAIL | vars ausentes: PROFIT_DLL_USER, PROFIT_DLL_PASSWORD, PQ_PROFIT_DLL_PATH | configurar variaveis de ambiente da sessao real e executar em host Windows |
| freshness | FAIL | artefatos fora da janela de pre-abertura (21600s) | regerar bundle/readiness/stress imediatamente antes da abertura |

## Mensagens operacionais

- PREOPEN-BLOCK: CEN-05 bloqueado ate correcoes obrigatorias.
- COMMANDS: gerar bundle de campo: python scripts/run_ovr_stab_field_bundle.py --strict
- BUNDLE: executar: python scripts/run_ovr_stab_field_bundle.py --strict
- READINESS: reexecutar verify_ovr_stab_g8_readiness.py com evidencias de campo atualizadas
- ENVIRONMENT: configurar variaveis de ambiente da sessao real e executar em host Windows
- FRESHNESS: regerar bundle/readiness/stress imediatamente antes da abertura

## Proximos passos

- commands: gerar bundle de campo: python scripts/run_ovr_stab_field_bundle.py --strict
- bundle: executar: python scripts/run_ovr_stab_field_bundle.py --strict
- readiness: reexecutar verify_ovr_stab_g8_readiness.py com evidencias de campo atualizadas
- environment: configurar variaveis de ambiente da sessao real e executar em host Windows
- freshness: regerar bundle/readiness/stress imediatamente antes da abertura
