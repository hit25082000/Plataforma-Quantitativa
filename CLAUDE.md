# Diretrizes de Engenharia Composta
Este projeto segue o ciclo: Plan → Work → Review → Compound → Repeat.
1. PLAN (Planejar):
- Nunca comece a codificar imediatamente.
- Primeiro, entenda o requisito, analise a base de código e crie um plano passo a passo.
- Salve o plano em `docs/plans/`. Aguarde a aprovação humana antes de codificar.
2. WORK (Trabalhar):
- Execute o plano focado em isolamento.
- Valide o código com testes e linting após cada mudança.
- Se o plano falhar, pare e adapte o plano antes de tentar "forçar" o código.
3. REVIEW (Revisar):
- Analise o código em busca de problemas de segurança, performance e arquitetura.
- Documente os achados na pasta `todos/` categorizados como P1 (Crítico), P2 (Importante) ou P3 (Opcional).
4. COMPOUND (Consolidar - O Mais Importante):
- Após finalizar uma tarefa, extraia os aprendizados.
- O que funcionou? O que falhou? Qual padrão devemos adotar?
- Documente a solução em `docs/solutions/` com metadados/tags claras.
- Atualize este arquivo (`CLAUDE.md`) com novos padrões e preferências de código à medida que aprendemos com os erros.

## Padroes aprendidos
- Endpoints de warm-up que recebem seletor de serie devem aplicar esse seletor antes de calcular o snapshot.
- Ao trocar IFR de 30m para Renko, reidrate o estado historico do ticker ativo antes de emitir o primeiro valor.
- Fluxos de warm-up do IFR devem expor loading visual para evitar parecer travamento durante a troca de serie.
- Status de mercado deve priorizar loading de troca/Times & Trades antes de heuristicas de fora do pregao.
