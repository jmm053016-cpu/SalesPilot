"""Runtime dependency baseline for the sales analysis agent migration."""

from __future__ import annotations

import importlib
import sys


def test_python_runtime_is_supported() -> None:
    assert sys.version_info >= (3, 10)


def test_langchain_v1_agent_api_is_available() -> None:
    agents = importlib.import_module("langchain.agents")

    assert hasattr(agents, "create_agent")


def test_required_runtime_packages_are_importable() -> None:
    required_modules = (
        "pandas",
        "openpyxl",
        "docx",
        "reportlab",
        "pytest",
    )

    for module_name in required_modules:
        importlib.import_module(module_name)
