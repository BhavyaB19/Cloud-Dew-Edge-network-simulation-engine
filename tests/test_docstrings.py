"""Every module, class and function in the project must have a docstring."""

import ast

from tests.conftest import ROOT

CHECKED = ["edgefogsim", "tests", "tools", "run_experiments.py", "make_zip.py"]
"""Folders and files whose Python code is checked."""


def test_everything_has_a_docstring():
    """Fail with a list of any module, class or function missing a docstring."""
    paths = []
    for name in CHECKED:
        target = ROOT / name
        paths += [target] if target.is_file() else sorted(target.rglob("*.py"))
    missing = []
    for path in paths:
        tree = ast.parse(path.read_text())
        relative = path.relative_to(ROOT)
        if not ast.get_docstring(tree):
            missing.append(f"{relative}: module")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not ast.get_docstring(node):
                missing.append(f"{relative}:{node.lineno} {node.name}")
    assert not missing, "Missing docstrings:\n" + "\n".join(missing)
