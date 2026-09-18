"""Rendering findings and digests into documents, and nothing else.

One call — `render(findings, digests, pack)` — builds one intermediate document, then
formats it twice: markdown for a person, JSON-ready data for the pages. The module may
sort, group and format; it may not derive. Every number it prints is a value from the
finding, digest or pack it came from, rendered with `repr` so it reads exactly as the
record holds it.
"""

from dataclasses import dataclass

from simcore.brief import assumptions_of
from simcore.schemas import (
    Finding,
    OutcomeDigest,
)
from simcore.schemas.base import SCHEMA_VERSION, canonical_hash

from ._pack import RenderedReport, ReportPack

# The JSON shape is a contract the mockup pages consume, so it carries the version it
# was rendered under; a page on another version breaks loudly rather than silently.
REPORT_CONTRACT_VERSION = SCHEMA_VERSION

# Ordering rules, explicit rather than incidental: a report is a function of its
# findings, so shuffling the inputs changes nothing and a diff means a difference.
# Findings read in kind order, each kind by id. Clusters read largest first, ties by
# quoted label. Digests read by scenario, then by seed.


def _finding_key(finding: Finding) -> tuple[str, str]:
    return (finding.kind.value, finding.finding_id)


def _cluster_key(label: str) -> str:
    return label


def _digest_key(digest: OutcomeDigest) -> tuple[str, int]:
    return (digest.scenario_hash, digest.seed)


@dataclass(frozen=True)
class _FindingSection:
    finding_id: str
    kind: str
    statement: str
    evidence_trace_ids: tuple[str, ...]
    disconfirming_test: str
    confidence: str


@dataclass(frozen=True)
class _ClusterSection:
    label: str
    size: int
    threshold: float
    verbatim_trace_ids: tuple[str, ...]
    embed_model_id: str


@dataclass(frozen=True)
class _DigestSection:
    scenario_hash: str
    seed: int
    world_id: str
    tick_unit: str
    adoption: float | None
    unmeasured_reason: str | None


@dataclass(frozen=True)
class _AssumptionSection:
    text: str
    source: str


@dataclass(frozen=True)
class _Document:
    """The one intermediate both formats are produced from."""

    run_id: str
    config_hash: str
    contract_version: str
    engine_commit: str
    forced_from: tuple[str, ...]
    trust_level: str
    trust_caveats: tuple[str, ...]
    findings: tuple[_FindingSection, ...]
    clusters: tuple[_ClusterSection, ...]
    digests: tuple[_DigestSection, ...]
    assumptions: tuple[_AssumptionSection, ...]
    pins: tuple[tuple[str, str], ...]
    fallbacks: tuple[tuple[str, str], ...]
    seeds: tuple[int, ...]
    template_hashes: tuple[tuple[str, str], ...]
    anchor_set_hashes: tuple[tuple[str, str], ...]
    validation: str


def _number(value: float) -> str:
    """Render a recorded number exactly as the record holds it — no rounding, no units."""
    return repr(float(value))


def _build(findings: tuple[Finding, ...], digests: tuple[OutcomeDigest, ...], pack: ReportPack) -> _Document:
    ordered_findings = tuple(
        _FindingSection(
            finding_id=finding.finding_id,
            kind=finding.kind.value,
            statement=finding.statement,
            evidence_trace_ids=tuple(finding.evidence_trace_ids),
            disconfirming_test=finding.disconfirming_test,
            confidence=finding.confidence.value,
        )
        for finding in sorted(findings, key=_finding_key)
    )
    by_label = sorted(pack.clusters, key=lambda cluster: _cluster_key(cluster.label))
    ordered_clusters = tuple(
        _ClusterSection(
            label=cluster.label,
            size=cluster.size,
            threshold=cluster.threshold,
            verbatim_trace_ids=tuple(cluster.verbatim_trace_ids),
            embed_model_id=cluster.embed_model_id,
        )
        for cluster in sorted(by_label, key=lambda cluster: cluster.size, reverse=True)
    )
    ordered_digests = tuple(
        _DigestSection(
            scenario_hash=digest.scenario_hash,
            seed=digest.seed,
            world_id=digest.world_id,
            tick_unit=digest.tick_unit.value,
            adoption=digest.adoption,
            unmeasured_reason=digest.unmeasured_reason,
        )
        for digest in sorted(digests, key=_digest_key)
    )
    ledger = assumptions_of(pack.brief_pack)
    pins = pack.config.pins
    roles = ("tier_a", "tier_b", "embed", "safety")
    ordered_pins = tuple(
        (role, getattr(pins, role).model_id) for role in roles if getattr(pins, role) is not None
    )
    return _Document(
        run_id=pack.config.run_id,
        config_hash=canonical_hash(pack.config),
        contract_version=pack.contract_version,
        engine_commit=pack.engine_commit,
        forced_from=tuple(pack.forced_from),
        trust_level=pack.trust.level.value,
        trust_caveats=tuple(pack.trust.caveats),
        findings=ordered_findings,
        clusters=ordered_clusters,
        digests=ordered_digests,
        assumptions=tuple(_AssumptionSection(text=item.text, source=item.source.value) for item in ledger),
        pins=ordered_pins,
        fallbacks=tuple(sorted((role.value, pin.model_id) for role, pin in pins.fallbacks.items())),
        seeds=tuple(pack.config.seeds),
        template_hashes=tuple(sorted(pack.config.template_hashes.items())),
        anchor_set_hashes=tuple(sorted(pack.config.anchor_set_hashes.items())),
        validation=pack.validation.strip(),
    )


def _to_markdown(doc: _Document) -> str:
    lines = ["# Study report", ""]
    lines.extend(["Run " + doc.run_id + " · contract " + doc.contract_version, ""])
    lines.extend(["## Trust", ""])
    lines.extend(["Calibration: " + doc.trust_level + ".", ""])
    for caveat in doc.trust_caveats:
        lines.extend([caveat, ""])
    lines.extend(["## Findings", ""])
    if not doc.findings:
        lines.extend(["No findings were authored for this run.", ""])
    for finding in doc.findings:
        lines.extend(["### " + finding.finding_id + " · " + finding.kind + " · confidence " + finding.confidence, ""])
        lines.extend([finding.statement, ""])
        lines.extend(["Evidence: " + ", ".join(finding.evidence_trace_ids), ""])
        lines.extend(["Disconfirming test: " + finding.disconfirming_test, ""])
    lines.extend(["## Objection clusters", ""])
    if not doc.clusters:
        lines.extend(["No objection clusters were reported for this run.", ""])
    for cluster in doc.clusters:
        lines.extend(
            [
                '"' + cluster.label + '" — '
                + repr(cluster.size)
                + " verbatims at cosine "
                + _number(cluster.threshold),
                "",
            ]
        )
    lines.extend(["## Digests", ""])
    for digest in doc.digests:
        lines.extend(["### World " + digest.world_id + " · seed " + repr(digest.seed), ""])
        lines.extend(["Scenario: " + digest.scenario_hash, ""])
        lines.extend(["Tick unit: " + digest.tick_unit, ""])
        if digest.adoption is None:
            lines.extend(["Adoption: unmeasured — " + str(digest.unmeasured_reason), ""])
        else:
            lines.extend(["Adoption: " + _number(digest.adoption), ""])
    lines.extend(["## Assumption ledger", ""])
    if not doc.assumptions:
        lines.extend(["No assumptions were recorded for this study.", ""])
    for assumption in doc.assumptions:
        lines.extend(["- " + assumption.text + " (" + assumption.source + ")", ""])
    lines.extend(["## Method disclosure", ""])
    for role, model_id in doc.pins:
        lines.extend(["- " + role + ": " + model_id, ""])
    for role, model_id in doc.fallbacks:
        lines.extend(["- fallback " + role + ": " + model_id, ""])
    lines.extend(["Seeds: " + ", ".join(repr(seed) for seed in doc.seeds), ""])
    for name, template_hash in doc.template_hashes:
        lines.extend(["- template " + name + ": " + template_hash, ""])
    for name, anchor_hash in doc.anchor_set_hashes:
        lines.extend(["- anchor set " + name + ": " + anchor_hash, ""])
    lines.extend(["Engine commit: " + doc.engine_commit, ""])
    if doc.forced_from:
        lines.extend(
            [
                "This run was forced across engine versions: "
                + ", ".join(doc.forced_from)
                + " → "
                + doc.engine_commit
                + "; worlds from different code are not directly comparable.",
                "",
            ]
        )
    lines.extend(["Config hash: " + doc.config_hash, ""])
    lines.extend(["## Recommended real-world validation", ""])
    lines.extend([doc.validation, ""])
    return "\n".join(lines)


def _to_data(doc: _Document) -> dict:
    return {
        "contract_version": doc.contract_version,
        "run_id": doc.run_id,
        "config_hash": doc.config_hash,
        "engine_commit": doc.engine_commit,
        "forced_from": list(doc.forced_from),
        "trust": {"level": doc.trust_level, "caveats": list(doc.trust_caveats)},
        "findings": [
            {
                "finding_id": finding.finding_id,
                "kind": finding.kind,
                "statement": finding.statement,
                "evidence_trace_ids": list(finding.evidence_trace_ids),
                "disconfirming_test": finding.disconfirming_test,
                "confidence": finding.confidence,
            }
            for finding in doc.findings
        ],
        "objection_clusters": [
            {
                "label": cluster.label,
                "size": cluster.size,
                "threshold": cluster.threshold,
                "verbatim_trace_ids": list(cluster.verbatim_trace_ids),
                "embed_model_id": cluster.embed_model_id,
            }
            for cluster in doc.clusters
        ],
        "digests": [
            {
                "scenario_hash": digest.scenario_hash,
                "seed": digest.seed,
                "world_id": digest.world_id,
                "tick_unit": digest.tick_unit,
                "adoption": digest.adoption,
                "unmeasured_reason": digest.unmeasured_reason,
            }
            for digest in doc.digests
        ],
        "assumptions": [
            {"text": assumption.text, "source": assumption.source} for assumption in doc.assumptions
        ],
        "method": {
            "pins": [{"role": role, "model_id": model_id} for role, model_id in doc.pins],
            "fallbacks": [{"role": role, "model_id": model_id} for role, model_id in doc.fallbacks],
            "seeds": list(doc.seeds),
            "template_hashes": [
                {"name": name, "hash": template_hash} for name, template_hash in doc.template_hashes
            ],
            "anchor_set_hashes": [
                {"name": name, "hash": anchor_hash} for name, anchor_hash in doc.anchor_set_hashes
            ],
        },
        "validation": doc.validation,
    }


def render(
    findings: tuple[Finding | dict, ...],
    digests: tuple[OutcomeDigest | dict, ...],
    pack: ReportPack,
) -> RenderedReport:
    """Format validated findings and digests into markdown and JSON-ready data.

    Both formats are produced from one intermediate over the same finding set. Hand-built
    finding sets are welcome: mappings are validated into `Finding` and `OutcomeDigest`
    on the way in.
    """
    validated_findings = tuple(
        finding if isinstance(finding, Finding) else Finding.model_validate(finding) for finding in findings
    )
    validated_digests = tuple(
        digest if isinstance(digest, OutcomeDigest) else OutcomeDigest.model_validate(digest)
        for digest in digests
    )
    doc = _build(validated_findings, validated_digests, pack)
    return RenderedReport(markdown=_to_markdown(doc), data=_to_data(doc))
