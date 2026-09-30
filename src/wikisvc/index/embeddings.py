"""Extension contract. The MVP has no embedding provider and performs no model calls."""

from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
