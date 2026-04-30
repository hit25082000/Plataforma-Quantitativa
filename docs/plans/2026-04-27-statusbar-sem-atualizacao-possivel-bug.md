# Plano de correção — StatusBar "SEM ATUALIZAÇÃO: POSSÍVEL BUG"

## Objetivo
Evitar falso positivo no status vermelho quando o mercado está ativo e há atualização, mas a comparação entre ticker selecionado e ticker do stream diverge por formatação.

## Escopo
- Arquivo alvo: `frontend/src/components/layout/StatusBar.tsx`
- Sem alterações de backend.

## Hipótese principal
- `selectedTicker` vem no formato de UI (ex.: `WINFUT · BMF`).
- `streamingTicker` vem do feed (ex.: `WINFUT`, `winfut`, com possíveis espaços/sufixos).
- A comparação literal atual pode disparar `POSSÍVEL BUG` mesmo com stream correto.

## Passos
1. Criar normalizador local para símbolo de ticker (trim, uppercase, remoção de sufixo de exchange/UI).
2. Aplicar normalização em `streamingTicker` e `selectedSymbol` antes das comparações de mismatch/match.
3. Manter mensagens e regras atuais; alterar apenas critério de igualdade.
4. Rodar checagem de lint nos arquivos alterados.

## Critérios de aceite
- Com mercado ativo e stream do mesmo ativo, o status não deve ficar em `SEM ATUALIZAÇÃO: POSSÍVEL BUG` por diferença de formatação.
- Caso o stream esteja realmente em outro ativo, o alerta vermelho deve permanecer.
