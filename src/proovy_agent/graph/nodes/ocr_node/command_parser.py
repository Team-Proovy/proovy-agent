"""
@커맨드 파싱 시스템 구현

사용자의 @커맨드와 자연어 의도를 분석하여 태그를 생성하는 파싱 시스템입니다.
명시적 커맨드(@용어, @해설영상)와 자연어 요청을 동일한 태그로 변환합니다.
"""

from enum import StrEnum
import re

from pydantic import BaseModel, Field

from .exceptions import CommandParsingError


class TagType(StrEnum):
    """태그 타입 정의"""

    TERM = "term"  # 용어 설명
    VIDEO = "video"  # 해설 영상
    PDF = "pdf"  # 해설지 생성
    SOLVE = "solve"  # 문제 풀이
    DETAILED = "detailed"  # 상세 설명
    PROBLEM = "problem"  # 문제 번호


class ParsedCommand(BaseModel):
    """파싱된 커맨드 결과"""

    tags: list[str] = Field(default_factory=list, description="파싱된 태그 목록")
    confidence: float = Field(default=0.0, description="파싱 신뢰도 (0.0-1.0)")
    original_text: str = Field(default="", description="원본 텍스트")
    detected_patterns: list[str] = Field(default_factory=list, description="감지된 패턴들")


class CommandParser:
    """@커맨드와 자연어 의도를 분석하는 파서"""

    def __init__(self):
        self._setup_patterns()
        self._setup_intent_keywords()

    def _setup_patterns(self) -> None:
        """@커맨드 정규식 패턴 정의"""
        self.command_patterns = {
            # 용어 설명 커맨드
            r"@용어\s+([가-힣a-zA-Z0-9]+(?:\s+[가-힣a-zA-Z0-9]+)*)": self._create_term_tag,
            r"@영어\s+([가-힣a-zA-Z0-9]+(?:\s+[가-힣a-zA-Z0-9]+)*)": self._create_term_tag,  # 오타 허용
            # 해설영상 커맨드
            r"@해설영상\s*([^@]*)": self._create_video_tag,
            r"@해설동영상\s*([^@]*)": self._create_video_tag,  # 변형 허용
            r"@영상\s*([^@]*)": self._create_video_tag,
            # 해설지 생성 커맨드
            r"@해설지\s*생성": self._create_pdf_tag,
            r"@PDF\s*생성": self._create_pdf_tag,
            r"@파일\s*생성": self._create_pdf_tag,
            # 풀이 과정 커맨드
            r"@풀이\s*과정": self._create_solve_tag,
            r"@해결\s*과정": self._create_solve_tag,
            r"@단계별\s*풀이": self._create_solve_tag,
        }

        # 컴파일된 패턴 캐시
        self.compiled_patterns = {
            re.compile(pattern, re.IGNORECASE): handler
            for pattern, handler in self.command_patterns.items()
        }

    def _setup_intent_keywords(self) -> None:
        """자연어 의도 분석을 위한 키워드 정의"""
        self.intent_keywords = {
            TagType.TERM: {
                "keywords": ["정의", "의미"],  # 범용 키워드 제거, 패턴 매칭에 의존
                "patterns": [
                    r"([가-힣a-zA-Z0-9]+)이?가?\s*뭐야",
                    r"([가-힣a-zA-Z0-9]+)이?란?\s*무엇",
                    r"([가-힣a-zA-Z0-9]+)의?\s*의미",
                    r"([가-힣a-zA-Z0-9]+)을?\s*설명해",
                    r"([가-힣a-zA-Z0-9]+)에?\s*대해\s*알려줘",
                    r"([가-힣a-zA-Z0-9]+)의?\s*정의",
                ],
            },
            TagType.VIDEO: {
                "keywords": ["영상", "동영상", "해설영상", "설명영상", "비디오"],  # 범용 동사 제거
                "patterns": [
                    r"영상으?로?\s*(만들어|보여줘|설명해)",
                    r"(해설영상|동영상)\s*(만들어|생성해)",
                    r"비디오로?\s*설명해",
                    r"(영상|동영상|비디오)\s*(제작|생성)",
                ],
            },
            TagType.PDF: {
                "keywords": ["해설지", "PDF"],  # 범용 키워드 제거
                "patterns": [
                    r"PDF로?\s*(저장|만들어|생성)",
                    r"해설지\s*(만들어|생성|저장)",
                    r"파일로?\s*(저장|다운로드)",
                    r"(문서|파일)\s*형태로?\s*(저장|생성)",
                ],
            },
            TagType.SOLVE: {
                "keywords": ["풀이"],  # 범용 키워드 제거
                "patterns": [
                    r"문제를?\s*(풀어|해결해)",
                    r"(풀이|해결)\s*과정",
                    r"단계별로?\s*(풀어|해결)",
                    r"이\s*문제를?\s*(계산|해결)",
                ],
            },
        }

        # 컴파일된 의도 패턴
        self.intent_compiled = {}
        for tag_type, data in self.intent_keywords.items():
            self.intent_compiled[tag_type] = [
                re.compile(pattern, re.IGNORECASE) for pattern in data["patterns"]
            ]

    def parse(self, text: str | None) -> ParsedCommand:
        """텍스트에서 커맨드와 의도를 파싱"""
        if not text or not text.strip():
            return ParsedCommand(original_text=text or "")

        try:
            # 1. @커맨드 파싱
            command_result = self._parse_explicit_commands(text)

            # 2. 자연어 의도 분석
            intent_result = self._analyze_natural_intent(text)

            # 3. 결과 병합 및 우선순위 적용
            final_result = self._merge_results(command_result, intent_result, text)

            return final_result

        except Exception as e:
            raise CommandParsingError(f"커맨드 파싱 중 오류 발생: {e!s}") from e

    def _parse_explicit_commands(self, text: str) -> ParsedCommand:
        """명시적 @커맨드 파싱"""
        tags = []
        detected_patterns = []
        confidence = 0.0

        for pattern, handler in self.compiled_patterns.items():
            matches = pattern.finditer(text)
            for match in matches:
                try:
                    new_tags = handler(match)
                    tags.extend(new_tags)
                    detected_patterns.append(f"@command: {match.group(0)}")
                    confidence += 0.3  # 명시적 커맨드는 높은 신뢰도
                except (AttributeError, IndexError):
                    # 정규식 그룹 접근 오류만 무시
                    continue
                except Exception:
                    # 예상치 못한 오류는 로깅하고 계속 진행
                    # 실제 운영에서는 logger.warning(f"Command parsing error: {e}")
                    continue

        return ParsedCommand(
            tags=tags, confidence=min(confidence, 1.0), detected_patterns=detected_patterns
        )

    def _analyze_natural_intent(self, text: str) -> ParsedCommand:
        """자연어 의도 분석"""
        tags = []
        detected_patterns = []
        confidence = 0.0

        for tag_type, patterns in self.intent_compiled.items():
            for pattern in patterns:
                matches = pattern.finditer(text)
                for match in matches:
                    try:
                        # 용어 설명의 경우 추출된 용어 포함
                        if tag_type == TagType.TERM and match.groups():
                            term = match.group(1).strip()
                            tags.append(f"{tag_type.value}:{term}")
                        else:
                            tags.append(tag_type.value)

                        detected_patterns.append(f"intent: {match.group(0)}")
                        confidence += 0.2  # 자연어는 중간 신뢰도
                    except (AttributeError, IndexError):
                        # 정규식 그룹 접근 오류만 무시
                        continue
                    except Exception:
                        # 예상치 못한 오류는 로깅하고 계속 진행
                        # 실제 운영에서는 logger.warning(f"Intent parsing error: {e}")
                        continue

        # 키워드 기반 추가 분석
        confidence += self._analyze_keywords(text, tags)

        return ParsedCommand(
            tags=tags, confidence=min(confidence, 1.0), detected_patterns=detected_patterns
        )

    def _analyze_keywords(self, text: str, current_tags: list[str]) -> float:
        """키워드 기반 의도 분석 - 패턴 매칭이 있을 때만 보조적으로 사용"""
        confidence_boost = 0.0
        text_lower = text.lower()

        # 패턴 매칭이 있는 경우에만 키워드 분석 적용
        has_pattern_match = len(current_tags) > 0

        if has_pattern_match:
            for tag_type, data in self.intent_keywords.items():
                keyword_count = sum(1 for keyword in data["keywords"] if keyword in text_lower)

                if keyword_count > 0:
                    # 패턴 매칭으로 이미 태그가 있는 경우에만 신뢰도 보정
                    tag_exists = any(tag.startswith(tag_type.value) for tag in current_tags)
                    if tag_exists:
                        confidence_boost += keyword_count * 0.1

        return confidence_boost

    def _merge_results(
        self, command_result: ParsedCommand, intent_result: ParsedCommand, original_text: str
    ) -> ParsedCommand:
        """결과 병합 및 우선순위 적용"""
        # 태그 중복 제거 및 우선순위 적용
        all_tags = command_result.tags + intent_result.tags
        unique_tags = self._deduplicate_tags(all_tags)

        # 최종 신뢰도 계산
        final_confidence = max(command_result.confidence, intent_result.confidence)
        if command_result.tags and intent_result.tags:
            final_confidence += 0.1  # 양쪽에서 감지되면 보너스

        # 문제 번호 추출
        problem_number = self._extract_problem_number(original_text)
        if problem_number:
            unique_tags.append(f"problem:{problem_number}")

        return ParsedCommand(
            tags=unique_tags,
            confidence=min(final_confidence, 1.0),
            original_text=original_text,
            detected_patterns=command_result.detected_patterns + intent_result.detected_patterns,
        )

    def _deduplicate_tags(self, tags: list[str]) -> list[str]:
        """태그 중복 제거 및 우선순위 적용"""
        seen = set()
        result = []
        term_tags = []  # term: 태그들은 별도 관리 (다중 허용)

        # 명시적 커맨드 우선순위: @용어 > @영상 > @해설지 > @풀이
        priority_order = [TagType.TERM, TagType.VIDEO, TagType.PDF, TagType.SOLVE]

        # 우선순위에 따라 정렬
        sorted_tags = []
        for tag_type in priority_order:
            for tag in tags:
                if tag.startswith(tag_type.value) and tag not in sorted_tags:
                    sorted_tags.append(tag)

        # 나머지 태그 추가
        for tag in tags:
            if tag not in sorted_tags:
                sorted_tags.append(tag)

        # 중복 제거 (term: 태그는 다중 허용)
        for tag in sorted_tags:
            if tag.startswith("term:"):
                # term: 태그는 동일한 내용이 아닌 경우 다중 허용
                if tag not in term_tags:
                    term_tags.append(tag)
                    result.append(tag)
            else:
                base_tag = tag.split(":")[0]
                if base_tag not in seen:
                    result.append(tag)
                    seen.add(base_tag)

        return result

    def _extract_problem_number(self, text: str) -> str | None:
        """문제 번호 추출 - 문맥이 있는 경우만 인식"""
        patterns = [
            r"(\d+)번\s*문제",  # "2번 문제"
            r"문제\s*(\d+)번?",  # "문제 3번"
            r"#(\d+)번?\s*문제",  # "#7번 문제"
            r"#(\d+)",  # "#7"
            # 단독 "(\d+)번" 패턴 제거 - 오탐 방지
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    # 태그 생성 헬퍼 메서드들
    def _create_term_tag(self, match: re.Match[str]) -> list[str]:
        """용어 설명 태그 생성"""
        term = match.group(1).strip()
        return [f"term:{term}"]

    def _create_video_tag(self, match: re.Match[str]) -> list[str]:
        """비디오 태그 생성"""
        additional = match.group(1).strip() if match.group(1) else ""
        tags = ["video"]

        # 추가 매개변수가 있으면 포함
        if additional:
            problem_num = self._extract_problem_number(additional)
            if problem_num:
                tags.append(f"problem:{problem_num}")

        return tags

    def _create_pdf_tag(self, match: re.Match[str]) -> list[str]:
        """PDF 태그 생성"""
        return ["pdf"]

    def _create_solve_tag(self, match: re.Match[str]) -> list[str]:
        """풀이 태그 생성"""
        return ["solve", "detailed"]


def create_command_parser() -> CommandParser:
    """CommandParser 인스턴스 생성 팩토리 함수"""
    return CommandParser()
