"""Architecture invariants for the domain layer."""

from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).resolve().parents[1] / "app" / "domain"


def _imports_sqlalchemy(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlalchemy" or alias.name.startswith("sqlalchemy."):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "sqlalchemy" or mod.startswith("sqlalchemy."):
                hits.append(mod)
    return hits


def test_domain_never_imports_sqlalchemy():
    offenders: list[str] = []
    for path in sorted(DOMAIN_ROOT.rglob("*.py")):
        for name in _imports_sqlalchemy(path):
            offenders.append(f"{path.relative_to(DOMAIN_ROOT.parent.parent)}: {name}")
    assert offenders == [], "app/domain must stay DB-free:\n" + "\n".join(offenders)


def _imports_matching(path: Path, prefixes: tuple[str, ...]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
                hits.append(name)
    return hits


def test_domain_never_imports_langchain():
    prefixes = ("langchain", "langchain_core", "langchain_openai", "langgraph")
    offenders: list[str] = []
    for path in sorted(DOMAIN_ROOT.rglob("*.py")):
        for name in _imports_matching(path, prefixes):
            offenders.append(f"{path.relative_to(DOMAIN_ROOT.parent.parent)}: {name}")
    assert offenders == [], "app/domain must not import LangChain:\n" + "\n".join(offenders)


def test_report_spec_package_is_present_and_db_free():
    spec_root = DOMAIN_ROOT / "report_spec"
    assert spec_root.is_dir()
    assert list(spec_root.glob("*.py"))
    for path in spec_root.rglob("*.py"):
        assert not _imports_sqlalchemy(path), path.name
