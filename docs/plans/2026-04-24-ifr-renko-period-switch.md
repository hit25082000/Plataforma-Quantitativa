# Plano: IFR em 42R/16R apos troca de periodo

## Objetivo
Corrigir o IFR para continuar atualizando quando a serie muda entre 30m, 42R e 16R.

## Diagnostico
- O frontend envia a serie desejada no warm-up, mas o endpoint `/api/warm-macd` ainda nao aplica esse parametro.
- Ao sair de 30m para Renko, o distributor limpa os tijolos Renko em memoria e nao recarrega/reconstroi a serie para o ticker ja ativo.
- O resultado pratico e que 30m volta com dados, enquanto 42R/16R podem ficar sem valor util ou presos no fallback inicial.

## Plano de mudanca
1. Ajustar `distributor/candle_macd.py` para reidratar/reconstruir o estado Renko dos tickers ja carregados quando a serie IFR mudar para 42R ou 16R.
2. Ajustar `distributor/websocket_server.py` para aceitar `series` em `/api/warm-macd` e sincronizar o modo antes de gerar o snapshot.
3. Adicionar testes focados em troca 30m -> 42R/16R e no warm-up com `series`.
4. Rodar testes Python do distributor relacionados ao caminho alterado.

## Validacao
- `rtk pytest distributor/tests/...`
- Checagem manual via `CandleMacd`: 30m, 42r e 16r devem retornar `ifr_series` correto e IFR diferente do fallback quando houver dados historicos suficientes.
