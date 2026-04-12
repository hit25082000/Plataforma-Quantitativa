# AI Copilot (Multimodal Conversational Agent) Specification

## Problem Statement

A plataforma exige monitoramento visual constante de gráficos, overlays e feeds de alertas. O trader precisa interpretar visualmente múltiplos sinais simultâneos (DOM, T&T, regras R1-R6, MACD, fluxo de agressão) enquanto toma decisões em milissegundos. Não existe forma natural de perguntar "o que está acontecendo?" sem desviar os olhos do book. Um Copiloto de IA por voz permite interação hands-free e eyes-free com o estado do mercado em tempo real.

## Goals

- [ ] Latência voz-para-voz (fala do trader → resposta da IA falada) entre 200ms e 500ms
- [ ] IA com acesso em tempo real ao estado do motor C++ via Function Calling
- [ ] VAD com suporte a barge-in (trader interrompe → IA silencia e recalcula)
- [ ] Respostas contextuais: IA entende o estado atual das regras, agressão e book

## Out of Scope

- IA executando ordens de compra/venda (apenas informacional)
- Treinamento de modelo customizado (usa modelo pré-treinado via API)
- Transcrição/gravação permanente de conversas
- Suporte a idiomas além de português brasileiro

---

## User Stories

### P1: Conexão WebRTC com Realtime API ⭐ MVP

**User Story**: As a trader, I want to talk to the AI copilot using my microphone and hear responses through my speakers so that I can interact hands-free while monitoring the market.

**Why P1**: Sem conexão de áudio bidirecional, o copiloto não existe.

**Acceptance Criteria**:

1. WHEN trader clicks "Ativar Copiloto" THEN frontend SHALL establish WebRTC connection to OpenAI Realtime API (`gpt-4o-realtime-preview`)
2. WHEN connection is established THEN system SHALL show visual indicator (mic icon + "Copiloto ativo")
3. WHEN trader speaks THEN audio SHALL stream to the API with < 100ms transport latency
4. WHEN AI responds THEN audio SHALL play through the trader's default audio device
5. WHEN connection drops THEN system SHALL attempt reconnect with exponential backoff and show "Reconectando..."

**Independent Test**: Ativar copiloto, dizer "Olá, como está o mercado?", ouvir resposta da IA em < 500ms.

---

### P1: Function Calling — Estado do Motor ⭐ MVP

**User Story**: As a trader, I want to ask the AI "qual o saldo de agressão?" and get a real-time answer based on actual engine data so that I don't need to look at the screen.

**Why P1**: Sem dados reais, a IA é um chatbot genérico — o diferencial é acesso ao estado vivo.

**Acceptance Criteria**:

1. WHEN AI receives a question about market state THEN it SHALL invoke the appropriate function (e.g., `analyze_order_book`)
2. WHEN function is called THEN bridge SHALL read data from shared memory or distributor state and return structured result in < 50ms
3. WHEN AI receives function result THEN it SHALL synthesize a spoken response incorporating the data
4. WHEN function call fails THEN AI SHALL say "Não consegui acessar os dados no momento" instead of hallucinating

**Functions to expose (schema):**

- `analyze_order_book`: retorna desequilíbrio bid/ask, top corretoras, saldo de agressão
- `get_current_signal`: estado das regras R1-R6 (ativa, valor, direção)
- `get_wall_status`: muralhas ativas no DOM (preço, qtd, tempo, spoofing status)
- `get_vwap_position`: posição do preço relativo à VWAP institucional por corretora
- `get_macd_state`: sinal MACD atual (histograma, cruzamento, tendência)
- `get_flow_summary`: resumo de fluxo dos últimos N minutos

**Independent Test**: Perguntar "quem está agredindo mais?" com pregão ativo; validar que a resposta cita corretoras e valores coerentes com o que o painel de agressão mostra.

---

### P1: VAD e Barge-in ⭐ MVP

**User Story**: As a trader, I want to interrupt the AI mid-sentence so that it stops talking immediately and listens to my new question.

**Why P1**: Em HFT, o trader precisa de controle total do canal de áudio — não pode esperar a IA terminar.

**Acceptance Criteria**:

1. WHEN trader starts speaking while AI is talking THEN AI SHALL stop audio playback within 100ms
2. WHEN AI detects silence > `silence_duration_ms` (configurable, default 800ms) THEN it SHALL process the accumulated speech
3. WHEN trader is in a noisy environment THEN VAD sensitivity SHALL be configurable in settings

**Independent Test**: Ativar copiloto, fazer pergunta, interromper no meio da resposta com nova pergunta; verificar que IA para e responde à nova pergunta.

---

### P2: UI do Copiloto

**User Story**: As a trader, I want a visual panel showing the copilot status and recent interactions so that I have context of what was discussed.

**Why P2**: Visual feedback é importante mas não bloqueia a funcionalidade de voz.

**Acceptance Criteria**:

1. WHEN copilot is active THEN UI SHALL show: estado (ouvindo/processando/falando), waveform do áudio, últimas 5 interações em texto
2. WHEN a function call occurs THEN UI SHALL briefly flash the data source consulted (e.g., "Consultando saldo de agressão...")
3. WHEN trader hovers over a past interaction THEN it SHALL show the function calls and data that informed the response

**Independent Test**: Usar copiloto por 5 minutos; verificar que o painel lateral mostra histórico corretamente.

---

### P3: Push-to-Talk alternativo

**User Story**: As a trader, I want a push-to-talk mode (hold key to speak) as an alternative to always-listening so that I can control when the AI listens.

**Why P3**: Alguns traders preferem controle explícito; ambiente pode ser barulhento.

**Acceptance Criteria**:

1. WHEN push-to-talk mode is enabled THEN AI SHALL only listen while configured key is held
2. WHEN key is released THEN AI SHALL process the speech immediately

---

## Edge Cases

- WHEN OpenAI API is down THEN system SHALL show "Copiloto indisponível" and disable the mic button
- WHEN trader asks about an asset not currently subscribed THEN AI SHALL say "Não estou monitorando esse ativo no momento"
- WHEN multiple function calls are needed for one question THEN AI SHALL chain them and respond once with consolidated data
- WHEN audio device changes (e.g., headphone plugged in) THEN system SHALL auto-switch without restart
- WHEN pregão is closed THEN AI SHALL adjust responses accordingly ("Mercado fechado, últimos dados de...")

---

## Success Criteria

- [ ] Latência voz-para-voz p95 < 500ms
- [ ] Function Calling retorna dados coerentes com o estado visual da UI em 100% dos testes
- [ ] Barge-in interrompe áudio em < 100ms
- [ ] Sessão contínua de 2 horas sem degradação de latência ou desconexão
