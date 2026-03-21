# Resumo do Projeto - Plataforma Quantitativa

## Visao Geral

A **Plataforma Quantitativa** e um sistema desktop para analise de microestrutura de mercado da B3 em tempo real.  
Ele coleta dados do livro de ofertas e do fluxo de negocios via Profit DLL, processa eventos quantitativos e entrega alertas taticos em uma interface desktop.

## Objetivo Principal

Transformar dados brutos de mercado em alertas acionaveis com baixa latencia, cobrindo:

- ingestao de dados de mercado em tempo real;
- deteccao de padroes por regras quantitativas;
- distribuicao em tempo real para clientes WebSocket;
- visualizacao tatico-operacional em frontend React;
- empacotamento como aplicativo desktop (Tauri + instalador Windows).

## Arquitetura (alto nivel)

O projeto segue um pipeline em 4 camadas:

1. **Engine (C++)**
   - integra com Profit DLL;
   - mantem snapshot de DOM e acumuladores T&T;
   - aplica regras event-driven (incluindo logica anti-spoofing);
   - publica eventos JSON via ZeroMQ (`tcp://localhost:5555`).

2. **Distributor (Python/FastAPI)**
   - consome eventos do ZeroMQ;
   - roteia mensagens para clientes WebSocket;
   - expoe endpoint WebSocket para consumo do frontend/app.

3. **Frontend (React + TypeScript + Vite)**
   - exibe feed de alertas, visoes de livro/agressao e paineis taticos;
   - conecta ao WebSocket do distributor para atualizacao em tempo real.

4. **Desktop App (Tauri v2 + Rust)**
   - embute o frontend;
   - orquestra spawn/kill de `engine` e `distributor`;
   - integra notificacoes do sistema e recursos de configuracao;
   - gera instalador `.exe` (NSIS).

## Estrutura de Pastas

- `app/` - aplicacao desktop Tauri (Rust + wrapper do frontend)
- `engine/` - motor C++ de ingestao/processamento e publicacao ZeroMQ
- `distributor/` - camada Python de distribuicao (ZMQ -> WebSocket)
- `frontend/` - interface React/TypeScript
- `scripts/` - automacao de desenvolvimento/build
- `installer-resources/` - recursos usados no bundle/instalador
- `ProfitDLL/` e DLLs na raiz - dependencia de integracao com Profit

## Stack Tecnica

- **Core de mercado:** C++ (MSVC/CMake/vcpkg)
- **Mensageria interna:** ZeroMQ
- **Distribuicao realtime:** Python + asyncio + Uvicorn/FastAPI
- **UI:** React 18 + TypeScript + Vite + Zustand + Recharts
- **Desktop:** Tauri v2 (Rust) + plugin de notificacoes
- **Empacotamento:** NSIS (via build do Tauri)

## Fluxo de Execucao

1. Engine conecta na Profit DLL e recebe eventos de mercado.
2. Engine processa e publica mensagens JSON via ZeroMQ.
3. Distributor consome essas mensagens e encaminha por WebSocket.
4. Frontend/app recebe e renderiza os dados em tempo real.
5. Tauri coordena servicos locais e experiencia desktop.

## Operacao em Desenvolvimento

Comando recomendado na raiz:

```powershell
npm run dev
```

Esse comando executa o script `scripts/run-dev.ps1`, que sobe os servicos do ecossistema para desenvolvimento local.

## Estado do Projeto

De acordo com a documentacao principal, os marcos M1 a M5 estao concluidos:

- M1: Engine de dados (Profit DLL -> DOM/T&T -> ZMQ)
- M2: Rule Engine com regras quantitativas
- M3: Distributor realtime (ZMQ -> WebSocket)
- M4: Frontend React
- M5: Desktop Tauri com notificacoes, sons e instalador

## Observacoes Importantes

- O sistema depende de credenciais/ativacao da Profit via variaveis de ambiente.
- Para build 64-bit da engine, deve-se usar a DLL 64-bit correspondente.
- O app desktop pode orquestrar processos auxiliares na inicializacao.
