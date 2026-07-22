"""OCRNode 통합 테스트 모듈.

메인 OCR 노드의 전체 파이프라인과 LangGraph 통합을 검증합니다.
"""

import base64
import io
from unittest.mock import AsyncMock, patch

from PIL import Image
import pytest

from proovy_agent.graph.nodes.ocr_node import OCRNode, ocr_node
from proovy_agent.graph.nodes.ocr_node.models import (
    ProcessedImage,
    VLMResult,
)
from proovy_agent.graph.state import ProovyState


class TestOCRNode:
    """OCRNode 메인 클래스 테스트."""

    def setup_method(self):
        """각 테스트 전 초기화."""
        self.ocr_node = OCRNode()

    def test_initialization(self):
        """노드 초기화 테스트."""
        assert self.ocr_node.image_processor is not None
        assert self.ocr_node.vlm_engine is not None
        assert self.ocr_node.command_parser is not None
        assert self.ocr_node.math_processor is not None

    @pytest.mark.asyncio
    async def test_text_only_processing(self):
        """이미지 없이 텍스트만 처리하는 경우."""
        state = ProovyState(
            raw_input={"problem": "@용어 기각역 이 문제를 풀어주세요"},
            user_id="test_user",
            thread_id="test_thread",
        )

        result = await self.ocr_node.process(state)

        assert "ocr_text" in result
        assert "ocr_confidence" in result
        assert "tags" in result
        assert result["ocr_confidence"] == 1.0  # 텍스트 입력은 100% 신뢰도
        # 기존 preprocessor 호환성 - @원문 형태 태그 확인
        assert "@용어" in " ".join(result["tags"]) or any("@" in tag for tag in result["tags"])

    def test_extract_image_data_bytes(self):
        """바이트 이미지 데이터 추출 테스트."""
        # 작은 PNG 이미지 생성
        img = Image.new("RGB", (100, 100), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        image_data = self.ocr_node._extract_image_data({"image": img_data})
        assert image_data == img_data

    def test_extract_image_data_base64(self):
        """base64 이미지 데이터 추출 테스트."""
        # 작은 PNG 이미지 생성
        img = Image.new("RGB", (100, 100), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()
        base64_data = base64.b64encode(img_data).decode()

        image_data = self.ocr_node._extract_image_data({"image": base64_data})
        assert image_data == img_data

    def test_extract_image_data_none(self):
        """이미지 데이터가 없는 경우."""
        result = self.ocr_node._extract_image_data({"problem": "텍스트만 있음"})
        assert result is None

    def test_load_image_valid(self):
        """유효한 이미지 로드 테스트."""
        # 작은 PNG 이미지 생성
        img = Image.new("RGB", (100, 100), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        loaded_img = self.ocr_node._load_image(img_data)
        assert isinstance(loaded_img, Image.Image)
        assert loaded_img.size == (100, 100)

    def test_load_image_rgba_conversion(self):
        """RGBA 이미지를 RGB로 변환하는 테스트."""
        # RGBA 이미지 생성
        img = Image.new("RGBA", (100, 100), color=(255, 255, 255, 128))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        loaded_img = self.ocr_node._load_image(img_data)
        assert loaded_img.mode == "RGB"

    def test_load_image_too_small(self):
        """너무 작은 이미지 처리 테스트."""
        # 너무 작은 이미지 생성
        img = Image.new("RGB", (30, 30), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        from proovy_agent.graph.nodes.ocr_node.exceptions import ImageProcessingError

        with pytest.raises(ImageProcessingError):  # ImageProcessingError가 발생해야 함
            self.ocr_node._load_image(img_data)

    def test_convert_to_state_update(self):
        """OCRResult를 state 업데이트로 변환 테스트."""
        from proovy_agent.graph.nodes.ocr_node.models import (
            CommandTag,
            OCRResult,
            ProcessingMetadata,
        )

        # 테스트용 OCRResult 생성
        metadata = ProcessingMetadata(
            total_processing_time=1.5,
            model_used="flash",
            fallback_used=False,
            pages_processed=1,
            quality_score=0.8,
            language_detected="ko",
        )

        command_tags = [
            CommandTag(
                command="term:기각역", original_text="@용어 기각역", confidence=0.9, position=0
            ),
            CommandTag(command="pdf", original_text="@해설지", confidence=0.8, position=10),
        ]

        ocr_result = OCRResult(
            extracted_text="기각역의 정의에 대해 설명하겠습니다.",
            confidence=0.85,
            command_tags=command_tags,
            math_expressions=[],
            language="ko",
            processing_metadata=metadata,
        )

        state_update = self.ocr_node._convert_to_state_update(ocr_result)

        assert state_update["ocr_text"] == "기각역의 정의에 대해 설명하겠습니다."
        assert state_update["ocr_confidence"] == 0.85
        assert state_update["tags"] == ["@용어 기각역", "@해설지"]  # 기존 preprocessor 호환성

    @pytest.mark.asyncio
    async def test_handle_processing_error(self):
        """처리 오류 발생 시 폴백 테스트."""
        import time

        state = ProovyState(
            raw_input={"problem": "@용어 삼각함수 설명해주세요"},
            user_id="test_user",
            thread_id="test_thread",
        )

        start_time = time.time()
        error = Exception("테스트 오류")

        result = await self.ocr_node._handle_processing_error(error, state, start_time)

        assert "ocr_text" in result
        assert "ocr_confidence" in result
        assert "tags" in result
        assert result["ocr_confidence"] < 1.0  # 오류로 인한 신뢰도 감소
        assert any("@용어" in tag for tag in result["tags"])  # 폴백에서 파싱된 @원문 태그


class TestOCRNodeIntegration:
    """OCRNode 전체 파이프라인 통합 테스트."""

    def setup_method(self):
        """각 테스트 전 초기화."""
        self.ocr_node = OCRNode()

    @pytest.mark.asyncio
    @patch("proovy_agent.graph.nodes.ocr_node.ocr_node.ImageProcessor")
    @patch("proovy_agent.graph.nodes.ocr_node.ocr_node.VLMEngine")
    async def test_full_pipeline_with_mocks(self, mock_vlm_engine, mock_image_processor):
        """전체 파이프라인 테스트 (모킹 사용)."""
        # Mock 설정
        mock_processed_image = ProcessedImage(
            image_data=b"processed_image_data",
            format="PNG",
            width=300,
            height=200,
            dpi=300,
            preprocessing_applied=["contrast_enhancement"],
        )

        mock_vlm_result = VLMResult(
            model_name="flash",
            raw_text="@용어 기각역 삼각함수의 기각역을 구하시오. sin²θ + cos²θ = 1",
            confidence=0.85,
            processing_time=2.3,
            token_usage={"input": 150, "output": 50, "total": 200},
        )

        # ImageProcessor 모킹
        mock_processor_instance = AsyncMock()
        mock_processor_instance.process.return_value = mock_processed_image
        mock_image_processor.return_value = mock_processor_instance

        # VLMEngine 모킹
        mock_vlm_instance = AsyncMock()
        mock_vlm_instance.process_image.return_value = mock_vlm_result
        mock_vlm_instance.detect_language.return_value = "ko"
        mock_vlm_engine.return_value = mock_vlm_instance

        # 테스트용 이미지 데이터
        img = Image.new("RGB", (100, 100), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        # 상태 설정
        state = ProovyState(
            raw_input={"image": img_data},
            user_id="test_user",
            thread_id="test_thread",
        )

        # 새 인스턴스 생성하여 모킹된 클래스 사용
        ocr_node_test = OCRNode()

        result = await ocr_node_test.process(state)

        # 결과 검증
        assert "ocr_text" in result
        assert "ocr_confidence" in result
        assert "tags" in result
        assert result["ocr_confidence"] == 0.85
        assert any("@용어" in tag for tag in result["tags"])

        # Mock 호출 검증
        mock_processor_instance.process.assert_called_once()
        mock_vlm_instance.process_image.assert_called_once()
        mock_vlm_instance.detect_language.assert_called_once()


class TestLangGraphIntegration:
    """LangGraph 통합 테스트."""

    @pytest.mark.asyncio
    async def test_ocr_node_function(self):
        """ocr_node 함수 (LangGraph 래퍼) 테스트."""
        state = ProovyState(
            raw_input={"problem": "@해설영상 이 문제 풀어주세요"},
            user_id="test_user",
            thread_id="test_thread",
        )

        result = await ocr_node(state)

        assert isinstance(result, dict)
        assert "ocr_text" in result
        assert "ocr_confidence" in result
        assert "tags" in result
        assert any("@해설영상" in tag for tag in result["tags"])


class TestErrorHandling:
    """에러 처리 테스트."""

    def setup_method(self):
        """각 테스트 전 초기화."""
        self.ocr_node = OCRNode()

    @pytest.mark.asyncio
    async def test_invalid_image_data(self):
        """잘못된 이미지 데이터 처리."""
        state = ProovyState(
            raw_input={"image": b"invalid_image_data"},
            user_id="test_user",
            thread_id="test_thread",
        )

        result = await self.ocr_node.process(state)

        # 오류 발생 시 폴백 처리가 되어야 함
        assert "ocr_text" in result
        assert "ocr_confidence" in result
        assert result["ocr_confidence"] < 1.0  # 오류로 인한 신뢰도 감소

    @pytest.mark.asyncio
    async def test_empty_raw_input(self):
        """빈 raw_input 처리."""
        state = ProovyState(
            raw_input={},
            user_id="test_user",
            thread_id="test_thread",
        )

        result = await self.ocr_node.process(state)

        assert "ocr_text" in result
        assert "ocr_confidence" in result
        assert "tags" in result
        assert result["ocr_text"] == ""
        assert result["tags"] == []


class TestPerformanceAndEdgeCases:
    """성능 및 엣지 케이스 테스트."""

    def setup_method(self):
        """각 테스트 전 초기화."""
        self.ocr_node = OCRNode()

    @pytest.mark.asyncio
    async def test_large_text_input(self):
        """큰 텍스트 입력 처리."""
        large_text = "수학 문제입니다. " * 1000  # 긴 텍스트
        state = ProovyState(
            raw_input={"problem": f"@용어 기각역 {large_text}"},
            user_id="test_user",
            thread_id="test_thread",
        )

        result = await self.ocr_node.process(state)

        assert "ocr_text" in result
        assert len(result["ocr_text"]) > 0
        assert any("@용어" in tag for tag in result["tags"])

    def test_multiple_image_fields(self):
        """여러 이미지 필드가 있는 경우 첫 번째 유효한 것 사용."""
        # 유효한 이미지 생성
        img = Image.new("RGB", (100, 100), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        valid_img_data = img_bytes.getvalue()

        raw_input = {
            "invalid_field": "not_image",
            "image": valid_img_data,  # 이것이 사용되어야 함
            "photo": b"invalid_data",
        }

        extracted = self.ocr_node._extract_image_data(raw_input)
        assert extracted == valid_img_data

    @pytest.mark.asyncio
    async def test_unicode_text_processing(self):
        """유니코드 텍스트 처리 테스트."""
        unicode_text = "@용어 삼각함수 sinθ, cosθ, α + β = γ 계산하기"  # noqa: RUF001
        state = ProovyState(
            raw_input={"problem": unicode_text},
            user_id="test_user",
            thread_id="test_thread",
        )

        result = await self.ocr_node.process(state)

        assert "ocr_text" in result
        assert any("@용어" in tag for tag in result["tags"])
        # 유니코드 문자가 손실되지 않아야 함
        assert "α" in result["ocr_text"]  # noqa: RUF001


if __name__ == "__main__":
    # 개별 테스트 실행을 위한 코드
    pytest.main([__file__, "-v"])
