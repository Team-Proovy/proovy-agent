"""LangGraph 빌더 — lazy singleton 테스트."""

from unittest.mock import MagicMock, patch

import pytest

from proovy_agent.graph import builder as builder_module


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder_module, "_graph", None)


def test_get_graph_builds_only_once() -> None:
    mock_graph = MagicMock()
    with patch.object(builder_module, "_build", return_value=mock_graph) as mock_build:
        g1 = builder_module.get_graph()
        g2 = builder_module.get_graph()

    assert g1 is g2
    assert mock_build.call_count == 1


def test_get_graph_returns_build_result() -> None:
    sentinel = object()
    with patch.object(builder_module, "_build", return_value=sentinel):
        assert builder_module.get_graph() is sentinel
