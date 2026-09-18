"""Phase 4: objection clusters — deterministic, quoted, embedded once."""

import numpy as np
import pytest

from simcore.analysis import cluster_objections
from simcore.ports.embed import EmbedResult
from simcore.ports.fake import FakeEmbed
from simcore.schemas import VerbatimGrouping
from simcore.trace import TraceStore
from tests.boundary.trace.support import seed_header_and_entry, write_by_tick
from tests.study_builders import partition_payload

from simcore.schemas import TraceEvent


class _CountingEmbed(FakeEmbed):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return super().embed(texts)


class _TopicalEmbed:
    """Paraphrases share a direction; different topics are orthogonal."""

    model_id = "test/topical"

    def embed(self, texts):
        vectors = []
        for text in texts:
            lowered = text.lower()
            if any(word in lowered for word in ("price", "expensive", "cost")):
                vectors.append([1.0, 0.0, 0.0])
            elif any(word in lowered for word in ("taste", "flavour", "flavor")):
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return EmbedResult(vectors=np.asarray(vectors, dtype=np.float32), model_id=self.model_id,
                           served_model_id=self.model_id, normalization="l2", dim=3, costs=())


class _SingleTextView:
    """A minimal view over caller-supplied verbatims, for clustering fixtures."""

    def __init__(self, texts):
        from simcore.schemas import VerbatimGroup, VerbatimRecord

        records = [
            VerbatimRecord.model_validate({
                "event_id": f"ev-{'0' * 21}{index:05d}",
                "persona_id": f"p-00000{index % 3 + 1}",
                "tick": index,
                "subject_stimulus_id": f"st-{'0' * 21}{index:05d}",
                "action": "comment",
                "text": text,
            })
            for index, text in enumerate(texts)
        ]
        by_persona: dict[str, list] = {}
        for record in records:
            by_persona.setdefault(record.persona_id, []).append(record)
        self._groups = tuple(
            VerbatimGroup(grouping=VerbatimGrouping.PERSONA, key=persona, records=tuple(items))
            for persona, items in sorted(by_persona.items())
        )

    def verbatims(self, grouping):
        assert grouping is VerbatimGrouping.PERSONA
        return self._groups


def _seeded_view(store: TraceStore):
    from tests.study_builders import partition_payload as payload

    header, entry = seed_header_and_entry(store)
    events = [TraceEvent.model_validate(record) for record in payload()["events"]]
    write_by_tick(store, events)
    return store.view(entry.config.run_id, header.world_id)


def test_clustering_twice_produces_identical_clusters_in_identical_order(tmp_path):
    store = TraceStore(tmp_path)
    view = _seeded_view(store)
    embed = FakeEmbed()
    first = cluster_objections(view, embed=embed, threshold=0.75, seed=4021)
    second = cluster_objections(store.view(view._run_id, view._worlds[0]), embed=embed, threshold=0.75, seed=4021)
    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]


def test_cluster_label_is_a_verbatim_from_the_trace(tmp_path):
    store = TraceStore(tmp_path)
    view = _seeded_view(store)
    clusters = cluster_objections(view, embed=FakeEmbed(), threshold=0.99, seed=7)
    texts = {record.text for group in view.verbatims(VerbatimGrouping.PERSONA) for record in group.records}
    assert clusters
    for cluster in clusters:
        assert cluster.label in texts


def test_threshold_is_a_recorded_parameter_on_every_cluster():
    view = _SingleTextView(["too expensive for me", "the taste is off"])
    clusters = cluster_objections(view, embed=_TopicalEmbed(), threshold=0.6, seed=0)
    assert clusters
    assert all(cluster.threshold == 0.6 for cluster in clusters)


def test_paraphrases_group_together_on_a_built_fixture():
    view = _SingleTextView([
        "too expensive for daily use",
        "the price is too high",
        "the taste is strange",
        "odd flavour, did not like it",
    ])
    clusters = cluster_objections(view, embed=_TopicalEmbed(), threshold=0.5, seed=0)
    assert len(clusters) == 2
    assert sorted(len(c.verbatim_trace_ids) for c in clusters) == [2, 2]


def test_verbatims_embedded_once_per_run():
    view = _SingleTextView(["too expensive", "the price is high", "tastes odd"])
    embed = _CountingEmbed()
    cluster_objections(view, embed=embed, threshold=0.5, seed=0)
    assert embed.calls == 1


def test_no_verbatims_produces_no_clusters_and_no_error():
    assert cluster_objections(_SingleTextView([]), embed=FakeEmbed()) == ()
