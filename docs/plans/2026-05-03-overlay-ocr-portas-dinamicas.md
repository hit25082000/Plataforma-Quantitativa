# Plano — OCR e Overlay sem porta fixa

## Objetivo
Eliminar dependência de portas fixas no fluxo do OCR e das janelas de overlay, cobrindo runtime Tauri + frontend.

## Diagnóstico atual
- `OCR`: já possui seleção de porta em runtime no backend (`commands.rs`), mas ainda há fallback fixo no frontend (`VITE_PQ_OCR_PORT` default `5558`).
- `Overlay windows` (Tauri): URL externa de dev hardcoded para `http://localhost:5173` em múltiplos pontos.
- `CSP` do Tauri: `connect-src` restringe OCR para `127.0.0.1:5558`/`localhost:5558`, o que bloqueia portas dinâmicas fora desse valor.

## Plano de implementação
1. **Centralizar resolução de URL do frontend para janelas auxiliares**
   - Criar helper em `commands.rs` para resolver URL base em dev sem hardcode de `5173`.
   - Prioridade de resolução:
     - URL da janela `main` (quando disponível);
     - variável de ambiente explícita para dev;
     - fallback seguro legado.
   - Aplicar esse helper em criação de:
     - `profit-overlay`
     - `profit-overlay-control`
     - `ocr-roi-picker`
     - widgets (`create_widget_window`, se aplicável)

2. **Remover dependência efetiva de porta fixa no frontend OCR**
   - Ajustar `frontend/src/config/ocrPort.ts` para não depender de `5558` como comportamento normal.
   - Manter fallback mínimo apenas para modo não-Tauri/diagnóstico, priorizando porta runtime retornada por `get_ocr_runtime_port`.

3. **Liberar CSP para OCR em porta dinâmica local**
   - Atualizar `app/src-tauri/tauri.conf.json` em `connect-src` para permitir `http/ws` em `127.0.0.1:*` e `localhost:*` (escopo local).
   - Preservar demais origens já existentes.

4. **Validação**
   - Verificar lint dos arquivos alterados.
   - Verificar build/config parsing do Tauri (se possível no tempo da sessão).
   - Checar fluxo funcional esperado:
     - clicar `Ativar` -> OCR sobe em porta escolhida;
     - overlay conecta via porta runtime;
     - janelas auxiliares abrem mesmo com dev server fora de `5173`.

## Critérios de aceite
- Overlay funciona com OCR em porta diferente de `5558`.
- Sem hardcode obrigatório de `localhost:5173` para abrir janelas auxiliares no modo dev.
- Sem regressão no modo release (uso de `WebviewUrl::App` preservado).
