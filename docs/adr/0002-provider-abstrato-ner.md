# ADR-0002: Abstração do fornecedor de NER (provider pattern)

**Status.** Aceito.

## Contexto

O serviço faz NER com spaCy. O risco é o spaCy vazar por toda a aplicação, de modo que trocar de
modelo/fornecedor no futuro exija reescrever a API. O PicPay valoriza explicitamente "abstrair o
fornecedor" e uma plataforma que atenda diversos casos.

## Decisão

Definir uma interface abstrata `NERProvider` (`load(model_name)`, `predict(text) -> list[Entity]`).
`SpacyNERProvider` é uma implementação. A API e o service só conhecem a interface, nunca o spaCy
diretamente.

## Alternativas

- *Chamar spaCy direto no handler da rota:* mais rápido de escrever, mas acopla o fornecedor à
  API; cada novo modelo/fornecedor vira reescrita e o teste fica difícil de isolar.

## Consequências

- (+) Trocar spaCy por HuggingFace, um endpoint externo ou um modelo próprio não toca a API.
- (+) Testável: dá pra usar um provider fake nos testes, sem carregar modelo real.
- (−) Uma camada de indireção a mais (uma interface + factory).
