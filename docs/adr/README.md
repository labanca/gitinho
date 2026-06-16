# Architecture Decision Records (ADRs)

Decisões arquiteturais com lifetime longo. Cada ADR captura **o porquê** de uma decisão pra que daqui a 6 meses (ou pra um dev novo) ela não seja revisitada por desconhecimento. Diferente do `docs/spec/`, que descreve o que o sistema FAZ, ADR descreve **por que foi feito assim** e o que foi considerado e rejeitado.

## Formato

Cada ADR é numerada sequencialmente (`0001-...md`, `0002-...md`, ...). Mesmo se uma for revogada, o número não é reusado.

Estrutura:

- **Status**: `Proposed`, `Accepted`, `Deprecated`, `Superseded by NNNN` — qualquer mudança vira commit visível.
- **Context**: situação que motivou a decisão. Concreto, com referências de código onde aplicável.
- **Decision**: o que foi decidido. Direto, sem hedge.
- **Consequences**: bom e ruim. Não dourar.
- **Alternatives considered**: o que foi avaliado e rejeitado, com motivo curto.
- **Enforcement**: como detectar regressão (lint, test, code review check).
- **References**: links pra código, specs, outras ADRs.

## Quando criar ADR

- Decisão de longo prazo que afeta como o sistema cresce.
- Tradeoff não-óbvio que outro dev questionaria.
- Algo que "todo mundo sabe" mas não está documentado — e por isso vai ser revisitado.

## Quando NÃO criar ADR

- Decisão tática de implementação (vai mudar em 2 sprints).
- Algo já capturado em `docs/spec/`.
- "Vamos usar React" — convenção da indústria, não decisão local.

## Índice atual

| # | Título | Status |
|---|---|---|
| [0001](0001-one-mcp-per-external-domain.md) | One MCP server per external domain | Accepted |
| [0002](0002-one-proxy-route-per-external-domain.md) | One proxy route per external domain | Accepted |
