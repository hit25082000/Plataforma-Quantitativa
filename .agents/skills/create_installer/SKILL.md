---
name: create_installer
description: Build the complete installer for the Plataforma Quantitativa project
---

# Create Installer Skill

This skill automates the multi-step process of building the engine, distributor, and bundling them into a Tauri-based NSIS installer.

## Prerequisites

- **CMake**: For building the C++ engine.
- **Node.js & npm**: For building the frontend and Tauri bundle.
- **Rust**: For Tauri core.
- **Python**: For the distributor.
- **ProfitDLL64.dll** (e opcionalmente **ProfitDLL.dll**): na **raiz** do repositório, ou em `engine/build/Release/` após build — ver [README.md](../../../README.md).

## Usage

Script canónico na raiz (recomendado):

```powershell
.\scripts\build-installer.ps1
```

Atalho equivalente (delega para o script acima):

```powershell
powershell -ExecutionPolicy Bypass -File .agents/skills/create_installer/scripts/build_installer.ps1
```

## What it does

1. **Builds Engine**: Compiles the C++ engine in `Release` mode using CMake.
2. **Builds Distributor**: Uses PyInstaller to bundle the Python distributor into a single executable.
3. **Prepares Resources**: Sincroniza `profit_ocr_service.py` (desde `distributor/`), copia `engine.exe`, `distributor.exe`, DLLs Profit e sons para `app/src-tauri/resources/`.
4. **Builds Tauri**: Executes `npm run tauri build` to generate the final installer.

**Runtime:** O instalador não embute credenciais. Utilizadores finais configuram Profit e chaves API (ex. OpenRouter para o Agente 007) no menu **Configurações** da app; o Tauri repassa esses valores ao engine e ao `distributor.exe`.

## Outputs

The final installer will be located in:
`app/src-tauri/target/release/bundle/nsis/Plataforma Quantitativa_0.1.0_x64-setup.exe`
