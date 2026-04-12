# Security & Key Governance Specification

## Problem Statement

O projeto armazena credenciais sensíveis (chaves API da OpenAI, credenciais da Profit DLL, tokens de corretora) em arquivos `.env` ou em texto plano no código. Com a adição do Copiloto IA (chave OpenAI com custo por uso) e integrações cloud (Redpanda, Pinecone), a superfície de ataque aumenta significativamente. Chaves vazadas podem gerar custos financeiros diretos (API billing) e comprometer dados de mercado do trader.

## Goals

- [ ] Zero credenciais em plaintext no repositório ou em arquivos `.env` no deploy
- [ ] Todas as chaves sensíveis gerenciadas via AWS KMS ou equivalente
- [ ] Auditoria de acesso a segredos (quem acessou, quando)
- [ ] IP Allowlist para serviços externos com acesso a APIs da plataforma

## Out of Scope

- Criptografia de dados de mercado em trânsito (IPC local é trusted)
- Autenticação de usuário (single-machine, single-user)
- Compliance regulatório (SOX, PCI) — foco é segurança prática
- HSM (Hardware Security Module) físico

---

## User Stories

### P1: Migração de .env para AWS KMS ⭐ MVP

**User Story**: As a developer, I want all sensitive credentials stored in AWS KMS so that they are never committed to the repository or stored in plaintext on disk.

**Why P1**: Fundação de segurança; sem isso, cada novo serviço integrado aumenta o risco.

**Acceptance Criteria**:

1. WHEN distributor/engine starts THEN it SHALL fetch credentials from AWS KMS via SDK (not from .env)
2. WHEN KMS is unreachable THEN system SHALL retry 3x with backoff, then fail with clear error message ("Não foi possível acessar credenciais. Verifique conexão com AWS.")
3. WHEN a new credential is added THEN developer SHALL store it in KMS and reference it by key alias (never paste the value in code)
4. WHEN `.env` file exists in deploy THEN it SHALL contain only non-sensitive configuration (ports, feature flags) — never API keys

**Credentials to migrate:**

- `OPENAI_API_KEY` (copiloto IA)
- `PROFIT_DLL_USER` / `PROFIT_DLL_PASSWORD` (Profit DLL login)
- `PINECONE_API_KEY` (banco vetorial)
- `REDPANDA_CREDENTIALS` (se aplicável)
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (bootstrap — handled via IAM role or instance profile)

**Independent Test**: Remover `.env` com chaves; iniciar sistema; verificar que credenciais são lidas do KMS; verificar que sistema funciona normalmente.

---

### P1: Scan de segredos no repositório ⭐ MVP

**User Story**: As a developer, I want automated secret scanning in the repository so that accidental commits of credentials are blocked before push.

**Why P1**: Prevenção é mais barata que remediação; uma chave vazada no git history é permanente.

**Acceptance Criteria**:

1. WHEN developer runs `git commit` THEN pre-commit hook SHALL scan for patterns matching API keys, passwords, tokens
2. WHEN a potential secret is detected THEN commit SHALL be blocked with message identifying the file and line
3. WHEN scanning runs THEN it SHALL check for: AWS keys, OpenAI keys, generic high-entropy strings, common password patterns

**Independent Test**: Tentar commitar um arquivo com `OPENAI_API_KEY=sk-...`; verificar que o commit é bloqueado.

---

### P2: IP Allowlist para serviços externos

**User Story**: As a platform, I want outbound connections restricted to known IPs/domains so that compromised code can't exfiltrate data to arbitrary endpoints.

**Why P2**: Camada adicional de defesa; não bloqueia funcionalidade core.

**Acceptance Criteria**:

1. WHEN system makes outbound connections THEN only allowlisted domains SHALL be permitted: `api.openai.com`, `*.pinecone.io`, AWS KMS endpoints, Profit DLL servers
2. WHEN a connection to an unknown domain is attempted THEN it SHALL be logged as security warning
3. WHEN allowlist needs updating THEN it SHALL be configurable via KMS-stored config (not hardcoded)

**Independent Test**: Configurar allowlist; tentar fazer request para domínio não autorizado; verificar que é bloqueado e logado.

---

### P2: Rotação automática de chaves

**User Story**: As a security practice, I want credentials automatically rotated on a configurable schedule so that long-lived keys don't accumulate risk.

**Why P2**: Boa prática de segurança mas não urgente para v1 do security.

**Acceptance Criteria**:

1. WHEN credential rotation period expires (configurable, default 90 days) THEN system SHALL generate new key in KMS and update references
2. WHEN rotation occurs THEN system SHALL log audit event and verify new key works before deactivating old one
3. WHEN rotation fails THEN old key SHALL remain active and alert SHALL be generated

**Independent Test**: Configurar rotação para 1 minuto; verificar que chave é rotacionada; verificar que sistema continua funcionando.

---

### P3: Auditoria de acesso a segredos

**User Story**: As a developer, I want a log of who accessed which secrets and when so that I can investigate suspicious activity.

**Why P3**: Compliance e investigação pós-incidente; nice-to-have.

**Acceptance Criteria**:

1. WHEN a secret is read from KMS THEN system SHALL log: timestamp, secret alias, caller identity, success/failure
2. WHEN audit log is queried THEN it SHALL be available via AWS CloudTrail integration

---

## Edge Cases

- WHEN AWS credentials (IAM role) expire THEN system SHALL refresh automatically via STS (not crash)
- WHEN KMS rate limit is hit THEN system SHALL cache decrypted secrets in memory (encrypted at rest in process memory)
- WHEN trader has no internet (offline trading with cached Profit DLL data) THEN system SHALL use cached credentials with TTL
- WHEN multiple instances of the platform run (rare but possible) THEN KMS access SHALL NOT create race conditions
- WHEN developer accidentally adds a key to `.env` in dev THEN pre-commit hook SHALL catch it before it reaches the repo

---

## Success Criteria

- [ ] Zero credenciais em plaintext no repositório (verificado por scan automatizado)
- [ ] Sistema inicia e opera normalmente com credenciais exclusivamente do KMS
- [ ] Pre-commit hook bloqueia 100% das tentativas de commit com secrets
- [ ] Tempo de startup adicionado pelo KMS fetch < 2 segundos
