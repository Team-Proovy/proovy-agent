"""PDF ContentParser 단위 테스트."""

from langchain_core.messages import AIMessage
import pytest

from proovy_agent.graph.nodes.pdf_node.content_parser import ContentParser


@pytest.mark.asyncio
async def test_parse_hidden_verified_solution_section() -> None:
    parser = ContentParser()

    sections = await parser.parse_messages(
        [
            AIMessage(
                content="학생용 전체 설명",
                metadata={"display": "content"},
            ),
            AIMessage(
                content="1단계: 검증된 계산\n최종답: 2",
                metadata={"kind": "verified_solution", "display": "hidden"},
            ),
        ]
    )

    verified_section = next(
        section for section in sections if section.metadata.get("source") == "verified_solution"
    )
    assert verified_section.title == "검증된 풀이"
    assert verified_section.content == "1단계: 검증된 계산\n최종답: 2"


@pytest.mark.asyncio
async def test_verified_solution_display_content_is_not_duplicated_as_main_content() -> None:
    parser = ContentParser()

    sections = await parser.parse_messages(
        [
            AIMessage(
                content="검증된 풀이",
                metadata={"kind": "verified_solution", "display": "content"},
            )
        ]
    )

    assert len(sections) == 1
    assert sections[0].metadata == {"source": "verified_solution"}
    assert sections[0].content == "검증된 풀이"
