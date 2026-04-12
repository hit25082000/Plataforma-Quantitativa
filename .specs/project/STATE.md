# State

**Last Updated:** 2026-04-12
**Current Work:** v2 Planning — PRD "Evolução HFT e Copiloto de IA" inicializado. Próximo: especificação detalhada das 5 features (M6-M9).

---

## Recent Decisions (Last 60 days)

### AD-005: Substituir ZeroMQ por Memória Compartilhada (2026-04-12)

**Decision:** Migrar IPC de ZeroMQ (TCP + JSON) para Memory-Mapped Files com Lock-Free Ring Buffer (SPSC).
**Reason:** ZMQ exige serialização JSON e cópias de buffer de rede, adicionando ~1-5ms de latência. SHM com ring buffer lock-free reduz para microssegundos e elimina cópias.
**Trade-off:** Complexidade significativamente maior (atomics, memory ordering, validação de concorrência); perda da portabilidade de rede do ZMQ; ZMQ será mantido como fallback durante migração.
**Impact:** Requer reescrever `ZmqPublisher` (C++) e `ZmqConsumer` (Python); novo reader Rust no Tauri; structs binárias no lugar de JSON.

### AD-006: OpenAI Realtime API para Copiloto de Voz (2026-04-12)

**Decision:** Usar OpenAI Realtime API (`gpt-4o-realtime-preview`) via WebRTC para interação voz-para-voz com o trader.
**Reason:** Latência nativa de 200-500ms fala-para-fala; VAD embutido com suporte a barge-in; Function Calling integrado para consultar o motor C++.
**Trade-off:** Custo por minuto de áudio; dependência de terceiro para feature crítica; alternativas (Cartesia Sonic, ElevenLabs) serão avaliadas para TTS.
**Impact:** Frontend precisa de componente WebRTC; bridge de Function Calling conectando IA → Tauri/Python → SHM/estado do motor.

### AD-007: Pipeline RAG com Redpanda + Banco Vetorial (2026-04-12)

**Decision:** Implementar RAG em tempo real com Redpanda para streaming e Pinecone/Vectara para busca vetorial.
**Reason:** A IA precisa de contexto contínuo do mercado (janelas de 5min) para respostas fundamentadas; embedding de dados tabulares financeiros permite busca semântica de padrões.
**Trade-off:** Infraestrutura adicional (Redpanda broker); custo de banco vetorial cloud; complexidade de pipeline de embeddings.
**Impact:** Novo componente de streaming entre SHM e banco vetorial; Context Engine como middleware antes de cada resposta da IA.

### AD-008: CPU Pinning e otimizações de SO Windows (2026-04-12)

**Decision:** Implementar afinidade de CPU, NUMA-aware allocation e Huge Pages para threads críticas.
**Reason:** Context switching do Windows limpa caches L1/L2 e introduz jitter inaceitável para HFT; isolar cores garante latência previsível.
**Trade-off:** Reduz cores disponíveis para outras aplicações; configuração por máquina pode variar; requer hardware recomendado (i7+/Ryzen 7+).
**Impact:** Mudanças no `main.cpp` do engine (afinidade de thread); Huge Pages requerem privilégio de Lock Pages in Memory no Windows.

### AD-009: AWS KMS para gestão de segredos (2026-04-12)

**Decision:** Migrar todas as chaves sensíveis (.env, credenciais) para AWS KMS.
**Reason:** Chaves em plaintext no repo/env são risco de segurança inaceitável quando há chaves de API da OpenAI e credenciais de corretora.
**Trade-off:** Dependência de AWS; latência de leitura de segredos no startup; custo mensal marginal do KMS.
**Impact:** SDK AWS no Python e possivelmente no Rust; IP Allowlist nos serviços externos.

---

## Active Blockers

_Nenhum blocker ativo._

---

## Lessons Learned

### L-001: EventQueue com mutex e condition_variable é gargalo potencial (2026-04-12)

**Context:** Análise do `event_bus.h` revelou que o engine usa `std::queue<Event>` com `std::mutex` e `std::condition_variable`.
**Problem:** Mutex cria contenção quando produtor (Profit DLL callbacks) e consumidor (dispatcher/rules) competem pela fila.
**Solution:** Ring buffer SPSC lock-free (com atomics `memory_order_release/acquire`) eliminará a contenção.
**Prevents:** Latência imprevisível por contenção de lock em cenários de alto throughput.

---

## Preferences

**Model Guidance Shown:** 2026-04-12
