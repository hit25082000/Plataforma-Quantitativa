# CEN-05 preflight validator

- preflight_ok: `0`
- preopen_status_code: `PREOPEN_BLOCKED`
- stress_manifest: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\overlay-ws-stress-regression-final-pass\summary.manifest.json`
- commands_file: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-field-bundle-cen03-semantic-check\commands.ready.md`
- bundle_manifest: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-field-bundle-cen03-semantic-check\summary.manifest.json`
- readiness_manifest: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-g8-readiness-20260430-152824\summary.manifest.json`

| check | status | preopen_status_code | details | next_step |
| --- | --- | --- | --- | --- |
| artifacts | PASS | OK | artefatos presentes em C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\overlay-ws-stress-regression-final-pass | nenhum |
| thresholds | PASS | OK | stress gate aprovado (overall_ok=true e gate.ok=true) | nenhum |
| commands | FAIL | COMMANDS_FILE_MISSING | commands.ready.md ausente | gerar bundle de campo: python scripts/run_ovr_stab_field_bundle.py --strict |
| bundle | FAIL | BUNDLE_MANIFEST_MISSING | bundle summary.manifest.json ausente | executar: python scripts/run_ovr_stab_field_bundle.py --strict |
| readiness | FAIL | READINESS_G8_OR_CEN05_FAILED | readiness nao aprovado para G8/CEN-05 (C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-g8-readiness-20260430-152824\summary.manifest.json) | reexecutar verify_ovr_stab_g8_readiness.py com evidencias de campo atualizadas |
| environment | FAIL | ENVIRONMENT_NOT_READY | vars ausentes: PROFIT_DLL_USER, PROFIT_DLL_PASSWORD, PQ_PROFIT_DLL_PATH | configurar variaveis de ambiente da sessao real e executar em host Windows |
| freshness | FAIL | FRESHNESS_WINDOW_EXCEEDED | artefatos fora da janela de pre-abertura (21600s) | regerar bundle/readiness/stress imediatamente antes da abertura |

## Mensagens operacionais

- PREOPEN-BLOCK: CEN-05 bloqueado ate correcoes obrigatorias.
- COMMANDS: gerar bundle de campo: python scripts/run_ovr_stab_field_bundle.py --strict
- BUNDLE: executar: python scripts/run_ovr_stab_field_bundle.py --strict
- READINESS: reexecutar verify_ovr_stab_g8_readiness.py com evidencias de campo atualizadas
- ENVIRONMENT: configurar variaveis de ambiente da sessao real e executar em host Windows
- FRESHNESS: regerar bundle/readiness/stress imediatamente antes da abertura

## Proximos passos operacionais

- P1 `COMMANDS_FILE_MISSING` | commands: gerar bundle de campo: python scripts/run_ovr_stab_field_bundle.py --strict | comando: `python scripts/run_ovr_stab_field_bundle.py --strict` | criterio: commands com status PASS no proximo verify_cen05_preflight.
- P2 `BUNDLE_MANIFEST_MISSING` | bundle: executar: python scripts/run_ovr_stab_field_bundle.py --strict | comando: `python scripts/run_ovr_stab_field_bundle.py --strict` | criterio: bundle com status PASS no proximo verify_cen05_preflight.
- P3 `READINESS_G8_OR_CEN05_FAILED` | readiness: reexecutar verify_ovr_stab_g8_readiness.py com evidencias de campo atualizadas | comando: `python scripts/verify_ovr_stab_g8_readiness.py --strict` | criterio: readiness com status PASS no proximo verify_cen05_preflight.
- P4 `ENVIRONMENT_NOT_READY` | environment: configurar variaveis de ambiente da sessao real e executar em host Windows | comando: `set PROFIT_DLL_USER=... && set PROFIT_DLL_PASSWORD=... && set PQ_PROFIT_DLL_PATH=...` | criterio: environment com status PASS no proximo verify_cen05_preflight.
- P5 `FRESHNESS_WINDOW_EXCEEDED` | freshness: regerar bundle/readiness/stress imediatamente antes da abertura | comando: `python scripts/run_overlay_ws_stress_regression.py && python scripts/run_ovr_stab_field_bundle.py --strict && python scripts/verify_ovr_stab_g8_readiness.py --strict` | criterio: freshness com status PASS no proximo verify_cen05_preflight.
- P6 `PREOPEN_BLOCKED` | final_recheck: Reexecutar preflight estrito apos correcoes. | comando: `python scripts/verify_cen05_preflight.py --strict` | criterio: preflight_ok=true e preopen_status_code=PREOPEN_GO.
