# Plano de correção — overlay / OCR em PCs lentos

**Implementado (revisão):** OCR antes das janelas em `open_profit_overlay`; retries + timeout longo em `ocr_port_occupied_without_healthcheck`; estado `activating` + botão “A ligar…” e texto de estado no `OverlayControl`.

## 1. Sintomas observados

- Ao clicar **Ativar**, demora muito até o botão mostrar **Desativar**.
- Em alguns casos aparece no dropdown: porta OCR (5558) “já em uso”, enquanto o OCR acaba por arrancar e o overlay fullscreen parece reagir.
- Top comprador / top vendedor não sincronizam com o serviço OCR quando o fluxo principal regista falha.

## 2. Causas possíveis (decompostas)

| # | Causa | Onde se manifesta |
|---|--------|-------------------|
| A | **`active` só é definido após `invoke("open_profit_overlay")` terminar** — o comando espera até ~120 s (ou `PQ_OCR_STARTUP_TIMEOUT_MS`) pelo healthcheck do OCR. | UI: botão permanece “Ativar” durante todo esse tempo (`useProfitOverlay.openOverlay` + `OverlayControl`). |
| B | **Janelas do overlay abrem antes de `ensure_profit_ocr_running`**; se `ensure` falhar, as janelas podem ficar visíveis mas o frontend trata como erro. | Sensação de “overlay OK” com dropdown em erro. |
| C | **Falso positivo “porta em uso”**: TCP em 5558 aceita ligação mas `/status` ainda não responde dentro dos timeouts do ramo `ocr_port_occupied_without_healthcheck` / `profit_ocr_http_compatible` (1200 ms vs. arranque lento). | `commands.rs` → `ensure_profit_ocr_running` antes do spawn. |
| D | **Processo realmente a ocupar 5558** (OCR órfão, segunda instância, outro software). | Mesma mensagem; requer `netstat` / logs. |
| E | **OCR antigo** sem `/analysis_roi` responde em 5558 → erro de incompatibilidade (mensagem diferente, mas confundível na prática). | `profit_ocr_has_analysis_roi_endpoint`. |
| F | **Falha do `invoke` não dispara `connectWs()` nem `pushTargets`** — métricas dinâmicas nunca chegam ao OCR mesmo com WS da `OverlayPage` ativo. | `useProfitOverlay.ts` ramo `catch`. |

## 3. Direções de correção (por causa)

### A — Atraso “Ativar” → “Desativar” (UX + modelo de estado)

**Objetivo:** Feedback imediato e estado coerente com “overlay pedido pelo utilizador”.

1. **Estado intermédio `activating` (ou `pending`)**  
   - Ao clicar Ativar: `setState({ activating: true })` (ou `status: 'warming_up'` já existe parcialmente).  
   - Botão: mostrar **“A ligar…”** / desativar duplo clique / opcional spinner.  
   - Só mostrar **Desativar** quando: (opção preferida) **janelas Tauri criadas** OU OCR confirmado — ver ponto B.

2. **Opção mais robusta — comando Tauri em duas fases**  
   - **Fase 1 (rápida):** `show_overlay_windows` — só cria/mostra janelas, retorna `Ok` de imediato.  
   - **Fase 2 (assíncrona):** `ensure_profit_ocr_running` invocado em background (outro comando ou mesmo app após Fase 1), com eventos `ocr_ready` / `ocr_failed` para o frontend atualizar status e então `connectWs` + `pushTargets`.  
   - **Desativar** durante Fase 2: fechar janelas e cancelar/reap child OCR se aplicável.

3. **Mínimo viável sem novo comando:**  
   - No frontend, após `invoke` **resolver** (sucesso ou falha parcial), manter lógica atual; mas **definir `activating` true** antes do `await` e **definir `active` true assim que as janelas existirem** só é possível se o backend devolver sucesso parcial ou evento — daí a preferência pela fase 1/2 no Tauri.

**Confiança de impacto:** alto — resolve diretamente o detalhe “demora a mostrar Desativar”.

### B — Ordem: OCR antes das janelas ou rollback

**Opções:**

- **(B1)** Chamar `ensure_profit_ocr_running` **antes** de criar webviews; se falhar, não abrir janelas (evita estado “fantasma”).  
- **(B2)** Manter ordem atual mas em falha chamar **`close_profit_overlay`** no próprio `open_profit_overlay` antes de `return Err` (reverte UI).  
- **(B3)** Combinar com A: abrir janelas cedo mas marcar frontend como ativo com Fase 1 explícita.

**Trade-off:** B1 aumenta tempo até o utilizador “ver” algo no ecrã, mas remove inconsistência; A2 resolve feedback sem obrigar a esperar OCR para mostrar janela.

### C — Falso positivo “porta em uso”

1. **Retries com backoff** em `ocr_port_occupied_without_healthcheck`: se TCP ocupado mas HTTP não compatível, esperar 200–500 ms e repetir N vezes antes de erro final.  
2. **Alinhar timeouts:** usar para “compatível” um timeout ≥ ao de `profit_ocr_http_reachable` ou reutilizar a mesma função de reachability com polling.  
3. **Só falhar “porta estranha”** se após J tentativas ainda `!profit_ocr_http_compatible()`.

### D — Conflito real de porta

- Documentar diagnóstico: `Get-NetTCPConnection -LocalPort 5558` (PowerShell), `profit_ocr_stderr.log`.  
- Opcional: comando Tauri “matar OCR órfão da app” só se PID for filho conhecido (cuidado com segurança).

### E — Versão OCR

- Manter mensagem atual; no instalador garantir sync do `profit_ocr_service` para resources.

### F — Sync de métricas após falha parcial

- Se **janelas abertas** mas `ensure` falhou: ainda assim chamar `connectWs()` + `pushTargets` quando WebSocket OCR abrir **ou** expor `set_overlay_positions` HTTP após retry.  
- Melhor: não entrar em estado “falha total” se as janelas ficaram abertas — alinhar com B.

## 4. Ordem de implementação sugerida

1. **Curto prazo — backend C + mensagens:** retries no check de porta; reduz falsos “em uso”.  
2. **Curto prazo — frontend A (mínimo):** estado `activating`, texto “A ligar…”, botão disabled durante `await invoke` (melhora percepção; não reduz tempo real até `active`).  
3. **Médio prazo — Tauri A+B:** dividir `open_profit_overlay` ou adicionar `prepare_overlay_ui` + `ensure_ocr_async` com eventos; `active` / Desativar alinhados à Fase 1.  
4. **Médio prazo — F:** após qualquer caminho em que janelas existam, garantir envio de `set_positions` (WS ou `set_overlay_positions`).  
5. **Validação:** PC lento / 1.ª execução com antivírus; duplo clique rápido em Ativar; porta 5558 ocupada por processo externo (deve continuar a falhar com mensagem clara).

## 5. Critérios de verificação

- Clicar **Ativar**: em &lt; 500 ms o utilizador vê estado “a ligar” ou **Desativar** (conforme opção A escolhida).  
- Após OCR pronto, métricas líder comprador/vendedor aparecem no serviço (linhas / labels coerentes).  
- Sem regressão: fechar overlay liberta recursos; sem duplicar bind na mesma porta em uso legítimo por terceiros.

## 6. Referências no código

- `frontend/src/hooks/useProfitOverlay.ts` — `openOverlay`, `active`, `connectWs`, `pushTargets`.  
- `frontend/src/components/OverlayControl/index.tsx` — botão Ativar/Desativar.  
- `frontend/src/pages/OverlayPage.tsx` — WebSocket independente ao montar.  
- `app/src-tauri/src/commands.rs` — `open_profit_overlay`, `ensure_profit_ocr_running`, `ocr_port_occupied_without_healthcheck`.  
- `docs/PORTS.md` — `PQ_OCR_PORT`, `VITE_PQ_OCR_PORT`, `PQ_OCR_STARTUP_TIMEOUT_MS`.
