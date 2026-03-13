# State

**Last Updated:** 2026-03-04
**Current Work:** M4 concluído. Próximo: M5 - Desktop & Polish (Tauri, notificações, instalador .exe)

---

## Recent Decisions (Last 60 days)

### AD-001: C++ para camada de captura e motor de análise (2026-03-04)

**Decision:** Usar C++ para captura de dados (Profit DLL) e processamento das 5 regras.
**Reason:** Performance crítica para tick-by-tick; integração nativa com DLL Windows; controle total de memória e latência.
**Trade-off:** Maior complexidade de desenvolvimento e debugging vs. C#.
**Impact:** Requer toolchain C++ (MSVC/CMake), cuidado com memory management, mas garante latência mínima.

### AD-002: ZeroMQ como IPC em vez de Redis (2026-03-04)

**Decision:** ZeroMQ para comunicação C++ → Python em vez de Redis Pub/Sub.
**Reason:** Biblioteca embarcável (sem serviço externo rodando), simplifica deploy single-machine e instalador .exe.
**Trade-off:** API ligeiramente mais verbosa que Redis; sem persistência nativa de mensagens.
**Impact:** Zero dependência de servidor externo; IPC de baixíssima latência in-process.

### AD-003: Tauri v2 para desktop em vez de Electron (2026-03-04)

**Decision:** Tauri v2 para empacotamento da UI como app desktop Windows.
**Reason:** Instalador ~10MB vs. ~100MB+ (Electron); melhor performance; notificações nativas via Rust; menor footprint.
**Trade-off:** Ecossistema menos maduro que Electron; requer Rust toolchain no build.
**Impact:** Instalador leve para o trader; Rust apenas no build (shell), toda lógica de UI continua em React/TS.

### AD-004: FastAPI + React como stack de manutenibilidade (2026-03-04)

**Decision:** Python FastAPI para API de distribuição, React + TypeScript para frontend.
**Reason:** Desenvolvedor solo priorizando manutenção; FastAPI tem tipagem forte e docs automática; React tem o maior ecossistema frontend.
**Trade-off:** Python adiciona overhead vs. servir WebSocket direto do C++, mas desacopla as camadas.
**Impact:** Stack bem documentada, fácil de manter e evoluir.

---

## Active Blockers

_Nenhum blocker ativo._

---

## Lessons Learned

_Nenhuma lição registrada ainda._

---

## Preferences

**Model Guidance Shown:** never
