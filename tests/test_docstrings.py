"""Every module, class and function in the project must have a docstring."""

import ast

from tests.conftest import ROOT


def test_everything_has_a_docstring():
    """Fail with a list of any module, class or function missing a docstring."""
    missing = []
    for folder in ("edgefogsim", "tests"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            tree = ast.parse(path.read_text())
            relative = path.relative_to(ROOT)
            if not ast.get_docstring(tree):
                missing.append(f"{relative}: module")
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                        and not ast.get_docstring(node):
                    missing.append(f"{relative}:{node.lineno} {node.name}")
    assert not missing, "Missing docstrings:\n" + "\n".join(missing)
