# ruff: noqa: RUF001
"""수학 표기법 후처리 모듈 - VLM OCR 결과를 LaTeX으로 변환."""

import re

from pydantic import BaseModel, Field

from .exceptions import MathParsingError
from .models import MathExpression


class MathPattern(BaseModel):
    """수학 표기법 패턴 정의."""

    pattern: str = Field(description="정규식 패턴")
    replacement: str = Field(description="LaTeX 치환")
    priority: int = Field(description="처리 우선순위 (낮을수록 먼저)")
    description: str = Field(description="패턴 설명")


class MathPostProcessor:
    """수학 표기법 후처리기 - 한국어 수학 교육 환경 특화."""

    def __init__(self) -> None:
        """수학 후처리기 초기화."""
        self.patterns = self._initialize_patterns()
        self.korean_math_terms = self._initialize_korean_terms()

    def _initialize_patterns(self) -> list[MathPattern]:
        """수학 표기법 변환 패턴 초기화."""
        return [
            # 1. 기본 연산자 (우선순위 1)
            MathPattern(
                pattern=r"×", replacement=r"\\times", priority=1, description="곱하기 기호"
            ),
            MathPattern(pattern=r"÷", replacement=r"\\div", priority=1, description="나누기 기호"),
            MathPattern(
                pattern=r"±", replacement=r"\\pm", priority=1, description="플러스마이너스"
            ),
            MathPattern(
                pattern=r"∓", replacement=r"\\mp", priority=1, description="마이너스플러스"
            ),
            # 2. 비교 연산자 (우선순위 2)
            MathPattern(pattern=r"≤", replacement=r"\\leq", priority=2, description="작거나 같음"),
            MathPattern(pattern=r"≥", replacement=r"\\geq", priority=2, description="크거나 같음"),
            MathPattern(pattern=r"≠", replacement=r"\\neq", priority=2, description="같지 않음"),
            MathPattern(pattern=r"≈", replacement=r"\\approx", priority=2, description="근사값"),
            MathPattern(pattern=r"≡", replacement=r"\\equiv", priority=2, description="합동"),
            # 3. 지수와 밑수 (우선순위 3)
            MathPattern(
                pattern=r"([a-zA-Z0-9]+)\^([a-zA-Z0-9]+)",
                replacement=r"\1^{\2}",
                priority=3,
                description="지수 표기",
            ),
            MathPattern(
                pattern=r"([a-zA-Z0-9]+)_([a-zA-Z0-9]+)",
                replacement=r"\1_{\2}",
                priority=3,
                description="밑수 표기",
            ),
            # 4. 특수 지수 문자 (우선순위 4)
            MathPattern(pattern=r"²", replacement=r"^{2}", priority=4, description="제곱"),
            MathPattern(pattern=r"³", replacement=r"^{3}", priority=4, description="세제곱"),
            MathPattern(pattern=r"¹", replacement=r"^{1}", priority=4, description="첫 제곱"),
            # 5. 루트와 제곱근 (우선순위 5)
            MathPattern(
                pattern=r"√\(([^)]+)\)",
                replacement=r"\\sqrt{\1}",
                priority=5,
                description="괄호 루트",
            ),
            MathPattern(
                pattern=r"√([a-zA-Z0-9]+)",
                replacement=r"\\sqrt{\1}",
                priority=5,
                description="단순 루트",
            ),
            MathPattern(
                pattern=r"∛\(([^)]+)\)",
                replacement=r"\\sqrt[3]{\1}",
                priority=5,
                description="세제곱근",
            ),
            # 6. 분수 표기 (우선순위 6) - 수학적 컨텍스트만
            MathPattern(
                pattern=r"(?<!\d{2,4}/)([a-zA-Z]+[a-zA-Z0-9()]*|[0-9]*[a-zA-Z]+[a-zA-Z0-9()]*)/([a-zA-Z]+[a-zA-Z0-9()]*|[0-9]*[a-zA-Z]+[a-zA-Z0-9()]*)(?!/\d{2,4})",
                replacement=r"\\frac{\1}{\2}",
                priority=6,
                description="분수 표기",
            ),
            # 7. 적분 기호 (우선순위 7)
            MathPattern(pattern=r"∫", replacement=r"\\int", priority=7, description="적분"),
            MathPattern(pattern=r"∬", replacement=r"\\iint", priority=7, description="이중적분"),
            MathPattern(pattern=r"∭", replacement=r"\\iiint", priority=7, description="삼중적분"),
            # 8. 합과 곱 기호 (우선순위 8)
            MathPattern(pattern=r"∑", replacement=r"\\sum", priority=8, description="합 기호"),
            MathPattern(pattern=r"∏", replacement=r"\\prod", priority=8, description="곱 기호"),
            # 9. 극한과 무한대 (우선순위 9)
            MathPattern(pattern=r"\blim\b", replacement=r"\\lim", priority=9, description="극한"),
            MathPattern(pattern=r"∞", replacement=r"\\infty", priority=9, description="무한대"),
            # 10. 삼각함수 (우선순위 10)
            MathPattern(
                pattern=r"\bsin\b", replacement=r"\\sin", priority=10, description="사인함수"
            ),
            MathPattern(
                pattern=r"\bcos\b", replacement=r"\\cos", priority=10, description="코사인함수"
            ),
            MathPattern(
                pattern=r"\btan\b", replacement=r"\\tan", priority=10, description="탄젠트함수"
            ),
            # 11. 그리스 문자 (우선순위 11)
            MathPattern(pattern=r"α", replacement=r"\\alpha", priority=11, description="알파"),
            MathPattern(pattern=r"β", replacement=r"\\beta", priority=11, description="베타"),
            MathPattern(pattern=r"γ", replacement=r"\\gamma", priority=11, description="감마"),
            MathPattern(pattern=r"δ", replacement=r"\\delta", priority=11, description="델타"),
            MathPattern(pattern=r"ε", replacement=r"\\epsilon", priority=11, description="엡실론"),
            MathPattern(pattern=r"θ", replacement=r"\\theta", priority=11, description="세타"),
            MathPattern(pattern=r"λ", replacement=r"\\lambda", priority=11, description="람다"),
            MathPattern(pattern=r"μ", replacement=r"\\mu", priority=11, description="뮤"),
            MathPattern(pattern=r"π", replacement=r"\\pi", priority=11, description="파이"),
            MathPattern(pattern=r"ρ", replacement=r"\\rho", priority=11, description="로"),
            MathPattern(pattern=r"σ", replacement=r"\\sigma", priority=11, description="시그마"),
            MathPattern(pattern=r"τ", replacement=r"\\tau", priority=11, description="타우"),
            MathPattern(pattern=r"φ", replacement=r"\\phi", priority=11, description="파이"),
            MathPattern(pattern=r"ω", replacement=r"\\omega", priority=11, description="오메가"),
            # 12. 집합 기호 (우선순위 12)
            MathPattern(pattern=r"∈", replacement=r"\\in", priority=12, description="원소"),
            MathPattern(
                pattern=r"∉", replacement=r"\\notin", priority=12, description="원소가 아님"
            ),
            MathPattern(pattern=r"⊂", replacement=r"\\subset", priority=12, description="부분집합"),
            MathPattern(
                pattern=r"⊆",
                replacement=r"\\subseteq",
                priority=12,
                description="부분집합 또는 같음",
            ),
            MathPattern(pattern=r"∪", replacement=r"\\cup", priority=12, description="합집합"),
            MathPattern(pattern=r"∩", replacement=r"\\cap", priority=12, description="교집합"),
            MathPattern(pattern=r"∅", replacement=r"\\emptyset", priority=12, description="공집합"),
            # 13. 미분과 편미분 (우선순위 13)
            MathPattern(pattern=r"∂", replacement=r"\\partial", priority=13, description="편미분"),
            MathPattern(pattern=r"∇", replacement=r"\\nabla", priority=13, description="나블라"),
            # 14. 벡터와 행렬 (우선순위 14)
            MathPattern(pattern=r"⃗", replacement=r"\\vec", priority=14, description="벡터 화살표"),
        ]

    def _initialize_korean_terms(self) -> dict[str, str]:
        """한국어 수학 용어 매핑."""
        return {
            # 기본 연산
            "더하기": "+",
            "빼기": "-",
            "곱하기": "\\times",
            "나누기": "\\div",
            "나눈다": "\\div",
            # 지수와 제곱
            "제곱": "^2",
            "세제곱": "^3",
            "거듭제곱": "^",
            # 함수
            "사인": "\\sin",
            "코사인": "\\cos",
            "탄젠트": "\\tan",
            "로그": "\\log",
            "자연로그": "\\ln",
            # 수학 상수
            "파이": "\\pi",
            "무한대": "\\infty",
            # 집합
            "교집합": "\\cap",
            "합집합": "\\cup",
            "공집합": "\\emptyset",
            # 미적분
            "적분": "\\int",
            "미분": "\\frac{d}{dx}",
            "편미분": "\\partial",
            # 부등식
            "작거나같다": "\\leq",
            "크거나같다": "\\geq",
            "같지않다": "\\neq",
        }

    def process_text(self, text: str) -> list[MathExpression]:
        """텍스트에서 수학 표현식을 추출하고 LaTeX으로 변환."""
        if not text or not text.strip():
            return []

        expressions = []

        # 1. 수학 표현식 패턴 감지
        math_regions = self._detect_math_regions(text)

        for region_start, region_end, original_text in math_regions:
            try:
                # 2. 한국어 수학 용어 변환
                processed_text = self._convert_korean_terms(original_text)

                # 3. 수학 기호 LaTeX 변환
                latex_text = self._convert_math_symbols(processed_text)

                # 4. 후처리 및 정리
                latex_text = self._cleanup_latex(latex_text)

                expressions.append(
                    MathExpression(
                        latex=latex_text,
                        original=original_text,
                        position=(region_start, region_end),
                    )
                )

            except Exception as e:
                raise MathParsingError(
                    f"수학 표현식 변환 실패: {original_text}",
                    {"original_text": original_text, "error": str(e)},
                    original_text=original_text,
                ) from e

        return expressions

    def _detect_math_regions(self, text: str) -> list[tuple[int, int, str]]:
        """수학 표현식 영역 감지."""
        regions = []

        # 패턴 1: 명시적인 수학 기호가 포함된 영역
        math_symbol_pattern = r"[∫∑∏√±×÷≤≥≠≈∞αβγδεθλμπρστφωΓΔΘΛΞΠΣΦΨΩ∂∇²³¹∈∉⊂⊆∪∩∅⃗]+"

        for match in re.finditer(math_symbol_pattern, text):
            start, end = match.span()
            # 실제 수학 영역 경계 정확히 찾기
            math_start = self._find_math_boundary(text, start, -1)
            math_end = self._find_math_boundary(text, end, 1)

            original_text = text[math_start:math_end].strip()
            if original_text:  # 단일 기호도 허용
                regions.append((math_start, math_end, original_text))

        # 패턴 2: 수학적 표현 패턴 (분수, 지수 등)
        equation_patterns = [
            r"[a-zA-Z0-9]+\^[a-zA-Z0-9]+",  # 지수
            r"[a-zA-Z0-9]+/[a-zA-Z0-9]+",  # 분수
            r"\\b(?:sin|cos|tan|log|ln)\\s*\\([^)]+\\)",  # 함수
            r"\\blim\\s+[a-zA-Z0-9→∞]+",  # 극한
        ]

        for pattern in equation_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start, end = match.span()
                original_text = text[start:end].strip()
                if original_text:
                    # 중복 검사
                    is_duplicate = any(
                        start >= region_start and end <= region_end
                        for region_start, region_end, _ in regions
                    )
                    if not is_duplicate:
                        regions.append((start, end, original_text))

        # 패턴 3: 한국어 수학 용어 패턴
        korean_math_pattern = r"(?:제곱|세제곱|거듭제곱|사인|코사인|탄젠트|로그|적분|미분|편미분|교집합|합집합|더하기|빼기|곱하기|나누기)"

        for match in re.finditer(korean_math_pattern, text):
            start, end = match.span()
            # 앞뒤 확장하여 수학 컨텍스트 캡처
            math_start = self._find_math_boundary(text, start, -1)
            math_end = self._find_math_boundary(text, end, 1)

            original_text = text[math_start:math_end].strip()
            if original_text:
                is_duplicate = any(
                    math_start >= region_start and math_end <= region_end
                    for region_start, region_end, _ in regions
                )
                if not is_duplicate:
                    regions.append((math_start, math_end, original_text))

        # 중복 제거 및 정렬
        regions = self._merge_overlapping_regions(regions, text)
        regions.sort(key=lambda x: x[0])

        return regions

    def _find_math_boundary(self, text: str, pos: int, direction: int) -> int:
        """수학 표현식의 경계를 찾음."""
        math_chars = set(
            "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ()[]{}+-*/=<>^_.,\\×÷≤≥≠≈∞±²³¹√∫∑∏αβγδεθλμπρστφωΓΔΘΛΞΠΣΦΨΩ∂∇∈∉⊂⊆∪∩∅⃗≡∬∭∛"
        )

        current_pos = pos
        # direction이 -1이면 왼쪽으로, 1이면 오른쪽으로 확장
        while 0 <= current_pos < len(text):
            char = text[current_pos]
            # 공백은 한 개까지 허용하여 "a × b" 같은 표현을 하나로 처리  # ruff: noqa: RUF003
            if char in math_chars or ("가" <= char <= "힣") or char == " ":
                current_pos += direction
            else:
                break

        # direction에 따라 경계를 조정
        if direction == -1:
            # 왼쪽으로 확장했으므로 현재 위치 반환
            return max(0, current_pos)
        else:
            # 오른쪽으로 확장했으므로 현재 위치 반환
            return min(len(text), current_pos)

    def _merge_overlapping_regions(
        self, regions: list[tuple[int, int, str]], text: str
    ) -> list[tuple[int, int, str]]:
        """겹치는 영역들을 병합."""
        if not regions:
            return []

        sorted_regions = sorted(regions, key=lambda x: x[0])
        merged = [sorted_regions[0]]

        for current in sorted_regions[1:]:
            last = merged[-1]

            # 겹치거나 인접한 경우 병합
            if current[0] <= last[1] + 5:  # 5글자 이내 간격도 병합
                # 병합된 영역의 실제 텍스트로 업데이트
                new_start = min(last[0], current[0])
                new_end = max(last[1], current[1])
                new_text = text[new_start:new_end].strip()
                merged[-1] = (new_start, new_end, new_text)
            else:
                merged.append(current)

        return merged

    def _convert_korean_terms(self, text: str) -> str:
        """한국어 수학 용어를 기호로 변환."""
        converted_text = text

        # 긴 용어부터 치환하여 부분 매치 문제 방지
        sorted_terms = sorted(self.korean_math_terms.items(), key=lambda x: len(x[0]), reverse=True)
        for korean_term, math_symbol in sorted_terms:
            # 한국어는 단어 경계가 다르므로 단순 치환
            converted_text = converted_text.replace(korean_term, math_symbol)

        return converted_text

    def _convert_math_symbols(self, text: str) -> str:
        """수학 기호를 LaTeX으로 변환."""
        converted_text = text

        # 우선순위 순으로 패턴 적용
        sorted_patterns = sorted(self.patterns, key=lambda x: x.priority)

        for pattern_obj in sorted_patterns:
            try:
                converted_text = re.sub(
                    pattern_obj.pattern, pattern_obj.replacement, converted_text
                )
            except re.error:
                # 정규식 오류는 건너뛰고 계속 진행
                continue

        return converted_text

    def _cleanup_latex(self, latex_text: str) -> str:
        """LaTeX 코드 정리 및 최적화."""
        cleaned = latex_text

        # 1. 중복된 백슬래시 제거
        cleaned = re.sub(r"\\{2,}", r"\\", cleaned)

        # 2. 불필요한 공백 정리
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip()

        # 3. 중괄호 최적화
        cleaned = re.sub(r"\{([a-zA-Z0-9])\}", r"{\1}", cleaned)

        # 4. 빈 중괄호 제거
        cleaned = re.sub(r"\{\}", "", cleaned)

        # 5. 연속된 공백 정리
        cleaned = re.sub(r"\s+", " ", cleaned)

        return cleaned.strip()

    def extract_math_confidence(self, expression: MathExpression) -> float:
        """수학 표현식의 신뢰도 계산."""
        confidence = 0.5  # 기본값

        latex_text = expression.latex
        original_text = expression.original

        # LaTeX 명령어 개수 기반 보너스
        latex_commands = len(re.findall(r"\\[a-zA-Z]+", latex_text))
        if latex_commands > 0:
            confidence += min(latex_commands * 0.1, 0.3)

        # 수학 기호 밀도
        math_symbol_count = len(re.findall(r"[∫∑∏√±×÷≤≥≠≈∞αβγδεθλμπρστφω]", original_text))
        if math_symbol_count > 0:
            symbol_density = math_symbol_count / len(original_text)
            confidence += min(symbol_density * 2, 0.2)

        # 괄호 균형 확인
        open_brackets = (
            original_text.count("(") + original_text.count("[") + original_text.count("{")
        )
        close_brackets = (
            original_text.count(")") + original_text.count("]") + original_text.count("}")
        )
        if open_brackets == close_brackets and open_brackets > 0:
            confidence += 0.1
        elif open_brackets != close_brackets:
            confidence -= 0.1

        # 길이 기반 조정
        if len(original_text) < 3:
            confidence -= 0.2  # 너무 짧으면 감점
        elif len(original_text) > 20:
            confidence += 0.1  # 적절히 길면 보너스

        return min(max(confidence, 0.0), 1.0)
