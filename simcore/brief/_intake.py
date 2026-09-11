"""Reading an authored brief: YAML in, a validated pack out, every failure a gate failure."""

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from simcore.schemas import BriefPack, CategoryOntology, GateFailure, ProductBrief

# A broken file usually breaks in one way many times over; the first several say what that way is.
MAX_REPORTED_PROBLEMS = 10


def load_brief(path: Path, ontology_dir: Path) -> BriefPack:
    """The authored brief at `path`, joined with the category ontology it names from `ontology_dir`.

    Reads two files and nothing else: no network, no clock, no environment. Anything the brief
    contract refuses, and anything the files cannot supply, is raised as a `GateFailure` naming
    the file it came from and the field within it."""
    brief = _validate(ProductBrief, _read_yaml(path), path)
    ontology = _read_ontology(ontology_dir, brief.product.category, brief.ontology_version)
    return _validate(BriefPack, {"brief": brief, "ontology": ontology}, path)


def _read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise GateFailure(f"{path}: cannot be read ({error.strerror or error})") from error
    return yaml.safe_load(text)


def _read_ontology(ontology_dir: Path, category: str, version: str) -> CategoryOntology:
    path = Path(ontology_dir) / category / f"{version}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise GateFailure(
            f"no ontology for category {category!r} at version {version!r}: looked for {path}"
        ) from error
    except json.JSONDecodeError as error:
        raise GateFailure(f"{path}: is not valid JSON ({error.msg} at line {error.lineno})") from error
    return _validate(CategoryOntology, raw, path)


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
