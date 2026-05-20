"""Tests for OCR models and data validation."""

from pydantic import ValidationError
import pytest

from proovy_agent.graph.nodes.ocr_node.models import (
    OCREngineResult,
    OCROptions,
    OCRRequest,
    OCRResult,
)


class TestOCROptions:
    """Test OCR options model."""

    def test_default_options(self):
        """Test default OCR options."""
        options = OCROptions()

        assert options.engines == ["tesseract", "vision_api"]
        assert options.language == "kor+eng"
        assert options.math_mode is True
        assert options.confidence_threshold == 0.8
        assert options.max_processing_time == 30.0

    def test_custom_options(self):
        """Test custom OCR options."""
        options = OCROptions(
            engines=["paddleocr"],
            language="eng",
            math_mode=False,
            confidence_threshold=0.9,
            max_processing_time=60.0,
        )

        assert options.engines == ["paddleocr"]
        assert options.language == "eng"
        assert options.math_mode is False
        assert options.confidence_threshold == 0.9
        assert options.max_processing_time == 60.0

    def test_empty_engines_validation(self):
        """Test that empty engines list raises validation error."""
        with pytest.raises(ValidationError, match="At least one OCR engine must be specified"):
            OCROptions(engines=[])

    def test_confidence_threshold_validation(self):
        """Test confidence threshold bounds."""
        # Valid range
        OCROptions(confidence_threshold=0.0)
        OCROptions(confidence_threshold=1.0)

        # Invalid range
        with pytest.raises(ValidationError):
            OCROptions(confidence_threshold=-0.1)

        with pytest.raises(ValidationError):
            OCROptions(confidence_threshold=1.1)

    def test_max_processing_time_validation(self):
        """Test max processing time validation."""
        # Valid
        OCROptions(max_processing_time=1.0)

        # Invalid (must be positive)
        with pytest.raises(ValidationError):
            OCROptions(max_processing_time=0.0)

        with pytest.raises(ValidationError):
            OCROptions(max_processing_time=-1.0)


class TestOCREngineResult:
    """Test OCR engine result model."""

    def test_valid_engine_result(self):
        """Test valid engine result creation."""
        result = OCREngineResult(
            engine_name="tesseract",
            raw_text="Hello world",
            confidence=0.95,
            processing_time=1.5,
            bbox_data=[{"x": 0, "y": 0, "width": 100, "height": 20}],
            metadata={"version": "5.0"},
        )

        assert result.engine_name == "tesseract"
        assert result.raw_text == "Hello world"
        assert result.confidence == 0.95
        assert result.processing_time == 1.5
        assert len(result.bbox_data) == 1
        assert result.metadata["version"] == "5.0"

    def test_confidence_bounds(self):
        """Test confidence score validation."""
        # Valid range
        OCREngineResult(engine_name="test", raw_text="test", confidence=0.0, processing_time=1.0)

        OCREngineResult(engine_name="test", raw_text="test", confidence=1.0, processing_time=1.0)

        # Invalid range
        with pytest.raises(ValidationError):
            OCREngineResult(
                engine_name="test", raw_text="test", confidence=-0.1, processing_time=1.0
            )

        with pytest.raises(ValidationError):
            OCREngineResult(
                engine_name="test", raw_text="test", confidence=1.1, processing_time=1.0
            )

    def test_processing_time_validation(self):
        """Test processing time validation."""
        # Valid
        OCREngineResult(engine_name="test", raw_text="test", confidence=0.9, processing_time=0.0)

        # Invalid (negative)
        with pytest.raises(ValidationError):
            OCREngineResult(
                engine_name="test", raw_text="test", confidence=0.9, processing_time=-1.0
            )


class TestOCRRequest:
    """Test OCR request model."""

    def test_valid_request(self):
        """Test valid OCR request creation."""
        image_data = b"fake_image_data"

        request = OCRRequest(
            image_data=image_data, image_format="png", user_id="user123", thread_id="thread456"
        )

        assert request.image_data == image_data
        assert request.image_format == "png"
        assert request.user_id == "user123"
        assert request.thread_id == "thread456"
        assert isinstance(request.processing_options, OCROptions)

    def test_custom_processing_options(self):
        """Test OCR request with custom options."""
        image_data = b"fake_image_data"
        options = OCROptions(engines=["paddleocr"], math_mode=False)

        request = OCRRequest(
            image_data=image_data,
            image_format="jpg",
            user_id="user123",
            thread_id="thread456",
            processing_options=options,
        )

        assert request.processing_options.engines == ["paddleocr"]
        assert request.processing_options.math_mode is False

    def test_empty_image_data_validation(self):
        """Test empty image data validation."""
        with pytest.raises(ValidationError, match="Image data cannot be empty"):
            OCRRequest(image_data=b"", image_format="png", user_id="user123", thread_id="thread456")

    def test_large_image_validation(self):
        """Test large image size validation."""
        # Create image data larger than 50MB
        large_data = b"x" * (51 * 1024 * 1024)

        with pytest.raises(ValidationError, match="exceeds maximum"):
            OCRRequest(
                image_data=large_data, image_format="png", user_id="user123", thread_id="thread456"
            )


class TestOCRResult:
    """Test OCR result model."""

    def test_valid_result(self):
        """Test valid OCR result creation."""
        engine_result = OCREngineResult(
            engine_name="tesseract", raw_text="x = 5", confidence=0.9, processing_time=1.0
        )

        result = OCRResult(
            extracted_text="x = 5",
            confidence=0.9,
            tags=["solve"],
            math_expressions=["x = 5"],
            engine_results=[engine_result],
            processing_time=2.5,
            metadata={"preprocessed": True},
        )

        assert result.extracted_text == "x = 5"
        assert result.confidence == 0.9
        assert result.tags == ["solve"]
        assert result.math_expressions == ["x = 5"]
        assert len(result.engine_results) == 1
        assert result.processing_time == 2.5
        assert result.metadata["preprocessed"] is True

    def test_empty_text_validation(self):
        """Test empty extracted text validation."""
        with pytest.raises(ValidationError, match="Extracted text cannot be empty"):
            OCRResult(extracted_text="", confidence=0.9, processing_time=1.0)

        with pytest.raises(ValidationError, match="Extracted text cannot be empty"):
            OCRResult(
                extracted_text="   ",  # Only whitespace
                confidence=0.9,
                processing_time=1.0,
            )

    def test_confidence_bounds(self):
        """Test confidence score validation."""
        # Valid range
        OCRResult(extracted_text="test", confidence=0.0, processing_time=1.0)

        OCRResult(extracted_text="test", confidence=1.0, processing_time=1.0)

        # Invalid range
        with pytest.raises(ValidationError):
            OCRResult(extracted_text="test", confidence=-0.1, processing_time=1.0)

        with pytest.raises(ValidationError):
            OCRResult(extracted_text="test", confidence=1.1, processing_time=1.0)

    def test_processing_time_validation(self):
        """Test processing time validation."""
        # Valid
        OCRResult(extracted_text="test", confidence=0.9, processing_time=0.0)

        # Invalid (negative)
        with pytest.raises(ValidationError):
            OCRResult(extracted_text="test", confidence=0.9, processing_time=-1.0)
