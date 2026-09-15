"""The offline quickstart: a synthetic population, no corpus, no download.

Run it with ``python examples/beverage_quickstart.py``. Every field it conditions on is supplied by the
synthetic source, so the population it grades is measured stand-in data — this study is a smoke test of
the engine, not a claim about the real beverage category, and it carries no category targets to pretend
otherwise (ADR 0017, ADR 0018).
"""

from pathlib import Path

from simcore.brief import load_brief
from simcore.population import PreviewRequest, assess, build, preview
from simcore.ports.fake import FakeChat
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# The synthetic shape supplies exactly the attributes the beverage ontology conditions on and filters by,
# so nothing is synthesized: what the study draws is what the stand-in corpus carries.
SHAPE = SyntheticShape(
    {
        "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
        "sex": AttributeShape(("female", "male")),
        "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
        "diet_protein_focus": AttributeShape(("low", "medium", "high")),
    },
    rows=4000,
)


def coreset() -> SyntheticCoresetSource:
    return SyntheticCoresetSource(SHAPE, seed=11)


def pack():
    return load_brief(HERE / "protein_water.yaml", ROOT / "ontologies")


def run(n: int = 400, seed: int = 4021):
    """Preview, assess and build the quickstart against the synthetic source, offline."""
    source = coreset()
    forecast = preview(PreviewRequest(pack(), n), catalog=source)
    report = assess(pack(), n, seed, coreset=source)
    built = build(pack(), n, seed, coreset=source, inference=FakeChat())
    return forecast, report, built.population


def main() -> None:
    forecast, report, population = run()
    print("beverage_protein quickstart — offline, synthetic, downloads nothing")
    print(f"  sources {sorted(catalog_totals(forecast))}")
    print(f"  synthesized fields {forecast.synthesized_fields} ({forecast.synthesized_share:.1%} of projected)")
    print(f"  evidence {forecast.evidence.value} -> report {report.evidence.value}")
    print(f"  gates overall {report.overall}; population {len(population.personas)} personas; hash {population.population_hash[:12]}")


def catalog_totals(forecast):
    return {source.source: source.total for source in forecast.sources}


if __name__ == "__main__":
    main()
