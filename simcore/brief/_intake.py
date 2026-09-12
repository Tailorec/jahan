"""Reading an authored brief: YAML in, a validated pack out, every failure a gate failure."""

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from simcore.schemas import BriefPack, CategoryOntology, Evidence, GateFailure, ProductBrief

# A broken file usually breaks in one way many times over; the first several say what that way is.
MAX_REPORTED_PROBLEMS = 10

# The machine-written evidence beside a brief: `<brief>.evidence.json`, keyed by cited URL.
SIDECAR_SUFFIX = ".evidence.json"


def load_brief(path: Path, ontology_dir: Path) -> BriefPack:
    """The authored brief at `path`, joined with the category ontology it names from `ontology_dir`.

    Reads two files and nothing else: no network, no clock, no environment. Anything the brief
    contract refuses, and anything the files cannot supply, is raised as a `GateFailure` naming
    the file it came from and the field within it."""
    payload = _join_evidence(_read_yaml(path), path)
    brief = _validate(ProductBrief, payload, path)
    ontology = _read_ontology(ontology_dir, brief.product.category, brief.ontology_version)
    return _validate(BriefPack, {"brief": brief, "ontology": ontology}, path)


class _RefuseDuplicateKeys(yaml.SafeLoader):
    """`safe_load` keeps the last of a repeated key, so a brief with two `claims:` blocks would
    silently lose one — and its hash would pin the truncated study."""


def _mapping_without_duplicates(loader: _RefuseDuplicateKeys, node: yaml.MappingNode, deep: bool = False) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while reading a mapping", node.start_mark, f"the key {key!r} is given more than once", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_RefuseDuplicateKeys.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_without_duplicates)


def _read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise GateFailure(f"{path}: cannot be read ({error.strerror or error})") from error
    try:
        payload = yaml.load(text, _RefuseDuplicateKeys)
    except yaml.constructor.ConstructorError as error:
        where = f" (line {error.problem_mark.line + 1})" if error.problem_mark is not None else ""
        raise GateFailure(f"{path}: {error.problem}{where}") from error
    except yaml.YAMLError as error:
        raise GateFailure(f"{path}: is not valid YAML\n{error}") from error
    if payload is None:
        raise GateFailure(f"{path}: is empty")
    if not isinstance(payload, dict):
        raise GateFailure(f"{path}: must be a mapping of fields at its top level, not {_describe(payload)}")
    return payload


def _sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + SIDECAR_SUFFIX)


def _join_evidence(payload: dict, path: Path) -> dict:
    """Replace each claim's `evidence_url` with the `Evidence` the sidecar supplies for it.

    Claim identity is a claim's position, so an authored id is refused; evidence comes from the
    sidecar, so an authored `evidence` mapping is refused rather than trusted."""
    claims = payload.get("claims")
    if not isinstance(claims, list):
        return payload
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        if "id" in claim:
            raise GateFailure(
                f"{path}: claims[{index}].id: claim identifiers are assigned by position and must not be authored"
            )
        if "evidence_url" in claim and not (isinstance(claim["evidence_url"], str) and claim["evidence_url"].strip()):
            raise GateFailure(
                f"{path}: claims[{index}].evidence_url: cite a url or leave the field out; "
                f"an empty citation is neither ({claim['evidence_url']!r})"
            )
        if "evidence" in claim:
            raise GateFailure(
                f"{path}: claims[{index}].evidence: evidence is supplied by the sidecar, not authored; cite it with `evidence_url`"
            )
    cited = {claim["evidence_url"] for claim in claims if isinstance(claim, dict) and claim.get("evidence_url")}
    if not cited:
        return payload
    sidecar = _read_sidecar(path)
    sidecar_path = _sidecar_path(path)
    for index, claim in enumerate(claims):
        url = claim.pop("evidence_url", None) if isinstance(claim, dict) else None
        if url is None:
            continue
        entry = sidecar.get(url)
        if entry is None:
            raise GateFailure(
                f"{path}: claims[{index}].evidence_url: {url!r} was cited but never fetched; "
                f"{sidecar_path} has no entry for it"
            )
        if not isinstance(entry, dict):
            raise GateFailure(
                f"{sidecar_path}: the entry for {url!r} must be a mapping of what was retrieved, not {_describe(entry)}"
            )
        stated = entry.get("url")
        if stated is not None and stated != url:
            raise GateFailure(
                f"{sidecar_path}: the entry for {url!r} names a different url {stated!r}; "
                "a claim's evidence is what it cites, whatever a redirect led to"
            )
        # The cited url is the provenance and cannot be displaced by the entry (ADR 0013).
        claim["evidence"] = _validate(Evidence, {**entry, "url": url}, sidecar_path)
    return payload


def _read_sidecar(path: Path) -> dict:
    sidecar_path = _sidecar_path(path)
    if not sidecar_path.is_file():
        raise GateFailure(f"{path}: cites evidence but its sidecar {sidecar_path} is missing")
    try:
        raw = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise GateFailure(f"{sidecar_path}: cannot be read ({error.strerror or error})") from error
    except json.JSONDecodeError as error:
        raise GateFailure(f"{sidecar_path}: is not valid JSON ({error.msg} at line {error.lineno})") from error
    if not isinstance(raw, dict):
        raise GateFailure(f"{sidecar_path}: must be a mapping of cited URLs at its top level, not {_describe(raw)}")
    return raw


def _read_ontology(ontology_dir: Path, category: str, version: str) -> CategoryOntology:
    directory = Path(ontology_dir) / category
    path = directory / f"{version}.json"
    if not path.is_file():
        raise GateFailure(_missing_ontology(category, version, directory, path))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise GateFailure(f"{path}: cannot be read ({error.strerror or error})") from error
    except json.JSONDecodeError as error:
        raise GateFailure(f"{path}: is not valid JSON ({error.msg} at line {error.lineno})") from error
    ontology = _validate(CategoryOntology, raw, path)
    if (ontology.category, ontology.version) != (category, version):
        raise GateFailure(
            f"{path}: declares category {ontology.category!r} at version {ontology.version!r}, "
            f"but its path says {category!r} at version {version!r}"
        )
    return ontology


def _missing_ontology(category: str, version: str, directory: Path, path: Path) -> str:
    looked = f"no ontology for category {category!r} at version {version!r}: looked for {path}"
    if not directory.is_dir():
        return f"{looked}; the category directory {directory} does not exist"
    present = sorted(item.stem for item in directory.glob("*.json"))
    listing = ", ".join(repr(item) for item in present) if present else "none"
    return f"{looked}; versions present: {listing}"


def _validate(model: type, payload: Any, path: Path):
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        raise GateFailure(_format(error, path)) from error


def _format(error: ValidationError, path: Path) -> str:
    problems = error.errors()
    lines = [f"{path}: {_where(problem['loc'])}{problem['msg']}{_got(problem)}" for problem in problems[:MAX_REPORTED_PROBLEMS]]
    if len(problems) > MAX_REPORTED_PROBLEMS:
        lines.append(f"{path}: and {len(problems) - MAX_REPORTED_PROBLEMS} more problems")
    return "\n".join(lines)


def _where(loc: tuple) -> str:
    """A field path in the author's terms: `claims[1].source`, indices as the file orders them."""
    rendered = ""
    for part in loc:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}" if rendered else str(part)
    return f"{rendered}: " if rendered else ""


def _got(problem: dict) -> str:
    value = problem.get("input")
    if isinstance(value, (dict, list)) or value is None:
        return ""
    return f" (got {value!r})"


def _describe(payload: Any) -> str:
    return {list: "a list", str: "text", int: "a number", float: "a number", bool: "a true/false value"}.get(
        type(payload), type(payload).__name__
    )
