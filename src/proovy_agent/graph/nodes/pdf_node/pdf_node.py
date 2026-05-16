"""PDF 해설지 생성 LangGraph 노드."""

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import AnyMessage

from ...state import ProovyState as State
from .content_parser import ContentParser
from .exceptions import PDFError, handle_pdf_error
from .models import PDFConfig, PDFRequest, PDFResult
from .pdf_generator import PDFGenerator
from .template_renderer import TemplateRenderer


class PDFNode:
    """PDF 해설지 생성을 담당하는 LangGraph 노드."""

    def __init__(
        self,
        output_dir: str | Path = "outputs",
        template_dir: str | Path | None = None,
    ) -> None:
        """PDFNode 초기화.

        Args:
            output_dir: PDF 파일 저장 디렉토리
            template_dir: 템플릿 디렉토리 경로
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # PDF 생성 컴포넌트 초기화
        self.content_parser = ContentParser()
        self.template_renderer = TemplateRenderer(template_dir)
        self.pdf_generator = PDFGenerator(self.template_renderer)

    async def __call__(self, state: State) -> dict[str, Any]:
        """LangGraph 노드 실행 함수.

        Args:
            state: LangGraph State 인스턴스

        Returns:
            State 업데이트용 딕셔너리
        """
        try:
            start_time = time.time()

            # 1. State에서 PDF 생성 요청 추출
            pdf_request = await self._create_pdf_request_from_state(state)
            
            # 2. PDF 생성
            pdf_result = await self._generate_pdf(pdf_request)
            
            # 3. 파일로 저장
            if pdf_result.success:
                file_path = await self._save_pdf_to_file(pdf_result, pdf_request)
                pdf_result.file_path = str(file_path)
            
            # 4. 생성 시간 업데이트
            pdf_result.generation_time_ms = (time.time() - start_time) * 1000

            # 5. State에 결과 저장
            return await self._update_state_with_result(state, pdf_result)

        except Exception as e:
            # 에러 처리 및 State 업데이트
            error = handle_pdf_error(e)
            return await self._update_state_with_error(state, error)

    async def _create_pdf_request_from_state(self, state: State) -> PDFRequest:
        """State에서 PDFRequest 생성.

        Args:
            state: LangGraph State

        Returns:
            PDF 생성 요청 객체
        """
        # State.messages를 구조화된 섹션으로 파싱
        messages = getattr(state, "messages", [])
        if not messages:
            messages = []

        sections = await self.content_parser.parse_messages(messages)

        # 필수 메타데이터 확인
        thread_id = getattr(state, "thread_id", None)
        user_id = getattr(state, "user_id", None)
        
        if not thread_id:
            raise ValueError("thread_id가 State에 없습니다. PDF 생성에 필수입니다.")
        if not user_id:
            raise ValueError("user_id가 State에 없습니다. PDF 생성에 필수입니다.")

        # PDFRequest 생성
        request = PDFRequest(
            thread_id=thread_id,
            user_id=user_id, 
            content_sections=sections,
            request_id=f"pdf_{int(time.time() * 1000)}",  # 타임스탬프 기반 ID
            config=PDFConfig()  # 기본 설정 사용
        )

        return request

    async def _generate_pdf(self, request: PDFRequest) -> PDFResult:
        """PDF 생성 실행.

        Args:
            request: PDF 생성 요청

        Returns:
            PDF 생성 결과
        """
        try:
            result = await self.pdf_generator.generate_pdf_from_request(request)
            return result

        except Exception as e:
            # PDF 생성 실패 시 에러 PDFResult 반환
            error = handle_pdf_error(e)
            return PDFResult(
                pdf_data=b"",
                file_size=0,
                success=False,
                request_id=request.request_id,
                metadata={
                    "error": str(error),
                    "error_type": type(error).__name__,
                    "recovery_suggestion": getattr(error, "recovery_suggestion", "")
                }
            )

    async def _save_pdf_to_file(self, pdf_result: PDFResult, request: PDFRequest) -> Path:
        """PDF 데이터를 파일로 저장.

        Args:
            pdf_result: PDF 생성 결과
            request: 원본 요청 (파일명 생성용)

        Returns:
            저장된 파일 경로
        """
        try:
            # 파일명 생성 (thread_id, request_id 경로 안전화)
            safe_thread_id = re.sub(r'[^\w\-_]', '_', request.thread_id)[:50]
            safe_request_id = re.sub(r'[^\w\-_]', '_', str(request.request_id))[:30]
            filename = f"solution_{safe_thread_id}_{safe_request_id}.pdf"
            file_path = self.output_dir / filename

            # 비동기적으로 파일 저장
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                file_path.write_bytes,
                pdf_result.pdf_data
            )

            return file_path

        except Exception as e:
            # 파일 저장 실패는 PDF 생성 성공이므로 로깅만 하고 임시 경로 반환
            print(f"Warning: PDF 파일 저장 실패 ({e}), 메모리에만 보관됩니다.")
            return Path(f"/tmp/solution_{request.thread_id}.pdf")

    async def _update_state_with_result(self, state: State, result: PDFResult) -> dict[str, Any]:
        """PDF 생성 성공 시 State 업데이트.

        Args:
            state: 현재 State
            result: PDF 생성 결과

        Returns:
            State 업데이트용 딕셔너리
        """
        # PDF 생성 완료 메시지 추가
        success_message = self._create_success_message(result)
        
        # State 업데이트 (messages 추가, pdf_result 저장)
        updates = {
            "messages": getattr(state, "messages", []) + [success_message]
        }
        
        # PDF 관련 상태 추가 (있으면)
        if hasattr(state, "pdf_result") or not hasattr(state, "__annotations__"):
            updates["pdf_result"] = result
            
        return updates

    async def _update_state_with_error(self, state: State, error: PDFError) -> dict[str, Any]:
        """PDF 생성 실패 시 State 업데이트.

        Args:
            state: 현재 State  
            error: 발생한 에러

        Returns:
            State 업데이트용 딕셔너리
        """
        # 에러 메시지 생성
        error_message = self._create_error_message(error)
        
        # State 업데이트 (에러 메시지 추가)
        updates = {
            "messages": getattr(state, "messages", []) + [error_message]
        }
        
        # 에러 상태 추가 (있으면)
        if hasattr(state, "pdf_error") or not hasattr(state, "__annotations__"):
            updates["pdf_error"] = error
            
        return updates

    def _create_success_message(self, result: PDFResult) -> AnyMessage:
        """PDF 생성 성공 메시지 생성."""
        from langchain_core.messages import AIMessage
        
        content = f"✅ PDF 해설지가 성공적으로 생성되었습니다!\n"
        content += f"📄 파일 크기: {result.file_size_display}\n"
        content += f"⏱️ 생성 시간: {result.generation_time_ms:.0f}ms\n"
        
        if result.file_path:
            content += f"📁 저장 위치: {result.file_path}\n"
            
        if result.metadata:
            sections_count = result.metadata.get("sections_count", 0)
            if sections_count > 0:
                content += f"📝 해설 섹션: {sections_count}개\n"
                
        return AIMessage(
            content=content.strip(),
            metadata={
                "display": "pdf_success",
                "pdf_result": {
                    "file_path": result.file_path,
                    "file_size": result.file_size,
                    "download_url": result.download_url
                }
            }
        )

    def _create_error_message(self, error: PDFError) -> AnyMessage:
        """PDF 생성 에러 메시지 생성."""
        from langchain_core.messages import AIMessage
        
        content = f"❌ PDF 해설지 생성 중 오류가 발생했습니다.\n"
        content += f"🔍 원인: {error.message}\n"
        
        if hasattr(error, "recovery_suggestion"):
            content += f"💡 해결 방법: {error.recovery_suggestion}\n"
            
        return AIMessage(
            content=content.strip(),
            metadata={
                "display": "pdf_error",
                "error": {
                    "type": type(error).__name__,
                    "message": str(error),
                    "details": getattr(error, "details", {})
                }
            }
        )

    # 편의 메서드들
    async def generate_pdf_preview(
        self,
        state: State,
        image_format: str = "png"
    ) -> Path:
        """PDF 첫 페이지를 이미지로 미리보기 생성.

        Args:
            state: LangGraph State
            image_format: 이미지 포맷 ("png", "jpeg")

        Returns:
            생성된 미리보기 이미지 파일 경로

        Raises:
            PDFError: 미리보기 생성 실패 시
        """
        try:
            # PDF 요청 생성
            request = await self._create_pdf_request_from_state(state)
            
            # 미리보기 이미지 생성
            preview_filename = f"preview_{request.thread_id}.{image_format.lower()}"
            preview_path = self.output_dir / preview_filename
            
            result_path = await self.pdf_generator.generate_preview_image(
                request, preview_path, image_format
            )
            
            return result_path
            
        except Exception as e:
            raise handle_pdf_error(e) from e

    def get_available_templates(self) -> list[str]:
        """사용 가능한 PDF 템플릿 목록 반환."""
        return self.template_renderer.get_available_templates()

    def validate_configuration(self) -> bool:
        """PDF 노드 구성이 유효한지 검증."""
        try:
            # 템플릿 디렉토리 확인
            if not self.template_renderer.template_dir.exists():
                return False
                
            # 기본 템플릿 존재 확인
            return self.template_renderer.validate_template("solution.html")
            
        except Exception:
            return False


# LangGraph 노드 함수로 사용할 인스턴스
def create_pdf_node(output_dir: str = "outputs", template_dir: str | None = None) -> PDFNode:
    """PDFNode 인스턴스 생성 팩토리 함수.
    
    Args:
        output_dir: PDF 출력 디렉토리
        template_dir: 템플릿 디렉토리
        
    Returns:
        PDFNode 인스턴스
    """
    return PDFNode(output_dir=output_dir, template_dir=template_dir)