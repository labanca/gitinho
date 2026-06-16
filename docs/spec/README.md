# Spec do Gitinho

Base documental pra rebuild e manutenção do projeto. Cada doc é um spec executável — descreve **o que o sistema DEVE fazer**, não como o código atual está organizado.

## Ordem de leitura

1. **[`01-acceptance-cases.md`](01-acceptance-cases.md)** — Casos canônicos de pergunta extraídos do histórico de produção. Cada caso descreve pergunta, tool calls esperados, render esperado e anti-padrões observados. É o spec executável — qualquer rebuild precisa passar nesses casos.

2. **[`02-security-invariants.md`](02-security-invariants.md)** — O que NÃO pode regredir. 10 invariantes (read-only, org allowlist, GitHub App, CSP, etc.) com referência ao código que enforça hoje e como detectar regressão.

3. **[`03-anti-patterns.md`](03-anti-patterns.md)** — Catálogo de falhas reais observadas em produção (XML vazando como texto, code blocks vazios, agente chutando paths, hang de 20min, etc.). Cada anti-padrão tem causa raiz, exemplo concreto e regra de prevenção.

## Como atualizar

- **Caso novo** (pergunta de usuário que não cabe em nenhuma família) → adicionar em `01` ANTES de mexer em código.
- **Invariante quebrada** (e.g., adição de método mutador no GitHub client) → o `02` é o gate; o PR deve ser barrado.
- **Novo modo de falha** → entrar em `03` com referência ao commit do fix. Aí vira regression test.

## Princípio

> Spec ANTES de código. Cada decisão técnica que vire trade-off de longo prazo precisa de ADR (a criar em `docs/adr/` quando houver demanda). Cada comportamento observável precisa de caso de aceitação. Cada bug que cair precisa de anti-padrão.
