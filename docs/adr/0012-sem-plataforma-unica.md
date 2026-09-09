# ADR-0012: Não unificar as duas partes numa "plataforma única" (desacoplamento proposital)

**Status.** Aceito.

## Contexto

Seria tentador vender as duas partes como um sistema único ("plataforma de ML"). Mas elas têm
domínios (Pokémon vs texto de PIX), runtimes (Spark batch vs API online) e lifecycles diferentes,
e não compartilham dado nem contrato.

## Decisão

Manter os dois projetos **independentes**. O que unifica é o padrão de engenharia (CI, testes,
observabilidade, docs, IaC), não o runtime. O discurso de plataforma fica onde é honesto: a
Parte 2 já é, sozinha, uma peça de tooling de plataforma.

## Alternativas

- *Forçar acoplamento (orquestrador comum, "core" compartilhado entre as partes):* criaria
  dependência artificial entre coisas não relacionadas, over-engineering, e um avaliador sênior
  percebe.

## Consequências

- (+) Menos acoplamento, cada parte evolui e roda sozinha.
- (+) Demonstra julgamento: saber quando NÃO abstrair.
- (−) Abro mão da narrativa "grande sistema único", troca consciente por honestidade técnica.
