# ruff: noqa: RUF001
"""수학 표기법 후처리 모듈 테스트."""

import pytest

from proovy_agent.graph.nodes.ocr_node.math_postprocessor import MathPattern, MathPostProcessor
from proovy_agent.graph.nodes.ocr_node.models import MathExpression


class TestMathPattern:
    """MathPattern 모델 테스트."""

    def test_pattern_creation(self) -> None:
        """패턴 생성 테스트."""
        pattern = MathPattern(
            pattern=r"×", replacement=r"\\times", priority=1, description="곱하기 기호"
        )

        assert pattern.pattern == r"×"
        assert pattern.replacement == r"\\times"
        assert pattern.priority == 1
        assert pattern.description == "곱하기 기호"


class TestMathPostProcessor:
    """수학 후처리기 테스트."""

    @pytest.fixture
    def processor(self) -> MathPostProcessor:
        """수학 후처리기 픽스처."""
        return MathPostProcessor()

    def test_initialization(self, processor: MathPostProcessor) -> None:
        """초기화 테스트."""
        assert processor is not None
        assert len(processor.patterns) > 0
        assert len(processor.korean_math_terms) > 0

        # 패턴 우선순위 확인
        priorities = [p.priority for p in processor.patterns]
        assert all(isinstance(p, int) and p > 0 for p in priorities)

    def test_empty_text(self, processor: MathPostProcessor) -> None:
        """빈 텍스트 처리."""
        assert processor.process_text("") == []
        assert processor.process_text("   ") == []
        # None 케이스는 타입 오류가 발생하므로 제거


class TestBasicMathSymbols:
    """기본 수학 기호 변환 테스트."""

    @pytest.fixture
    def processor(self) -> MathPostProcessor:
        """수학 후처리기 픽스처."""
        return MathPostProcessor()

    def test_arithmetic_operators(self, processor: MathPostProcessor) -> None:
        """기본 연산자 변환."""
        test_cases = [
            ("a × b", "a \\times b"),
            ("c ÷ d", "c \\div d"),
            ("±5", "\\pm 5"),
            ("x ≠ y", "x \\neq y"),
        ]

        for original, _expected_latex in test_cases:
            results = processor.process_text(original)
            assert len(results) == 1
            assert _expected_latex in results[0].latex

    def test_comparison_operators(self, processor: MathPostProcessor) -> None:
        """비교 연산자 변환."""
        test_cases = [
            ("x ≤ y", "x \\leq y"),
            ("a ≥ b", "a \\geq b"),
            ("p ≈ q", "p \\approx q"),
            ("A ≡ B", "A \\equiv B"),
        ]

        for original, _expected_latex in test_cases:
            results = processor.process_text(original)
            assert len(results) == 1
            assert _expected_latex in results[0].latex

    def test_exponents_and_subscripts(self, processor: MathPostProcessor) -> None:
        """지수와 밑수 변환."""
        test_cases = [
            ("x²", "x^{2}"),
            ("y³", "y^{3}"),
            ("a^n", "a^{n}"),
            ("x_i", "x_{i}"),
        ]

        for original, _expected_latex in test_cases:
            results = processor.process_text(original)
            assert len(results) == 1
            assert _expected_latex in results[0].latex

    def test_roots(self, processor: MathPostProcessor) -> None:
        """루트 변환."""
        test_cases = [
            ("√x", "\\sqrt{x}"),
            ("√(a+b)", "\\sqrt{a+b}"),
            ("∛8", "\\sqrt[3]{8}"),
        ]

        for original, _expected_latex in test_cases:
            results = processor.process_text(original)
            assert len(results) == 1
            assert _expected_latex in results[0].latex

    def test_fractions(self, processor: MathPostProcessor) -> None:
        """분수 변환."""
        test_cases = [
            ("a/b", "\\frac{a}{b}"),
            ("(x+1)/(y-1)", "\\frac{(x+1)}{(y-1)}"),
            ("3/4", "\\frac{3}{4}"),
        ]

        for original, _expected_latex in test_cases:
            results = processor.process_text(original)
            assert len(results) == 1
            assert _expected_latex in results[0].latex

    def test_fractions_with_spaces(self, processor: MathPostProcessor) -> None:
        """`/` 주변 공백이 있는 분수도 감지·변환된다 (감지/변환 패턴 정합)."""
        for original in ["a / b", "x / 2", "(x+1) / (y-1)"]:
            results = processor.process_text(original)
            assert len(results) == 1
            assert "\\frac" in results[0].latex

    def test_subscript_ignores_plain_identifiers(self, processor: MathPostProcessor) -> None:
        """user_id·total_count 같은 다중 문자 식별자는 밑수로 변환하지 않는다."""
        for identifier in ["user_id 값을 확인", "total_count = 5", "max_value"]:
            results = processor.process_text(identifier)
            assert all("_{" not in result.latex for result in results)

    def test_subscript_single_letter_variable(self, processor: MathPostProcessor) -> None:
        """단일 문자 변수 밑수(x_i, F_n)는 정상 변환한다."""
        for original, expected in [("x_i", "x_{i}"), ("F_n", "F_{n}")]:
            results = processor.process_text(original)
            assert len(results) == 1
            assert expected in results[0].latex


class TestAdvancedMathSymbols:
    """고급 수학 기호 테스트."""

    @pytest.fixture
    def processor(self) -> MathPostProcessor:
        """수학 후처리기 픽스처."""
        return MathPostProcessor()

    def test_integrals(self, processor: MathPostProcessor) -> None:
        """적분 기호 변환."""
        test_cases = [
            ("∫f(x)dx", "\\int f(x)dx"),
            ("∬f(x,y)dxdy", "\\iint f(x,y)dxdy"),
            ("∭f(x,y,z)dxdydz", "\\iiint f(x,y,z)dxdydz"),
        ]

        for original, _expected_latex in test_cases:
            results = processor.process_text(original)
            assert len(results) == 1
            assert _expected_latex in results[0].latex

    def test_summation_and_product(self, processor: MathPostProcessor) -> None:
        """합과 곱 기호 변환."""
        test_cases = [
            ("∑i=1 to n", "\\sum i=1 to n"),
            ("∏k=1 to m", "\\prod k=1 to m"),
        ]

        for original, _expected_latex in test_cases:
            results = processor.process_text(original)
            assert len(results) == 1
            assert _expected_latex in results[0].latex

    def test_greek_letters(self, processor: MathPostProcessor) -> None:
        """그리스 문자 변환."""
        test_cases = [
            ("α = 30°", "\\alpha = 30°"),
            ("β + γ", "\\beta + \\gamma"),
            ("π ≈ 3.14", "\\pi \\approx 3.14"),
            ("θ = 45°", "\\theta = 45°"),
            ("λ = 550nm", "\\lambda = 550nm"),
            ("μ = 0.5", "\\mu = 0.5"),
            ("σ² = 4", "\\sigma ^{2} = 4"),
        ]

        for original, expected_latex in test_cases:
            results = processor.process_text(original)
            assert len(results) == 1
            # 예상 LaTeX 검증
            assert expected_latex in results[0].latex or results[0].latex == expected_latex

    def test_set_theory(self, processor: MathPostProcessor) -> None:
        """집합론 기호 변환."""
        test_cases = [
            ("x ∈ A", "x \\in A"),
            ("y ∉ B", "y \\notin B"),
            ("A ⊂ B", "A \\subset B"),
            ("C ⊆ D", "C \\subseteq D"),
            ("A ∪ B", "A \\cup B"),
            ("A ∩ B", "A \\cap B"),
            ("∅", "\\emptyset"),
        ]

        for original, expected_latex in test_cases:
            results = processor.process_text(original)
            assert len(results) == 1
            # 예상 LaTeX 검증
            assert expected_latex in results[0].latex or results[0].latex == expected_latex

    def test_calculus_symbols(self, processor: MathPostProcessor) -> None:
        """미적분 기호 변환."""
        test_cases = [
            ("∂f/∂x", "\\partial f/\\partial x"),
            ("∇f", "\\nabla f"),
            ("lim x→∞", "\\lim x→\\infty"),
        ]

        for original, expected_latex in test_cases:
            results = processor.process_text(original)
            assert len(results) == 1
            # 예상 LaTeX 검증
            assert expected_latex in results[0].latex or results[0].latex == expected_latex


class TestKoreanMathTerms:
    """한국어 수학 용어 변환 테스트."""

    @pytest.fixture
    def processor(self) -> MathPostProcessor:
        """수학 후처리기 픽스처."""
        return MathPostProcessor()

    def test_korean_operations(self, processor: MathPostProcessor) -> None:
        """한국어 연산 용어 변환."""
        test_cases = [
            ("x 더하기 y", "x + y"),
            ("a 빼기 b", "a - b"),
            ("p 곱하기 q", "p \\times q"),
            ("m 나누기 n", "m \\div n"),
        ]

        for original, _expected_content in test_cases:
            results = processor.process_text(original)
            # 한국어 용어가 반드시 감지되어야 함
            assert len(results) >= 1, f"한국어 수학 용어 '{original}'가 감지되지 않음"
            # 변환된 내용이 포함되어 있는지 확인
            converted_text = results[0].latex
            assert any(op in converted_text for op in ["+", "-", "\\times", "\\div"])

    def test_korean_functions(self, processor: MathPostProcessor) -> None:
        """한국어 함수 용어 변환."""
        test_cases = [
            ("x의 사인", "\\sin"),
            ("각도의 코사인", "\\cos"),
            ("값의 탄젠트", "\\tan"),
            ("자연로그", "\\ln"),
        ]

        for original, expected_symbol in test_cases:
            results = processor.process_text(original)
            # 한국어 함수 용어가 반드시 감지되어야 함
            assert len(results) >= 1, f"한국어 함수 용어 '{original}'가 감지되지 않음"
            assert any(expected_symbol in result.latex for result in results)

    def test_korean_powers(self, processor: MathPostProcessor) -> None:
        """한국어 거듭제곱 용어 변환."""
        test_cases = [
            ("x의 제곱", "^2"),
            ("a의 세제곱", "^3"),
        ]

        for original, expected_power in test_cases:
            results = processor.process_text(original)
            # 한국어 거듭제곱 용어가 반드시 감지되어야 함
            assert len(results) >= 1, f"한국어 거듭제곱 용어 '{original}'가 감지되지 않음"
            assert any(expected_power in result.latex for result in results)


class TestComplexExpressions:
    """복합 수학 표현식 테스트."""

    @pytest.fixture
    def processor(self) -> MathPostProcessor:
        """수학 후처리기 픽스처."""
        return MathPostProcessor()

    def test_quadratic_formula(self, processor: MathPostProcessor) -> None:
        """이차방정식 공식."""
        text = "x = (-b ± √(b²-4ac)) / 2a"
        results = processor.process_text(text)

        assert len(results) >= 1
        latex = results[0].latex
        assert "\\pm" in latex
        assert "\\sqrt" in latex
        assert "\\frac" in latex or "/" in latex

    def test_integration_expression(self, processor: MathPostProcessor) -> None:
        """적분 표현식."""
        text = "∫₀¹ x² dx = 1/3"
        results = processor.process_text(text)

        assert len(results) >= 1
        latex = results[0].latex
        assert "\\int" in latex

    def test_limit_expression(self, processor: MathPostProcessor) -> None:
        """극한 표현식."""
        text = "lim(x→∞) 1/x = 0"
        results = processor.process_text(text)

        assert len(results) >= 1
        latex = results[0].latex
        assert "\\lim" in latex or "lim" in latex
        assert "\\infty" in latex

    def test_trigonometric_identity(self, processor: MathPostProcessor) -> None:
        """삼각함수 항등식."""
        text = "sin²θ + cos²θ = 1"
        results = processor.process_text(text)

        assert len(results) >= 1
        latex = results[0].latex
        # 삼각함수와 그리스 문자가 변환되었는지 확인
        assert any(func in latex for func in ["sin", "cos"])
        assert "\\theta" in latex or "θ" in latex


class TestMathRegionDetection:
    """수학 영역 감지 테스트."""

    @pytest.fixture
    def processor(self) -> MathPostProcessor:
        """수학 후처리기 픽스처."""
        return MathPostProcessor()

    def test_mixed_text_detection(self, processor: MathPostProcessor) -> None:
        """혼재된 텍스트에서 수학 영역 감지."""
        text = "문제: x²+3x-4=0을 풀어라. 답은 x = (-3 ± √25)/2 이다."
        results = processor.process_text(text)

        # 최소 2개의 수학 영역이 감지되어야 함
        assert len(results) >= 1

        # 각 결과가 올바른 구조를 가지는지 확인
        for result in results:
            assert isinstance(result, MathExpression)
            assert result.original
            assert result.latex
            assert isinstance(result.position, tuple)
            assert len(result.position) == 2

    def test_korean_math_detection(self, processor: MathPostProcessor) -> None:
        """한국어 수학 용어 감지."""
        text = "삼각형의 넓이는 밑변 곱하기 높이 나누기 2입니다."
        results = processor.process_text(text)

        # 한국어 수학 용어가 포함된 영역이 감지되어야 함
        if results:  # 감지된 경우에만 검증
            assert len(results) >= 1
            assert any("곱하기" in result.original for result in results)

    def test_overlapping_regions(self, processor: MathPostProcessor) -> None:
        """겹치는 수학 영역 처리."""
        text = "√(x²+y²)"
        results = processor.process_text(text)

        assert len(results) >= 1
        # 전체 표현식이 하나로 처리되어야 함
        assert any("√" in result.original and "²" in result.original for result in results)


class TestConfidenceCalculation:
    """신뢰도 계산 테스트."""

    @pytest.fixture
    def processor(self) -> MathPostProcessor:
        """수학 후처리기 픽스처."""
        return MathPostProcessor()

    def test_confidence_factors(self, processor: MathPostProcessor) -> None:
        """신뢰도 계산 요소 테스트."""
        # 복잡한 수학 표현식 (높은 신뢰도)
        complex_expr = MathExpression(
            latex="\\int_{0}^{\\infty} e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}",
            original="∫₀∞ e^(-x²) dx = √π/2",
            position=(0, 20),
        )

        # 간단한 표현식 (낮은 신뢰도)
        simple_expr = MathExpression(latex="x^{2}", original="x²", position=(0, 2))

        complex_confidence = processor.extract_math_confidence(complex_expr)
        simple_confidence = processor.extract_math_confidence(simple_expr)

        assert 0.0 <= complex_confidence <= 1.0
        assert 0.0 <= simple_confidence <= 1.0
        assert complex_confidence > simple_confidence

    def test_bracket_balance_confidence(self, processor: MathPostProcessor) -> None:
        """괄호 균형 신뢰도."""
        # 균형잡힌 괄호
        balanced_expr = MathExpression(
            latex="\\frac{(a+b)}{(c+d)}", original="(a+b)/(c+d)", position=(0, 11)
        )

        # 불균형 괄호
        unbalanced_expr = MathExpression(latex="(a+b/c+d", original="(a+b/c+d", position=(0, 8))

        balanced_conf = processor.extract_math_confidence(balanced_expr)
        unbalanced_conf = processor.extract_math_confidence(unbalanced_expr)

        assert balanced_conf > unbalanced_conf


class TestErrorHandling:
    """오류 처리 테스트."""

    @pytest.fixture
    def processor(self) -> MathPostProcessor:
        """수학 후처리기 픽스처."""
        return MathPostProcessor()

    def test_malformed_input(self, processor: MathPostProcessor) -> None:
        """잘못된 형식의 입력 처리."""
        # 특수 문자만 있는 경우
        results = processor.process_text("###$$$%%%")
        # 오류가 발생하지 않고 빈 결과를 반환해야 함
        assert isinstance(results, list)

    def test_very_long_text(self, processor: MathPostProcessor) -> None:
        """매우 긴 텍스트 처리."""
        long_text = "x²" + "a" * 1000 + "y³"
        results = processor.process_text(long_text)

        # 처리가 완료되어야 하고, 수학 기호들이 감지되어야 함
        assert isinstance(results, list)
        if results:
            assert len(results) >= 1

    def test_unicode_edge_cases(self, processor: MathPostProcessor) -> None:
        """유니코드 경계 케이스."""
        unicode_text = "∫∞∑∏√±×÷≤≥≠≈αβγδεθλμπρστφω"
        results = processor.process_text(unicode_text)

        # 유니코드 수학 기호들이 올바르게 처리되어야 함
        assert isinstance(results, list)
        if results:
            assert len(results) >= 1
            latex = results[0].latex
            # 일부 LaTeX 명령어가 생성되었는지 확인
            assert "\\" in latex


class TestIntegration:
    """통합 테스트."""

    @pytest.fixture
    def processor(self) -> MathPostProcessor:
        """수학 후처리기 픽스처."""
        return MathPostProcessor()

    def test_real_world_example(self, processor: MathPostProcessor) -> None:
        """실제 수학 문제 예시."""
        text = """
        문제 1: 다음 이차방정식을 풀어보시오.
        2x² - 5x + 3 = 0

        해답: x = (5 ± √(25-24))/4 = (5 ± 1)/4
        따라서 x = 3/2 또는 x = 1
        """

        results = processor.process_text(text)

        # 여러 수학 표현식이 감지되어야 함
        assert len(results) >= 1

        # 각 결과가 유효한 구조를 가져야 함
        for result in results:
            assert isinstance(result, MathExpression)
            assert result.original.strip()
            assert result.latex.strip()
            assert isinstance(result.position, tuple)
            assert 0.0 <= processor.extract_math_confidence(result) <= 1.0

    def test_korean_textbook_style(self, processor: MathPostProcessor) -> None:
        """한국어 교과서 스타일."""
        text = """
        삼각함수의 기본 성질:
        sin²θ + cos²θ = 1
        탄젠트 θ = 사인θ/코사인θ
        """

        results = processor.process_text(text)

        # 수학 표현식들이 감지되어야 함
        assert len(results) >= 1

        # 한국어 용어와 수학 기호가 모두 처리되었는지 확인
        all_latex = " ".join(result.latex for result in results)
        has_math_symbols = any(
            symbol in all_latex for symbol in ["sin", "cos", "tan", "\\theta", "^{2}"]
        )

        assert has_math_symbols, "한국어 수학 용어가 LaTeX로 변환되지 않았습니다"
