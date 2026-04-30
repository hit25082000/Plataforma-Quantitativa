# Plano - CEN-05 preflight com env doctor de abertura

Data: 2026-04-30  
Status: proposto (aguardando aprovacao para execucao)

## Objetivo

Complementar o `scripts/verify_cen05_preflight.py` com um env doctor focado em abertura para:
- checar variaveis, paths e dependencias minimas;
- retornar plano de correcao por falha detectada;
- adicionar testes dedicados;
- integrar ao fluxo atual de `verify_cen05_preflight` sem quebrar contratos existentes.

## Escopo tecnico

1. **Novo check de env doctor**
   - Criar check dedicado (ex.: `env_doctor`) com validacoes de:
     - variaveis obrigatorias;
     - paths obrigatorios (DLL/artefatos locais minimos);
     - dependencias runtime essenciais para o fluxo de abertura.
   - Incluir codigo de status especifico por tipo de falha.

2. **Plano de correcao estruturado**
   - Para cada falha do env doctor, retornar:
     - causa resumida;
     - acao recomendada;
     - comando sugerido (quando aplicavel);
     - criterio de saida.
   - Integrar na secao `next_actions` e no `summary.md`.

3. **Integracao no preflight CEN-05**
   - Encadear o env doctor na lista de checks do `main`.
   - Manter comportamento de `--strict` e codigo de saida atual.
   - Preservar mensagens operacionais de bloqueio/liberacao para pre-abertura.

4. **Testes dedicados**
   - Expandir `distributor/tests/test_verify_cen05_preflight.py` com cenarios para:
     - vars ausentes;
     - path invalido/inexistente;
     - dependencia ausente;
     - sucesso completo do env doctor;
     - reflexo em `next_actions` e no `summary.md`.

## Arquivos previstos

- `scripts/verify_cen05_preflight.py`
- `distributor/tests/test_verify_cen05_preflight.py`

## Validacao prevista

- `python -m unittest distributor.tests.test_verify_cen05_preflight`
- `python scripts/verify_cen05_preflight.py --strict` (com ambiente de teste controlado)

## Dependencias manuais esperadas (saida final)

- Definicao de variaveis da sessao real no host de abertura.
- Garantia de paths locais obrigatorios (DLL/binarios) no operador.
- Confirmacao de ferramentas runtime minimas presentes no host alvo.
