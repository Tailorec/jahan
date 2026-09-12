"""The three independent random streams a population spawns from its one population seed.

Sampling, graph rewiring and community detection each draw from their own stream, so no two stages can
correlate and none is left unseeded. Spawning them from one seed rather than authoring three keeps a
caller from setting two equal and quietly coupling two stages (ADR 0001)."""

import numpy as np


def spawn(population_seed: int) -> tuple[int, int, int]:
    """`(sampling, rewiring, communities)` seeds, each independent of the other two."""

    def seed(child: np.random.SeedSequence) -> int:
        return int(child.generate_state(1, dtype=np.uint64)[0])

    sampling, rewiring, communities = np.random.SeedSequence(population_seed).spawn(3)
    return seed(sampling), seed(rewiring), seed(communities)
