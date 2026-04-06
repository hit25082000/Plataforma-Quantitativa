# Skill: Observabilidade Tempo Real (Plataforma Quantitativa)

## Objetivo
Guiar o agente para observar as métricas essenciais e explicar rapidamente o comportamento do pipeline:
`DLL/Engine -> ZMQ -> Distributor -> WebSocket -> Frontend`.

Use esta skill quando o usuário pedir:
- análise de performance em tempo real
- investigação de "dashboard travando" ou "parou de atualizar"
- comparação com Times & Trades do Profit

---

## O mínimo que deve ser coletado
1. **Engine logs**
   - linha `ZmqPublisher Metrics`
   - campos:
     - `q_trade`
     - `q_normal`
     - `trade_latency_ms(avg/max)`
2. **Distributor logs**
   - linha `Pipeline health`
   - linha `Router metrics`
   - linhas de pressão de fila:
     - `Market queue full: dropped ... dom_snapshot`
     - `rescued ... trade-like`
3. **Sinal de backlog**
   - `Consume loop backlog=...`

Não colete métricas secundárias antes dessas.

---

## Leitura rápida (interpretação)

### 1) Atraso no engine
Se `q_trade` cresce **e** `trade_latency_ms(avg/max)` sobe:
- gargalo antes do distributor (engine não está drenando rápido o suficiente).

Se `q_normal` cresce e `q_trade` fica baixo:
- livro/dom está pesado, mas prioridade de trade está funcionando.

### 2) Perda/pressão no distributor
Se `dropped_dom` sobe e `rescued_trade_like` sobe:
- sistema está sob carga, mas protegendo trade.

Se `backlog` cresce continuamente **e** `route_avg_ms` sobe:
- `route()` está mais lento que entrada de mensagens.

Se `throttled_dom` sobe:
- throttle de DOM está atuando (esperado sob carga).

### 3) Sintoma na UI
Se backend saudável (`q_trade` baixo, backlog baixo) e UI com lag:
- provável custo de renderização/re-render no frontend.

---

## Diagnóstico em 3 passos
1. **Confirmar onde acumula**
   - engine (`q_trade/q_normal`) ou distributor (`backlog`).
2. **Confirmar custo de processamento**
   - `trade_latency_ms(avg/max)` e `route_avg_ms`.
3. **Confirmar política de proteção**
   - `dropped_dom` e `rescued_trade_like`.

Em seguida, retornar conclusão em 1 bloco:
- **Origem do gargalo**
- **Evidências (métricas)**
- **Ação imediata**

---

## Resposta padrão (curta)
Use este formato:

1. **Estado atual:** saudável | degradado | crítico  
2. **Onde está o gargalo:** engine | distributor | frontend  
3. **Evidências:** 3-5 métricas objetivas  
4. **Impacto em trade:** atraso | perda | sem perda  
5. **Próxima ação:** 1 ação de maior impacto

---

## Regras
- Não inventar números; usar apenas logs observados.
- Não propor refactor grande sem evidência nas métricas acima.
- Priorizar sempre preservação de `trade`.
