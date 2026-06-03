"""OCRNode - 메인 OCR 통합 노드 구현.

VLM 기반 이미지 텍스트 추출, @커맨드 파싱, 수학 표기법 후처리를 통합하여
LangGraph Preprocessor로 동작하는 메인 OCR 노드입니다.
"""

import io
import time
from typing import Any

from PIL import Image

from proovy_agent.graph.state import ProovyState

from .command_parser import create_command_parser
from .exceptions import (
    FileConversionError,
    ImageProcessingError,
    OCRError,
)
from .image_processor import ImageProcessor, ProcessingOptions
from .math_postprocessor import MathPostProcessor
from .models import OCROptions, OCRRequest, OCRResult, ProcessingMetadata
from .vlm_engine import VLMEngine


class OCRNode:
    """메인 OCR 통합 노드 - VLM 기반 전체 파이프라인."""

    def __init__(self) -> None:
        """OCRNode 초기화."""
        self.image_processor = ImageProcessor()
        self.vlm_engine = VLMEngine()
        self.command_parser = create_command_parser()
        self.math_processor = MathPostProcessor()

    async def process(self, state: ProovyState) -> dict[str, Any]:
        """
        메인 OCR 처리 함수 - LangGraph 노드로 동작.

        Args:
            state: ProovyState 객체

        Returns:
            업데이트할 상태 딕셔너리 (ocr_text, ocr_confidence, tags)
        """
        start_time = time.time()

        try:
            # 1. raw_input에서 이미지 데이터 추출
            image_data = await self._extract_image_data(state.raw_input)

            # 이미지가 없으면 텍스트만 처리 (기존 preprocessor 동작)
            if not image_data:
                return await self._process_text_only(state)

            # 2. OCRRequest 생성
            ocr_request = OCRRequest(
                raw_input=state.raw_input,
                user_id=state.user_id,
                thread_id=state.thread_id,
                options=OCROptions(),  # 기본 옵션 사용
            )

            # 3. 전체 OCR 파이프라인 실행
            ocr_result = await self._process_full_pipeline(image_data, ocr_request)

            # 4. ProovyState 형태로 변환하여 반환
            return self._convert_to_state_update(ocr_result)

        except Exception as e:
            # 오류 발생 시 기본값으로 폴백
            return await self._handle_processing_error(e, state, start_time)

    async def _extract_image_data(self, raw_input: dict[str, Any]) -> bytes | None:
        """raw_input에서 이미지 데이터 추출."""
        # 이미지 필드들 확인
        image_fields = ["image", "images", "file", "upload", "photo"]

        for field in image_fields:
            if raw_input.get(field):
                try:
                    image_value = raw_input[field]

                    # 바이트 데이터인 경우
                    if isinstance(image_value, bytes):
                        return image_value

                    # base64 문자열인 경우
                    if isinstance(image_value, str):
                        import base64

                        try:
                            return base64.b64decode(image_value)
                        except Exception:
                            continue  # base64가 아닌 일반 텍스트

                    # 파일 경로인 경우 (동기 파일 읽기는 일반적으로 허용됨)
                    if isinstance(image_value, str) and image_value.endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp")
                    ):
                        try:
                            with open(image_value, "rb") as f:  # noqa: ASYNC230
                                return f.read()
                        except Exception:
                            continue

                except Exception:
                    # 해당 필드에서 이미지 추출 실패, 다음 필드 시도
                    continue

        return None

    async def _process_text_only(self, state: ProovyState) -> dict[str, Any]:
        """이미지가 없는 경우 텍스트만 처리 (기존 preprocessor 동작)."""
        import re

        problem = state.raw_input.get("problem", "")

        # @커맨드 파싱
        parsing_result = self.command_parser.parse(problem)

        # @커맨드 제거한 순수 텍스트
        clean_text = re.sub(r"@\S+", "", problem).strip()

        return {
            "ocr_text": clean_text or problem,
            "ocr_confidence": 1.0,  # 텍스트 입력은 100% 신뢰도
            "tags": parsing_result.tags,
        }

    async def _process_full_pipeline(
        self, image_data: bytes, request: OCRRequest
    ) -> OCRResult:
        """전체 OCR 파이프라인 실행."""
        start_time = time.time()

        try:
            # 1. 이미지 로드
            pil_image = await self._load_image(image_data)

            # 2. 이미지 전처리
            processing_options = ProcessingOptions(
                target_dpi=300,
                enhance_contrast=True,
                remove_noise=True,
                auto_rotate=True,
                binarize=True,
            )
            processed_image = await self.image_processor.process(pil_image, processing_options)

            # 3. VLM OCR 처리
            vlm_result = await self.vlm_engine.process_image(processed_image, request.options)

            # 4. 수학 표기법 후처리
            math_expressions = self.math_processor.process_text(vlm_result.raw_text)

            # 5. @커맨드 파싱
            command_result = self.command_parser.parse(vlm_result.raw_text)

            # 6. 언어 감지
            detected_language = await self.vlm_engine.detect_language(vlm_result.raw_text)

            # 7. 결과 통합
            processing_time = time.time() - start_time

            metadata = ProcessingMetadata(
                total_processing_time=processing_time,
                model_used=vlm_result.model_name,
                fallback_used=False,  # TODO: 실제 폴백 사용 여부 추적
                pages_processed=1,
                quality_score=vlm_result.confidence,
                language_detected=detected_language,
            )

            # 커맨드 태그로 변환
            from .models import CommandTag

            command_tags = [
                CommandTag(
                    command=tag,
                    original_text=tag,
                    confidence=command_result.confidence,
                    position=0,  # 간단히 0으로 설정
                )
                for tag in command_result.tags
            ]

            return OCRResult(
                extracted_text=vlm_result.raw_text,
                confidence=vlm_result.confidence,
                command_tags=command_tags,
                math_expressions=math_expressions,
                language=detected_language,
                processing_metadata=metadata,
            )

        except Exception as e:
            raise OCRError(
                f"OCR 파이프라인 실행 실패: {e!s}",
                {
                    "processing_time": time.time() - start_time,
                    "request": request.model_dump(),
                },
                "이미지 품질을 확인하거나 다른 이미지로 시도해보세요",
            ) from e

    async def _load_image(self, image_data: bytes) -> Image.Image:
        """이미지 데이터를 PIL Image로 로드."""
        try:
            image_stream = io.BytesIO(image_data)
            pil_image = Image.open(image_stream)

            # 이미지 검증
            if pil_image.width < 50 or pil_image.height < 50:
                raise ImageProcessingError(
                    "이미지가 너무 작습니다 (최소 50x50)",
                    {"size": (pil_image.width, pil_image.height)},
                    "더 큰 해상도의 이미지를 사용해주세요",
                )

            # RGBA를 RGB로 변환
            if pil_image.mode == "RGBA":
                background = Image.new("RGB", pil_image.size, (255, 255, 255))
                background.paste(pil_image, mask=pil_image.split()[-1])
                pil_image = background

            return pil_image

        except Exception as e:
            if isinstance(e, ImageProcessingError):
                raise

            raise FileConversionError(
                "이미지 로드 실패",
                {"data_length": len(image_data)},
                "지원되는 이미지 형식(.jpg, .png, .gif 등)인지 확인해주세요",
            ) from e

    def _convert_to_state_update(self, ocr_result: OCRResult) -> dict[str, Any]:
        """OCRResult를 ProovyState 업데이트 형태로 변환."""
        # 커맨드 태그에서 태그 문자열만 추출
        tags = [tag.command for tag in ocr_result.command_tags]

        return {
            "ocr_text": ocr_result.extracted_text,
            "ocr_confidence": ocr_result.confidence,
            "tags": tags,
        }

    async def _handle_processing_error(
        self, error: Exception, state: ProovyState, start_time: float
    ) -> dict[str, Any]:
        """처리 오류 발생 시 폴백 처리."""
        processing_time = time.time() - start_time

        # 오류 로깅 (실제 운영에서는 logger 사용)
        # logger.warning(f"OCR processing failed: {error}, fallback to text-only")

        # 오류 정보를 메타데이터로 포함 (향후 로깅에 사용 가능)
        error_info = {  # noqa: F841
            "error_type": type(error).__name__,
            "error_message": str(error),
            "processing_time": processing_time,
        }

        # 텍스트만 처리하여 폴백
        try:
            fallback_result = await self._process_text_only(state)
            # 오류 정보를 신뢰도에 반영
            fallback_result["ocr_confidence"] = max(
                fallback_result.get("ocr_confidence", 0.0) - 0.3, 0.1
            )
            return fallback_result

        except Exception:
            # 최종 폴백 - 빈 결과 반환
            return {
                "ocr_text": state.raw_input.get("problem", ""),
                "ocr_confidence": 0.1,
                "tags": [],
            }


# LangGraph 노드 함수
async def ocr_node(state: ProovyState) -> dict[str, Any]:
    """OCRNode를 LangGraph 노드로 래핑."""
    node = OCRNode()
    return await node.process(state)
