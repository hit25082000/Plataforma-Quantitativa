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
$env:PROFIT_PASSWORD = "<SECRET>"
```

Aliases aceitos:

```powershell
$env:PROFIT_DLL_ACTIVATION_KEY = "sua_chave"
$env:PROFIT_DLL_USER = "seu_usuario"
$env:PROFIT_DLL_PASSWORD = "<SECRET>"
```

Ou edite `src/config.h` para valores padrão.

## Execução

```powershell
# Copiar a DLL correta: 64-bit → ProfitDLL64.dll (pasta ProfitDLL ou raiz do projeto)
copy ..\..\ProfitDLL64.dll .
.\Release\engine.exe

# Rodar por tempo controlado (encerramento gracioso + dump QPC)
.\Release\engine.exe --run-seconds=120
```

O engine publica mensagens JSON em `tcp://localhost:5555`. Use um subscriber ZeroMQ para consumir.

## Shared Memory IPC (P2)

Além do caminho ZMQ, o ecossistema agora suporta leitura por shared memory com fallback:

- Distributor: quando `IPC_MODE=shm`, faz probe do mapping (`SHM_MAPPING_NAME`) no startup.
- Se SHM não estiver disponível no tempo de probe (`SHM_FALLBACK_PROBE_TIMEOUT_MS`), ativa fallback para ZMQ.
- O fallback é one-way até restart (não há auto-switch de volta para SHM em runtime).
- O estado efetivo de IPC fica exposto em `GET /health` e `GET /ipc-state` no distributor.

Variáveis úteis no distributor:

- `IPC_MODE=shm|zmq`
- `SHM_MAPPING_NAME=Local\\PQMarketDataV1`
- `SHM_SIZE_MB=64`
- `SHM_QPC_DIAG=1` — amostra duração de `write_trade` com `QueryPerformanceCounter` (stderr ao shutdown; `SHM_QPC_SAMPLE_EVERY`, `SHM_QPC_MAX_SAMPLES`, p50/p95/p99/p999/max)
- `SHM_LARGE_PAGES=1` — tenta mapear ring buffer com Large Pages (fallback automático se indisponível)
- `SHM_LARGE_PAGES_STRICT=1` — falha o startup se Large Pages não forem aplicáveis (sem fallback)
- `SHM_NUMA_NODE=0` — preferência de node NUMA para criação do mapping (usa API NUMA quando disponível)
- `SHM_PREFETCH_NEXT_SLOT=1` — prefetch do próximo slot do ring no writer SHM
- `SHM_FALLBACK_PROBE_TIMEOUT_MS=3000`
- `SHM_FALLBACK_PROBE_INTERVAL_MS=200`

Integridade de slot SHM:

- `TradePayload.reserved0` é usado como CRC16-CCITT do slot (`message_type` + `payload_size` + `trade` com `reserved0=0`)
- Consumers Python/Tauri descartam slots com `payload_size` inválido ou CRC inválido e incrementam `integrity_failures`
- Evidência IPC suporta gates de integridade: `--stress-max-crc-mismatch`, `--stress-max-payload-mismatch`, `--session-max-crc-mismatch`, `--session-max-payload-mismatch`

## HFT CPU Pinning (M7 P1)

Pinning é opcional e desativado por padrão. Ative no ambiente do `engine.exe`:

- `HFT_CPU_PINNING=1` — habilita tuning de afinidade
- `HFT_PROCESS_PRIORITY=1` — eleva processo para `HIGH_PRIORITY_CLASS` (default quando pinning ativo)
- `HFT_MAIN_CORE=0` — core da thread principal do engine
- `HFT_PUBLISHER_CORE=1` — core da thread de publicação (ZMQ/SHM)
- `HFT_PROFIT_CALLBACK_CORE=2` — core para threads de callback da Profit DLL (aplicado no primeiro callback da thread)
- `HFT_CORE_INDEX_MODE=physical|logical` — modo de interpretação dos índices (`physical` padrão; evita siblings SMT ao mapear `HFT_*_CORE` para núcleos físicos)
- `HFT_QPC_DIAG=1` — mede jitter de intervalo (callbacks Profit e loop publisher) com QPC
- `HFT_QPC_SAMPLE_EVERY=1` — amostragem do jitter (1 = todos os eventos)
- `HFT_QPC_MAX_SAMPLES=1000000` — limite de amostras para cálculo de percentis
- `HFT_PREFETCH=1` — habilita prefetch explícito nos hot paths de DOM/T&T

Ferramenta de evidência M7:

- `python scripts/benchmark_hft_qpc.py --runs baseline,pinned --duration-seconds 120 --out distributor/logs/hft_qpc_benchmark_last.csv`
- `python scripts/benchmark_hft_qpc.py --runs baseline,pinned --duration-seconds 120 --hft-core-index-mode physical --out distributor/logs/hft_qpc_benchmark_last.csv`
- `python scripts/benchmark_hft_qpc.py --runs baseline,pinned --duration-seconds 120 --shm-large-pages --shm-numa-node 0 --out distributor/logs/hft_qpc_benchmark_last.csv`
- `powershell -ExecutionPolicy Bypass -File scripts/run-hft-qpc-evidence.ps1 -Mode all -DurationSeconds 120 -CoreIndexMode physical -EnableShmQpc -ShmLargePages -ShmNumaNode 0`
- `powershell -ExecutionPolicy Bypass -File scripts/run-hft-qpc-evidence.ps1 -Mode all -DurationSeconds 120 -EnableShmQpc -RunMatrix -MatrixShmLargePages 0,1 -MatrixShmNumaNodes -1,0` (gera `matrix_summary.csv` + `matrix_manifest.json` com cenários combinados)
- `powershell -ExecutionPolicy Bypass -File scripts/run-m6-m7-evidence.ps1 -HftDurationSeconds 3600 -SessionSeconds 21600 -HftEnableShmQpc -MatrixShmLargePages 0,1 -MatrixShmNumaNodes -1,0 -SessionFailOnLoss` (orquestra matriz HFT + sessão IPC e gera `summary.csv` + `summary.manifest.json`)

Fallback seguro:

- Em máquina com menos cores que a configuração, o engine mantém scheduling padrão para a thread e escreve warning no stderr.
- Em plataforma não-Windows, as flags são ignoradas.

## Formato das mensagens

- **trade**: novo negócio com VWAP e net_aggression
- **wall_add**: muralha detectada (qty >= 500)
- **wall_remove**: ordem removida (possível spoofing)
- **dom_snapshot**: snapshot completo do DOM
