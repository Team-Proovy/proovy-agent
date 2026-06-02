"""Gemini 2.0 Flash 기반 OCR 엔진 구현."""

import asyncio
import base64
import os
import time

import aiohttp
from pydantic import BaseModel, Field

from .exceptions import (
    LanguageDetectionError,
    OCRTimeoutError,
    QualityThresholdError,
    VLMProcessingError,
)
from .models import (
    OCROptions,
    ProcessedImage,
    VLMResult,
)


class VLMPromptTemplate(BaseModel):
    """VLM 프롬프트 템플릿."""

    system_prompt: str = Field(description="시스템 프롬프트")
    user_prompt_template: str = Field(description="사용자 프롬프트 템플릿")
    math_mode_addition: str = Field(description="수학 모드 추가 프롬프트")
    command_mode_addition: str = Field(description="커맨드 모드 추가 프롬프트")


class VLMConfig(BaseModel):
    """VLM 설정."""

    model_name: str = Field(description="모델명")
    api_endpoint: str = Field(description="API 엔드포인트")
    max_tokens: int = Field(default=2048, description="최대 토큰 수")
    temperature: float = Field(default=0.1, description="온도")
    timeout_seconds: float = Field(default=30.0, description="타임아웃")


class VLMEngine:
    """Gemini 2.0 Flash 기반 OCR 엔진."""

    def __init__(self):
        """VLM 엔진 초기화."""
        self.prompt_templates = self._initialize_prompt_templates()
        self.model_configs = self._initialize_model_configs()

    def _initialize_prompt_templates(self) -> dict[str, VLMPromptTemplate]:
        """VLM 프롬프트 템플릿 초기화."""

        # 기본 OCR 프롬프트 (한국어/영어 혼재 환경에 최적화)
        base_system = """You are an expert OCR system specialized in Korean and English mixed content.
Your task is to accurately extract ALL text from images with perfect precision.

CRITICAL REQUIREMENTS:
1. Extract EVERY visible text character without omission
2. Maintain exact formatting, spacing, and structure
3. Handle Korean, English, numbers, and symbols accurately
4. Preserve mathematical expressions and special characters
5. Return ONLY the extracted text - no explanations or commentary"""

        base_user = """Extract ALL text from this image with perfect accuracy.
Target language preference: {target_language}

Instructions:
- Transcribe everything you see
- Maintain original layout and formatting
- Don't skip any text, headers, captions, or labels
- Be extremely precise with Korean characters
- Preserve spacing and line breaks"""

        # 수학 모드 프롬프트 강화
        math_addition = """
MATHEMATICS MODE ACTIVE:
- This image contains mathematical expressions, equations, or formulas
- Convert mathematical symbols accurately: ² → ^2, ∫ → integral, √ → sqrt()
- Preserve equation structure and mathematical notation
- Use standard LaTeX-compatible notation when possible
- Be especially careful with fractions, exponents, and complex expressions"""

        # 커맨드 모드 프롬프트
        command_addition = """
COMMAND PARSING MODE ACTIVE:
- Look for @command patterns (e.g., @solve, @explain, @calculate, @show)
- These @ symbols are CRITICAL - preserve them exactly
- @commands may appear anywhere in the text
- Transcribe @commands with 100% accuracy
- Do not modify or interpret @commands - just extract them exactly"""

        return {
            "default": VLMPromptTemplate(
                system_prompt=base_system,
                user_prompt_template=base_user,
                math_mode_addition=math_addition,
                command_mode_addition=command_addition
            )
        }

    def _initialize_model_configs(self) -> dict[str, VLMConfig]:
        """모델 설정 초기화."""
        return {
            "flash": VLMConfig(
                model_name="gemini-2.0-flash-exp",
                api_endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",
                max_tokens=4096,
                temperature=0.0,  # 정확성을 위해 0으로 설정
                timeout_seconds=30.0
            ),
            "gpt4o-mini": VLMConfig(
                model_name="gpt-4o-mini",
                api_endpoint="https://api.openai.com/v1/chat/completions",
                max_tokens=4096,
                temperature=0.0,
                timeout_seconds=45.0
            )
        }

    async def process_image(
        self,
        image: ProcessedImage,
        options: OCROptions
    ) -> VLMResult:
        """이미지를 VLM으로 처리."""

        # Gemini 2.0 Flash로 먼저 시도
        try:
            result = await self._process_with_model(
                image, options, "flash"
            )

            # 품질 검증
            if result.confidence >= options.quality_threshold:
                return result
            else:
                # 품질이 낮으면 폴백 시도
                if options.fallback_model and options.fallback_model != "flash":
                    fallback_result = await self._process_with_model(
                        image, options, options.fallback_model
                    )

                    if fallback_result.confidence >= options.quality_threshold:
                        return fallback_result

                    # 두 결과 중 더 좋은 것 선택
                    return result if result.confidence > fallback_result.confidence else fallback_result
                else:
                    # 폴백이 없거나 동일 모델이면 결과 그대로 반환
                    if result.confidence < options.quality_threshold:
                        raise QualityThresholdError(
                            options.quality_threshold,
                            result.confidence,
                            "OCR 결과가 품질 기준에 미달합니다"
                        )
                    return result

        except VLMProcessingError as e:
            if not e.is_recoverable:
                raise

            # 복구 가능한 오류면 폴백 시도
            if options.fallback_model and options.fallback_model != "flash":
                try:
                    return await self._process_with_model(
                        image, options, options.fallback_model
                    )
                except Exception as fallback_error:
                    # 폴백도 실패하면 원래 오류 재발생
                    raise e from fallback_error
            else:
                raise

    async def _process_with_model(
        self,
        image: ProcessedImage,
        options: OCROptions,
        model_name: str
    ) -> VLMResult:
        """특정 모델로 이미지 처리."""

        if model_name not in self.model_configs:
            raise VLMProcessingError(
                model_name,
                f"지원하지 않는 모델: {model_name}",
                {"available_models": list(self.model_configs.keys())},
                is_recoverable=False
            )

        config = self.model_configs[model_name]
        start_time = time.time()

        try:
            # 타임아웃 설정
            timeout = min(config.timeout_seconds, options.max_processing_time)

            # 모델별 처리
            if model_name == "flash":
                result = await asyncio.wait_for(
                    self._process_with_gemini(image, options, config),
                    timeout=timeout
                )
            elif model_name == "gpt4o-mini":
                result = await asyncio.wait_for(
                    self._process_with_gpt4o(image, options, config),
                    timeout=timeout
                )
            else:
                raise VLMProcessingError(
                    model_name,
                    f"구현되지 않은 모델: {model_name}",
                    is_recoverable=False
                )

            processing_time = time.time() - start_time
            result.processing_time = processing_time

            return result

        except TimeoutError as timeout_err:
            raise OCRTimeoutError(
                timeout,
                f"{model_name} 모델 처리 시간 초과",
                {"model": model_name, "timeout": timeout}
            ) from timeout_err
        except Exception as e:
            if isinstance(e, (VLMProcessingError, OCRTimeoutError)):
                raise
            raise VLMProcessingError(
                model_name,
                f"모델 처리 중 오류: {e!s}",
                {"processing_time": time.time() - start_time}
            ) from e

    async def _process_with_gemini(
        self,
        image: ProcessedImage,
        options: OCROptions,
        config: VLMConfig
    ) -> VLMResult:
        """Gemini 2.0 Flash로 처리."""

        # 프롬프트 생성
        prompt = self._build_prompt(options)

        # 이미지 인코딩
        image_data = base64.b64encode(image.image_data).decode()

        # API 요청 데이터
        request_data = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": f"image/{image.format}",
                            "data": image_data
                        }
                    }
                ]
            }],
            "generationConfig": {
                "maxOutputTokens": config.max_tokens,
                "temperature": config.temperature,
                "candidateCount": 1
            }
        }

        # API 키 가져오기
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY")
        if not api_key:
            raise VLMProcessingError(
                config.model_name,
                "Gemini API 키가 설정되지 않았습니다",
                {"env_vars": ["GEMINI_API_KEY", "GOOGLE_AI_API_KEY"]},
                is_recoverable=False
            )

        # API 호출
        async with aiohttp.ClientSession() as session:
            headers = {
                "Content-Type": "application/json"
            }

            # API 키를 URL 파라미터로 추가
            url_with_key = f"{config.api_endpoint}?key={api_key}"

            async with session.post(
                url_with_key,
                json=request_data,
                headers=headers
            ) as response:

                if response.status != 200:
                    error_text = await response.text()

                    # 특정 오류 코드에 따른 복구 가능성 판단
                    is_recoverable = response.status in [429, 503, 502]  # Rate limit, service issues

                    raise VLMProcessingError(
                        config.model_name,
                        f"Gemini API 오류: {response.status}",
                        {"status_code": response.status, "response": error_text},
                        is_recoverable=is_recoverable
                    )

                result_data = await response.json()

                # 응답 파싱
                if "candidates" not in result_data or not result_data["candidates"]:
                    raise VLMProcessingError(
                        config.model_name,
                        "Gemini 응답에 후보가 없습니다",
                        {"response": result_data}
                    )

                candidate = result_data["candidates"][0]

                # 안전성 필터링으로 차단된 경우
                if "content" not in candidate:
                    if "finishReason" in candidate and candidate["finishReason"] == "SAFETY":
                        raise VLMProcessingError(
                            config.model_name,
                            "Gemini 안전성 필터로 인한 처리 실패",
                            {"finish_reason": candidate.get("finishReason"), "safety_ratings": candidate.get("safetyRatings")},
                            is_recoverable=True  # 다른 이미지나 프롬프트로 재시도 가능
                        )
                    else:
                        raise VLMProcessingError(
                            config.model_name,
                            "Gemini 응답 형식 오류",
                            {"candidate": candidate}
                        )

                if "parts" not in candidate["content"]:
                    raise VLMProcessingError(
                        config.model_name,
                        "Gemini 응답에 parts가 없습니다",
                        {"content": candidate["content"]}
                    )

                # 텍스트 추출
                extracted_text = ""
                for part in candidate["content"]["parts"]:
                    if "text" in part:
                        extracted_text += part["text"]

                if not extracted_text.strip():
                    raise VLMProcessingError(
                        config.model_name,
                        "Gemini가 빈 텍스트를 반환했습니다",
                        {"candidate": candidate},
                        is_recoverable=True
                    )

                # 신뢰도 계산
                confidence = self._calculate_confidence(extracted_text, image)

                # 토큰 사용량
                token_usage = {}
                if "usageMetadata" in result_data:
                    usage = result_data["usageMetadata"]
                    token_usage = {
                        "input": usage.get("promptTokenCount", 0),
                        "output": usage.get("candidatesTokenCount", 0),
                        "total": usage.get("totalTokenCount", 0)
                    }

                return VLMResult(
                    model_name=config.model_name,
                    raw_text=extracted_text.strip(),
                    confidence=confidence,
                    processing_time=0.0,  # 나중에 설정됨
                    token_usage=token_usage
                )

    async def _process_with_gpt4o(
        self,
        image: ProcessedImage,
        options: OCROptions,
        config: VLMConfig
    ) -> VLMResult:
        """GPT-4o mini로 처리 (폴백용)."""

        # 프롬프트 생성
        prompt = self._build_prompt(options)

        # 이미지 인코딩
        image_data = base64.b64encode(image.image_data).decode()

        # API 요청 데이터
        request_data = {
            "model": config.model_name,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{image.format};base64,{image_data}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ]
        }

        # API 키 가져오기
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise VLMProcessingError(
                config.model_name,
                "OpenAI API 키가 설정되지 않았습니다",
                {"env_vars": ["OPENAI_API_KEY"]},
                is_recoverable=False
            )

        # API 호출
        async with aiohttp.ClientSession() as session:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            async with session.post(
                config.api_endpoint,
                json=request_data,
                headers=headers
            ) as response:

                if response.status != 200:
                    error_text = await response.text()

                    # 특정 오류 코드에 따른 복구 가능성 판단
                    is_recoverable = response.status in [429, 503, 502]

                    raise VLMProcessingError(
                        config.model_name,
                        f"OpenAI API 오류: {response.status}",
                        {"status_code": response.status, "response": error_text},
                        is_recoverable=is_recoverable
                    )

                result_data = await response.json()

                # 응답 파싱
                if "choices" not in result_data or not result_data["choices"]:
                    raise VLMProcessingError(
                        config.model_name,
                        "OpenAI 응답에 choices가 없습니다",
                        {"response": result_data}
                    )

                choice = result_data["choices"][0]
                if "message" not in choice or "content" not in choice["message"]:
                    raise VLMProcessingError(
                        config.model_name,
                        "OpenAI 응답 형식 오류",
                        {"choice": choice}
                    )

                extracted_text = choice["message"]["content"]

                if not extracted_text or not extracted_text.strip():
                    raise VLMProcessingError(
                        config.model_name,
                        "OpenAI가 빈 텍스트를 반환했습니다",
                        {"choice": choice},
                        is_recoverable=True
                    )

                # 신뢰도 계산
                confidence = self._calculate_confidence(extracted_text, image)

                # 토큰 사용량
                token_usage = {}
                if "usage" in result_data:
                    usage = result_data["usage"]
                    token_usage = {
                        "input": usage.get("prompt_tokens", 0),
                        "output": usage.get("completion_tokens", 0),
                        "total": usage.get("total_tokens", 0)
                    }

                return VLMResult(
                    model_name=config.model_name,
                    raw_text=extracted_text.strip(),
                    confidence=confidence,
                    processing_time=0.0,
                    token_usage=token_usage
                )

    def _build_prompt(self, options: OCROptions) -> str:
        """OCR 프롬프트 구성."""
        template = self.prompt_templates["default"]

        # 기본 프롬프트
        prompt = template.system_prompt + "\n\n"
        prompt += template.user_prompt_template.format(
            target_language=options.target_language
        )

        # 수학 모드 추가
        if options.enable_math_mode:
            prompt += "\n" + template.math_mode_addition

        # 커맨드 모드 추가
        if options.enable_command_parsing:
            prompt += "\n" + template.command_mode_addition

        return prompt

    def _calculate_confidence(self, text: str, image: ProcessedImage) -> float:
        """신뢰도 계산."""
        if not text or not text.strip():
            return 0.0

        confidence = 0.6  # 기본값 (VLM이므로 높게 설정)

        # 텍스트 길이 기반 조정
        text_length = len(text.strip())
        if text_length > 200:
            confidence += 0.2
        elif text_length > 100:
            confidence += 0.15
        elif text_length > 50:
            confidence += 0.1
        elif text_length < 10:
            confidence -= 0.2  # 너무 짧으면 감점

        # 이미지 품질 기반 조정
        if image.dpi >= 400:
            confidence += 0.15
        elif image.dpi >= 300:
            confidence += 0.1
        elif image.dpi >= 200:
            confidence += 0.05
        else:
            confidence -= 0.1  # 저해상도 감점

        # 전처리 적용 여부
        preprocessing_bonus = 0
        if "adaptive_threshold" in image.preprocessing_applied:
            preprocessing_bonus += 0.08
        if "contrast_enhancement" in image.preprocessing_applied:
            preprocessing_bonus += 0.05
        if "rotation_correction" in image.preprocessing_applied:
            preprocessing_bonus += 0.05
        if "noise_removal" in image.preprocessing_applied:
            preprocessing_bonus += 0.07

        confidence += min(preprocessing_bonus, 0.2)  # 최대 0.2 보너스

        # 한글/영어 혼재 패턴 분석
        korean_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7af')
        english_chars = sum(1 for c in text if c.isascii() and c.isalpha())
        total_chars = korean_chars + english_chars

        if total_chars > 0:
            # 한글과 영어가 적절히 섞여있으면 보너스 (한국 교육 자료 특성)
            korean_ratio = korean_chars / total_chars
            if 0.3 <= korean_ratio <= 0.7:  # 적절한 혼재
                confidence += 0.05

        # 특수 문자/수학 기호 처리 품질
        math_symbols = sum(1 for c in text if c in "∫∑√±×÷∞≤≥≠∂∆")  # noqa: RUF001
        if math_symbols > 0 and text_length > 0:
            # 수학 기호가 있으면서 적절한 길이라면 수학 처리 성공으로 간주
            math_ratio = math_symbols / text_length
            if math_ratio < 0.1:  # 적절한 수학 기호 비율
                confidence += 0.1
            else:
                confidence -= 0.05  # 너무 많으면 오인식 가능성

        # @ 커맨드 패턴 검증
        import re
        command_pattern = r'@[a-zA-Z가-힣][a-zA-Z가-힣0-9_]*'
        commands = re.findall(command_pattern, text)
        if commands:
            # @커맨드가 올바르게 인식되었으면 보너스
            confidence += 0.1

        return min(max(confidence, 0.0), 1.0)

    async def detect_language(self, text: str) -> str:
        """텍스트 언어 감지."""
        if not text or not text.strip():
            raise LanguageDetectionError(
                "빈 텍스트로 인한 언어 감지 실패",
                {"text_length": len(text)}
            )

        # 한글, 영어, 기타 문자 비율 계산
        korean_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7af')
        english_chars = sum(1 for c in text if c.isascii() and c.isalpha())
        other_chars = sum(1 for c in text if c.isalpha() and not ('\uac00' <= c <= '\ud7af') and not c.isascii())

        total_alpha_chars = korean_chars + english_chars + other_chars

        if total_alpha_chars == 0:
            return "unknown"  # 숫자나 기호만 있는 경우

        korean_ratio = korean_chars / total_alpha_chars
        english_ratio = english_chars / total_alpha_chars

        if korean_ratio > 0.6:
            return "ko"
        elif english_ratio > 0.7:
            return "en"
        elif korean_ratio > 0.2 and english_ratio > 0.2:
            return "mixed"  # 한영 혼재
        elif other_chars > total_alpha_chars * 0.3:
            return "other"
        else:
            # 더 많은 비율을 차지하는 언어 선택
            return "ko" if korean_ratio > english_ratio else "en"

    async def process_batch(
        self,
        images: list[ProcessedImage],
        options: OCROptions
    ) -> list[VLMResult]:
        """배치 처리 (병렬 처리로 성능 최적화)."""

        # 배치 크기 제한 (API 제한 고려)
        batch_size = 5
        all_results = []

        for i in range(0, len(images), batch_size):
            batch = images[i:i + batch_size]

            # 배치 내 병렬 처리
            tasks = [
                self.process_image(image, options)
                for image in batch
            ]

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # 예외를 실패 결과로 변환
            for _j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    # 실패한 경우 기본 VLMResult 생성
                    all_results.append(
                        VLMResult(
                            model_name="failed",
                            raw_text="",
                            confidence=0.0,
                            processing_time=0.0,
                            token_usage={}
                        )
                    )
                else:
                    all_results.append(result)

            # API 제한 고려한 간격 조정
            if i + batch_size < len(images):
                await asyncio.sleep(0.1)  # 100ms 간격

        return all_results

