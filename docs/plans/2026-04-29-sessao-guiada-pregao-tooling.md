# Plano - sessão guiada de pregão (tooling)

## Objetivo

Criar fluxo de preparação de evidência para sessão real (60-120s), sem exigir execução imediata dos coletores.

## Etapas

1. Implementar runner Python que gere diretório de evidência, snapshots (status/config), checklist e manifesto detalhado.
2. Integrar o fluxo com scripts existentes (`run_ovr_stab_field_qa.py`, `collect_ocr_overlay_trace_60s.py`, `run-m6-m7-evidence.ps1`) via `commands.md`.
3. Criar wrapper PowerShell para uso operacional no pregão.
4. Atualizar documentação operacional e README com fluxo novo.
5. Validar em dry-run local e adicionar teste automatizado do novo runner.
