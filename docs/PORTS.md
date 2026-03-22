# Portas locais (fonte canónica)

Todas as portas abaixo são **localhost** (máquina única). Ao alterar uma porta, atualize **todos** os ficheiros listados e o script `scripts/run-dev.ps1` (função `Kill-StaleProcesses` / `Kill-ListenersOnPort`).

**Não reutilizar a porta 5557 para HTTP/WebSocket** — está reservada ao **ZMQ PUB** do `sync_monitor`.

## Matriz

| Porta | Protocolo | Processo / função | Ficheiros de referência |
|-------|-----------|-------------------|-------------------------|
| **8000** | HTTP + WebSocket | Distributor (FastAPI → clientes); REST `GET /api/agent007/snapshot`, `POST /api/agent007/chat`, `POST /api/agent007/weis` | `distributor/config.py` (`WS_PORT`), `frontend/vite.config.ts`, `frontend/src/hooks/useWebSocket.ts`, `app/src-tauri/src/commands.rs` (`HEALTH_URL`) |
| **5555** | ZMQ | Engine PUB → distributor SUB (mercado) | `distributor/config.py` (`ZMQ_ADDRESS`) |
| **5556** | TCP | Engine listener **SWITCH** (troca de ativo / controle) | `app/src-tauri/src/commands.rs` (`ENGINE_CONTROL_PORT`), `distributor/websocket_server.py` (`ENGINE_CONTROL_PORT`) |
| **5557** | ZMQ | Sync monitor PUB → distributor SUB | `sync_monitor/config.py` (`ZMQ_PUB_PORT`), `distributor/config.py` (`ZMQ_SYNC_ADDRESS`) |
| **5558** | HTTP + WebSocket | Serviço OCR do overlay (`profit_ocr_service.py`) | `distributor/profit_ocr_service.py`, `app/src-tauri/resources/profit_ocr_service.py`, `app/src-tauri/src/commands.rs`, `frontend/src/config/ocrPort.ts` |

## Agente 007 — chat (OpenRouter)

- Chave: **`AGENT007_API_KEY`** ou **`OPENROUTER_API_KEY`** (obter em [openrouter.ai/keys](https://openrouter.ai/keys)).
- Por defeito: **`AGENT007_BASE_URL=https://openrouter.ai/api/v1`** e modelo **`AGENT007_MODEL=openai/gpt-4o-mini`** (IDs no formato `provedor/modelo` na documentação OpenRouter).
- Opcional: **`AGENT007_OPENROUTER_HTTP_REFERER`** / **`OPENROUTER_HTTP_REFERER`**, **`AGENT007_OPENROUTER_APP_TITLE`** (cabeçalhos de atribuição).
- Para usar OpenAI direto: defina `AGENT007_BASE_URL=https://api.openai.com/v1` e um modelo OpenAI em `AGENT007_MODEL`.

## Porta OCR configurável

- Variável de ambiente **`PQ_OCR_PORT`**: porta HTTP do OCR (por defeito **5558**).
- O processo Python lê `PQ_OCR_PORT` ao arrancar.
- O Tauri repassa `PQ_OCR_PORT` ao fazer spawn do script e usa o mesmo valor nas URLs HTTP internas.
- No frontend (Vite), defina **`VITE_PQ_OCR_PORT`** no `.env` se precisar de outra porta no WebSocket do overlay (deve coincidir com `PQ_OCR_PORT`).

## Reinícios e processos órfãos

- `scripts/run-dev.ps1` tenta libertar listeners em **8000, 5555, 5556, 5557** e na porta OCR (`PQ_OCR_PORT` ou 5558) antes e depois do fluxo.
- **5556** é o **engine (SWITCH)**, não o OCR.
- Com **`npm run dev`** / `run-dev.ps1` **sem** `-StartOcr`, o OCR **não** é iniciado pelo script: o Tauri inicia o serviço ao abrir o overlay, evitando dois binds na mesma porta.
