# Plano: indicador visual de carregamento do IFR

## Objetivo
Mostrar um estado visual enquanto o IFR esta aguardando warm-up/recalculo apos troca entre 30m, 42R e 16R.

## Plano de mudanca
1. Adicionar no `marketStore` um estado de carregamento do IFR, com serie alvo e mensagem curta.
2. Atualizar `fetchWarmMacdSnapshot` para ligar/desligar esse estado durante tentativas de warm-up.
3. Ajustar `RenkoBrickSelector` para acionar o loading imediatamente ao trocar a serie.
4. Atualizar `IfrChart` para mostrar spinner/estado "carregando" quando o IFR da serie alvo ainda nao chegou.
5. Validar com typecheck/build do frontend.

## Validacao
- `rtk npm run typecheck --prefix frontend`
- `rtk npm run build --prefix frontend`
