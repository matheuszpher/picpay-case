"""Implementação de NERProvider usando spaCy (ADR-0002, ADR-0011).

Cada instância de `SpacyNERProvider` guarda no máximo um pipeline spaCy carregado
(`self._nlp`) e o nome do modelo que ele representa. É esse "um provider por modelo"
que resolve a ausência de parâmetro `model` em `predict()`: quem decide QUAL modelo
usar é a camada acima (`ModelRegistry`, fase 2.2), que mantém uma instância de
provider por modelo registrado e chama `predict()` na instância certa.
"""

from __future__ import annotations

import spacy
from spacy.language import Language
from spacy.util import is_package

from src.nercore.providers.base import ModelLoadError, NERProvider
from src.nercore.schemas import Entity


class SpacyNERProvider(NERProvider):
    def __init__(self) -> None:
        self._model_name: str | None = None
        self._nlp: Language | None = None

    def load(self, model_name: str) -> None:
        if not is_package(model_name):
            try:
                spacy.cli.download(model_name)
            except (Exception, SystemExit) as exc:
                # spacy.cli.download chama sys.exit em alguns caminhos de falha
                # (nome de modelo inexistente, sem rede); convertido em exceção de
                # domínio para o chamador não precisar conhecer detalhes do spaCy.
                raise ModelLoadError(
                    f"falha ao baixar o modelo spaCy '{model_name}'"
                ) from exc
        self._nlp = spacy.load(model_name)
        self._model_name = model_name

    def predict(self, text: str) -> list[Entity]:
        if self._nlp is None:
            raise RuntimeError("SpacyNERProvider.predict() chamado antes de load()")
        doc = self._nlp(text)
        return [
            Entity(
                label=ent.label_,
                text=ent.text,
                start_char=ent.start_char,
                end_char=ent.end_char,
            )
            for ent in doc.ents
        ]

    def is_loaded(self, model_name: str) -> bool:
        return self._model_name == model_name and self._nlp is not None
