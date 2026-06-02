"""VLM OCR 엔진 테스트."""

import asyncio
import base64
from unittest.mock import AsyncMock, patch

import pytest

from proovy_agent.graph.nodes.ocr_node.exceptions import (
    LanguageDetectionError,
    OCRTimeoutError,
    VLMProcessingError,
)
from proovy_agent.graph.nodes.ocr_node.models import OCROptions, ProcessedImage, VLMResult
from proovy_agent.graph.nodes.ocr_node.vlm_engine import VLMEngine


@pytest.fixture
def vlm_engine():
    """VLM 엔진 픽스처."""
    return VLMEngine()


@pytest.fixture
def sample_processed_image():
    """샘플 처리된 이미지."""
    # 1x1 PNG 이미지 데이터 (base64)
    png_data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

    return ProcessedImage(
        image_data=png_data,
        format="png",
        width=100,
        height=100,
        dpi=300,
        preprocessing_applied=["contrast_enhancement", "adaptive_threshold"]
    )


@pytest.fixture
def default_options():
    """기본 OCR 옵션."""
    return OCROptions(
        primary_model="flash",
        fallback_model="gpt4o-mini",
        target_language="auto",
        enable_math_mode=True,
        enable_command_parsing=True,
        quality_threshold=0.7,
        max_processing_time=30.0
    )


class TestVLMEngine:
    """VLM 엔진 기본 테스트."""

    def test_initialization(self, vlm_engine):
        """엔진 초기화 테스트."""
        assert vlm_engine is not None
        assert "default" in vlm_engine.prompt_templates
        assert "flash" in vlm_engine.model_configs
        assert "gpt4o-mini" in vlm_engine.model_configs

    def test_prompt_templates(self, vlm_engine):
        """프롬프트 템플릿 테스트."""
        template = vlm_engine.prompt_templates["default"]

        assert "OCR system" in template.system_prompt
        assert "Korean and English" in template.system_prompt
        assert "{target_language}" in template.user_prompt_template
        assert "mathematical expressions" in template.math_mode_addition
        assert "@command" in template.command_mode_addition

    def test_model_configs(self, vlm_engine):
        """모델 설정 테스트."""
        flash_config = vlm_engine.model_configs["flash"]
        gpt_config = vlm_engine.model_configs["gpt4o-mini"]

        assert flash_config.model_name == "gemini-2.0-flash-exp"
        assert "generativelanguage.googleapis.com" in flash_config.api_endpoint
        assert gpt_config.model_name == "gpt-4o-mini"
        assert "api.openai.com" in gpt_config.api_endpoint

    def test_build_prompt_basic(self, vlm_engine, default_options):
        """기본 프롬프트 생성 테스트."""
        prompt = vlm_engine._build_prompt(default_options)

        assert "OCR system" in prompt
        assert "auto" in prompt  # target_language
        assert "mathematical expressions" in prompt  # math mode
        assert "@command" in prompt  # command mode

    def test_build_prompt_options(self, vlm_engine):
        """프롬프트 옵션별 생성 테스트."""
        # 수학 모드만 활성화
        options_math = OCROptions(
            enable_math_mode=True,
            enable_command_parsing=False,
            target_language="ko"
        )
        prompt = vlm_engine._build_prompt(options_math)
        assert "mathematical expressions" in prompt
        assert "@command" not in prompt
        assert "ko" in prompt

        # 커맨드 모드만 활성화
        options_command = OCROptions(
            enable_math_mode=False,
            enable_command_parsing=True,
            target_language="en"
        )
        prompt = vlm_engine._build_prompt(options_command)
        # 수학 모드 비활성화 시에는 수학 관련 추가 프롬프트만 없어야 함
        # 하지만 시스템 프롬프트에는 여전히 "mathematical expressions"가 있을 수 있음
        template = vlm_engine.prompt_templates["default"]
        assert template.math_mode_addition not in prompt
        assert "@command" in prompt
        assert "en" in prompt


class TestConfidenceCalculation:
    """신뢰도 계산 테스트."""

    def test_empty_text_confidence(self, vlm_engine, sample_processed_image):
        """빈 텍스트 신뢰도."""
        assert vlm_engine._calculate_confidence("", sample_processed_image) == 0.0
        assert vlm_engine._calculate_confidence("   ", sample_processed_image) == 0.0

    def test_text_length_confidence(self, vlm_engine, sample_processed_image):
        """텍스트 길이별 신뢰도."""
        short_text = "Hi"
        medium_text = "This is a medium length text for testing OCR confidence calculation."
        long_text = "This is a very long text that contains many words and sentences to test the confidence calculation algorithm in the VLM OCR engine. It should receive higher confidence scores due to its length and complexity."

        short_conf = vlm_engine._calculate_confidence(short_text, sample_processed_image)
        medium_conf = vlm_engine._calculate_confidence(medium_text, sample_processed_image)
        long_conf = vlm_engine._calculate_confidence(long_text, sample_processed_image)

        assert short_conf < medium_conf < long_conf

    def test_image_quality_confidence(self, vlm_engine):
        """이미지 품질별 신뢰도."""
        text = "Sample text for testing"

        # 고해상도 이미지
        high_dpi_image = ProcessedImage(
            image_data=b"dummy",
            format="png",
            width=100,
            height=100,
            dpi=400,
            preprocessing_applied=[]
        )

        # 저해상도 이미지
        low_dpi_image = ProcessedImage(
            image_data=b"dummy",
            format="png",
            width=100,
            height=100,
            dpi=150,
            preprocessing_applied=[]
        )

        high_conf = vlm_engine._calculate_confidence(text, high_dpi_image)
        low_conf = vlm_engine._calculate_confidence(text, low_dpi_image)

        assert high_conf > low_conf

    def test_preprocessing_confidence(self, vlm_engine):
        """전처리 적용에 따른 신뢰도."""
        text = "Sample text for testing"

        # 전처리 적용된 이미지
        processed_image = ProcessedImage(
            image_data=b"dummy",
            format="png",
            width=100,
            height=100,
            dpi=300,
            preprocessing_applied=["contrast_enhancement", "adaptive_threshold", "noise_removal"]
        )

        # 전처리 없는 이미지
        raw_image = ProcessedImage(
            image_data=b"dummy",
            format="png",
            width=100,
            height=100,
            dpi=300,
            preprocessing_applied=[]
        )

        processed_conf = vlm_engine._calculate_confidence(text, processed_image)
        raw_conf = vlm_engine._calculate_confidence(text, raw_image)

        assert processed_conf > raw_conf

    def test_korean_english_mixed_confidence(self, vlm_engine, sample_processed_image):
        """한영 혼재 텍스트 신뢰도."""
        korean_only = "안녕하세요 한국어 텍스트입니다"
        english_only = "Hello this is English text"
        mixed_text = "안녕하세요 Hello 한국어와 English mixed text"

        korean_conf = vlm_engine._calculate_confidence(korean_only, sample_processed_image)
        english_conf = vlm_engine._calculate_confidence(english_only, sample_processed_image)
        mixed_conf = vlm_engine._calculate_confidence(mixed_text, sample_processed_image)

        # 한영 혼재는 한국 교육 자료의 특성으로 보너스
        assert mixed_conf >= korean_conf
        assert mixed_conf >= english_conf

    def test_math_symbols_confidence(self, vlm_engine, sample_processed_image):
        """수학 기호 포함 신뢰도."""
        text_with_math = "수학 공식: ∫₀¹ f(x)dx = √(a²+b²) ≤ ∞"
        text_without_math = "일반 텍스트입니다"

        math_conf = vlm_engine._calculate_confidence(text_with_math, sample_processed_image)
        normal_conf = vlm_engine._calculate_confidence(text_without_math, sample_processed_image)

        # 적절한 수학 기호는 보너스
        assert math_conf > normal_conf

    def test_command_pattern_confidence(self, vlm_engine, sample_processed_image):
        """@커맨드 패턴 신뢰도."""
        text_with_commands = "@solve this equation @explain the result"
        text_without_commands = "solve this equation explain the result"

        command_conf = vlm_engine._calculate_confidence(text_with_commands, sample_processed_image)
        normal_conf = vlm_engine._calculate_confidence(text_without_commands, sample_processed_image)

        # @커맨드가 인식되면 보너스
        assert command_conf > normal_conf


class TestLanguageDetection:
    """언어 감지 테스트."""

    @pytest.mark.asyncio
    async def test_empty_text_detection(self, vlm_engine):
        """빈 텍스트 언어 감지."""
        with pytest.raises(LanguageDetectionError):
            await vlm_engine.detect_language("")

        with pytest.raises(LanguageDetectionError):
            await vlm_engine.detect_language("   ")

    @pytest.mark.asyncio
    async def test_korean_detection(self, vlm_engine):
        """한국어 감지."""
        korean_text = "안녕하세요 한국어 텍스트입니다"
        result = await vlm_engine.detect_language(korean_text)
        assert result == "ko"

    @pytest.mark.asyncio
    async def test_english_detection(self, vlm_engine):
        """영어 감지."""
        english_text = "Hello this is English text"
        result = await vlm_engine.detect_language(english_text)
        assert result == "en"

    @pytest.mark.asyncio
    async def test_mixed_language_detection(self, vlm_engine):
        """혼재 언어 감지."""
        mixed_text = "안녕하세요 Hello 한국어와 English mixed"
        result = await vlm_engine.detect_language(mixed_text)
        assert result == "mixed"

    @pytest.mark.asyncio
    async def test_numbers_only_detection(self, vlm_engine):
        """숫자만 있는 텍스트."""
        numbers_text = "123 456 789"
        result = await vlm_engine.detect_language(numbers_text)
        assert result == "unknown"


class TestGeminiProcessing:
    """Gemini API 처리 테스트."""

    @pytest.mark.asyncio
    async def test_missing_api_key(self, vlm_engine, sample_processed_image, default_options):
        """API 키 누락 테스트."""
        with (
            patch.dict('os.environ', {}, clear=True),
            pytest.raises(VLMProcessingError, match="API 키가 설정되지 않았습니다")
        ):
                await vlm_engine._process_with_gemini(
                    sample_processed_image,
                    default_options,
                    vlm_engine.model_configs["flash"]
                )

    @pytest.mark.asyncio
    async def test_successful_gemini_response(self, vlm_engine, sample_processed_image, default_options):
        """성공적인 Gemini 응답 테스트."""
        mock_response_data = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "Extracted text from image"}]
                },
                "finishReason": "STOP"
            }],
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 20,
                "totalTokenCount": 120
            }
        }

        with (
            patch.dict('os.environ', {'GEMINI_API_KEY': 'test-key'}),
            patch('aiohttp.ClientSession.post') as mock_post
        ):
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json.return_value = mock_response_data
                mock_post.return_value.__aenter__.return_value = mock_response

                result = await vlm_engine._process_with_gemini(
                    sample_processed_image,
                    default_options,
                    vlm_engine.model_configs["flash"]
                )

                assert isinstance(result, VLMResult)
                assert result.raw_text == "Extracted text from image"
                assert result.model_name == "gemini-2.0-flash-exp"
                assert result.token_usage["total"] == 120
                assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_gemini_api_error(self, vlm_engine, sample_processed_image, default_options):
        """Gemini API 오류 테스트."""
        with (
            patch.dict('os.environ', {'GEMINI_API_KEY': 'test-key'}),
            patch('aiohttp.ClientSession.post') as mock_post
        ):
                mock_response = AsyncMock()
                mock_response.status = 429  # Rate limit
                mock_response.text.return_value = "Rate limit exceeded"
                mock_post.return_value.__aenter__.return_value = mock_response

                with pytest.raises(VLMProcessingError) as exc_info:
                    await vlm_engine._process_with_gemini(
                        sample_processed_image,
                        default_options,
                        vlm_engine.model_configs["flash"]
                    )

                assert exc_info.value.is_recoverable is True  # 429는 복구 가능
                assert "429" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_gemini_safety_filter(self, vlm_engine, sample_processed_image, default_options):
        """Gemini 안전성 필터 테스트."""
        mock_response_data = {
            "candidates": [{
                "finishReason": "SAFETY",
                "safetyRatings": [{"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "probability": "HIGH"}]
            }]
        }

        with (
            patch.dict('os.environ', {'GEMINI_API_KEY': 'test-key'}),
            patch('aiohttp.ClientSession.post') as mock_post
        ):
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json.return_value = mock_response_data
                mock_post.return_value.__aenter__.return_value = mock_response

                with pytest.raises(VLMProcessingError) as exc_info:
                    await vlm_engine._process_with_gemini(
                        sample_processed_image,
                        default_options,
                        vlm_engine.model_configs["flash"]
                    )

                assert "안전성 필터" in str(exc_info.value)
                assert exc_info.value.is_recoverable is True

    @pytest.mark.asyncio
    async def test_gemini_empty_response(self, vlm_engine, sample_processed_image, default_options):
        """Gemini 빈 응답 테스트."""
        mock_response_data = {
            "candidates": [{
                "content": {
                    "parts": [{"text": ""}]
                }
            }]
        }

        with (
            patch.dict('os.environ', {'GEMINI_API_KEY': 'test-key'}),
            patch('aiohttp.ClientSession.post') as mock_post
        ):
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json.return_value = mock_response_data
                mock_post.return_value.__aenter__.return_value = mock_response

                with pytest.raises(VLMProcessingError, match="빈 텍스트를 반환했습니다"):
                    await vlm_engine._process_with_gemini(
                        sample_processed_image,
                        default_options,
                        vlm_engine.model_configs["flash"]
                    )


class TestProcessImage:
    """이미지 처리 통합 테스트."""

    @pytest.mark.asyncio
    async def test_successful_processing(self, vlm_engine, sample_processed_image, default_options):
        """성공적인 이미지 처리."""
        mock_result = VLMResult(
            model_name="gemini-2.0-flash-exp",
            raw_text="Test extracted text",
            confidence=0.8,
            processing_time=1.5,
            token_usage={"input": 100, "output": 20, "total": 120}
        )

        with patch.object(vlm_engine, '_process_with_model', return_value=mock_result) as mock_process:
            result = await vlm_engine.process_image(sample_processed_image, default_options)

            assert result == mock_result
            mock_process.assert_called_once_with(sample_processed_image, default_options, "flash")

    @pytest.mark.asyncio
    async def test_quality_threshold_fallback(self, vlm_engine, sample_processed_image, default_options):
        """품질 기준 미달 시 폴백 테스트."""
        low_quality_result = VLMResult(
            model_name="gemini-2.0-flash-exp",
            raw_text="Low quality text",
            confidence=0.5,  # 기준(0.7) 미달
            processing_time=1.0,
            token_usage={}
        )

        high_quality_result = VLMResult(
            model_name="gpt-4o-mini",
            raw_text="High quality text",
            confidence=0.9,
            processing_time=2.0,
            token_usage={}
        )

        with patch.object(vlm_engine, '_process_with_model') as mock_process:
            mock_process.side_effect = [low_quality_result, high_quality_result]

            result = await vlm_engine.process_image(sample_processed_image, default_options)

            assert result == high_quality_result
            assert mock_process.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_error(self, vlm_engine, sample_processed_image, default_options):
        """타임아웃 오류 테스트."""
        short_timeout_options = OCROptions(
            primary_model="flash",
            max_processing_time=0.001  # 매우 짧은 타임아웃
        )

        with patch.object(vlm_engine, '_process_with_gemini') as mock_gemini:
            # 긴 지연 시뮬레이션
            async def slow_process(*args, **kwargs):
                await asyncio.sleep(1)
                return VLMResult(
                    model_name="test",
                    raw_text="text",
                    confidence=0.8,
                    processing_time=1.0,
                    token_usage={}
                )

            mock_gemini.side_effect = slow_process

            with pytest.raises(OCRTimeoutError):
                await vlm_engine._process_with_model(
                    sample_processed_image,
                    short_timeout_options,
                    "flash"
                )


class TestBatchProcessing:
    """배치 처리 테스트."""

    @pytest.mark.asyncio
    async def test_batch_processing_success(self, vlm_engine, default_options):
        """성공적인 배치 처리."""
        # 테스트용 이미지 3개
        images = [
            ProcessedImage(
                image_data=b"dummy1",
                format="png",
                width=100,
                height=100,
                dpi=300,
                preprocessing_applied=[]
            ),
            ProcessedImage(
                image_data=b"dummy2",
                format="png",
                width=100,
                height=100,
                dpi=300,
                preprocessing_applied=[]
            ),
            ProcessedImage(
                image_data=b"dummy3",
                format="png",
                width=100,
                height=100,
                dpi=300,
                preprocessing_applied=[]
            )
        ]

        mock_results = [
            VLMResult(
                model_name="gemini-2.0-flash-exp",
                raw_text=f"Text from image {i+1}",
                confidence=0.8,
                processing_time=1.0,
                token_usage={}
            )
            for i in range(3)
        ]

        with patch.object(vlm_engine, 'process_image') as mock_process:
            mock_process.side_effect = mock_results

            results = await vlm_engine.process_batch(images, default_options)

            assert len(results) == 3
            assert all(isinstance(result, VLMResult) for result in results)
            assert mock_process.call_count == 3

    @pytest.mark.asyncio
    async def test_batch_processing_with_failures(self, vlm_engine, default_options):
        """일부 실패가 포함된 배치 처리."""
        images = [
            ProcessedImage(
                image_data=b"dummy1",
                format="png",
                width=100,
                height=100,
                dpi=300,
                preprocessing_applied=[]
            ),
            ProcessedImage(
                image_data=b"dummy2",
                format="png",
                width=100,
                height=100,
                dpi=300,
                preprocessing_applied=[]
            )
        ]

        success_result = VLMResult(
            model_name="gemini-2.0-flash-exp",
            raw_text="Success text",
            confidence=0.8,
            processing_time=1.0,
            token_usage={}
        )

        with patch.object(vlm_engine, 'process_image') as mock_process:
            mock_process.side_effect = [success_result, VLMProcessingError("flash", "API Error")]

            results = await vlm_engine.process_batch(images, default_options)

            assert len(results) == 2
            assert results[0] == success_result
            # 실패한 경우 기본 VLMResult 반환
            assert results[1].model_name == "failed"
            assert results[1].confidence == 0.0

