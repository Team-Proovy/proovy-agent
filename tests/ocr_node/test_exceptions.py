"""Tests for OCR exception classes."""

import pytest

from proovy_agent.graph.nodes.ocr_node.exceptions import (
    CommandParsingError,
    ConfidenceThresholdError,
    ImageProcessingError,
    MathParsingError,
    OCREngineError,
    OCRError,
    OCRResourceError,
    OCRTimeoutError,
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


class TestOCREngineError:
    """Test OCR engine error class."""

    def test_recoverable_error(self):
        """Test recoverable OCR engine error."""
        error = OCREngineError("tesseract", "Tesseract process crashed", {"exit_code": 1})

        assert "Tesseract process crashed" in str(error)
        assert "Engine: tesseract" in str(error)
        assert "Can try fallback engines" in str(error)
        assert error.engine_name == "tesseract"
        assert error.is_recoverable is True

    def test_non_recoverable_error(self):
        """Test non-recoverable OCR engine error."""
        error = OCREngineError(
            "vision_api", "API quota exceeded", {"quota": "daily_limit"}, is_recoverable=False
        )

        assert "API quota exceeded" in str(error)
        assert "Engine: vision_api" in str(error)
        assert "No fallback available" in str(error)
        assert error.engine_name == "vision_api"
        assert error.is_recoverable is False


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
        assert "OCR processing timed out after 30.0 seconds" in error_str
        assert error.timeout_seconds == 30.0

    def test_custom_message(self):
        """Test timeout error with custom message."""
        error = OCRTimeoutError(
            60.0, "Large image processing exceeded time limit", {"image_size": "50MB"}
        )

        error_str = str(error)
        assert "Large image processing exceeded time limit" in error_str
        assert error.timeout_seconds == 60.0


class TestOCRResourceError:
    """Test OCR resource error class."""

    def test_default_message(self):
        """Test resource error with default message."""
        error = OCRResourceError("memory")

        error_str = str(error)
        assert "OCR processing failed due to memory constraints" in error_str
        assert error.resource_type == "memory"

    def test_custom_message(self):
        """Test resource error with custom message."""
        error = OCRResourceError(
            "GPU", "CUDA out of memory", {"available_memory": "2GB", "required_memory": "4GB"}
        )

        error_str = str(error)
        assert "CUDA out of memory" in error_str
        assert error.resource_type == "GPU"


class TestExceptionInheritance:
    """Test exception inheritance and catching."""

    def test_all_inherit_from_ocr_error(self):
        """Test that all OCR exceptions inherit from OCRError."""
        exceptions = [
            ImageProcessingError(),
            OCREngineError("test"),
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
            raise OCREngineError("tesseract", "Test error")

        with pytest.raises(OCRError):
            raise ConfidenceThresholdError(0.8, 0.6)
