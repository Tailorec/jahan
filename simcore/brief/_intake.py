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


def _describe(payload: Any) -> str:
    return {list: "a list", str: "text", int: "a number", float: "a number", bool: "a true/false value"}.get(
        type(payload), type(payload).__name__
    )
