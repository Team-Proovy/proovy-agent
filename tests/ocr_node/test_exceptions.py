"""Tests for OCR exception classes."""

import pytest

from proovy_agent.graph.nodes.ocr_node.exceptions import (
    CommandParsingError,
    ConfidenceThresholdError,
    FileConversionError,
    ImageProcessingError,
    LanguageDetectionError,
    MathParsingError,
    OCRError,
    OCRResourceError,
    OCRTimeoutError,
    QualityThresholdError,
    VLMProcessingError,
)


class TestOCRError:
    """Test base OCR error class."""

    def test_basic_error(self):
        """Test basic OCR error creation."""
        error = OCRError("Test error message")

        assert str(error) == "Test error message"
        assert error.message == "Test error message"
        assert error.details == {}

    def test_error_with_details(self):
        """Test OCR error with details."""
        details = {"file": "test.png", "size": 1024}
        error = OCRError("Test error message", details)

        expected_str = "Test error message (Details: {'file': 'test.png', 'size': 1024})"
        assert str(error) == expected_str
        assert error.message == "Test error message"
        assert error.details == details


class TestImageProcessingError:
    """Test image processing error class."""

    def test_default_error(self):
        """Test default image processing error."""
        error = ImageProcessingError()

        assert "Image preprocessing failed" in str(error)
        assert "Try with a different image format" in str(error)
        assert error.recovery_suggestion == "Try with a different image format or quality"

    def test_custom_error(self):
        """Test custom image processing error."""
        details = {"step": "noise_removal", "error_code": "CV_ERROR"}
        error = ImageProcessingError(
            "Noise removal failed", details, "Reduce image resolution and try again"
        )

        assert "Noise removal failed" in str(error)
        assert "Reduce image resolution" in str(error)
        assert error.recovery_suggestion == "Reduce image resolution and try again"


class TestVLMProcessingError:
    """Test VLM processing error class."""

    def test_recoverable_error(self):
        """Test recoverable VLM processing error."""
        error = VLMProcessingError("flash", "모델 처리 중 오류 발생", {"error_code": "RATE_LIMIT"})

        assert "모델 처리 중 오류 발생" in str(error)
        assert "모델: flash" in str(error)
        assert "폴백 모델 사용 가능" in str(error)
        assert error.model_name == "flash"
        assert error.is_recoverable is True

    def test_non_recoverable_error(self):
        """Test non-recoverable VLM processing error."""
        error = VLMProcessingError(
            "sonnet", "API 키가 유효하지 않음", {"api_status": "invalid"}, is_recoverable=False
        )

        assert "API 키가 유효하지 않음" in str(error)
        assert "모델: sonnet" in str(error)
        assert "폴백 불가능" in str(error)
        assert error.model_name == "sonnet"
        assert error.is_recoverable is False


class TestFileConversionError:
    """Test file conversion error class."""

    def test_default_message(self):
        """Test file conversion error with default message."""
        error = FileConversionError("pdf")

        error_str = str(error)
        assert "pdf 파일 변환에 실패했습니다" in error_str
        assert error.file_type == "pdf"

    def test_custom_message(self):
        """Test file conversion error with custom message."""
        error = FileConversionError(
            "docx", "지원하지 않는 문서 형식입니다", {"version": "2003"}
        )

        error_str = str(error)
        assert "지원하지 않는 문서 형식입니다" in error_str
        assert error.file_type == "docx"


class TestQualityThresholdError:
    """Test quality threshold error class."""

    def test_default_message(self):
        """Test quality threshold error with default message."""
        error = QualityThresholdError(0.8, 0.6)

        error_str = str(error)
        assert "OCR 품질이 기준에 미달합니다" in error_str
        assert "기준: 0.8" in error_str
        assert "실제: 0.6" in error_str
        assert error.threshold == 0.8
        assert error.actual_score == 0.6

    def test_custom_message(self):
        """Test quality threshold error with custom message."""
        error = QualityThresholdError(
            0.9, 0.7, "이미지 품질이 너무 낮습니다", {"blur_detected": True}
        )

        error_str = str(error)
        assert "이미지 품질이 너무 낮습니다" in error_str
        assert "기준: 0.9" in error_str
        assert "실제: 0.7" in error_str


class TestLanguageDetectionError:
    """Test language detection error class."""

    def test_default_error(self):
        """Test default language detection error."""
        error = LanguageDetectionError()

        assert "언어 감지에 실패했습니다" in str(error)

    def test_custom_error(self):
        """Test custom language detection error."""
        error = LanguageDetectionError(
            "혼합 언어 텍스트로 인한 감지 실패", {"languages_detected": ["ko", "en", "zh"]}
        )

        assert "혼합 언어 텍스트로 인한 감지 실패" in str(error)


class TestMathParsingError:
    """Test mathematical parsing error class."""

    def test_default_error(self):
        """Test default math parsing error."""
        error = MathParsingError()

        assert "Mathematical expression parsing failed" in str(error)
        assert error.original_text is None

    def test_error_with_original_text(self):
        """Test math parsing error with original text."""
        original = "This is a very long mathematical expression that should be truncated in the error message when displayed"
        error = MathParsingError("Failed to parse fraction", {"pattern": "a/b"}, original)

        error_str = str(error)
        assert "Failed to parse fraction" in error_str
        assert "Original text:" in error_str
        assert len(error_str) < len(original) + 100  # Should be truncated
        assert error.original_text == original


class TestCommandParsingError:
    """Test command parsing error class."""

    def test_default_error(self):
        """Test default command parsing error."""
        error = CommandParsingError()

        assert "Command parsing failed" in str(error)
        assert error.invalid_commands == []

    def test_error_with_invalid_commands(self):
        """Test command parsing error with invalid commands."""
        invalid_commands = ["@unknow", "@badcommand"]
        error = CommandParsingError("Unknown commands detected", {"count": 2}, invalid_commands)

        error_str = str(error)
        assert "Unknown commands detected" in error_str
        assert "Invalid commands: @unknow, @badcommand" in error_str
        assert error.invalid_commands == invalid_commands


class TestConfidenceThresholdError:
    """Test confidence threshold error class."""

    def test_default_message(self):
        """Test confidence threshold error with default message."""
        error = ConfidenceThresholdError(0.8, 0.6)

        error_str = str(error)
        assert "All OCR results below confidence threshold 0.8" in error_str
        assert "Threshold: 0.8" in error_str
        assert "Highest: 0.6" in error_str
        assert error.threshold == 0.8
        assert error.highest_confidence == 0.6

    def test_custom_message(self):
        """Test confidence threshold error with custom message."""
        error = ConfidenceThresholdError(
            0.9, 0.7, "Poor quality image detected", {"engines_tried": ["tesseract", "paddleocr"]}
        )

        error_str = str(error)
        assert "Poor quality image detected" in error_str
        assert "Threshold: 0.9" in error_str
        assert "Highest: 0.7" in error_str


class TestOCRTimeoutError:
    """Test OCR timeout error class."""

    def test_default_message(self):
        """Test timeout error with default message."""
        error = OCRTimeoutError(30.0)

        error_str = str(error)
        assert "OCR 처리가 30.0초 후 시간 초과되었습니다" in error_str
        assert "이미지 복잡도를 줄이거나" in error_str
        assert error.timeout_seconds == 30.0

    def test_custom_message(self):
        """Test timeout error with custom message."""
        error = OCRTimeoutError(
            60.0, "대용량 이미지 처리 시간 초과", {"image_size": "50MB"}
        )

        error_str = str(error)
        assert "대용량 이미지 처리 시간 초과" in error_str
        assert error.timeout_seconds == 60.0


class TestOCRResourceError:
    """Test OCR resource error class."""

    def test_default_message(self):
        """Test resource error with default message."""
        error = OCRResourceError("메모리")

        error_str = str(error)
        assert "메모리 리소스 제약으로 OCR 처리에 실패했습니다" in error_str
        assert error.resource_type == "메모리"

    def test_custom_message(self):
        """Test resource error with custom message."""
        error = OCRResourceError(
            "GPU", "CUDA 메모리 부족", {"available_memory": "2GB", "required_memory": "4GB"}
        )

        error_str = str(error)
        assert "CUDA 메모리 부족" in error_str
        assert error.resource_type == "GPU"


class TestExceptionInheritance:
    """Test exception inheritance and catching."""

    def test_all_inherit_from_ocr_error(self):
        """Test that all OCR exceptions inherit from OCRError."""
        exceptions = [
            ImageProcessingError(),
            VLMProcessingError("flash"),
            FileConversionError("pdf"),
            QualityThresholdError(0.8, 0.6),
            LanguageDetectionError(),
            MathParsingError(),
            CommandParsingError(),
            ConfidenceThresholdError(0.8, 0.6),
            OCRTimeoutError(30.0),
            OCRResourceError("memory"),
        ]

        for exc in exceptions:
            assert isinstance(exc, OCRError)

    def test_can_catch_as_base_exception(self):
        """Test that specific exceptions can be caught as OCRError."""
        with pytest.raises(OCRError):
            raise ImageProcessingError("Test error")

        with pytest.raises(OCRError):
            raise VLMProcessingError("flash", "Test error")

        with pytest.raises(OCRError):
            raise QualityThresholdError(0.8, 0.6)
