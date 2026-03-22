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
- **ProfitDLL.dll**: Must be present in the project root.

## Usage

To generate the installer, run the following command from the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .agents/skills/create_installer/scripts/build_installer.ps1
```

## What it does

1. **Builds Engine**: Compiles the C++ engine in `Release` mode using CMake.
2. **Builds Distributor**: Uses PyInstaller to bundle the Python distributor into a single executable.
3. **Prepares Resources**: Copies `engine.exe`, `distributor.exe`, `ProfitDLL.dll`, and sound files to the `app/src-tauri/resources` directory.
4. **Builds Tauri**: Executes `npm run tauri build` to generate the final installer.

**Runtime:** O instalador não embute credenciais. Utilizadores finais configuram Profit e chaves API (ex. OpenRouter para o Agente 007) no menu **Configurações** da app; o Tauri repassa esses valores ao engine e ao `distributor.exe`.

## Outputs

The final installer will be located in:
`app/src-tauri/target/release/bundle/nsis/Plataforma Quantitativa_0.1.0_x64-setup.exe`
