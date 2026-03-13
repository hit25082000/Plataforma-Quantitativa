# Roadmap

**Current Milestone:** M5 - Desktop & Polish
**Status:** Planning

---

## M1 - Data Foundation

**Goal:** C++ capturando dados reais da Profit DLL, mantendo snapshot do livro em memória e publicando eventos via ZeroMQ.
**Target:** Fluxo de dados end-to-end funcionando (Profit DLL → C++ → ZeroMQ)
**Status:** COMPLETE

### Features

**Integração Profit DLL** - COMPLETE

- Conexão e autenticação com a DLL
- Callbacks de atualização do DOM (ofertas de compra/venda)
- Callbacks de negócios realizados (Times & Trades)
- Gestão de reconexão e heartbeat

**DOM Snapshot Engine** - COMPLETE

- Estrutura de dados em memória (arrays pré-alocados) para o livro de ofertas
- Atualização incremental por tick (nunca reprocessar)
- Rastreamento de corretora por nível de preço

**T&T Stream Processor** - COMPLETE

- Parsing de negócios com identificação de corretora compradora/vendedora
- Acumuladores contínuos: volume total, saldo de agressão, VWAP incremental
- Publicação de eventos via ZeroMQ (formato JSON)

---

## M2 - Rule Engine

**Goal:** As 5 regras operando como listeners event-driven sobre os processadores de dados.
**Target:** Alertas sendo gerados e publicados no ZeroMQ.
**Status:** COMPLETE

### Features

**Event Framework** - COMPLETE

- Sistema de eventos tipados (DOM update, trade, wall detected, etc.)
- Registro e dispatch de listeners com prioridade
- Pipeline: Processadores → Eventos → Regras → Alertas

**Regra 1: Saldo de Agressão** - COMPLETE

- Delta de agressão por corretora (compras agressivas - vendas agressivas)
- Detecção de divergência saldo vs. direção do preço (falso rompimento)

**Regra 2: Muralhas (≥500 lotes)** - COMPLETE

- Detecção de ordens ≥500 lotes no DOM
- Anti-spoofing: timer por ID de ordem no nível de preço
- Descarte silencioso se ordem some antes de X ms sem agressão no T&T

**Regra 3: VWAP Institucional** - COMPLETE

- VWAP contínua incremental por corretora (soma do novo tick ao acumulado)
- Detecção de acúmulo/distribuição relativo à VWAP do dia

**Regra 4: Renovação / Iceberg** - COMPLETE

- Detecção de reposição de ordens no mesmo nível de preço
- Correlação com corretoras identificadas no T&T

**Regra 5: Convergência + IFR** - COMPLETE

- Cruzamento de sinais entre múltiplas regras (multi-signal)
- Verificação de IFR para zonas de exaustão (sobrecompra/sobrevenda)
- Alerta de alta convicção quando há convergência

---

## M3 - Distribution Layer

**Goal:** API Python servindo alertas em tempo real para o frontend via WebSocket.
**Target:** Alertas chegando no frontend em <100ms após geração no C++.
**Status:** COMPLETE

### Features

**ZeroMQ Consumer** - COMPLETE

- Subscriber Python conectado ao publisher C++
- Deserialização e validação de mensagens JSON
- Buffer de reconexão

**WebSocket Server** - COMPLETE

- FastAPI com endpoint WebSocket
- Broadcast de alertas para clientes conectados
- Health check e reconexão automática

---

## M4 - Frontend Core

**Goal:** Interface React funcional exibindo alertas em tempo real com design tático.
**Target:** Trader visualiza alertas com distinção visual instantânea por tipo e convicção.
**Status:** COMPLETE

### Features

**Alert Feed Tático** - COMPLETE

- Cards de alerta em feed vertical (estilo timeline)
- Design progressivo: R5 (alta convicção) pisca em neon vermelho/verde; R2 (info) em cinza
- Timestamp, ativo, regra, dados de suporte em cada card

**Heatmap do Livro** - COMPLETE

- Visualização estilo Bookmap dos níveis de preço
- Cores quentes (vermelho escuro/laranja) para concentrações ≥500 lotes
- Atualização em tempo real sincronizada com DOM

**Painel de Agressão Dinâmico** - COMPLETE

- Gráfico de barras do Delta de Agressão em tempo real
- Top 3 corretoras compradoras / vendedoras
- Validação visual dos alertas disparados

---

## M5 - Desktop & Polish

**Goal:** Aplicação desktop instalável com notificações nativas e experiência completa.
**Target:** Arquivo .exe instalável, pronto para uso em produção no desktop do trader.

### Features

**Tauri Desktop App** - PLANNED

- Empacotamento React como app nativo Windows
- System tray integration
- Auto-start opcional com Windows

**Notificações e Sons** - PLANNED

- Notificações nativas do Windows (toast notifications)
- Sons distintos: grave para muralhas institucionais, agudo para rompimentos confirmados
- Volume e ativação configuráveis

**Instalador** - PLANNED

- Installer .exe via Tauri bundler (NSIS)
- Bundling de dependências (C++ engine, Python runtime, ZeroMQ)
- Setup wizard simples (próximo → próximo → instalar)

---

## Future Considerations

- Backtesting e replay de sessões gravadas
- Suporte a Cedro e outras fontes de dados além da Profit DLL
- Dashboard de performance (win rate por tipo de alerta)
- Modo multi-monitor / layout customizável pelo trader
- Alertas remotos via Telegram / Discord
- Múltiplos ativos simultâneos com abas
