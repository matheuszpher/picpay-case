# ADR-0001: Entrega em um único repositório Git

**Status.** Aceito.

## Contexto

O case tem duas partes (análise batch e microserviço de serving) e pede submissão por um
repositório Git público. Preciso decidir se é um repo ou dois.

## Decisão

Um único repositório, com cada parte em um diretório autossuficiente
(`part1-pokeapi-analytics/`, `part2-ner-serving/`), mais `docs/`, `infra/` e `.github/` na raiz.

## Alternativas

- *Dois repositórios separados:* mais isolado, mas fragmenta a avaliação, duplica configuração
  de CI/docs e dificulta enxergar o padrão de engenharia comum.
- *Monorepo com pacote compartilhado entre as partes:* rejeitado, ver [ADR-0012](0012-sem-plataforma-unica.md), não há código
  de domínio que valha compartilhar.

## Consequências

- (+) Uma leitura só, um README raiz que dá o tour, CI e convenções compartilhadas.
- (+) Fácil para o avaliador clonar e rodar cada parte.
- (−) Exige disciplina para as duas partes não vazarem dependências uma na outra (mitigado: cada
  diretório tem seu próprio ambiente/Docker).
