# Guia de Integração — Profit Overlay OCR
# =========================================
# Este arquivo contém os trechos de código para integrar
# os novos arquivos ao projeto existente.

# ════════════════════════════════════════════════════════════════════════════════
# 1. CARGO.TOML  (app/src-tauri/Cargo.toml)
#    Adicione as dependências:
# ════════════════════════════════════════════════════════════════════════════════

# [dependencies]
# reqwest = { version = "0.12", features = ["json"] }
# serde_json = "1"
# # (tauri e demais já devem estar presentes)


# ════════════════════════════════════════════════════════════════════════════════
# 2. LIB.RS / MAIN.RS  (app/src-tauri/src/lib.rs  ou  main.rs)
#    Registre o módulo e os comandos:
# ════════════════════════════════════════════════════════════════════════════════

# // No topo do arquivo:
# mod commands;   // se já existir, apenas adicione o sub-módulo abaixo
#
# // Se os commands estiverem em sub-pastas:
# pub mod overlay;   // dentro de commands/mod.rs
#
# // No builder do Tauri (.invoke_handler):
# .invoke_handler(tauri::generate_handler![
#     // ... seus comandos existentes ...
#     commands::overlay::open_profit_overlay,
#     commands::overlay::close_profit_overlay,
#     commands::overlay::set_overlay_positions,
# ])


# ════════════════════════════════════════════════════════════════════════════════
# 3. ROUTER FRONTEND  (frontend/src/App.tsx  ou  router.tsx)
#    Adicione a rota do overlay:
# ════════════════════════════════════════════════════════════════════════════════

# import OverlayPage from "./pages/OverlayPage";
#
# // Dentro do BrowserRouter / Routes:
# <Route path="/overlay" element={<OverlayPage />} />
#
# // A janela Tauri usa WebviewUrl::App("overlay".into())
# // que resolve para /#/overlay em hash routing, ou /overlay em history routing.
# // Ajuste conforme o modo de roteamento do seu projeto.


# ════════════════════════════════════════════════════════════════════════════════
# 4. PAINEL PRINCIPAL  (onde quiser exibir os controles do overlay)
# ════════════════════════════════════════════════════════════════════════════════

# import OverlayControl from "./components/OverlayControl";
#
# // Adicione em qualquer lugar da sua UI:
# <OverlayControl />


# ════════════════════════════════════════════════════════════════════════════════
# 5. SCRIPT DE DESENVOLVIMENTO  (scripts/run-dev.ps1)
#    Adicione a inicialização do serviço OCR:
# ════════════════════════════════════════════════════════════════════════════════

# # Após iniciar o distributor existente, adicione:
# Write-Host "Iniciando serviço OCR (porta 5558; ver docs/PORTS.md)..."
# Start-Process -NoNewWindow python -ArgumentList "distributor/profit_ocr_service.py"
# Start-Sleep -Seconds 1


# ════════════════════════════════════════════════════════════════════════════════
# 6. TAURI CAPABILITIES  (app/src-tauri/capabilities/default.json)
#    Adicione permissões para window management:
# ════════════════════════════════════════════════════════════════════════════════

# {
#   "permissions": [
#     "core:window:allow-create",
#     "core:window:allow-show",
#     "core:window:allow-hide",
#     "core:window:allow-set-always-on-top",
#     "core:window:allow-set-ignore-cursor-events",
#     "core:webview:allow-create-webview-window"
#   ]
# }


# ════════════════════════════════════════════════════════════════════════════════
# 7. INSTALAÇÃO DAS DEPENDÊNCIAS PYTHON
# ════════════════════════════════════════════════════════════════════════════════

# pip install -r distributor/requirements_ocr.txt
#
# Também é necessário instalar o Tesseract OCR:
#   https://github.com/UB-Mannheim/tesseract/wiki
#   Baixe o instalador Windows e instale em C:\Program Files\Tesseract-OCR\
#   O pytesseract encontra automaticamente se estiver no PATH.
#
# Adicione ao PATH do sistema:
#   C:\Program Files\Tesseract-OCR
#
# Opcional: para melhor performance com números, adicione o pacote de treinamento:
#   Tesseract data: digits.traineddata
#   Copie para C:\Program Files\Tesseract-OCR\tessdata\


# ════════════════════════════════════════════════════════════════════════════════
# 8. AJUSTE FINO — TOOLBAR_H
#    Se as linhas aparecerem deslocadas verticalmente, ajuste TOOLBAR_H
#    no profit_ocr_service.py. Esse valor é a altura em pixels da barra
#    de ferramentas do Profit que fica acima da área do gráfico.
#    Valores típicos: 60-120 px. Use print(chart) para depurar.
# ════════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════════
# 9. ESTRUTURA DE ARQUIVOS NOVOS
# ════════════════════════════════════════════════════════════════════════════════

# distributor/
#   profit_ocr_service.py          ← Serviço OCR (FastAPI + WebSocket)
#   requirements_ocr.txt           ← Dependências Python
#
# frontend/src/
#   pages/
#     OverlayPage.tsx               ← Janela overlay (SVG full-screen)
#   hooks/
#     useProfitOverlay.ts           ← Hook de estado e controle
#   components/
#     OverlayControl/
#       index.tsx                   ← Painel de controle (UI principal)
#
# app/src-tauri/src/commands/
#   overlay.rs                      ← Comandos Tauri (open/close/set_positions)
