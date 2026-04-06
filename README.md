# Plataforma Quantitativa

Plataforma desktop de análise de microestrutura de mercado (B3): processa livro de ofertas e fluxo de ordens em tempo real, disparando alertas táticos baseados em 5 regras quantitativas.

---

## Situação do Projeto (v1)

| Marco | Status | Descrição |
|-------|--------|-----------|
| **M1** | ✅ Concluído | Engine C++ (Profit DLL → DOM Snapshot + T&T Stream → ZeroMQ) |
| **M2** | ✅ Concluído | Rule Engine (5 regras event-driven, anti-spoofing, alertas JSON) |
| **M3** | ✅ Concluído | Distributor Python (ZMQ Sub → FastAPI WebSocket) |
| **M4** | ✅ Concluído | Frontend React (Feed de Alertas, Heatmap do Livro, Painel de Agressão) |
| **M5** | ✅ Concluído | Desktop (Tauri), notificações Windows, sons, instalador .exe |

---

## Estrutura do Repositório

```
Plataforma Quantitativa/
├── app/              # Tauri v2 (M5): wrapper desktop, orquestração
├── engine/           # C++ (M1+M2): Profit DLL, DOM, T&T, regras, ZMQ PUB
├── distributor/      # Python (M3): ZMQ SUB → WebSocket; OCR overlay (fonte canónica)
├── frontend/         # React+TS (M4): UI tática
├── installer-resources/  # Sons e recursos para o bundle
├── scripts/          # run-dev.ps1, build-installer.ps1, sync-profit-ocr-to-tauri-resources.ps1
├── docs/             # PORTS.md + TROUBLESHOOTING_LOGS.md
├── .specs/           # Specs do projeto (PROJECT, ROADMAP, STATE)
├── ProfitDLL.dll     # (opcional) DLL 32 bits — colocar na RAIZ para scripts copiarem p/ engine/resources
├── ProfitDLL64.dll   # DLL 64 bits — na RAIZ (ou só em engine/build/Release após build); obrigatória p/ instalador
└── Manual - ProfitDLL.pdf
```

**DLLs Nelogica:** Os scripts `run-dev.ps1` e `build-installer.ps1` procuram `ProfitDLL64.dll` / `ProfitDLL.dll` na **raiz** do repositório e copiam para `engine/build/...` e `app/src-tauri/resources/`. Pode manter cópias só em `app/src-tauri/resources/` para testes manuais, mas a convenção suportada pelos scripts é **raiz → cópia automática**.

**OCR (`profit_ocr_service.py`):** Editar apenas `distributor/profit_ocr_service.py`. A cópia em `app/src-tauri/resources/` é gerada por `scripts/sync-profit-ocr-to-tauri-resources.ps1` (executado pelo `run-dev.ps1` e pelo `build-installer.ps1`).

---

## Rodar tudo com um comando

Para subir **engine**, **distributor** e **app Tauri** de uma vez (desenvolvimento):

1. Defina as variáveis de ambiente Profit no terminal (veja abaixo).
2. Execute na raiz do repositório:

   ```powershell
   .\scripts\run-dev.ps1
   ```

   Ou, com npm:

   ```powershell
   npm run dev
   ```

O script compila/copia a **engine**, inicia **distributor** e **sync_monitor** em background e abre o app Tauri. **Por defeito não inicia o OCR** (o Tauri faz spawn ao abrir o overlay, evitando dois binds na mesma porta). Para subir o OCR pelo script:

```powershell
.\scripts\run-dev.ps1 -StartOcr
```

Antes e depois do fluxo, o script tenta libertar listeners órfãos nas portas do stack (incl. OCR em 5558 ou `PQ_OCR_PORT`).

**Pré-requisitos:** Python com pip, Node/npm. O script tenta gerar a engine.

### Portas locais

Matriz canónica: **[docs/PORTS.md](docs/PORTS.md)**. Resumo: **8000** distributor; **5555** ZMQ mercado; **5556** TCP **SWITCH** do engine (não é OCR); **5557** ZMQ sync; **5558** OCR (ou `PQ_OCR_PORT` / `VITE_PQ_OCR_PORT` no frontend).

### Logs e diagnóstico

Guia de troubleshooting para instalador e app instalado: **[docs/TROUBLESHOOTING_LOGS.md](docs/TROUBLESHOOTING_LOGS.md)**.

---

## Como Rodar o Sistema Completo

1. **Variáveis de ambiente** (engine):
   ```powershell
   $env:PROFIT_ACTIVATION_KEY = "sua_chave"
   $env:PROFIT_USER = "seu_usuario"
   $env:PROFIT_PASSWORD = "sua_senha"
   ```

2. **Engine** (publica em `tcp://localhost:5555`):
   ```powershell
   cd engine\build\Release
   copy ..\..\..\ProfitDLL.dll .
   .\engine.exe
   ```

3. **Distributor** (consome ZMQ, serve WebSocket em `ws://127.0.0.1:8000/ws`):
   ```powershell
   cd distributor
   pip install -r requirements.txt
   python main.py
   ```

4. **Frontend** (conecta ao WebSocket):
   ```powershell
   cd frontend
   npm install
   npm run dev
   ```
   Abra o endereço indicado pelo Vite (ex.: http://localhost:5173). O proxy Vite aponta para `127.0.0.1:8000` (`frontend/vite.config.ts`); no Tauri o WS é `ws://127.0.0.1:8000/ws` (`useWebSocket.ts`).

**Ordem recomendada:** 1 → 2 → 3 → 4.

---

## M5 - Desktop & Polish (Implementado)

- **App Tauri v2** em `app/` – wrapper que usa o frontend em `frontend/`
- **Orquestração**: spawn automático de engine e distributor ao iniciar
- **Notificações Windows** e **sons** por tipo de alerta (R2 → wall.wav, R5 → breakout.wav)
- **Painel de Configurações**: credenciais Profit, chave API OpenRouter (Agente 007), notificações, sons, volume
- **Instalador .exe** (NSIS) via `npm run tauri build` — na app empacotada, segredos ficam em **Configurações** (persistidos em `config.json` na pasta de dados do app), não num `.env` do repositório

### Build do Instalador

**Pré-requisitos:** Rust, Node.js, Python, CMake, MSVC, PyInstaller

```powershell
.\scripts\build-installer.ps1
```

Ou manualmente:

1. `cd engine && cmake --build build --config Release`
2. `cd distributor && pyinstaller distributor.spec`
3. Copiar `engine.exe`, `ProfitDLL64.dll` (ou `ProfitDLL.dll` para 32-bit), `distributor.exe` e `distributor/profit_ocr_service.py` (via `scripts/sync-profit-ocr-to-tauri-resources.ps1`) para `app/src-tauri/resources/`
4. Copiar sons de `installer-resources/sounds/` para `app/src-tauri/resources/sounds/`
5. `cd app && npm run build`

Output: `app/src-tauri/target/release/bundle/nsis/PlataformaQuantitativa_*.exe`

### Desenvolvimento com Tauri

```powershell
cd app && npm run dev
```

(Requer engine e distributor rodando, ou o app fará spawn automático na primeira execução.)
