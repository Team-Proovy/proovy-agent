"""OCRNode - 메인 OCR 통합 노드 구현.

VLM 기반 이미지 텍스트 추출, @커맨드 파싱, 수학 표기법 후처리를 통합하여
LangGraph Preprocessor로 동작하는 메인 OCR 노드입니다.
"""

import asyncio
import base64
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
from .models import CommandTag, OCROptions, OCRRequest, OCRResult, ProcessingMetadata
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
        start_time = time.time()  # 처리 시작 시간 기록

        try:
            # 1. raw_input에서 이미지 데이터 추출
            image_data = self._extract_image_data(state.raw_input)

            # 이미지가 없으면 텍스트만 처리 (기존 preprocessor 동작)
            if not image_data:
                return self._process_text_only(state)

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

    def _extract_image_data(self, raw_input: dict[str, Any]) -> bytes | None:
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

                    # 문자열 입력 처리 (base64 또는 data URL)
                    if isinstance(image_value, str):

                        # data URL 형태인 경우 (data:image/png;base64,...)
                        if image_value.startswith("data:image/") and ";base64," in image_value:
                            try:
                                # data URL에서 base64 부분만 추출
                                base64_data = image_value.split(";base64,", 1)[1]
                                return base64.b64decode(base64_data)
                            except Exception:
                                pass  # data URL 처리 실패, 다른 방법 시도

                        # 순수 base64 문자열인 경우
                        try:
                            return base64.b64decode(image_value)
                        except Exception:
                            pass  # base64 디코드 실패, 파일 경로로 시도

                        # 보안상 파일 경로 처리는 제거
                        # 프로덕션에서는 업로드된 이미지만 처리하는 것이 안전
                        continue

                except Exception:
                    # 해당 필드에서 이미지 추출 실패, 다음 필드 시도
                    continue

        return None

    def _process_text_only(self, state: ProovyState) -> dict[str, Any]:
        """이미지가 없는 경우 텍스트만 처리 (기존 preprocessor 동작)."""

        problem = state.raw_input.get("problem", "")

        # @커맨드 파싱 (CommandParser 사용)
        parsing_result = self.command_parser.parse(problem)

        # CommandParser detected_patterns에서 원문 커맨드 추출
        original_tags = []
        clean_text = problem
        for pattern in parsing_result.detected_patterns:
            if pattern.startswith("@command: "):
                original_command = pattern.replace("@command: ", "").strip()
                original_tags.append(original_command)
                # 실제 원문 커맨드를 텍스트에서 제거 (멀티워드 커맨드 지원)
                clean_text = clean_text.replace(original_command, "").strip()

        # CommandParser가 패턴을 찾지 못한 경우에는 빈 태그 반환
        # regex fallback 제거 - CommandParser 결과만 신뢰
        if not original_tags:
            original_tags = []

        return {
            "ocr_text": clean_text or problem,
            "ocr_confidence": 1.0,  # 텍스트 입력은 100% 신뢰도
            "tags": original_tags,  # 기존 preprocessor 호환성 유지
        }

    async def _process_full_pipeline(
        self, image_data: bytes, request: OCRRequest
    ) -> OCRResult:
        """전체 OCR 파이프라인 실행."""
        start_time = time.time()

        try:
            # 1. 이미지 로드
            pil_image = self._load_image(image_data)

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

            # VLMResult에서 폴백 사용 여부 확인
            fallback_used = hasattr(vlm_result, 'fallback_used') and vlm_result.fallback_used

            metadata = ProcessingMetadata(
                total_processing_time=processing_time,
                model_used=vlm_result.model_name,
                fallback_used=fallback_used,
                pages_processed=1,
                quality_score=vlm_result.confidence,
                language_detected=detected_language,
            )

            # 커맨드 태그로 변환 (CommandParser detected_patterns 사용)

            # CommandParser detected_patterns에서 원본 @커맨드 추출
            # detected_patterns가 실제 원문 @커맨드를 포함한다고 가정
            original_commands = []
            for pattern in command_result.detected_patterns:
                if pattern.startswith("@command: "):
                    original_command = pattern.replace("@command: ", "").strip()
                    original_commands.append(original_command)

            # CommandTag 생성 - 안전한 매핑 방식 사용
            command_tags = []
            # original_commands를 기준으로 CommandTag 생성
            # tags 매핑은 단순화하여 안전성 확보
            for idx, original_command in enumerate(original_commands):
                # 태그 매핑을 단순화 - 인덱스 충돌 방지
                if idx < len(command_result.tags):
                    tag = command_result.tags[idx]
                else:
                    # 매핑 실패시 원문에서 추정
                    if original_command.startswith("@"):
                        tag = original_command[1:].split()[0] if " " in original_command else original_command[1:]
                    else:
                        tag = "unknown"

                command_tags.append(CommandTag(
                    command=tag,
                    original_text=original_command,
                    confidence=command_result.confidence,
                    position=0,  # 위치 정보는 단순화
                ))

            # @커맨드 제거된 텍스트로 통일성 유지
            # detected_patterns에서 실제 원문 커맨드 제거 (멀티워드 커맨드 지원)
            clean_text = vlm_result.raw_text
            for original_command in original_commands:
                clean_text = clean_text.replace(original_command, "").strip()
            final_text = clean_text or vlm_result.raw_text

            return OCRResult(
                extracted_text=final_text,  # @커맨드 제거된 텍스트
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

    def _load_image(self, image_data: bytes) -> Image.Image:
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
        # 기존 preprocessor 호환성을 위해 @원문 형태로 변환
        original_tags = [tag.original_text for tag in ocr_result.command_tags]

        return {
            "ocr_text": ocr_result.extracted_text,
            "ocr_confidence": ocr_result.confidence,
            "tags": original_tags,  # 기존 preprocessor 호환성 유지
        }

    async def _handle_processing_error(
        self, error: Exception, state: ProovyState, start_time: float
    ) -> dict[str, Any]:
        """처리 오류 발생 시 폴백 처리."""
        # 오류 로깅 (실제 운영에서는 logger 사용)
        # processing_time = time.time() - start_time
        # logger.warning(f"OCR processing failed: {error}, fallback to text-only")

        # 텍스트만 처리하여 폴백
        try:
            fallback_result = self._process_text_only(state)
            # 오류 정보를 신뢰도에 반영
            fallback_result["ocr_confidence"] = max(
                fallback_result.get("ocr_confidence", 0.0) - 0.3, 0.1
            )
            return fallback_result

        except Exception:
            # 최종 폴백 - 다른 텍스트 필드 확인
            text_fields = ["problem", "text", "content", "description"]
            fallback_text = ""

            for field in text_fields:
                if state.raw_input.get(field):
                    fallback_text = str(state.raw_input[field])
                    break

            return {
                "ocr_text": fallback_text or "이미지 처리 실패",
                "ocr_confidence": 0.1,
                "tags": [],
            }


# 모듈 레벨 싱글톤 (동시성 안전)
_ocr_node_instance: OCRNode | None = None
_ocr_node_lock = asyncio.Lock()


async def _get_ocr_node() -> OCRNode:
    """OCRNode 싱글톤 인스턴스 반환 (동시성 안전)."""
    global _ocr_node_instance
    async with _ocr_node_lock:
        if _ocr_node_instance is None:
            _ocr_node_instance = OCRNode()
    return _ocr_node_instance


# LangGraph 노드 함수
async def ocr_node(state: ProovyState) -> dict[str, Any]:
    """OCRNode를 LangGraph 노드로 래핑."""
    node = await _get_ocr_node()  # 동시성 안전한 싱글톤
    return await node.process(state)
