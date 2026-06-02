"""Tests for image preprocessing system."""

from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw
import pytest

from proovy_agent.graph.nodes.ocr_node.exceptions import ImageProcessingError
from proovy_agent.graph.nodes.ocr_node.image_processor import (
    ImageProcessor,
    ImageQuality,
    ProcessingOptions,
)
from proovy_agent.graph.nodes.ocr_node.models import ProcessedImage


class TestImageQuality:
    """Test ImageQuality model."""

    def test_valid_quality_metrics(self):
        """Test valid quality metrics creation."""
        quality = ImageQuality(
            blur_score=150.0,
            noise_level=0.3,
            contrast_ratio=2.5,
            text_density=0.7,
            brightness=128.0,
            resolution_dpi=300,
        )

        assert quality.blur_score == 150.0
        assert quality.noise_level == 0.3
        assert quality.contrast_ratio == 2.5
        assert quality.text_density == 0.7
        assert quality.brightness == 128.0
        assert quality.resolution_dpi == 300

    def test_quality_bounds_validation(self):
        """Test quality metrics bounds validation."""
        # Valid bounds
        ImageQuality(
            blur_score=0.0,
            noise_level=0.0,
            contrast_ratio=0.0,
            text_density=0.0,
            brightness=0.0,
            resolution_dpi=1,
        )

        ImageQuality(
            blur_score=1000.0,
            noise_level=1.0,
            contrast_ratio=100.0,
            text_density=1.0,
            brightness=255.0,
            resolution_dpi=9999,
        )

        # Invalid bounds
        with pytest.raises(ValueError):
            ImageQuality(
                blur_score=-1.0,  # Must be >= 0
                noise_level=0.5,
                contrast_ratio=2.0,
                text_density=0.5,
                brightness=128.0,
                resolution_dpi=300,
            )

        with pytest.raises(ValueError):
            ImageQuality(
                blur_score=100.0,
                noise_level=1.5,  # Must be <= 1.0
                contrast_ratio=2.0,
                text_density=0.5,
                brightness=128.0,
                resolution_dpi=300,
            )


class TestProcessingOptions:
    """Test ProcessingOptions model."""

    def test_default_options(self):
        """Test default processing options."""
        options = ProcessingOptions()

        assert options.target_dpi == 300
        assert options.enhance_contrast is True
        assert options.remove_noise is True
        assert options.auto_rotate is True
        assert options.binarize is True
        assert options.preserve_color is False
        assert options.max_dimension == 4096

    def test_custom_options(self):
        """Test custom processing options."""
        options = ProcessingOptions(
            target_dpi=600,
            enhance_contrast=False,
            remove_noise=False,
            auto_rotate=False,
            binarize=False,
            preserve_color=True,
            max_dimension=2048,
        )

        assert options.target_dpi == 600
        assert options.enhance_contrast is False
        assert options.remove_noise is False
        assert options.auto_rotate is False
        assert options.binarize is False
        assert options.preserve_color is True
        assert options.max_dimension == 2048

    def test_validation_errors(self):
        """Test processing options validation."""
        with pytest.raises(ValueError):
            ProcessingOptions(target_dpi=0)  # Must be > 0

        with pytest.raises(ValueError):
            ProcessingOptions(max_dimension=0)  # Must be > 0


class TestImageProcessor:
    """Test ImageProcessor functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.processor = ImageProcessor()

    def create_test_image(self, size=(800, 600), mode="RGB", color="white"):
        """Create a test image with optional text."""
        image = Image.new(mode, size, color)
        if color == "white":
            # Add some text for processing tests
            draw = ImageDraw.Draw(image)
            draw.text((50, 50), "Test Text 123", fill="black")
            draw.rectangle([100, 100, 300, 150], outline="black", width=2)
        return image

    @pytest.mark.asyncio
    async def test_basic_processing(self):
        """Test basic image processing pipeline."""
        image = self.create_test_image()

        result = await self.processor.process(image)

        assert isinstance(result, ProcessedImage)
        assert result.width > 0 and result.height > 0
        assert result.dpi > 0
        assert len(result.image_data) > 0
        assert result.format in ["png", "jpeg"]
        assert isinstance(result.preprocessing_applied, list)

    @pytest.mark.asyncio
    async def test_processing_with_custom_options(self):
        """Test processing with custom options."""
        image = self.create_test_image()
        options = ProcessingOptions(
            target_dpi=150,
            enhance_contrast=False,
            binarize=False,
        )

        result = await self.processor.process(image, options)

        assert isinstance(result, ProcessedImage)
        assert result.width > 0 and result.height > 0

    @pytest.mark.asyncio
    async def test_analyze_quality(self):
        """Test image quality analysis."""
        image = self.create_test_image()

        quality = await self.processor._analyze_quality(image)

        assert isinstance(quality, ImageQuality)
        assert quality.blur_score >= 0
        assert 0 <= quality.noise_level <= 1
        assert quality.contrast_ratio >= 0
        assert 0 <= quality.text_density <= 1
        assert 0 <= quality.brightness <= 255
        assert quality.resolution_dpi > 0

    @pytest.mark.asyncio
    async def test_preprocess_basic(self):
        """Test basic preprocessing steps."""
        # Large image that should be resized
        large_image = self.create_test_image(size=(5000, 4000))
        options = ProcessingOptions(max_dimension=2000)

        result = await self.processor._preprocess_basic(large_image, options)

        assert max(result.size) <= 2000
        assert result.size != large_image.size  # Should be resized

    @pytest.mark.asyncio
    async def test_color_conversion(self):
        """Test color space conversion."""
        color_image = self.create_test_image(mode="RGB")
        options = ProcessingOptions(preserve_color=False)

        result = await self.processor._preprocess_basic(color_image, options)

        assert result.mode == "L"  # Should be grayscale

    @pytest.mark.asyncio
    async def test_preserve_color(self):
        """Test color preservation option."""
        color_image = self.create_test_image(mode="RGB")
        options = ProcessingOptions(preserve_color=True)

        result = await self.processor._preprocess_basic(color_image, options)

        assert result.mode == "RGB"  # Should preserve color

    @pytest.mark.asyncio
    async def test_resolution_optimization(self):
        """Test resolution optimization."""
        small_image = self.create_test_image(size=(400, 300))  # Low resolution

        # Should upscale
        result = await self.processor._optimize_resolution(small_image, 300)

        assert result.size[0] > small_image.size[0]
        assert result.size[1] > small_image.size[1]

    @pytest.mark.asyncio
    async def test_quality_enhancement(self):
        """Test quality enhancement based on analysis."""
        image = self.create_test_image()
        quality = ImageQuality(
            blur_score=100.0,
            noise_level=0.8,  # High noise
            contrast_ratio=1.0,  # Low contrast
            text_density=0.5,
            brightness=50.0,  # Too dark
            resolution_dpi=300,
        )
        options = ProcessingOptions()

        result = await self.processor._enhance_quality(image, quality, options)

        assert isinstance(result, Image.Image)

    @pytest.mark.asyncio
    async def test_adaptive_threshold(self):
        """Test adaptive thresholding."""
        image = self.create_test_image(mode="L")  # Grayscale

        result = self.processor._adaptive_threshold(image)

        assert isinstance(result, Image.Image)
        assert result.mode == "L"

    @pytest.mark.asyncio
    async def test_create_multiple_versions(self):
        """Test creating multiple processed versions."""
        image = self.create_test_image()

        versions = await self.processor.create_multiple_versions(image)

        assert "minimal" in versions
        assert "standard" in versions
        assert "aggressive" in versions
        assert all(isinstance(img, ProcessedImage) for img in versions.values())

        # Check that all versions have valid ProcessedImage fields
        for _version_name, processed_img in versions.items():
            assert processed_img.width > 0
            assert processed_img.height > 0
            assert processed_img.dpi > 0
            assert len(processed_img.image_data) > 0
            assert processed_img.format in ["png", "jpeg"]

    @pytest.mark.asyncio
    async def test_auto_rotate_no_rotation_needed(self):
        """Test auto-rotation when no rotation is needed."""
        image = self.create_test_image()

        # Mock cv2 to return no lines (no rotation needed)
        with patch("proovy_agent.graph.nodes.ocr_node.image_processor.cv2") as mock_cv2:
            mock_cv2.Canny.return_value = np.zeros((100, 100))
            mock_cv2.HoughLines.return_value = None

            result = await self.processor._auto_rotate(image)

            assert result.size == image.size  # No change expected

    def test_estimate_dpi(self):
        """Test DPI estimation."""
        small_image = self.create_test_image(size=(400, 300))
        medium_image = self.create_test_image(size=(1200, 900))
        large_image = self.create_test_image(size=(3000, 2400))

        small_dpi = self.processor._estimate_dpi(small_image)
        medium_dpi = self.processor._estimate_dpi(medium_image)
        large_dpi = self.processor._estimate_dpi(large_image)

        assert small_dpi == 150
        assert medium_dpi == 300
        assert large_dpi == 600

    def test_resize_preserve_aspect(self):
        """Test aspect ratio preservation during resize."""
        image = self.create_test_image(size=(1000, 500))  # 2:1 aspect ratio

        result = self.processor._resize_preserve_aspect(image, 600)

        # Should maintain 2:1 aspect ratio
        aspect_ratio = result.width / result.height
        expected_ratio = 1000 / 500
        assert abs(aspect_ratio - expected_ratio) < 0.01

    def test_estimate_noise_level(self):
        """Test noise level estimation."""
        # Create a clean image
        clean_array = np.ones((100, 100)) * 128  # Uniform gray
        noise_level = self.processor._estimate_noise_level(clean_array)
        assert noise_level >= 0.0

        # Create a noisy image
        noisy_array = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
        noise_level = self.processor._estimate_noise_level(noisy_array)
        assert noise_level > 0.0

    def test_estimate_text_density(self):
        """Test text density estimation."""
        # Create image with edges (simulating text)
        image_with_edges = np.zeros((100, 100))
        image_with_edges[45:55, :] = 255  # Horizontal line
        image_with_edges[:, 45:55] = 255  # Vertical line

        text_density = self.processor._estimate_text_density(image_with_edges)
        assert 0.0 <= text_density <= 1.0

    @pytest.mark.asyncio
    async def test_processing_error_handling(self):
        """Test error handling in processing pipeline."""
        # Create an invalid image scenario
        with patch.object(self.processor, "_analyze_quality", side_effect=Exception("Test error")):
            image = self.create_test_image()

            with pytest.raises(ImageProcessingError) as exc_info:
                await self.processor.process(image)

            assert "Image processing pipeline failed" in str(exc_info.value)
            assert "Test error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_quality_analysis_error_handling(self):
        """Test error handling in quality analysis."""
        # Mock cv2 to raise an exception
        with patch(
            "proovy_agent.graph.nodes.ocr_node.image_processor.cv2.Laplacian",
            side_effect=Exception("CV error"),
        ):
            image = self.create_test_image()

            with pytest.raises(ImageProcessingError) as exc_info:
                await self.processor._analyze_quality(image)

            assert "Image quality analysis failed" in str(exc_info.value)

    def test_enhance_contrast(self):
        """Test contrast enhancement."""
        image = self.create_test_image()

        # Test with low contrast
        enhanced = self.processor._enhance_contrast(image, 0.5)
        assert isinstance(enhanced, Image.Image)

        # Test with high contrast (should limit enhancement)
        enhanced = self.processor._enhance_contrast(image, 5.0)
        assert isinstance(enhanced, Image.Image)

    def test_adjust_brightness(self):
        """Test brightness adjustment."""
        image = self.create_test_image()

        # Test too dark
        adjusted = self.processor._adjust_brightness(image, 50.0)
        assert isinstance(adjusted, Image.Image)

        # Test too bright
        adjusted = self.processor._adjust_brightness(image, 220.0)
        assert isinstance(adjusted, Image.Image)

        # Test normal brightness (no change)
        adjusted = self.processor._adjust_brightness(image, 128.0)
        assert isinstance(adjusted, Image.Image)

    @pytest.mark.asyncio
    async def test_processor_with_default_options(self):
        """Test processor initialization with default options."""
        custom_options = ProcessingOptions(target_dpi=150)
        processor = ImageProcessor(custom_options)

        assert processor.default_options.target_dpi == 150

    @pytest.mark.asyncio
    async def test_finalize_processing(self):
        """Test final processing steps."""
        image = self.create_test_image(mode="L")
        options = ProcessingOptions(binarize=True)

        result = await self.processor._finalize_processing(image, options)

        assert isinstance(result, Image.Image)
        assert result.mode == "L"

    @pytest.mark.asyncio
    async def test_finalize_processing_no_binarize(self):
        """Test final processing without binarization."""
        image = self.create_test_image()
        options = ProcessingOptions(binarize=False)

        result = await self.processor._finalize_processing(image, options)

        assert result is image  # Should return original if no binarization
