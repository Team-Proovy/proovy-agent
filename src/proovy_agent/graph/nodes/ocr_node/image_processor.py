"""Image preprocessing system for OCR optimization."""

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from pydantic import BaseModel, Field

from .exceptions import ImageProcessingError
from .models import ProcessedImage


class ImageQuality(BaseModel):
    """Image quality analysis result."""

    blur_score: float = Field(ge=0.0, description="Blur detection score (higher = more blurred)")
    noise_level: float = Field(ge=0.0, le=1.0, description="Noise level from 0.0 to 1.0")
    contrast_ratio: float = Field(ge=0.0, description="Contrast ratio measurement")
    text_density: float = Field(ge=0.0, le=1.0, description="Estimated text density in image")
    brightness: float = Field(ge=0.0, le=255.0, description="Average brightness level")
    resolution_dpi: int = Field(gt=0, description="Estimated DPI resolution")


class ProcessingOptions(BaseModel):
    """Image processing configuration options."""

    target_dpi: int = Field(default=300, gt=0, description="Target DPI for OCR optimization")
    enhance_contrast: bool = Field(default=True, description="Enable contrast enhancement")
    remove_noise: bool = Field(default=True, description="Enable noise removal")
    auto_rotate: bool = Field(default=True, description="Enable automatic rotation correction")
    binarize: bool = Field(default=True, description="Enable adaptive binarization")
    preserve_color: bool = Field(
        default=False, description="Preserve color information (vs grayscale)"
    )
    max_dimension: int = Field(default=4096, gt=0, description="Maximum image dimension in pixels")


class ImageProcessor:
    """Advanced image preprocessing system for OCR optimization."""

    def __init__(self, default_options: ProcessingOptions | None = None):
        """Initialize image processor with default options."""
        self.default_options = default_options or ProcessingOptions()

    async def process(
        self,
        image: Image.Image,
        options: ProcessingOptions | None = None,
    ) -> ProcessedImage:
        """
        Process image with full optimization pipeline.

        Args:
            image: Input PIL Image
            options: Processing configuration options

        Returns:
            ProcessedImage with optimized image data and metadata

        Raises:
            ImageProcessingError: If any processing step fails
        """
        try:
            processing_options = options or self.default_options

            # Step 1: Analyze image quality
            quality = await self._analyze_quality(image)

            # Step 2: Basic preprocessing
            processed = await self._preprocess_basic(image, processing_options)

            # Step 3: Rotation correction (if needed)
            if processing_options.auto_rotate:
                processed = await self._auto_rotate(processed)

            # Step 4: Resolution optimization
            processed = await self._optimize_resolution(processed, processing_options.target_dpi)

            # Step 5: Quality enhancement based on analysis
            processed = await self._enhance_quality(processed, quality, processing_options)

            # Step 6: Final optimization
            processed = await self._finalize_processing(processed, processing_options)

            # Convert to ProcessedImage with metadata
            return await self._create_processed_image(processed, processing_options, quality)

        except Exception as e:
            if isinstance(e, ImageProcessingError):
                raise
            raise ImageProcessingError(
                f"Image processing pipeline failed: {e!s}",
                {"original_size": image.size, "mode": image.mode},
                "Try with a simpler image or adjust processing options",
            ) from e

    async def _analyze_quality(self, image: Image.Image) -> ImageQuality:
        """Analyze image quality metrics."""
        try:
            # Convert to numpy array for analysis
            img_array = np.array(image.convert("L"))  # Grayscale

            # Blur detection using Laplacian variance
            blur_score = cv2.Laplacian(img_array, cv2.CV_64F).var()

            # Noise level estimation
            noise_level = self._estimate_noise_level(img_array)

            # Contrast ratio calculation
            contrast_ratio = img_array.std() / (img_array.mean() + 1e-8)

            # Text density estimation (rough approximation)
            text_density = self._estimate_text_density(img_array)

            # Brightness calculation
            brightness = float(img_array.mean())

            # DPI estimation based on image size
            resolution_dpi = self._estimate_dpi(image)

            return ImageQuality(
                blur_score=float(blur_score),
                noise_level=noise_level,
                contrast_ratio=float(contrast_ratio),
                text_density=text_density,
                brightness=brightness,
                resolution_dpi=resolution_dpi,
            )

        except Exception as e:
            raise ImageProcessingError(
                "Image quality analysis failed",
                {"error": str(e), "image_size": image.size},
            ) from e

    async def _preprocess_basic(
        self, image: Image.Image, options: ProcessingOptions
    ) -> Image.Image:
        """Apply basic preprocessing steps."""
        try:
            processed = image.copy()

            # Size normalization
            if max(processed.size) > options.max_dimension:
                processed = self._resize_preserve_aspect(processed, options.max_dimension)

            # Color space conversion
            if not options.preserve_color and processed.mode != "L":
                processed = processed.convert("L")

            return processed

        except Exception as e:
            raise ImageProcessingError(
                "Basic preprocessing failed",
                {"step": "basic", "error": str(e)},
            ) from e

    async def _auto_rotate(self, image: Image.Image) -> Image.Image:
        """Detect and correct text rotation using Hough line detection."""
        try:
            # Convert to OpenCV format
            img_array = np.array(image.convert("L"))

            # Edge detection
            edges = cv2.Canny(img_array, 50, 150, apertureSize=3)

            # Hough line detection
            lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)

            if lines is not None and len(lines) > 0:
                # Calculate dominant angle
                angles = []
                for line in lines[:50]:  # Use top 50 lines
                    _rho, theta = line[0]  # OpenCV returns array of arrays
                    angle = theta * 180 / np.pi
                    # Convert to rotation angle
                    if angle < 45:
                        angles.append(angle)
                    elif angle > 135:
                        angles.append(angle - 180)
                    else:
                        angles.append(angle - 90)

                if angles:
                    # Use median angle to avoid outliers
                    rotation_angle = -np.median(angles)

                    # Only rotate if angle is significant (> 0.5 degrees)
                    if abs(rotation_angle) > 0.5:
                        return image.rotate(rotation_angle, expand=True, fillcolor="white")

            return image

        except Exception as e:
            raise ImageProcessingError(
                "Auto-rotation failed",
                {"error": str(e)},
                "Continue without rotation correction",
            ) from e

    async def _optimize_resolution(self, image: Image.Image, target_dpi: int) -> Image.Image:
        """Optimize image resolution for OCR."""
        try:
            current_dpi = self._estimate_dpi(image)

            if current_dpi < target_dpi * 0.8:  # Need upscaling
                scale_factor = target_dpi / current_dpi
                new_size = (
                    int(image.width * scale_factor),
                    int(image.height * scale_factor),
                )
                # Use LANCZOS for high-quality upscaling
                return image.resize(new_size, Image.Resampling.LANCZOS)

            elif current_dpi > target_dpi * 1.5:  # Need downscaling
                scale_factor = target_dpi / current_dpi
                new_size = (
                    int(image.width * scale_factor),
                    int(image.height * scale_factor),
                )
                # Use LANCZOS for high-quality downscaling
                return image.resize(new_size, Image.Resampling.LANCZOS)

            return image

        except Exception as e:
            raise ImageProcessingError(
                "Resolution optimization failed",
                {"target_dpi": target_dpi, "error": str(e)},
            ) from e

    async def _enhance_quality(
        self,
        image: Image.Image,
        quality: ImageQuality,
        options: ProcessingOptions,
    ) -> Image.Image:
        """Apply quality enhancements based on quality analysis."""
        try:
            processed = image

            # Noise removal if needed
            if options.remove_noise and quality.noise_level > 0.3:
                processed = self._remove_noise(processed, quality.noise_level)

            # Contrast enhancement if needed
            if options.enhance_contrast and quality.contrast_ratio < 2.0:
                processed = self._enhance_contrast(processed, quality.contrast_ratio)

            # Brightness adjustment if needed
            if quality.brightness < 100 or quality.brightness > 200:
                processed = self._adjust_brightness(processed, quality.brightness)

            return processed

        except Exception as e:
            raise ImageProcessingError(
                "Quality enhancement failed",
                {"quality_metrics": quality.model_dump(), "error": str(e)},
            ) from e

    async def _finalize_processing(
        self, image: Image.Image, options: ProcessingOptions
    ) -> Image.Image:
        """Apply final processing steps."""
        try:
            processed = image

            # Adaptive binarization for text clarity
            if options.binarize:
                processed = self._adaptive_threshold(processed)

            return processed

        except Exception as e:
            raise ImageProcessingError(
                "Final processing failed",
                {"error": str(e)},
            ) from e

    def _estimate_noise_level(self, img_array: np.ndarray) -> float:
        """Estimate noise level using standard deviation of Laplacian."""
        laplacian = cv2.Laplacian(img_array, cv2.CV_64F)
        noise_estimate = laplacian.std() / 255.0  # Normalize to 0-1
        return min(noise_estimate, 1.0)

    def _estimate_text_density(self, img_array: np.ndarray) -> float:
        """Rough estimation of text density in image."""
        # Use edge density as proxy for text density
        # Convert to uint8 if necessary
        if img_array.dtype != np.uint8:
            img_array = img_array.astype(np.uint8)
        edges = cv2.Canny(img_array, 50, 150)
        edge_density = np.count_nonzero(edges) / edges.size
        return min(edge_density * 5, 1.0)  # Scale and clamp to 0-1

    def _estimate_dpi(self, image: Image.Image) -> int:
        """Estimate DPI based on image dimensions."""
        # Simple heuristic: assume text height of ~12pt (0.17 inches)
        # Typical text line height suggests DPI
        avg_dimension = (image.width + image.height) / 2
        if avg_dimension < 800:
            return 150  # Low resolution
        elif avg_dimension < 2000:
            return 300  # Standard
        else:
            return 600  # High resolution

    def _resize_preserve_aspect(self, image: Image.Image, max_dimension: int) -> Image.Image:
        """Resize image while preserving aspect ratio."""
        ratio = min(max_dimension / image.width, max_dimension / image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        return image.resize(new_size, Image.Resampling.LANCZOS)

    def _remove_noise(self, image: Image.Image, noise_level: float) -> Image.Image:
        """Remove noise using appropriate filters."""
        if noise_level < 0.5:
            # Light denoising
            return image.filter(ImageFilter.MedianFilter(size=3))
        else:
            # Stronger denoising
            img_array = np.array(image)
            if len(img_array.shape) == 3:
                # Color image
                denoised = cv2.fastNlMeansDenoisingColored(img_array, None, 10, 10, 7, 21)
            else:
                # Grayscale image
                denoised = cv2.fastNlMeansDenoising(img_array, None, 10, 7, 21)
            return Image.fromarray(denoised)

    def _enhance_contrast(self, image: Image.Image, current_contrast: float) -> Image.Image:
        """Enhance image contrast intelligently."""
        target_contrast = 3.0
        enhancement_factor = min(target_contrast / max(current_contrast, 0.1), 2.5)
        enhancer = ImageEnhance.Contrast(image)
        return enhancer.enhance(enhancement_factor)

    def _adjust_brightness(self, image: Image.Image, current_brightness: float) -> Image.Image:
        """Adjust image brightness for optimal OCR."""
        target_brightness = 128  # Mid-gray target
        if current_brightness < 80:
            # Too dark
            factor = min(target_brightness / current_brightness, 2.0)
            enhancer = ImageEnhance.Brightness(image)
            return enhancer.enhance(factor)
        elif current_brightness > 200:
            # Too bright
            factor = max(target_brightness / current_brightness, 0.5)
            enhancer = ImageEnhance.Brightness(image)
            return enhancer.enhance(factor)
        return image

    def _adaptive_threshold(self, image: Image.Image) -> Image.Image:
        """Apply adaptive thresholding for better text extraction."""
        img_array = np.array(image.convert("L"))

        # Apply adaptive threshold
        binary = cv2.adaptiveThreshold(
            img_array,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,  # Block size
            2,  # C constant
        )

        return Image.fromarray(binary)

    async def _create_processed_image(
        self, image: Image.Image, options: ProcessingOptions, quality: ImageQuality
    ) -> ProcessedImage:
        """Create ProcessedImage object with metadata."""
        import io

        # Convert image to bytes
        buffer = io.BytesIO()
        image_format = "PNG" if image.mode in ("RGBA", "LA") else "JPEG"
        image.save(buffer, format=image_format, quality=95 if image_format == "JPEG" else None)
        image_data = buffer.getvalue()

        # Track preprocessing steps
        preprocessing_applied = []
        if options.auto_rotate:
            preprocessing_applied.append("rotation_correction")
        if options.enhance_contrast:
            preprocessing_applied.append("contrast_enhancement")
        if options.remove_noise:
            preprocessing_applied.append("noise_removal")
        if options.binarize:
            preprocessing_applied.append("adaptive_threshold")

        return ProcessedImage(
            image_data=image_data,
            format=image_format.lower(),
            width=image.width,
            height=image.height,
            dpi=quality.resolution_dpi,
            preprocessing_applied=preprocessing_applied,
        )

    async def create_multiple_versions(self, image: Image.Image) -> dict[str, ProcessedImage]:
        """
        Create multiple processed versions for different OCR engines.

        Returns:
            Dictionary mapping version name to ProcessedImage object
        """
        versions = {}

        # Original (minimal processing)
        minimal_options = ProcessingOptions(
            enhance_contrast=False,
            remove_noise=False,
            binarize=False,
        )
        versions["minimal"] = await self.process(image, minimal_options)

        # Standard processing
        versions["standard"] = await self.process(image)

        # Aggressive processing for low quality images
        aggressive_options = ProcessingOptions(
            target_dpi=600,
            enhance_contrast=True,
            remove_noise=True,
            binarize=True,
        )
        versions["aggressive"] = await self.process(image, aggressive_options)

        return versions
