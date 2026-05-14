"""Jinja2 기반 PDF 템플릿 렌더링 시스템."""

import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import escape

from .exceptions import TemplateRenderingError, handle_pdf_error
from .models import ContentSection, TemplateData


class TemplateRenderer:
    """Jinja2 기반 HTML 템플릿 렌더링 시스템."""

    def __init__(self, template_dir: str | Path | None = None) -> None:
        """템플릿 렌더러 초기화.

        Args:
            template_dir: 템플릿 디렉토리 경로 (기본값: 현재 패키지의 templates 폴더)
        """
        if template_dir is None:
            template_dir = Path(__file__).parent / "templates"

        self.template_dir = Path(template_dir)

        # Jinja2 환경 설정
        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # 커스텀 필터 등록
        self._register_filters()

    def _register_filters(self) -> None:
        """Jinja2 커스텀 필터 등록."""

        @self.env.filter
        def format_math(content: str) -> str:
            """수식 내용을 HTML용으로 포맷팅 (기본 버전)."""
            # Phase 2에서 MathJax/KaTeX로 업그레이드 예정
            # 현재는 기본적인 치환만 수행
            replacements = {
                "≠": "&ne;",
                "≤": "&le;",
                "≥": "&ge;",
                "±": "&plusmn;",
                "∞": "&infin;",
                "∑": "&sum;",
                "∏": "&prod;",
                "∫": "&int;",
                "√": "&radic;",
                "∂": "&part;",
                "∇": "&nabla;",
            }

            for symbol, html_entity in replacements.items():
                content = content.replace(symbol, html_entity)

            return content

        @self.env.filter
        def section_icon(section_type: str) -> str:
            """섹션 타입별 아이콘 반환."""
            icons = {
                "text": "📝",
                "math": "🔢",
                "image": "📊",
                "code": "💻",
            }
            return icons.get(section_type, "📄")

        @self.env.filter
        def escape_newlines(content: str) -> str:
            """개행 문자를 HTML <br> 태그로 변환."""
            return content.replace("\n", "<br>")

        @self.env.filter
        def format_code_block(content: str) -> str:
            """코드 블록을 HTML pre/code 태그로 래핑."""
            if "```" in content:
                # 마크다운 코드 블록을 HTML로 변환
                parts = content.split("```")
                result = []
                for i, part in enumerate(parts):
                    if i % 2 == 1:  # 코드 블록 내부
                        result.append(f'<pre><code>{escape(part.strip())}</code></pre>')
                    else:  # 일반 텍스트
                        result.append(part)
                return "".join(result)
            return content

        @self.env.filter
        def image_to_base64(image_path: str) -> str:
            """이미지 파일을 base64로 변환하여 HTML에 임베딩."""
            try:
                image_file = Path(image_path).resolve()

                # 경로 순회 공격 방지: 허용된 디렉토리 내부인지 확인
                allowed_dirs = [
                    Path(__file__).parent.parent.parent.parent / "assets",  # assets 폴더
                    Path("/tmp"),  # 임시 파일
                    Path.cwd() / "uploads",  # 업로드 폴더
                ]

                is_safe_path = any(
                    str(image_file).startswith(str(allowed_dir.resolve()))
                    for allowed_dir in allowed_dirs
                    if allowed_dir.exists()
                )

                if not is_safe_path:
                    # 안전하지 않은 경로 접근 시도 로깅
                    print(f"Warning: Unsafe path access attempt: {image_path}")
                    return ""

                if not image_file.exists():
                    return ""

                # 파일 크기 제한 (10MB)
                file_size = image_file.stat().st_size
                if file_size > 10 * 1024 * 1024:
                    print(f"Warning: Image file too large: {file_size} bytes")
                    return ""

                with open(image_file, "rb") as f:
                    image_data = f.read()

                # MIME 타입 결정
                suffix = image_file.suffix.lower()
                mime_types = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".svg": "image/svg+xml",
                }
                mime_type = mime_types.get(suffix, "image/png")

                # base64 인코딩
                encoded = base64.b64encode(image_data).decode()
                return f"data:{mime_type};base64,{encoded}"

            except Exception as e:
                # 로깅 추가로 디버깅 개선
                print(f"Warning: Image processing failed for {image_path}: {e}")
                return ""  # 이미지 로드 실패 시 빈 문자열 반환

    def render_template(self, template_name: str, data: TemplateData) -> str:
        """템플릿을 렌더링하여 HTML 문자열 반환.

        Args:
            template_name: 사용할 템플릿 파일명 (예: "solution.html")
            data: 템플릿에 전달할 데이터

        Returns:
            렌더링된 HTML 문자열

        Raises:
            TemplateRenderingError: 템플릿 렌더링 실패 시
        """
        try:
            # 템플릿 로드
            template = self.env.get_template(template_name)

            # 템플릿 변수 준비
            template_vars = {
                "title": data.title,
                "thread_id": data.thread_id,
                "user_id": data.user_id,
                "sections": data.sections,
                "generated_at": data.generated_at,
                "formatted_date": data.formatted_date,
                # 추가 헬퍼 함수
                "has_math": self._has_math_content(data.sections),
                "has_images": self._has_image_content(data.sections),
                "section_count": len(data.sections),
            }

            # 템플릿 렌더링
            html = template.render(**template_vars)

            return html

        except Exception as e:
            raise handle_pdf_error(e) from e

    def _has_math_content(self, sections: list[ContentSection]) -> bool:
        """섹션들 중에 수식 내용이 있는지 확인."""
        return any(section.content_type == "math" for section in sections)

    def _has_image_content(self, sections: list[ContentSection]) -> bool:
        """섹션들 중에 이미지 내용이 있는지 확인."""
        return any(section.content_type == "image" for section in sections)

    def get_available_templates(self) -> list[str]:
        """사용 가능한 템플릿 목록 반환."""
        try:
            html_files = list(self.template_dir.glob("*.html"))
            return [f.name for f in html_files if not f.name.startswith("_")]
        except Exception:
            return ["solution.html"]  # 기본 템플릿

    def validate_template(self, template_name: str) -> bool:
        """템플릿 파일이 유효한지 검증."""
        try:
            template = self.env.get_template(template_name)
            # 기본 변수로 렌더링 시도
            test_data = TemplateData(
                title="테스트",
                thread_id="test",
                user_id="test",
                sections=[],
            )
            template.render(
                title=test_data.title,
                sections=test_data.sections,
                generated_at=test_data.generated_at,
            )
            return True
        except Exception:
            return False

    def render_inline_styles(self, css_content: str) -> str:
        """CSS 내용을 HTML style 태그로 래핑."""
        return f"<style>\n{css_content}\n</style>"

    def render_with_inline_css(
        self, template_name: str, data: TemplateData, css_file: str = "solution.css"
    ) -> str:
        """템플릿과 CSS를 함께 렌더링하여 인라인 스타일이 포함된 HTML 반환.

        Args:
            template_name: HTML 템플릿 파일명
            data: 템플릿 데이터
            css_file: CSS 파일명

        Returns:
            CSS가 인라인으로 포함된 HTML 문자열
        """
        try:
            # HTML 템플릿 렌더링
            html = self.render_template(template_name, data)

            # CSS 파일 로드
            css_path = self.template_dir / "styles" / css_file
            if css_path.exists():
                css_content = css_path.read_text(encoding="utf-8")
                inline_styles = self.render_inline_styles(css_content)

                # HTML head 섹션에 스타일 삽입
                if "</head>" in html:
                    html = html.replace("</head>", f"{inline_styles}\n</head>")
                else:
                    # head 태그가 없는 경우 body 앞에 추가
                    html = f"{inline_styles}\n{html}"

            return html

        except Exception as e:
            error = TemplateRenderingError(
                template_name=template_name,
                message=f"템플릿과 CSS 렌더링 실패: {e!s}",
                details={"template": template_name, "css": css_file}
            )
            raise error from e
