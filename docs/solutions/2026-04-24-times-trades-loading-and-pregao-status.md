---
date: 2026-04-24
tags: [frontend, times-trades, loading-state, status-bar]
status: applied
---

# Loading do Times & Trades e status de pregao

## Sintoma
Durante troca/carregamento de ativo, o status podia cair na heuristica de fora do pregao antes do primeiro dado chegar.

## Solucao
- Estado `timesTradesLoading` no store.
- Troca de ativo liga o loading do Times & Trades; primeiro trade ou snapshot de corretoras desliga.
- `TopBrokersTable` mostra spinner enquanto aguarda dados.
- `StatusBar` prioriza loading antes da heuristica de fora do pregao.
- `SIM/TESTE` nao e classificado como fora do pregao.

## Validacao
- `rtk npm run typecheck --prefix frontend`
- `rtk npm run build --prefix frontend`
