# Plataforma Quantitativa

**Vision:** Ecossistema desktop de ultra-baixa latência para análise de microestrutura de mercado, combinando motor C++ tick-by-tick com Copiloto de IA Conversacional em tempo real capaz de interpretar fluxo de ordens e interagir com o trader por voz, sustentado por memória de mercado via RAG vetorial.
**For:** Traders de day-trade focados em microestrutura e fluxo de ordens (B3).
**Solves:** Sobrecarga cognitiva na leitura do DOM e Times & Trades; ausência de memória contextual contínua; latência de IPC desnecessária; falta de interação natural (voz) com os dados de mercado.

## Goals

- Latência IPC Zero-Copy: comunicação Profit DLL → consumidores em microssegundos via memória compartilhada (substituir ZeroMQ)
- Interação IA em tempo real: resposta voz-para-voz entre 200ms e 500ms via WebRTC/Realtime API
- Memória de mercado (RAG): busca vetorial em janelas de 5 minutos de histórico de fluxo em < 10ms
- Zero perda de pacotes: processamento tick-by-tick sem interrupções de context switching do SO
- Processar dados do DOM e T&T com latência < 5ms por tick (mantido de v1)
- Interface profissional que reduza carga cognitiva do trader (mantido de v1)

## Tech Stack

**Core (v1 - estável):**

- Captura / Motor de Análise: C++ (Profit DLL - Nelogica)
- API de Distribuição: Python 3.12+ / FastAPI (WebSocket)
- Frontend: React 18 + TypeScript
- Desktop: Tauri v2 (Rust)
- State Management: Zustand

**Evolução v2 (planejado):**

- IPC: Memory-Mapped Files (`CreateFileMapping`/`MapViewOfFile` no Windows) + Lock-Free Ring Buffer
- IA Conversacional: OpenAI Realtime API (`gpt-4o-realtime-preview`) via WebRTC
- Streaming: Redpanda ou Apache Kafka para ingestão de eventos
- Banco Vetorial: Pinecone ou Vectara para embeddings de mercado
- Segredos: AWS KMS para gestão de chaves

**Key dependencies (v1 ativas):**

- Profit DLL (Nelogica) para dados de mercado B3
- libzmq + cppzmq (C++) / pyzmq (Python) para IPC atual
- FastAPI + uvicorn para WebSocket server
- Tauri v2 para empacotamento desktop

## Scope

**v1 (entregue):**

- Motor C++ com 6 regras event-driven (R1-R6)
- Processadores: DOM Snapshot e T&T Stream
- Backend: C++ → ZeroMQ → FastAPI → WebSocket
- UI: feed de alertas, heatmap, painel de agressão, MACD, Agent007
- Overlay transparente sobre Profit (OCR)
- Instalador .exe via Tauri/NSIS

**v2 (este PRD):**

- F1: Refatoração IPC para Memória Compartilhada (Zero-Copy)
- F2: Agente de IA Multimodal Conversacional (Copiloto por voz)
- F3: Arquitetura RAG em Tempo Real (memória estruturada de mercado)
- F4: Otimizações HFT de Hardware e SO Windows
- F5: Segurança e Governança de Chaves

**Explicitly out of scope:**

- Execução automática de ordens (autotrading)
- Suporte a múltiplas fontes de dados (apenas Profit DLL)
- Modo servidor / multi-usuário
- Backtesting ou replay de dados históricos
- Mobile ou acesso web remoto

## Constraints

- Timeline: 4 meses (1 fase por mês), desenvolvimento solo iterativo
- Technical: Windows-only (Profit DLL); Lock-Free Ring Buffer requer validação de concorrência rigorosa
- Resources: Desenvolvedor solo; priorizar features com maior impacto em latência primeiro
- Deploy: Single machine (desktop do trader), Windows 10+, mínimo i7/Ryzen 7, 16GB RAM
- Hardware recomendado: Intel i7/i9 ou Ryzen 7/9 3.6GHz+, conexão cabeada
