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
├── distributor/      # Python (M3): ZMQ SUB → WebSocket
├── frontend/         # React+TS (M4): UI tática
├── installer-resources/  # Sons e recursos para o bundle
├── scripts/          # run-dev.ps1, build-installer.ps1
├── .specs/           # Specs do projeto (PROJECT, ROADMAP, STATE)
├── ProfitDLL.dll     # DLL 32 bits (Nelogica)
├── ProfitDLL64.dll   # DLL 64 bits (obrigatória para engine 64-bit; ver Manual)
└── Manual - ProfitDLL.pdf
```

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

O script inicia engine e distributor em background e o app em primeiro plano. Ao encerrar o app (Ctrl+C ou fechar a janela), engine e distributor são encerrados automaticamente.

**Pré-requisitos:** Engine já buildada (`engine\build\Release\engine.exe`), Python com pip, Node/npm. A pasta `engine\build\Release` deve existir (rode o build da engine antes, se necessário).

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

3. **Distributor** (consome ZMQ, serve WebSocket em `ws://localhost:8000/ws`):
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
   Abra o endereço indicado pelo Vite (ex.: http://localhost:5173). Configure a URL do WebSocket em `frontend/src/hooks/useWebSocket.ts` se necessário (`ws://localhost:8000/ws`).

**Ordem recomendada:** 1 → 2 → 3 → 4.

---

## M5 - Desktop & Polish (Implementado)

- **App Tauri v2** em `app/` – wrapper que usa o frontend em `frontend/`
- **Orquestração**: spawn automático de engine e distributor ao iniciar
- **Notificações Windows** e **sons** por tipo de alerta (R2 → wall.wav, R5 → breakout.wav)
- **Painel de Configurações**: credenciais Profit, notificações, sons, volume
- **Instalador .exe** (NSIS) via `npm run tauri build`

### Build do Instalador

**Pré-requisitos:** Rust, Node.js, Python, CMake, MSVC, PyInstaller

```powershell
.\scripts\build-installer.ps1
```

Ou manualmente:

1. `cd engine && cmake --build build --config Release`
2. `cd distributor && pyinstaller distributor.spec`
3. Copiar `engine.exe`, `ProfitDLL64.dll` (ou `ProfitDLL.dll` para 32-bit), `distributor.exe` para `app/src-tauri/resources/`
4. Copiar sons de `installer-resources/sounds/` para `app/src-tauri/resources/sounds/`
5. `cd app && npm run build`

Output: `app/src-tauri/target/release/bundle/nsis/PlataformaQuantitativa_*.exe`

### Desenvolvimento com Tauri

```powershell
cd app && npm run dev
```

(Requer engine e distributor rodando, ou o app fará spawn automático na primeira execução.)
# Plataforma-Quantitativa
