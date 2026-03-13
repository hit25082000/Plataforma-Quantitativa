# Plataforma Quantitativa

**Vision:** Plataforma desktop de análise de microestrutura de mercado que processa dados de livro de ofertas e fluxo de ordens em tempo real, disparando alertas táticos baseados em 5 regras quantitativas para traders de day-trade no mercado brasileiro.
**For:** Traders de day-trade focados em microestrutura e fluxo de ordens (B3).
**Solves:** Sobrecarga cognitiva na leitura do DOM e Times & Trades, automatizando a detecção de padrões institucionais e pontos de inflexão com latência mínima.

## Goals

- Processar dados do DOM e T&T com latência < 5ms por tick (zero reprocessamento de dados)
- Disparar alertas visuais e sonoros em < 100ms após detecção de padrão
- Interface profissional que reduza carga cognitiva do trader (visual instantâneo, não textual)
- Instalação simples via arquivo .exe no desktop do trader

## Tech Stack

**Core:**

- Captura / Motor de Análise: C++ (Profit DLL - Nelogica)
- IPC: ZeroMQ (biblioteca embarcável, sem serviço externo)
- API de Distribuição: Python 3.12+ / FastAPI (WebSocket)
- Frontend: React + TypeScript
- Desktop: Tauri v2

**Key dependencies:**

- Profit DLL (Nelogica) para dados de mercado B3
- libzmq + cppzmq (C++) / pyzmq (Python) para IPC
- FastAPI + uvicorn para WebSocket server
- Tauri v2 para empacotamento desktop + instalador nativo

## Scope

**v1 includes:**

- Motor de análise C++ com 5 regras event-driven:
  - R1: Saldo de Agressão (divergência fluxo vs. preço)
  - R2: Muralhas ≥500 lotes + anti-spoofing (timer + validação T&T)
  - R3: VWAP Institucional contínua (soma incremental, sem recálculo)
  - R4: Renovação / Iceberg (reposição de ordens)
  - R5: Convergência multi-regra + IFR (alta convicção)
- Processadores de dados otimizados: DOM Snapshot e T&T Stream (cada dado processado uma única vez)
- Backend desacoplado: C++ → ZeroMQ → FastAPI → WebSocket
- UI profissional: feed de alertas tático, heatmap do livro (estilo Bookmap), painel de agressão dinâmico
- Notificações Windows nativas + alertas sonoros distintos por tipo de regra
- Instalador .exe single-machine para desktop do trader

**Explicitly out of scope:**

- Execução automática de ordens (autotrading)
- Suporte a múltiplas fontes de dados (apenas Profit DLL v1)
- Modo servidor / multi-usuário
- Backtesting ou replay de dados históricos
- Mobile ou acesso web remoto

## Constraints

- Timeline: Sem prazo fixo, desenvolvimento solo iterativo
- Technical: Dependência da Profit DLL (Windows-only); latência crítica no motor C++
- Resources: Desenvolvedor solo; stack escolhida priorizando manutenibilidade
- Deploy: Single machine (desktop do trader), Windows 10+, instalador .exe auto-contido
