# Sigla da corretora (VP SATO, overlay, T&T, mock, voz) — implementado

Referência: plano aprovado “Sigla corretora UI voz” (2026-05-04).

## Alterações

1. **Engine** — [`engine/src/zmq_publisher.cpp`](engine/src/zmq_publisher.cpp): `enrich_tape_intelligence_display_names` usa o resolver de **sigla** (`agent_short_name_resolver_` + `agent_short_name_cache_`), com fallback ao resolver de nome longo se o curto não existir.  
2. **Engine** — [`engine/src/profit_bridge.cpp`](engine/src/profit_bridge.cpp): `get_agent_short_name` tenta nome longo da DLL se a sigla vier vazia, antes de `#id`.  
3. **Distributor** — [`distributor/flow_tracker.py`](distributor/flow_tracker.py): prioridade `*_short_name` sobre `*_name` nos trades.  
4. **Distributor** — [`distributor/voice_realtime.py`](distributor/voice_realtime.py): instrução de sistema reforçando siglas ao citar corretoras.  
5. **Frontend** — [`frontend/src/components/AggressionPanel/TopBrokersTable.tsx`](frontend/src/components/AggressionPanel/TopBrokersTable.tsx): label sempre `short ?? full ?? #id`.  
6. **Frontend** — [`frontend/src/pages/OverlayPage.tsx`](frontend/src/pages/OverlayPage.tsx): `brokerDisplayName` trata `^#\d+$` como placeholder e usa `ID:${id}` com o id do jogador.  
7. **Mock TESTE** — Opção A: [`engine/include/mock_broker_catalog.h`](engine/include/mock_broker_catalog.h) com pares id + sigla; [`engine/src/mock_feed.cpp`](engine/src/mock_feed.cpp) e [`engine/src/main.cpp`](engine/src/main.cpp) alinhados.  
8. **Testes** — [`distributor/tests/test_flow_tracker.py`](distributor/tests/test_flow_tracker.py).

## Verificação

- `python -m pytest distributor/tests/test_flow_tracker.py`
- `engine\build\Debug\tape_intelligence_tests.exe`
