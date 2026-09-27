"""The packed decoder: the corpus's on-disk row format translated to what the engine consumes.

Three rules the dataset card omits and each cost a wrong answer to learn: codes are indexed from zero,
two to a byte, low nibble first; the null bitmap is the sole authority on presence and may be absent
entirely, which means fully populated; and `attribute_overrides` supersede the code, sit on code 0
without exception, and are out of vocabulary without exception. The decoder verifies its own output
against the corpus's `populated_attribute_count` and fails loudly on mismatch.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

# Structured missingness: the override carries a sentinel rather than a value.
_MISSINGNESS = frozenset({"null", "none", "n/a", "na", "not applicable", "no coding activity", "unknown", ""})


@dataclass(frozen=True)
class Codebook:
    """The ordered 1,290-field codebook: the attribute at each field index and the vocabulary a code
    selects from. Read from the corpus's own `persona_codes.schema.json`; no row enters the
    repository."""

    columns: tuple[Mapping[str, object], ...]  # each: {"id": str, "values": list[str]}

    @classmethod
    def from_json(cls, path: Path) -> "Codebook":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(columns=tuple(dict(col) for col in data["columns"]))

    @property
    def attributes(self) -> tuple[str, ...]:
        return tuple(col["id"] for col in self.columns)  # type: ignore[misc]

    def vocabulary(self, attribute: str) -> tuple[str, ...] | None:
        for col in self.columns:
            if col["id"] == attribute:  # type: ignore[comparison-overlap]
                return tuple(str(v) for v in col["values"])  # type: ignore[union-attr]
        return None

    def label(self, attribute: str) -> str:
        for col in self.columns:
            if col["id"] == attribute:  # type: ignore[comparison-overlap]
                return str(col.get("label") or attribute)  # type: ignore[union-attr]
        return attribute

    def category(self, attribute: str) -> str:
        for col in self.columns:
            if col["id"] == attribute:  # type: ignore[comparison-overlap]
                return str(col.get("category") or "")  # type: ignore[union-attr]
        return ""

    @property
    def field_count(self) -> int:
        return len(self.columns)

    @property
    def row_bytes(self) -> int:
        return (len(self.columns) + 1) // 2  # two 4-bit codes per byte


def decode_row(
    codebook: Codebook,
    attributes: bytes,
    null_bitmap: bytes | None,
    overrides: Sequence[tuple[int, str]] | None,
    populated_attribute_count: int,
    *,
    row_id: str = "",
) -> dict[str, str]:
    """Decode one packed row to the attribute values it carries.

    A field absent from the result was either marked missing in the bitmap, carried a code beyond the
    vocabulary, or had an override whose value was structured missingness or could not be mapped. The
    returned map is the decoded state after all three rules are applied, but the self-check against
    `populated_attribute_count` counts the bitmap-present fields before override folding, which is what
    the corpus's own populated count represents."""
    columns = codebook.columns
    field_count = len(columns)
    codes = _nibbles(attributes)[:field_count]

    present_fields: list[int] = []
    decoded: dict[str, str] = {}
    for i, col in enumerate(columns):
        if _is_missing(null_bitmap, i):
            continue
        code = codes[i]
        values = col["values"]  # type: ignore[assignment]
        if code >= len(values):
            continue
        present_fields.append(i)
        decoded[col["id"]] = str(values[code])  # type: ignore[call-overload]

    if len(present_fields) != populated_attribute_count:
        raise ValueError(
            f"row {row_id!r}: decoded {len(present_fields)} populated fields but the corpus says "
            f"{populated_attribute_count}; the bitmap or the packing was misread"
        )

    # Overrides: applied after the code, superseding it unconditionally. Out-of-vocabulary real values
    # are mapped case-insensitively or dropped; missingness sentinels fold the field to absent.
    for field_index, raw in (overrides or ()):
        if field_index >= field_count:
            continue
        col = columns[field_index]
        attribute = col["id"]  # type: ignore[assignment]
        vocabulary = [str(v) for v in col["values"]]  # type: ignore[union-attr]
        resolved = _resolve_override(raw, vocabulary)
        if resolved is None:
            decoded.pop(attribute, None)
        else:
            decoded[attribute] = resolved
    return decoded


def _nibbles(raw: bytes) -> list[int]:
    """4-bit codes two per byte, low nibble first, indexed from zero."""
    out = []
    for byte in raw:
        out.append(byte & 0x0F)
        out.append((byte >> 4) & 0x0F)
    return out


def _is_missing(bitmap: bytes | None, field_index: int) -> bool:
    """Whether field `field_index` is absent in the null bitmap. A bitmap that is absent entirely means
    fully populated — the 400,000 synthetic rows carry no bitmap and every field is populated."""
    if bitmap is None:
        return False
    byte = field_index // 8
    bit = field_index % 8
    if byte >= len(bitmap):
        return False
    return ((bitmap[byte] >> bit) & 1) == 1


def _resolve_override(raw: str, vocabulary: Sequence[str]) -> str | None:
    """Map an override value to its vocabulary value, or None when it encodes missingness or has no
    mapping. An out-of-vocabulary value is never admitted raw into a decoded row, because a closed
    vocabulary is what the gates and filters rest on.

    The vocabulary is consulted before the missingness sentinels: 435 codebook values are themselves
    words like `None` and `Not applicable`, and there they are answers — "no children", "no institution" —
    not the absence of one."""
    token = raw.strip()
    if token in vocabulary:
        return token
    lowered = {str(value).lower(): str(value) for value in vocabulary}
    if token.lower() in lowered:
        return lowered[token.lower()]
    return None


def is_unexpressible(raw: str, vocabulary: Sequence[str]) -> bool:
    """Whether an override records a real value the vocabulary cannot express — `65+` against bands that
    split at 75 and 85 — as opposed to encoding missingness. Such a field decodes as absent, because a
    demographic is never synthesized and choosing a band would invent a precision nobody measured; it is
    counted instead, so the loss is visible rather than a silent, value-correlated exclusion."""
    if _resolve_override(raw, vocabulary) is not None:
        return False
    return raw.strip().lower() not in _MISSINGNESS
