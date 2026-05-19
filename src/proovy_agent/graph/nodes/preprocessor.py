"""Preprocessor 노드 — @커맨드 파싱 (MVP: 이미지 OCR 없음)."""

import re

from proovy_agent.graph.state import ProovyState


async def preprocessor(state: ProovyState) -> dict:
    """raw_input에서 텍스트를 추출하고 @커맨드를 파싱합니다."""
    problem = state.raw_input.get("problem", "")
    tags = re.findall(r"@\S+", problem)
    clean_text = re.sub(r"@\S+", "", problem).strip()

    return {
        "ocr_text": clean_text or problem,
        "ocr_confidence": 1.0,
        "tags": tags,
    }
