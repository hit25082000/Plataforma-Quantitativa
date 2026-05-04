# Plano — Overlay top avg com sigla sempre

## Objetivo
Garantir que os labels de `top_player_avg_lines` no overlay exibam sempre a sigla/nome curto da corretora quando disponível, evitando ID numérico como identificação principal.

## Escopo
- `frontend/src/pages/OverlayPage.tsx` (render de labels em `TopPlayerAvgLinesLayer`)

## Passos
1. Identificar o ponto exato onde o label é definido para `top_player_avg_lines`.
2. Alterar a composição do label para priorizar `player_name` (sigla resolvida no publisher).
3. Manter fallback seguro para casos sem `player_name`.
4. Validar tipagem/lint do arquivo alterado.
5. Revisar risco visual e consistência de modos (`total`, `buy`, `sell`, `net`).

## Critérios de aceite
- Quando `player_name` existir, o label mostrado no overlay usa a sigla e não ID.
- Quando `player_name` não existir, o componente segue com fallback atual sem quebrar render.
- Sem erros de lint novos no arquivo modificado.
