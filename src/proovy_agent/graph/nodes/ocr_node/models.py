"""OCR data models and Pydantic schemas."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class OCROptions(BaseModel):
    """OCR processing options and configuration."""

    engines: list[Literal["tesseract", "vision_api", "paddleocr"]] = Field(
        default=["tesseract", "vision_api"],
        description="List of OCR engines to use in order of preference",
    )
    language: str = Field(
        default="kor+eng", description="Language codes for OCR recognition (e.g., 'kor+eng', 'eng')"
    )
    math_mode: bool = Field(default=True, description="Enable mathematical expression recognition")
    confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score for accepting OCR results",
    )
    max_processing_time: float = Field(
        default=30.0, gt=0, description="Maximum processing time in seconds"
    )

    @field_validator("engines")
    @classmethod
    def validate_engines(cls, v):
        """Validate that at least one engine is specified."""
        if not v:
            raise ValueError("At least one OCR engine must be specified")
        return v


class OCREngineResult(BaseModel):
    """Result from a single OCR engine."""

    engine_name: str = Field(description="Name of the OCR engine that produced this result")
    raw_text: str = Field(description="Raw text extracted by the engine")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    processing_time: float = Field(ge=0.0, description="Processing time in seconds")
    bbox_data: list[dict] = Field(
        default_factory=list, description="Bounding box data for detected text regions"
    )
    metadata: dict = Field(default_factory=dict, description="Additional engine-specific metadata")


class OCRRequest(BaseModel):
    """OCR processing request data."""

    image_data: bytes = Field(description="Binary image data")
    image_format: Literal["png", "jpg", "jpeg", "pdf"] = Field(
        description="Format of the input image"
    )
    user_id: str = Field(description="User ID for the request")
    thread_id: str = Field(description="Thread ID for conversation context")
    processing_options: OCROptions = Field(
        default_factory=OCROptions, description="OCR processing configuration"
    )

    @field_validator("image_data")
    @classmethod
    def validate_image_size(cls, v):
        """Validate image size limits."""
        max_size = 50 * 1024 * 1024  # 50MB limit
        if len(v) > max_size:
            raise ValueError(f"Image size {len(v)} bytes exceeds maximum {max_size} bytes")
        if len(v) == 0:
            raise ValueError("Image data cannot be empty")
        return v


class OCRResult(BaseModel):
    """Final OCR processing result."""

    extracted_text: str = Field(description="Final extracted and processed text")
    confidence: float = Field(ge=0.0, le=1.0, description="Overall confidence score")
    tags: list[str] = Field(default_factory=list, description="Parsed command tags and intentions")
    math_expressions: list[str] = Field(
        default_factory=list, description="Detected mathematical expressions in LaTeX format"
    )
    engine_results: list[OCREngineResult] = Field(
        default_factory=list, description="Results from individual OCR engines"
    )
    processing_time: float = Field(ge=0.0, description="Total processing time in seconds")
    metadata: dict = Field(default_factory=dict, description="Additional processing metadata")

    @field_validator("extracted_text")
    @classmethod
    def validate_text_content(cls, v):
        """Validate extracted text is not empty."""
        if not v.strip():
            raise ValueError("Extracted text cannot be empty")
        return v
