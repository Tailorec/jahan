import ast
import sys
from pathlib import Path

import pytest

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "simcore" / "schemas"
ALLOWED_THIRD_PARTY = {"pydantic"}


def package_imports():
    for path in sorted(SCHEMAS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield path, alias.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
                yield path, node.module.split(".")[0]


@pytest.mark.parametrize(
    ("path", "module"),
    list(package_imports()),
    ids=lambda item: item if isinstance(item, str) else item.name,
)
def test_import_is_stdlib_or_pydantic_only(path, module):
    assert module in sys.stdlib_module_names or module in ALLOWED_THIRD_PARTY, (
        f"{path} imports '{module}': the contracts package allows only the standard library and pydantic"
    )


def test_package_has_imports_to_inspect():
    assert any(True for _ in package_imports())
