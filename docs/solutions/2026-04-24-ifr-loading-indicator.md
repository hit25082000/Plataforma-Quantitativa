---
date: 2026-04-24
tags: [ifr, frontend, loading-state, renko]
status: applied
---

# Loading visual do IFR

## Sintoma
Ao trocar a serie do IFR, o recarregamento podia levar alguns segundos sem sinal visual.

## Solucao
- Estado `ifrLoading` no store compartilhado.
- `fetchWarmMacdSnapshot` liga/desliga o loading durante o warm-up.
- Cards/widgets de IFR mostram spinner e estado "Atualizando".
- O seletor 42R/16R/30m tambem mostra spinner na serie ativa.

## Validacao
- `rtk npm run typecheck --prefix frontend`
- `rtk npm run build --prefix frontend`
