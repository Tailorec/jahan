"""The shape-driven synthetic `CoresetSource`: the dataset-independence and quickstart seam.

A shape declares, per attribute, its value set, the distribution over it and how often it is
populated. That single knob is how a test forces a failing gate, a starved quota or a structureless
graph — the scenario is data, not a flag. Generation is deterministic across processes, so the same
shape and seed produce the same rows anywhere, with no dataset downloaded and no socket opened."""

import random
from collections.abc import Mapping
from dataclasses import dataclass

from simcore.schemas import AttributeId, AttributeValue, FrozenDict

from .coreset import DecodedRow, _DecodedRowSource


@dataclass(frozen=True)
class AttributeShape:
    """One attribute's value set, the distribution over it, and how often it is populated."""

    values: tuple[AttributeValue, ...]
    weights: tuple[float, ...] | None = None
    populated: float = 1.0

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("an attribute shape declares at least one value")
        if self.weights is not None:
            if len(self.weights) != len(self.values):
                raise ValueError("weights must match the value set one for one")
            if abs(sum(self.weights) - 1.0) > 1e-6:
                raise ValueError(f"weights must sum to one, got {sum(self.weights)}")
        if not 0.0 <= self.populated <= 1.0:
            raise ValueError(f"populated is a probability, got {self.populated}")


@dataclass(frozen=True)
class SyntheticShape:
    attributes: Mapping[AttributeId, AttributeShape]
    rows: int

    def __post_init__(self) -> None:
        if self.rows < 1:
            raise ValueError("a shape declares at least one row")
        if not self.attributes:
            raise ValueError("a shape declares at least one attribute")


class SyntheticCoresetSource(_DecodedRowSource):
    """Rows generated from a declared shape and a seed, in a fixed attribute order.

    The seed is part of the source, not of any study parameter: two studies that share a shape still
    differ by the shape they declared, and the row set is an input rather than an outcome."""

    def __init__(self, shape: SyntheticShape, seed: int = 0) -> None:
        self._shape = shape
        self._seed = seed
        self._attributes = tuple(sorted(shape.attributes))
        vocabulary = {attribute: shape.attributes[attribute].values for attribute in self._attributes}
        rows = tuple(self._generate(index) for index in range(shape.rows))
        super().__init__(rows, vocabulary)

    def _generate(self, index: int) -> DecodedRow:
        generator = random.Random(f"synthetic-coreset:{self._seed}:{index}")
        values: dict[AttributeId, AttributeValue] = {}
        for attribute in self._attributes:
            shape = self._shape.attributes[attribute]
            if generator.random() < shape.populated:
                values[attribute] = self._choose(generator, shape)
        return DecodedRow(row_id=f"{index:06d}", source="synthetic", values=FrozenDict(values))

    @staticmethod
    def _choose(generator: random.Random, shape: AttributeShape) -> AttributeValue:
        if shape.weights is None:
            return shape.values[generator.randrange(len(shape.values))]
        return generator.choices(shape.values, weights=shape.weights, k=1)[0]
