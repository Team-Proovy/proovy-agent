"""WeasyPrint 기반 PDF 생성기."""

import asyncio
from io import BytesIO
from pathlib import Path

from pdf2image import convert_from_bytes
from weasyprint import CSS, HTML

from .exceptions import PDFGenerationError, handle_pdf_error
from .models import PDFConfig, PDFRequest, PDFResult
from .template_renderer import TemplateRenderer


class PDFGenerator:
    """WeasyPrint를 사용한 PDF 생성기."""

    def __init__(self, template_renderer: TemplateRenderer | None = None) -> None:
        """PDF 생성기 초기화.

        Args:
            template_renderer: 템플릿 렌더러 인스턴스 (없으면 기본값 생성)
        """
        self.template_renderer = template_renderer or TemplateRenderer()

        # WeasyPrint 로깅 레벨 설정 (경고 메시지 최소화)
        import logging
        logging.getLogger("weasyprint").setLevel(logging.ERROR)
        logging.getLogger("fontTools").setLevel(logging.ERROR)

    async def generate_pdf_from_request(self, request: PDFRequest) -> PDFResult:
        """PDFRequest로부터 PDF 생성.

        Args:
            request: PDF 생성 요청 데이터

        Returns:
            PDF 생성 결과

        Raises:
            PDFGenerationError: PDF 생성 실패 시
        """
        try:
            # 템플릿 데이터 준비
            template_data = request.to_template_data()

            # HTML 렌더링 (CSS 인라인 포함)
            html_content = self.template_renderer.render_with_inline_css(
                template_name=request.config.template_name,
                data=template_data,
                css_file=request.config.css_file,
            )

            # HTML 유효성 검증
            if not self.validate_html_content(html_content):
                raise PDFGenerationError(
                    message="HTML 콘텐츠가 PDF 생성에 적합하지 않습니다",
                    details={"html_length": len(html_content)}
                )

            # PDF 생성
            pdf_bytes = await self._generate_pdf_bytes(html_content, request.config)

            # 결과 생성
            result = PDFResult(
                pdf_data=pdf_bytes,
                file_size=len(pdf_bytes),
                generation_time_ms=0,  # TODO: 실제 측정 추가
                request_id=request.request_id,
                success=True,
                metadata={
                    "template": request.config.template_name,
                    "sections_count": len(request.sections),
                    "has_images": any(s.content_type == "image" for s in request.sections),
                }
            )

            return result

        except Exception as e:
            error = handle_pdf_error(e)
            if isinstance(error, PDFGenerationError):
                raise error from e
            else:
                raise PDFGenerationError(
                    message=f"PDF 생성 중 예상치 못한 오류: {e!s}",
                    details={"request_id": request.request_id}
                ) from e

    async def _generate_pdf_bytes(self, html_content: str, config: PDFConfig) -> bytes:
        """HTML 콘텐츠를 PDF 바이트로 변환.

        Args:
            html_content: 인라인 CSS가 포함된 HTML 문자열
            config: PDF 설정

        Returns:
            PDF 파일 바이트 데이터

        Raises:
            PDFGenerationError: PDF 변환 실패 시
        """
        try:
            # WeasyPrint는 블로킹 I/O이므로 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            pdf_bytes = await loop.run_in_executor(
                None,
                self._create_pdf_sync,
                html_content,
                config
            )

            return pdf_bytes

        except Exception as e:
            raise PDFGenerationError(
                message=f"WeasyPrint PDF 변환 실패: {e!s}",
                details={"html_length": len(html_content)}
            ) from e

    async def generate_pdf_from_html_file(self, html_file_path: str | Path, output_path: str | Path) -> bool:
        """HTML 파일을 직접 PDF로 변환.
        
        Args:
            html_file_path: 입력 HTML 파일 경로
            output_path: 출력 PDF 파일 경로
            
        Returns:
            변환 성공 여부
        """
        try:
            html_file = Path(html_file_path)
            output_file = Path(output_path)
            
            if not html_file.exists():
                print(f"HTML 파일이 존재하지 않습니다: {html_file}")
                return False
                
            # HTML 파일을 직접 WeasyPrint로 변환
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._convert_html_file_sync,
                str(html_file),
                str(output_file)
            )
            
            return output_file.exists()
            
        except Exception as e:
            print(f"HTML → PDF 변환 실패: {e}")
            return False
    
    def _convert_html_file_sync(self, html_file_path: str, output_path: str) -> None:
        """동기적으로 HTML 파일을 PDF로 변환."""
        html_doc = HTML(filename=html_file_path)
        html_doc.write_pdf(output_path)

    def _create_pdf_sync(self, html_content: str, config: PDFConfig) -> bytes:
        """동기적으로 PDF 생성 (스레드 풀에서 실행).

        Args:
            html_content: HTML 콘텐츠
            config: PDF 설정

        Returns:
            PDF 바이트 데이터
        """
        try:
            # HTML 객체 생성
            html_doc = HTML(string=html_content, encoding="utf-8")

            # CSS 설정 (필요한 경우)
            css_list = []
            if config.additional_css:
                css_list.append(CSS(string=config.additional_css))

            # PDF 생성
            pdf_buffer = BytesIO()
            html_doc.write_pdf(
                target=pdf_buffer,
                stylesheets=css_list,
                # WeasyPrint 옵션
                zoom=1.0,
                presentational_hints=True,
                optimize_images=True,
            )

            return pdf_buffer.getvalue()

        except Exception as e:
            raise PDFGenerationError(
                message=f"WeasyPrint 내부 오류: {e!s}",
                details={"config": config.model_dump()}
            ) from e

    def save_pdf_to_file(self, pdf_data: bytes, file_path: Path) -> None:
        """PDF 데이터를 파일로 저장.

        Args:
            pdf_data: PDF 바이트 데이터
            file_path: 저장할 파일 경로

        Raises:
            PDFGenerationError: 파일 저장 실패 시
        """
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(pdf_data)

        except Exception as e:
            raise PDFGenerationError(
                message=f"PDF 파일 저장 실패: {e!s}",
                details={"file_path": str(file_path)}
            ) from e

    def validate_html_content(self, html_content: str) -> bool:
        """HTML 콘텐츠가 PDF 생성에 적합한지 검증.

        Args:
            html_content: 검증할 HTML 콘텐츠

        Returns:
            True if valid, False otherwise
        """
        try:
            # 기본적인 HTML 구조 확인
            required_tags = ["<html", "<head", "<body"]
            has_required_tags = all(tag in html_content.lower() for tag in required_tags)

            if not has_required_tags:
                return False

            # 길이 체크 (너무 짧거나 긴 경우)
            return not (len(html_content) < 100 or len(html_content) > 50_000_000)  # 50MB

        except Exception as e:
            # 예상치 못한 오류는 로깅 후 False 반환
            print(f"Warning: HTML validation failed due to unexpected error: {e}")
            return False

    async def generate_preview_image(
        self,
        request: PDFRequest,
        output_path: Path,
        image_format: str = "png",
    ) -> Path:
        """PDF의 첫 페이지를 이미지로 미리보기 생성.

        Args:
            request: PDF 생성 요청
            output_path: 이미지 저장 경로
            image_format: 이미지 포맷 ("png", "jpeg", "jpg")

        Returns:
            생성된 이미지 파일 경로

        Raises:
            PDFGenerationError: 미리보기 생성 실패 시
        """
        try:
            # HTML 렌더링
            template_data = request.to_template_data()
            html_content = self.template_renderer.render_with_inline_css(
                template_name=request.config.template_name,
                data=template_data,
                css_file=request.config.css_file,
            )

            # HTML 유효성 검증
            if not self.validate_html_content(html_content):
                raise PDFGenerationError(
                    message="HTML 콘텐츠가 미리보기 생성에 적합하지 않습니다",
                    details={"html_length": len(html_content)}
                )

            # 형식 정규화 (jpg → JPEG, png → PNG)
            normalized = image_format.lower()
            if normalized in ("jpg", "jpeg"):
                pil_format = "JPEG"
            elif normalized == "png":
                pil_format = "PNG"
            else:
                raise PDFGenerationError(
                    message=f"지원하지 않는 이미지 포맷: {image_format}",
                    details={"format": image_format},
                )

            # 별도 스레드에서 이미지 생성
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._create_preview_image_sync,
                html_content,
                output_path,
                pil_format,
            )

            return output_path

        except Exception as e:
            raise PDFGenerationError(
                message=f"PDF 미리보기 생성 실패: {e!s}",
                details={"output_path": str(output_path)}
            ) from e

    def _create_preview_image_sync(
        self,
        html_content: str,
        output_path: Path,
        pil_format: str,
    ) -> None:
        """동기적으로 미리보기 이미지 생성.

        Args:
            html_content: HTML 콘텐츠
            output_path: 출력 파일 경로
            pil_format: PIL 이미지 포맷 ("PNG", "JPEG")
        """
        try:
            # 1단계: HTML을 PDF로 변환
            html_doc = HTML(string=html_content, encoding="utf-8")
            pdf_bytes = html_doc.write_pdf()

            # 2단계: PDF 첫 페이지를 이미지로 변환 (pdf2image 사용)
            images = convert_from_bytes(
                pdf_bytes,
                first_page=1,
                last_page=1,
                dpi=150,
                fmt=pil_format,
            )

            if images:
                # 첫 번째 (그리고 유일한) 이미지 저장
                output_path.parent.mkdir(parents=True, exist_ok=True)
                images[0].save(output_path, pil_format)
            else:
                raise PDFGenerationError(
                    message="PDF에서 이미지 변환 결과가 없습니다",
                    details={"format": pil_format}
                )

        except Exception as e:
            raise PDFGenerationError(
                message=f"이미지 렌더링 실패: {e!s}",
                details={"format": pil_format}
            ) from e
