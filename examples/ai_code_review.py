"""The real-data study: an AI code-review assistant tested on Stack Overflow's measured rows.

Run it with ``python examples/ai_code_review.py`` **after** fetching the shards it needs. Nothing here
downloads on its own — a missing shard is refused with the exact command that fetches it (ADR 0016).
This is the study the corpus exists to run: Stack Overflow is the one source carrying demographics and
developer attitudes on the same person, so its audiences filter real survey rows rather than projections.
Its gate report grades as *extracted*, and that is the point: the demographic and professional fields are
measured, but part of `att_ai` and `coding_ai_sentiment` was inferred by a model from other answers —
and filtering for skeptics draws inferred `att_ai` values at about twice the corpus rate.

    hf download MatrAIx2026/MatrAIx_Persona_1M_Public_Release --repo-type dataset --local-dir "$HOME/.cache/consumersim/coreset/MatrAIx2026__MatrAIx_Persona_1M_Public_Release"
"""

from pathlib import Path

from simcore.brief import load_brief
from simcore.population import PreviewRequest, assess, build, preview
from simcore.ports.fake import FakeChat
from simcore.ports.hf import HfCoresetSource, MissingShard, default_cache_dir
from simcore.ports.index_catalog import from_hf_source
from simcore.schemas import DistributionThresholds, PopulationParameters

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = "MatrAIx2026/MatrAIx_Persona_1M_Public_Release"
SOURCES = ("stackoverflow",)


def cache_dir() -> Path:
    import os

    override = os.environ.get("CONSUMERSIM_CORESET_CACHE")
    return Path(override) if override else default_cache_dir(REPO)


def pack():
    return load_brief(HERE / "code_review_ai.yaml", ROOT / "ontologies")


def _shards_holding(cache: Path, sources: tuple[str, ...]) -> list[str]:
    """Which cached shards actually carry a source, read from each shard's `source` column — the corpus
    segregates sources across shards, and the manifest records counts per source but not per shard."""
    import json

    import pyarrow.parquet as pq

    manifest = json.loads((cache / "manifest.json").read_text())
    wanted = set(sources)
    found = []
    for entry in manifest["files"]:
        path = cache / entry["path"]
        if not path.is_file():
            continue
        if wanted & set(pq.read_table(path, columns=["source"])["source"].to_pylist()):
            found.append(entry["path"])
    return found


def coresets(cache: Path):
    shards = _shards_holding(cache, SOURCES)
    if not shards:
        raise MissingShard(
            f"no cached shard carries {list(SOURCES)}; fetch the release with: "
            f'hf download {REPO} --repo-type dataset --local-dir "{cache}"'
        )
    source = HfCoresetSource(cache_dir=cache, shards=shards, sources=SOURCES)
    index = from_hf_source(source, tuple(pack().ontology.relevance_order), sources=SOURCES)
    return source, index


def run(n: int = 1500, seed: int = 4021, cache: Path | None = None):
    """Preview from the index, then assess and build from the shards — the two stages of the pre-flight.

    The distribution gates are held at a deliberately loose significance: on a stack of measured marginals
    this study is checking *that* the draw resembles its pools, not chasing a two-decimal p-value, and the
    loosened threshold is recorded on the manifest wherever the population travels."""
    cache = cache or cache_dir()
    source, index = coresets(cache)
    parameters = PopulationParameters(distribution_gates=DistributionThresholds(significance_level=0.001, similarity_threshold=0.6))
    forecast = preview(PreviewRequest(pack(), n, parameters=parameters), catalog=index)
    report = assess(pack(), n, seed, coreset=source, parameters=parameters)
    built = build(pack(), n, seed, coreset=source, inference=FakeChat(), parameters=parameters)
    return forecast, report, built.population


def main() -> None:
    cache = cache_dir()
    if not (cache / "manifest.json").is_file():
        print(f"no coreset cached at {cache}; fetch it first:")
        print(f"  hf download {REPO} --repo-type dataset --local-dir {cache}")
        raise SystemExit(2)
    try:
        forecast, report, population = run(cache=cache)
    except MissingShard as error:
        print(str(error))
        raise SystemExit(2) from error
    print("software_dev / code-review AI — real survey rows")
    print(f"  preview evidence {forecast.evidence.value}; report evidence {report.evidence.value}")
    print(f"  source mix {dict(report.source_mix)}")
    print(f"  gates overall {report.overall}; {len(population.personas)} personas; hash {population.population_hash[:12]}")


if __name__ == "__main__":
    main()
