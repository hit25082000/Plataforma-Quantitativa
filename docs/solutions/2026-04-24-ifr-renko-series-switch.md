---
date: 2026-04-24
tags: [ifr, renko, distributor, warm-macd]
status: applied
---

# IFR Renko apos troca de periodo

## Sintoma
IFR continuava funcionando em 30m, mas perdia valor util ao trocar para 42R ou 16R.

## Causa
- O warm-up recebia a serie desejada, mas o distributor nao aplicava esse parametro antes do snapshot.
- Ao sair de 30m para Renko, o estado Renko do ticker ativo era limpo e ficava sem reidratacao imediata.

## Solucao
- `/api/warm-macd` aplica `series` antes de gerar o snapshot.
- A troca para 42R/16R recarrega/reconstroi os tijolos Renko para tickers ja ativos.
- Testes cobrem troca 30m -> 42R/16R e warm-up com `series`.

## Validacao
- `python -m unittest distributor.tests.test_ifr_series_switch -v`
- `python -m py_compile distributor\candle_macd.py distributor\websocket_server.py distributor\tests\test_ifr_series_switch.py`
- Smoke direto de `CandleMacd`: 30m, 42R e 16R retornaram IFR numerico.
