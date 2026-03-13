# Engine M1 - Data Foundation

Engine C++ que lê a Profit DLL, mantém snapshot do DOM e acumuladores T&T, e publica eventos via ZeroMQ.

**Referência:** A pasta `ProfitDLL/` na raiz do repositório contém manuais e exemplos oficiais (C++, C#, Delphi, Python). O fluxo do engine segue o **Exemplo C++**: registrar callbacks, inicializar, aguardar Market conectado e Ativação válida, depois SubscribeTicker e SubscribeOfferBook. Build 64-bit usa **ProfitDLL64.dll** (ver manual).

## Pré-requisitos

- **MSVC 2022** (Visual Studio 2022) ou superior
- **CMake 3.25+**
- **vcpkg** para dependências (cppzmq, nlohmann-json)

## Instalação vcpkg

```powershell
git clone https://github.com/Microsoft/vcpkg.git C:\vcpkg
cd C:\vcpkg
.\bootstrap-vcpkg.bat
.\vcpkg integrate install
.\vcpkg install cppzmq nlohmann-json
```

## Build

```powershell
cd engine
mkdir build
cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=C:/vcpkg/scripts/buildsystems/vcpkg.cmake
cmake --build . --config Release
```

O executável `engine.exe` será gerado em `build/Release/` (ou `build/` no Linux).

## Configuração

Defina as variáveis de ambiente antes de executar:

```powershell
$env:PROFIT_ACTIVATION_KEY = "sua_chave"
$env:PROFIT_USER = "seu_usuario"
$env:PROFIT_PASSWORD = "sua_senha"
```

Ou edite `src/config.h` para valores padrão.

## Execução

```powershell
# Copiar a DLL correta: 64-bit → ProfitDLL64.dll (pasta ProfitDLL ou raiz do projeto)
copy ..\..\ProfitDLL64.dll .
.\Release\engine.exe
```

O engine publica mensagens JSON em `tcp://localhost:5555`. Use um subscriber ZeroMQ para consumir.

## Formato das mensagens

- **trade**: novo negócio com VWAP e net_aggression
- **wall_add**: muralha detectada (qty >= 500)
- **wall_remove**: ordem removida (possível spoofing)
- **dom_snapshot**: snapshot completo do DOM
