"""State.messages를 PDF 해설지용 구조화된 섹션으로 파싱하는 시스템."""

import re

from langchain_core.messages import AnyMessage, ToolMessage

from .exceptions import ContentParsingError, handle_pdf_error
from .models import ContentSection


class ContentParser:
    """State.messages를 해설 섹션으로 변환하는 파싱 시스템."""

    def __init__(self) -> None:
        """파서 초기화."""
        # 풀이 단계를 나타내는 키워드 패턴
        self.step_patterns = [
            r"(\d+)\s*(?:단계|\.)\s*",  # "1단계", "2단계.", "1. "
            r"(?:먼저|첫째|첫\s*번째|우선)",  # 첫 번째 단계
            r"(?:다음|둘째|두\s*번째|그\s*다음)",  # 두 번째 단계
            r"(?:마지막|끝|결론|따라서|그러므로)",  # 마지막 단계
            r"(?:검증|확인|체크|검산)",  # 검증 단계
        ]

        # 수식 패턴 (LaTeX, 수학 기호)
        self.math_patterns = [
            r"\$[^$]+\$",  # $수식$
            r"\\\([^)]+\\\)",  # \(수식\)
            r"\\\[[^\]]+\\\]",  # \[수식\]
            r"[=≠><≤≥±∞∑∏∫√∂∇]",  # 수학 기호
        ]

        # 이미지 참조 패턴
        self.image_patterns = [
            r"그래프|차트|도표|그림|이미지",
            r"위\s*(?:그래프|차트|도표|그림)",
            r"아래\s*(?:그래프|차트|도표|그림)",
        ]

    async def parse_messages(self, messages: list[AnyMessage]) -> list[ContentSection]:
        """State.messages를 PDF용 구조화된 섹션으로 변환.

        Args:
            messages: LangGraph State의 messages

        Returns:
            구조화된 ContentSection 목록

        Raises:
            ContentParsingError: 파싱 실패 시
        """
        try:
            if not messages:
                raise ContentParsingError("파싱할 메시지가 없습니다")

            sections = []
            current_order = 0

            # 1. display 태그별로 messages 분류
            verified_solution_messages = self._filter_verified_solution_messages(messages)
            content_messages = [
                msg
                for msg in self._filter_by_display(messages, "content")
                if not self._is_verified_solution_message(msg)
            ]
            progress_messages = self._filter_by_display(messages, "progress")
            tool_messages = self._filter_by_display(messages, "tool")

            # 2. 메인 풀이 내용 파싱 (content)
            if content_messages:
                content_sections = await self._parse_content_messages(
                    content_messages, current_order
                )
                sections.extend(content_sections)
                current_order += len(content_sections)

            # 3. 검증된 풀이 원문 파싱 (verified_solution)
            if verified_solution_messages:
                verified_solution_section = self._create_verified_solution_section(
                    verified_solution_messages,
                    current_order,
                )
                sections.append(verified_solution_section)
                current_order += 1

            # 4. 풀이 진행 과정 파싱 (progress)
            if progress_messages:
                progress_section = self._create_progress_section(progress_messages, current_order)
                sections.append(progress_section)
                current_order += 1

            # 5. 코드 실행 결과 파싱 (tool)
            if tool_messages:
                tool_section = self._create_tool_section(tool_messages, current_order)
                sections.append(tool_section)
                current_order += 1

            # 6. 섹션이 없으면 fallback 처리
            if not sections:
                fallback_section = self._create_fallback_section(messages)
                sections.append(fallback_section)

            return sections

        except Exception as e:
            raise handle_pdf_error(e) from e

    def _filter_by_display(self, messages: list[AnyMessage], display_type: str) -> list[AnyMessage]:
        """특정 display 태그를 가진 메시지만 필터링."""
        filtered = []
        for msg in messages:
            display = getattr(msg, "metadata", {}).get("display", "")
            if display == display_type:
                filtered.append(msg)
        return filtered

    def _filter_verified_solution_messages(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        """CoreSolver의 verified_solution 메시지만 필터링."""
        return [
            msg
            for msg in messages
            if self._is_verified_solution_message(msg)
            and self._message_content_to_str(getattr(msg, "content", "")).strip()
        ]

    def _is_verified_solution_message(self, message: AnyMessage) -> bool:
        metadata = getattr(message, "metadata", {})
        return metadata.get("kind") == "verified_solution"

    async def _parse_content_messages(
        self, messages: list[AnyMessage], start_order: int
    ) -> list[ContentSection]:
        """content 태그를 가진 메시지들을 파싱하여 섹션 생성."""
        sections = []

        # 전체 content를 하나의 텍스트로 병합
        full_content = self._merge_message_contents(messages)

        # 단계별로 분할
        step_sections = self._split_by_steps(full_content, start_order)
        if step_sections:
            sections.extend(step_sections)
        else:
            # 단계 분할에 실패하면 전체를 하나의 섹션으로 처리
            section = ContentSection(
                title="문제 풀이",
                content_type=self._detect_content_type(full_content),
                content=full_content.strip(),
                order=start_order,
            )
            sections.append(section)

        return sections

    def _merge_message_contents(self, messages: list[AnyMessage]) -> str:
        """여러 메시지의 내용을 하나의 텍스트로 병합."""
        contents = []
        for msg in messages:
            if hasattr(msg, "content") and msg.content:
                contents.append(self._message_content_to_str(msg.content).strip())
        return "\n\n".join(contents)

    def _message_content_to_str(self, content: object) -> str:
        if content is None:
            return ""
        if isinstance(content, list):
            return "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return str(content)

    def _split_by_steps(self, content: str, start_order: int) -> list[ContentSection]:
        """텍스트를 풀이 단계별로 분할."""
        sections = []

        # 모든 단계 패턴으로 분할 위치 찾기
        split_positions = []
        for pattern in self.step_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                split_positions.append((match.start(), match.group()))

        # 위치 순서로 정렬
        split_positions.sort(key=lambda x: x[0])

        if not split_positions:
            return []  # 단계 분할 불가

        # 첫 번째 분할 전 내용 (문제 설명 등)
        if split_positions[0][0] > 0:
            intro_content = content[: split_positions[0][0]].strip()
            if intro_content:
                sections.append(
                    ContentSection(
                        title="문제 분석",
                        content_type=self._detect_content_type(intro_content),
                        content=intro_content,
                        order=start_order + len(sections),
                    )
                )

        # 각 단계별 내용 추출
        for i, (pos, step_marker) in enumerate(split_positions):
            # 다음 단계 시작 위치 찾기
            end_pos = split_positions[i + 1][0] if i + 1 < len(split_positions) else len(content)

            step_content = content[pos:end_pos].strip()
            if step_content:
                # 단계 제목 생성
                step_title = self._generate_step_title(step_marker, i + 1)

                sections.append(
                    ContentSection(
                        title=step_title,
                        content_type=self._detect_content_type(step_content),
                        content=step_content,
                        order=start_order + len(sections),
                    )
                )

        return sections

    def _generate_step_title(self, step_marker: str, step_number: int) -> str:
        """단계 마커로부터 적절한 제목 생성."""
        step_marker_lower = step_marker.lower()

        if "먼저" in step_marker_lower or "첫" in step_marker_lower or "우선" in step_marker_lower:
            return "1단계: 문제 접근"
        elif "다음" in step_marker_lower or "둘째" in step_marker_lower:
            return f"{step_number}단계: 풀이 진행"
        elif (
            "마지막" in step_marker_lower
            or "결론" in step_marker_lower
            or "따라서" in step_marker_lower
        ):
            return "최종단계: 결론 도출"
        elif "검증" in step_marker_lower or "확인" in step_marker_lower:
            return "검증단계: 답안 확인"
        else:
            # 숫자가 포함된 경우 추출
            number_match = re.search(r"(\d+)", step_marker)
            if number_match:
                num = number_match.group(1)
                return f"{num}단계: 풀이 과정"
            else:
                return f"{step_number}단계: 풀이 과정"

    def _detect_content_type(self, content: str) -> str:
        """내용 분석하여 타입 결정."""
        # 코드 블록 확인 (최우선)
        if "```" in content or "def " in content or "import " in content:
            return "code"

        # 이미지 참조 확인
        for pattern in self.image_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return "image"

        # 수식 위주 내용인지 확인 (더 엄격한 조건)
        math_count = 0
        text_lines = content.split("\n")
        total_lines = len(text_lines)

        for line in text_lines:
            line = line.strip()
            if not line:
                continue
            # 수식 기호가 많거나 LaTeX 형식이면 math
            math_symbols = sum(1 for pattern in self.math_patterns if re.search(pattern, line))
            if math_symbols > 2 or any(pattern in line for pattern in [r"\(", r"\[", "$"]):
                math_count += 1

        # 전체 라인의 절반 이상이 수식이면 math 타입
        if total_lines > 0 and math_count / total_lines > 0.5:
            return "math"

        return "text"

    def _create_progress_section(self, messages: list[AnyMessage], order: int) -> ContentSection:
        """progress 메시지들로부터 진행 과정 섹션 생성."""
        progress_content = self._merge_message_contents(messages)

        return ContentSection(
            title="풀이 진행 과정",
            content_type="text",
            content=progress_content,
            order=order,
            metadata={"source": "progress"},
        )

    def _create_verified_solution_section(
        self,
        messages: list[AnyMessage],
        order: int,
    ) -> ContentSection:
        """verified_solution 메시지로부터 검증된 풀이 섹션 생성."""
        verified_solution_content = self._merge_message_contents(messages)

        return ContentSection(
            title="검증된 풀이",
            content_type=self._detect_content_type(verified_solution_content),
            content=verified_solution_content,
            order=order,
            metadata={"source": "verified_solution"},
        )

    def _create_tool_section(self, messages: list[AnyMessage], order: int) -> ContentSection:
        """tool 메시지들로부터 코드 실행 결과 섹션 생성."""
        tool_results = []

        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "도구")
                tool_content = str(msg.content)
                tool_results.append(f"**{tool_name} 실행 결과:**\n```\n{tool_content}\n```")

        combined_content = "\n\n".join(tool_results)

        return ContentSection(
            title="코드 실행 결과",
            content_type="code",
            content=combined_content,
            order=order,
            metadata={"source": "tool"},
        )

    def _create_fallback_section(self, messages: list[AnyMessage]) -> ContentSection:
        """파싱 실패 시 전체 메시지를 하나의 섹션으로 생성."""
        all_content = []

        for msg in messages:
            if hasattr(msg, "content") and msg.content:
                msg_type = type(msg).__name__
                content = self._message_content_to_str(msg.content)
                all_content.append(f"[{msg_type}] {content}")

        return ContentSection(
            title="풀이 내용",
            content_type="text",
            content="\n\n".join(all_content),
            order=0,
            metadata={"source": "fallback", "warning": "자동 파싱 실패로 원본 메시지 사용"},
        )
