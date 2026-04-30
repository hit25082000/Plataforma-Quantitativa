# Plano: loading no Times & Trades e status de pregao

## Objetivo
Adicionar indicador visual de loading no Times & Trades/Saldo e impedir que o status mostre "fora do pregao" enquanto o ativo ainda esta carregando.

## Plano de mudanca
1. Adicionar estado de loading de mercado/Times & Trades no `marketStore`.
2. Ligar esse loading na troca de ativo e desligar ao receber o primeiro dado de mercado do ativo.
3. Renderizar spinner compacto em `TopBrokersTable` quando o Times & Trades estiver aguardando dados.
4. Ajustar `StatusBar` para priorizar loading/aguardando dados antes da heuristica de fora do pregao.
5. Tratar `TESTE/SIM` como mercado sempre aberto na heuristica.

## Validacao
- `rtk npm run typecheck --prefix frontend`
- `rtk npm run build --prefix frontend`
