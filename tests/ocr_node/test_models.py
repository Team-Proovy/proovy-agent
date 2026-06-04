"""Tests for OCR models and data validation."""

from pydantic import ValidationError
import pytest

from proovy_agent.graph.nodes.ocr_node.models import (
    CommandTag,
    MathExpression,
    OCROptions,
    OCRRequest,
    OCRResult,
    ProcessingMetadata,
    VLMResult,
)


class TestOCROptions:
    """Test OCR options model."""

    def test_default_options(self):
        """Test default OCR options."""
        options = OCROptions()

        assert options.primary_model == "flash"
        assert options.fallback_model == "sonnet"
        assert options.target_language == "auto"
        assert options.enable_math_mode is True
        assert options.enable_command_parsing is True
        assert options.quality_threshold == 0.7
        assert options.max_processing_time == 30.0

    def test_custom_options(self):
        """Test custom OCR options."""
        options = OCROptions(
            primary_model="sonnet",
            fallback_model="opus",
            target_language="ko",
            enable_math_mode=False,
            quality_threshold=0.9,
            max_processing_time=60.0,
        )

        assert options.primary_model == "sonnet"
        assert options.fallback_model == "opus"
        assert options.target_language == "ko"
        assert options.enable_math_mode is False
        assert options.quality_threshold == 0.9
        assert options.max_processing_time == 60.0

    def test_model_validation(self):
        """Test VLM model name validation."""
        # Valid models
        OCROptions(primary_model="flash")
        OCROptions(primary_model="sonnet")
        OCROptions(fallback_model="opus")

        # Invalid models
        with pytest.raises(ValidationError, match="지원하지 않는 모델"):
            OCROptions(primary_model="gpt4")

        with pytest.raises(ValidationError, match="지원하지 않는 모델"):
            OCROptions(fallback_model="invalid_model")

    def test_quality_threshold_validation(self):
        """Test quality threshold bounds."""
        # Valid range
        OCROptions(quality_threshold=0.0)
        OCROptions(quality_threshold=1.0)

        # Invalid range
        with pytest.raises(ValidationError):
            OCROptions(quality_threshold=-0.1)

        with pytest.raises(ValidationError):
            OCROptions(quality_threshold=1.1)

    def test_max_processing_time_validation(self):
        """Test max processing time validation."""
        # Valid
        OCROptions(max_processing_time=1.0)

        # Invalid (must be positive)
        with pytest.raises(ValidationError):
            OCROptions(max_processing_time=0.0)

        with pytest.raises(ValidationError):
            OCROptions(max_processing_time=-1.0)


class TestVLMResult:
    """Test VLM result model."""

    def test_valid_vlm_result(self):
        """Test valid VLM result creation."""
        result = VLMResult(
            model_name="flash",
            raw_text="Hello world",
            confidence=0.95,
            processing_time=1.5,
            token_usage={"input": 100, "output": 50},
        )

        assert result.model_name == "flash"
        assert result.raw_text == "Hello world"
        assert result.confidence == 0.95
        assert result.processing_time == 1.5
        assert result.token_usage["input"] == 100
        assert result.token_usage["output"] == 50

    def test_confidence_bounds(self):
        """Test confidence score validation."""
        # Valid range
        VLMResult(model_name="sonnet", raw_text="test", confidence=0.0, processing_time=1.0)
        VLMResult(model_name="sonnet", raw_text="test", confidence=1.0, processing_time=1.0)

        # Invalid range
        with pytest.raises(ValidationError):
            VLMResult(model_name="sonnet", raw_text="test", confidence=-0.1, processing_time=1.0)

        with pytest.raises(ValidationError):
            VLMResult(model_name="sonnet", raw_text="test", confidence=1.1, processing_time=1.0)

    def test_processing_time_validation(self):
        """Test processing time validation."""
        # Valid
        VLMResult(model_name="opus", raw_text="test", confidence=0.9, processing_time=0.0)

        # Invalid (negative)
        with pytest.raises(ValidationError):
            VLMResult(model_name="opus", raw_text="test", confidence=0.9, processing_time=-1.0)


class TestCommandTag:
    """Test command tag model."""

    def test_valid_command_tag(self):
        """Test valid command tag creation."""
        tag = CommandTag(
            command="solve", original_text="@solve this equation", confidence=0.9, position=5
        )

        assert tag.command == "solve"
        assert tag.original_text == "@solve this equation"
        assert tag.confidence == 0.9
        assert tag.position == 5

    def test_confidence_validation(self):
        """Test confidence validation."""
        # Valid
        CommandTag(command="solve", original_text="@solve", confidence=0.5, position=0)

        # Invalid
        with pytest.raises(ValidationError):
            CommandTag(command="solve", original_text="@solve", confidence=-0.1, position=0)


class TestMathExpression:
    """Test math expression model."""

    def test_valid_expression(self):
        """Test valid math expression creation."""
        expr = MathExpression(latex="x^2 + 2x + 1", original="x² + 2x + 1", position=(10, 20))

        assert expr.latex == "x^2 + 2x + 1"
        assert expr.original == "x² + 2x + 1"
        assert expr.position == (10, 20)

    def test_position_validation(self):
        """Test position validation."""
        # Valid
        MathExpression(latex="x+1", original="x+1", position=(0, 5))
        MathExpression(latex="x+1", original="x+1", position=(10, 10))

        # Invalid positions
        with pytest.raises(ValidationError, match="잘못된 위치 범위"):
            MathExpression(latex="x+1", original="x+1", position=(-1, 5))

        with pytest.raises(ValidationError, match="잘못된 위치 범위"):
            MathExpression(latex="x+1", original="x+1", position=(10, 5))


class TestOCRRequest:
    """Test OCR request model."""

    def test_valid_request(self):
        """Test valid OCR request creation."""
        raw_input = {"type": "image", "data": "base64_encoded_image"}

        request = OCRRequest(raw_input=raw_input, user_id="user123", thread_id="thread456")

        assert request.raw_input == raw_input
        assert request.user_id == "user123"
        assert request.thread_id == "thread456"
        assert isinstance(request.options, OCROptions)

    def test_custom_processing_options(self):
        """Test OCR request with custom options."""
        raw_input = {"type": "pdf", "pages": [1, 2, 3]}
        options = OCROptions(primary_model="sonnet", enable_math_mode=False)

        request = OCRRequest(
            raw_input=raw_input,
            user_id="user123",
            thread_id="thread456",
            options=options,
        )

        assert request.options.primary_model == "sonnet"
        assert request.options.enable_math_mode is False

    def test_empty_raw_input_validation(self):
        """Test empty raw input validation."""
        with pytest.raises(ValidationError, match="입력 데이터가 비어있습니다"):
            OCRRequest(raw_input={}, user_id="user123", thread_id="thread456")


class TestOCRResult:
    """Test OCR result model."""

    def test_valid_result(self):
        """Test valid OCR result creation."""
        command_tag = CommandTag(
            command="solve", original_text="@solve", confidence=0.9, position=0
        )
        math_expr = MathExpression(latex="x = 5", original="x = 5", position=(10, 15))
        metadata = ProcessingMetadata(
            total_processing_time=2.5,
            model_used="flash",
            pages_processed=1,
            quality_score=0.9,
            language_detected="ko",
        )

        result = OCRResult(
            extracted_text="x = 5",
            confidence=0.9,
            command_tags=[command_tag],
            math_expressions=[math_expr],
            language="ko",
            processing_metadata=metadata,
        )

        assert result.extracted_text == "x = 5"
        assert result.confidence == 0.9
        assert len(result.command_tags) == 1
        assert len(result.math_expressions) == 1
        assert result.language == "ko"
        assert result.processing_metadata.model_used == "flash"

    def test_empty_text_validation(self):
        """Test empty extracted text validation."""
        metadata = ProcessingMetadata(
            total_processing_time=1.0,
            model_used="flash",
            pages_processed=1,
            quality_score=0.5,
            language_detected="en",
        )

        with pytest.raises(ValidationError, match="추출된 텍스트가 비어있습니다"):
            OCRResult(
                extracted_text="", confidence=0.9, language="en", processing_metadata=metadata
            )

        with pytest.raises(ValidationError, match="추출된 텍스트가 비어있습니다"):
            OCRResult(
                extracted_text="   ",  # Only whitespace
                confidence=0.9,
                language="en",
                processing_metadata=metadata,
            )

    def test_confidence_bounds(self):
        """Test confidence score validation."""
        metadata = ProcessingMetadata(
            total_processing_time=1.0,
            model_used="flash",
            pages_processed=1,
            quality_score=0.5,
            language_detected="en",
        )

        # Valid range
        OCRResult(
            extracted_text="test", confidence=0.0, language="en", processing_metadata=metadata
        )
        OCRResult(
            extracted_text="test", confidence=1.0, language="en", processing_metadata=metadata
        )

        # Invalid range
        with pytest.raises(ValidationError):
            OCRResult(
                extracted_text="test", confidence=-0.1, language="en", processing_metadata=metadata
            )

        with pytest.raises(ValidationError):
            OCRResult(
                extracted_text="test", confidence=1.1, language="en", processing_metadata=metadata
            )
