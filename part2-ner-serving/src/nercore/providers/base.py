"""Interface abstrata do fornecedor de NER (ADR-0002).

A API e o `NERService` só conhecem `NERProvider`, nunca uma implementação concreta.
Trocar spaCy por outro fornecedor no futuro significa escrever uma nova classe aqui,
sem tocar em nenhuma camada acima.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.nercore.schemas import Entity


class ModelLoadError(Exception):
    """Um provider falhou ao carregar um modelo (não instalado e download falhou).

    Vive aqui, não numa implementação concreta, porque é um erro de contrato da
    interface `NERProvider`: qualquer implementação (spaCy, ou outra futura) pode
    levantá-lo, e quem chama `load()` não deveria precisar importar de um módulo de
    fornecedor específico só para tratar essa exceção.
    """


class NERProvider(ABC):
    @abstractmethod
    def load(self, model_name: str) -> None:
        """Garante que `model_name` está carregado em memória, baixando se preciso."""

    @abstractmethod
    def predict(self, text: str) -> list[Entity]:
        """Roda NER sobre `text` usando o modelo carregado mais recentemente."""

    @abstractmethod
    def is_loaded(self, model_name: str) -> bool:
        """Diz se `model_name` já está carregado em memória, sem tentar carregar."""
