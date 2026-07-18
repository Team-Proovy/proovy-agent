"""PDFNode 통합 테스트.

State → PDFRequest 파싱과 WeasyPrint HTML→PDF 변환을 실제로 실행해 노드
전체 경로가 유효한 PDF 파일을 만드는지 검증한다.
"""

import asyncio
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from proovy_agent.graph.nodes.pdf_node import PDFNode, create_pdf_node
from proovy_agent.graph.state import ProovyState


def _solution_state() -> ProovyState:
    """이차방정식 풀이가 담긴 최소 State를 만든다."""
    return ProovyState(
        thread_id="test_thread_123",
        user_id="test_user_456",
        messages=[
            HumanMessage(
                content="이차방정식 x² + 2x + 1 = 0을 풀어주세요",
                metadata={"display": "content"},
            ),
            AIMessage(
                content=(
                    "이 방정식은 완전제곱식입니다.\n\n"
                    "1단계: 인수분해\nx² + 2x + 1 = (x + 1)² = 0\n\n"
                    "2단계: 해 구하기\nx + 1 = 0\nx = -1 (중근)"
                ),
                metadata={"display": "content"},
            ),
        ],
    )


def test_pdf_node_initializes_and_reports_configuration(tmp_path: Path) -> None:
    node = PDFNode(output_dir=tmp_path)

    assert tmp_path.is_dir()
    assert node.validate_configuration() is True
    assert node.get_available_templates()


def test_create_pdf_node_factory(tmp_path: Path) -> None:
    node = create_pdf_node(output_dir=str(tmp_path))

    assert isinstance(node, PDFNode)
    assert node.output_dir == tmp_path


@pytest.mark.asyncio
async def test_create_pdf_request_from_state_extracts_sections(tmp_path: Path) -> None:
    node = PDFNode(output_dir=tmp_path)

    request = await node._create_pdf_request_from_state(_solution_state())

    assert request.thread_id == "test_thread_123"
    assert request.user_id == "test_user_456"
    assert request.request_id
    assert request.content_sections


@pytest.mark.asyncio
async def test_generate_pdf_produces_valid_pdf_bytes(tmp_path: Path) -> None:
    node = PDFNode(output_dir=tmp_path)
    request = await node._create_pdf_request_from_state(_solution_state())

    result = await node._generate_pdf(request)

    assert result.success is True
    assert result.pdf_data.startswith(b"%PDF")
    assert result.file_size > 0


def test_node_call_writes_pdf_and_updates_messages(tmp_path: Path) -> None:
    node = PDFNode(output_dir=tmp_path)

    updates = asyncio.run(node(_solution_state()))

    assert updates["messages"]
    saved_pdfs = list(tmp_path.glob("*.pdf"))
    assert saved_pdfs
    assert all(pdf.stat().st_size > 0 for pdf in saved_pdfs)
