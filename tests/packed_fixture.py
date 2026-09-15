"""A generator for the corpus's packed row format, so the decoder is proven against a real parquet the
repository writes rather than a corpus row it may not redistribute (ADR 0016).

Every decoding case the codebook's card omits is expressible here: an override on a code, no bitmap at
all, a code at the vocabulary boundary, a `populated_attribute_count` that disagrees.
"""

from collections.abc import Sequence

# A miniature codebook: enough fields to span a bitmap byte and to place an override's high nibble.
MINI_COLUMNS: tuple[dict, ...] = (
    {"id": "age_bracket", "values": ["Under 5", "5-12", "13-17", "18-24", "25-34"]},
    {"id": "region", "values": ["Africa", "Asia", "Europe", "North America", "South America", "Oceania"]},
    {"id": "sex", "values": ["female", "male"]},
    {"id": "trait_optimism", "values": ["low", "medium", "high"]},
    {"id": "spend_band", "values": ["0_5", "5_10", "10_20", "20_50"]},
    {"id": "coding_days", "values": ["none", "one_to_three", "four_plus"]},
    {"id": "urbanicity", "values": ["rural", "suburban", "urban"]},
    {"id": "employment", "values": ["student", "employed", "unemployed", "retired"]},
)


def row_bytes(field_count: int) -> int:
    return (field_count + 1) // 2


def bitmap_bytes(field_count: int) -> int:
    return (field_count + 7) // 8


def pack_codes(codes: Sequence[int]) -> bytes:
    """Two 4-bit codes to a byte, low nibble first, in declared field order."""
    buf = bytearray(row_bytes(len(codes)))
    for index, code in enumerate(codes):
        nibble = code & 0x0F
        if index % 2 == 0:
            buf[index // 2] = (buf[index // 2] & 0xF0) | nibble
        else:
            buf[index // 2] = (buf[index // 2] & 0x0F) | (nibble << 4)
    return bytes(buf)


def make_bitmap(missing: Sequence[int], field_count: int) -> bytes | None:
    """A null bitmap whose set bit means missing, LSB-first. Nothing missing and no rows to mark: the
    bitmap is absent entirely, which the decoder must read as fully populated."""
    if not missing:
        return None
    buf = bytearray(bitmap_bytes(field_count))
    for index in missing:
        buf[index // 8] |= 1 << (index % 8)
    return bytes(buf)


def write_packed_parquet(path, rows: Sequence[dict], columns: Sequence[dict] = MINI_COLUMNS) -> None:
    """Write generated rows to a parquet in the release's packed columns: `attributes`, `null_bitmap`,
    `attribute_overrides` and `populated_attribute_count`. `rows` are dicts of:

    - ``codes``: the packed code per field (int, indexed from zero into the column's values)
    - ``missing``: field indices the bitmap marks absent
    - ``overrides``: ``(field_index, value)`` pairs superseding the code
    - ``populated``: the corpus's own count (defaults to the bitmap-present count)
    - ``row_id``/``source``/``source_record_id``/``metadata_json``/``grounding``: provenance columns
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    field_count = len(columns)
    table = pa.Table.from_pylist(
        [_as_record(row, field_count) for row in rows],
        schema=pa.schema(
            [
                ("row_id", pa.string()),
                ("source", pa.string()),
                ("source_record_id", pa.string()),
                ("attributes", pa.binary()),
                ("null_bitmap", pa.binary()),
                ("attribute_overrides", pa.list_(pa.struct([("field_index", pa.int32()), ("value", pa.string())]))),
                ("populated_attribute_count", pa.int32()),
                ("metadata_json", pa.string()),
                ("grounding", pa.list_(pa.struct([("field_index", pa.int32()), ("assignment_type", pa.string())]))),
            ]
        ),
    )
    pq.write_table(table, path)


def _as_record(row: dict, field_count: int) -> dict:
    codes = row.get("codes", [0] * field_count)
    missing = row.get("missing", ())
    overrides = [{"field_index": index, "value": value} for index, value in row.get("overrides", ())]
    bitmap = make_bitmap(missing, field_count)
    present = field_count - len(set(missing))
    return {
        "row_id": row.get("row_id", ""),
        "source": row.get("source", "synthetic"),
        "source_record_id": row.get("source_record_id"),
        "attributes": pack_codes(codes),
        "null_bitmap": bitmap,
        "attribute_overrides": overrides or None,
        "populated_attribute_count": row.get("populated", present),
        "metadata_json": row.get("metadata_json"),
        "grounding": [{"field_index": index, "assignment_type": assignment} for index, assignment in row.get("grounding", ())] or None,
    }
