# Troubleshooting de Logs

Guia prático para diagnosticar problemas do instalador e do app instalado em outro PC.

## Onde os logs ficam

- **Build do instalador (máquina de build)**
  - `logs/installer-build-YYYYMMDD-HHMMSS.log`
- **Instalação NSIS (PC alvo)**
  - `%LOCALAPPDATA%\Plataforma Quantitativa\logs\installer-runtime.log`
- **Runtime do app instalado (PC alvo)**
  - `%LOCALAPPDATA%\Plataforma Quantitativa\logs\runtime-bootstrap.log`
  - `%LOCALAPPDATA%\Plataforma Quantitativa\logs\engine_stderr.log`
  - `%LOCALAPPDATA%\Plataforma Quantitativa\logs\distributor_stdout.log`
  - `%LOCALAPPDATA%\Plataforma Quantitativa\logs\distributor_stderr.log`
  - `%LOCALAPPDATA%\Plataforma Quantitativa\logs\ocr_stdout.log`
  - `%LOCALAPPDATA%\Plataforma Quantitativa\logs\profit_ocr_stderr.log`
  - `%LOCALAPPDATA%\Plataforma Quantitativa\profit_engine.log`

## Leitura rápida (5 minutos)

1. Abra `runtime-bootstrap.log` e confirme a sequência:
   - `engine.spawn_engine -> ok`
   - `distributor.spawn_distributor -> ok`
   - `ocr.ensure_running -> spawned_ready` ou `already_reachable`
2. Se OCR falhar, abra `profit_ocr_stderr.log` e `ocr_stdout.log`.
3. Se dados de mercado não chegarem, abra `engine_stderr.log`, `distributor_stdout.log` e `distributor_stderr.log`.
4. Se o erro for no instalador, abra `installer-runtime.log`.

## Mapa sintoma -> log -> causa provável -> ação

- **`Falha ao abrir overlay: OCR iniciou, mas não ficou alcançável no healthcheck`**
  - Logs: `runtime-bootstrap.log`, `profit_ocr_stderr.log`, `ocr_stdout.log`
  - Causas: primeira execução lenta (PyInstaller/antivírus), porta bloqueada, erro interno OCR.
  - Ação: aguardar nova tentativa, checar antivírus e porta OCR (`5558` ou `PQ_OCR_PORT`).

- **`OCR: eixo ilegível (0 labels)`**
  - Logs: `runtime-bootstrap.log` (OCR ok), `ocr_stdout.log`
  - Causas: eixo fora da área de captura, zoom/contraste/fontes, DPI diferente em 2 monitores.
  - Ação: colocar Profit no monitor principal, equalizar escala de texto entre monitores, ajustar zoom.

- **`Tesseract OCR não encontrado`**
  - Logs: `installer-runtime.log`, `profit_ocr_stderr.log`, `runtime-bootstrap.log`
  - Causa: tesseract não instalado/detectado.
  - Ação: instalar Tesseract e validar `C:\Program Files\Tesseract-OCR\tesseract.exe`.

- **`A porta do OCR (...) já está em uso`**
  - Logs: `runtime-bootstrap.log`, `profit_ocr_stderr.log`
  - Causa: processo externo ocupando a porta.
  - Ação: encerrar processo conflitante ou alinhar `PQ_OCR_PORT` e `VITE_PQ_OCR_PORT`.

- **Engine/Distributor não sobem**
  - Logs: `runtime-bootstrap.log`, `engine_stderr.log`, `distributor_stderr.log`
  - Causas: binário ausente, credenciais inválidas, DLL ausente, bloqueio por permissão.
  - Ação: conferir mensagem de `reason` no bootstrap e validar artefatos em `resources`.

## Exemplo de evento em `runtime-bootstrap.log`

```json
{"ts_ms":1711820000000,"session_id":"pq-1234-1711820000","component":"ocr","event":"ensure_running","status":"error","details":{"reason":"A porta do OCR (5558) já está em uso..."}}
```

Campos:

- `component`: `app`, `engine`, `distributor`, `ocr`, `overlay`, `diagnostics`
- `event`: operação executada
- `status`: `attempt`, `ok`, `error`, `already_reachable`, etc.
- `details.reason`: causa textual quando há falha

## Coletar pacote para suporte

Use o comando Tauri `collect_diagnostics_bundle` (via frontend/invoke) para gerar um pacote em:

- `%LOCALAPPDATA%\Plataforma Quantitativa\diagnostics\bundle-<timestamp>`

O bundle inclui logs principais + `metadata.json` (OS, arquitetura, porta OCR, detecção de Tesseract).

## Checklist para 2 monitores

- Profit visível e não minimizado.
- Preferir Profit no monitor principal.
- Mesma escala de texto/DPI nos dois monitores.
- Overlay ativo e status OCR em `ok`.
