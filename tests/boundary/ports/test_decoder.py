"""The packed decoder: proven against a parquet the suite generates, never against a corpus row."""

from pathlib import Path

import pytest
from tests.packed_fixture import MINI_COLUMNS, write_packed_parquet

from simcore.ports.decoder import Codebook, decode_row

CODEBOOK = Codebook(columns=MINI_COLUMNS)
N = len(MINI_COLUMNS)


def decode(*, codes=None, missing=(), overrides=(), populated=None, row_id="r"):
    codes = ((codes or []) + [0] * N)[:N]
    present = N - len(set(missing))
    return decode_row(
        CODEBOOK,
        _bytes(codes),
        _bitmap(missing),
        overrides,
        populated if populated is not None else present,
        row_id=row_id,
    )


def _bytes(codes):
    from tests.packed_fixture import pack_codes

    return pack_codes(codes)


def _bitmap(missing):
    from tests.packed_fixture import make_bitmap

    return make_bitmap(missing, N)


def test_a_generated_packed_parquet_backs_the_decoder(tmp_path: Path):
    path = tmp_path / "shard.parquet"
    write_packed_parquet(
        path,
        [
            {"row_id": "0", "codes": [3, 2, 1, 2, 0, 1, 2, 3]},
            {"row_id": "1", "codes": [4, 5, 0, 0, 1, 2, 0, 0], "missing": (6, 7)},
        ],
    )
    import pyarrow.parquet as pq

    rows = pq.read_table(path).to_pylist()
    first = decode(
        codes=list(_codes_of(rows[0]["attributes"])),
        populated=rows[0]["populated_attribute_count"],
    )
    assert first["age_bracket"] == "18-24"
    assert first["employment"] == "retired"
    second = decode(
        codes=list(_codes_of(rows[1]["attributes"])),
        missing=(6, 7),
        populated=rows[1]["populated_attribute_count"],
    )
    assert "urbanicity" not in second and "employment" not in second


def _codes_of(raw: bytes):
    out = []
    for byte in raw:
        out.append(byte & 0x0F)
        out.append((byte >> 4) & 0x0F)
    return out


def test_codes_are_indexed_from_zero_two_to_a_byte_low_nibble_first():
    decoded = decode(codes=[1, 2])
    assert decoded["age_bracket"] == "5-12"
    assert decoded["region"] == "Europe"


def test_a_code_at_the_vocabulary_boundary_decodes_to_its_last_value():
    decoded = decode(codes=[0, 5])
    assert decoded["region"] == "Oceania"


def test_a_field_marked_missing_in_the_bitmap_is_absent_even_when_its_code_is_non_zero():
    decoded = decode(codes=[2, 3, 1], missing=(1,))
    assert "region" not in decoded
    assert decoded["sex"] == "male"


def test_a_row_with_no_bitmap_decodes_every_field_as_present():
    decoded = decode(codes=[1, 2, 1, 1, 1, 1, 1, 1], missing=(), populated=N)
    assert len(decoded) == N


def test_an_override_supersedes_its_code():
    decoded = decode(codes=[0, 0], overrides=((0, "25-34"),))
    assert decoded["age_bracket"] == "25-34"


def test_a_missing_valued_override_decodes_its_field_as_absent():
    decoded = decode(codes=[0, 0], overrides=((0, "Not applicable"),))
    assert "age_bracket" not in decoded


def test_an_out_of_vocabulary_override_never_reaches_a_decoded_row_as_a_raw_string():
    decoded = decode(codes=[0, 0], overrides=((0, "65+"), (1, "Balanced")))
    assert "65+" not in decoded.get("age_bracket", "")
    assert "Balanced" not in decoded.values()
    assert "age_bracket" not in decoded and "region" not in decoded


def test_an_override_that_only_differs_in_case_is_mapped_into_the_vocabulary():
    decoded = decode(codes=[0, 0], overrides=((2, "MALE"),))
    assert decoded["sex"] == "male"


def test_a_populated_count_that_disagrees_raises_naming_the_row():
    with pytest.raises(ValueError, match="row 'shard-9'"):
        decode(codes=[1, 1], populated=N + 3, row_id="shard-9")
