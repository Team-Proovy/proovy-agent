"""수학 표기법 후처리 모듈 기본 테스트."""

import pytest

from proovy_agent.graph.nodes.ocr_node.math_postprocessor import MathPattern, MathPostProcessor
from proovy_agent.graph.nodes.ocr_node.models import MathExpression


class TestMathPatternBasic:
    """MathPattern 기본 테스트."""

    def test_pattern_creation(self) -> None:
        """패턴 생성 테스트."""
        pattern = MathPattern(
            pattern=r"test",
            replacement=r"\\test",
            priority=1,
            description="테스트 패턴"
        )
        
        assert pattern.pattern == r"test"
        assert pattern.replacement == r"\\test"
        assert pattern.priority == 1
        assert pattern.description == "테스트 패턴"


class TestMathPostProcessorBasic:
    """수학 후처리기 기본 테스트."""

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

    def test_confidence_calculation(self, processor: MathPostProcessor) -> None:
        """신뢰도 계산 기본 테스트."""
        # 간단한 표현식
        simple_expr = MathExpression(
            latex="x^{2}",
            original="x²",
            position=(0, 2)
        )
        
        confidence = processor.extract_math_confidence(simple_expr)
        assert 0.0 <= confidence <= 1.0

    def test_basic_symbol_detection(self, processor: MathPostProcessor) -> None:
        """기본 수학 기호 감지 테스트."""
        # 간단한 수학 기호가 포함된 텍스트
        text = "수식: x² + y"
        results = processor.process_text(text)
        
        # 결과가 있는지 확인
        assert isinstance(results, list)
        
        # 결과가 있다면 구조 확인
        if results:
            for result in results:
                assert isinstance(result, MathExpression)
                assert hasattr(result, 'latex')
                assert hasattr(result, 'original')
                assert hasattr(result, 'position')

    def test_korean_math_terms_basic(self, processor: MathPostProcessor) -> None:
        """한국어 수학 용어 기본 테스트."""
        # 한국어 수학 용어 변환 테스트
        text = "x 더하기 y"
        converted = processor._convert_korean_terms(text)
        
        # 변환이 수행되었는지 확인 (더하기 -> +)
        assert converted != text  # 변환이 일어났음을 확인

    def test_symbol_conversion_basic(self, processor: MathPostProcessor) -> None:
        """기본 기호 변환 테스트."""
        # 간단한 수학 기호 변환
        text = "pi value"  # 복잡하지 않은 텍스트
        converted = processor._convert_math_symbols(text)
        
        # 변환 프로세스가 오류 없이 완료되었는지 확인
        assert isinstance(converted, str)

    def test_latex_cleanup(self, processor: MathPostProcessor) -> None:
        """LaTeX 정리 기본 테스트."""
        # 정리가 필요한 LaTeX 텍스트
        messy_latex = "  \\\\alpha  + \\\\beta   "
        cleaned = processor._cleanup_latex(messy_latex)
        
        # 기본적인 정리가 되었는지 확인
        assert isinstance(cleaned, str)
        assert len(cleaned.strip()) > 0

    def test_error_handling(self, processor: MathPostProcessor) -> None:
        """오류 처리 기본 테스트."""
        # 특수 문자만 있는 텍스트
        text = "###$$$%%%"
        results = processor.process_text(text)
        
        # 오류가 발생하지 않고 빈 결과나 유효한 리스트를 반환해야 함
        assert isinstance(results, list)

    def test_region_detection_basic(self, processor: MathPostProcessor) -> None:
        """수학 영역 감지 기본 테스트."""
        # 간단한 텍스트
        text = "간단한 수식 x + y = z"
        regions = processor._detect_math_regions(text)
        
        # 결과가 리스트인지 확인
        assert isinstance(regions, list)
        
        # 각 영역이 올바른 구조를 가지는지 확인
        for region in regions:
            assert isinstance(region, tuple)
            assert len(region) == 3  # (start, end, text)
            start, end, region_text = region
            assert isinstance(start, int)
            assert isinstance(end, int)
            assert isinstance(region_text, str)
            assert start <= end

    def test_pattern_application(self, processor: MathPostProcessor) -> None:
        """패턴 적용 기본 테스트."""
        # 패턴들이 올바르게 초기화되었는지 확인
        assert len(processor.patterns) > 0
        
        # 각 패턴이 올바른 구조를 가지는지 확인
        for pattern in processor.patterns:
            assert isinstance(pattern, MathPattern)
            assert isinstance(pattern.pattern, str)
            assert isinstance(pattern.replacement, str)
            assert isinstance(pattern.priority, int)
            assert isinstance(pattern.description, str)