"""Provider fake para isolar testes de spaCy real (ADR-0002: "provider fake nos testes").

Mora em tests/, não em src/nercore: não tem valor de produção, e ficar dentro de
nercore criaria o risco de alguém importar por engano em código de aplicação real.
`conftest.py` deve conter só fixtures que *usam* esta classe, não a classe em si, pra
manter a flexibilidade de instanciar variantes por teste (ex.: `FakeProvider(raise_on_load=True)`
para exercitar o caminho de erro de `/load/`).
"""

from __future__ import annotations

from src.nercore.providers.base import ModelLoadError, NERProvider
from src.nercore.schemas import Entity


class FakeProvider(NERProvider):
    def __init__(
        self,
        entities: list[Entity] | None = None,
        raise_on_load: bool = False,
    ) -> None:
        self._entities = entities if entities is not None else []
        self._raise_on_load = raise_on_load
        self._model_name: str | None = None
        self.load_calls: list[str] = []
        self.predict_calls: list[str] = []

    def load(self, model_name: str) -> None:
        self.load_calls.append(model_name)
        if self._raise_on_load:
            raise ModelLoadError(f"falha simulada ao carregar '{model_name}'")
        self._model_name = model_name

    def predict(self, text: str) -> list[Entity]:
        self.predict_calls.append(text)
        return list(self._entities)

    def is_loaded(self, model_name: str) -> bool:
        return self._model_name == model_name
