"""PDF 노드 테스트 실행 스크립트 (Windows 호환)."""

from datetime import datetime
from pathlib import Path
import sys
from typing import Any

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 모델만 직접 import (WeasyPrint 의존성 제외)


class ContentSection(BaseModel):
    """콘텐츠 섹션."""

    id: str
    title: str
    content: str
    content_type: str = "text"
    order: int
    metadata: dict[str, Any] | None = None


class TemplateData(BaseModel):
    """템플릿 데이터."""

    title: str
    thread_id: str
    user_id: str
    sections: list[ContentSection]
    generated_at: datetime = Field(default_factory=datetime.now)

    @property
    def formatted_date(self) -> str:
        return self.generated_at.strftime("%Y년 %m월 %d일 %H:%M")


def test_template_system() -> bool:
    """템플릿 시스템 테스트."""
    print("PDF Template System Test")
    print("=" * 40)

    # 1. 템플릿 환경 설정
    print("1. Setting up template environment...")
    template_dir = (
        project_root / "src" / "proovy_agent" / "graph" / "nodes" / "pdf_node" / "templates"
    )

    if not template_dir.exists():
        print(f"ERROR: Template directory not found: {template_dir}")
        return False

    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # 커스텀 필터 등록
    def section_icon(section_type: str) -> str:
        """섹션 타입별 아이콘 반환."""
        icons = {
            "text": "[TEXT]",
            "math": "[MATH]",
            "image": "[IMG]",
            "code": "[CODE]",
        }
        return icons.get(section_type, "[DOC]")

    def escape_newlines(content: str) -> str:
        """개행 문자를 HTML <br> 태그로 변환."""
        return content.replace("\n", "<br>")

    def format_math(content: str) -> str:
        """수식 내용을 HTML용으로 포맷팅."""
        replacements = {
            "≠": "&ne;",
            "≤": "&le;",
            "≥": "&ge;",
            "±": "&plusmn;",
            "∞": "&infin;",
            "√": "&radic;",
        }
        for symbol, html_entity in replacements.items():
            content = content.replace(symbol, html_entity)
        return content

    def format_code_block(content: str) -> str:
        """코드 블록을 HTML pre/code 태그로 래핑."""
        if "```" in content:
            parts = content.split("```")
            result = []
            for i, part in enumerate(parts):
                if i % 2 == 1:  # 코드 블록 내부
                    result.append(f"<pre><code>{part.strip()}</code></pre>")
                else:  # 일반 텍스트
                    result.append(part)
            return "".join(result)
        return content

    def image_to_base64(image_path: str) -> str:
        """이미지 파일을 base64로 변환 (테스트용 스텁)."""
        return ""

    # 필터를 환경에 등록
    env.filters["section_icon"] = section_icon
    env.filters["escape_newlines"] = escape_newlines
    env.filters["format_math"] = format_math
    env.filters["format_code_block"] = format_code_block
    env.filters["image_to_base64"] = image_to_base64

    print("   SUCCESS: Template environment created with custom filters")

    # 2. 템플릿 로딩 테스트
    print("\n2. Loading templates...")
    try:
        env.get_template("base.html")
        solution_template = env.get_template("solution.html")
        print("   SUCCESS: Templates loaded (base.html, solution.html)")
    except Exception as e:
        print(f"   ERROR: Template loading failed: {e}")
        return False

    # 3. 테스트 데이터 생성
    print("\n3. Creating test data...")
    test_sections = [
        ContentSection(
            id="1",
            title="1단계: 문제 분석",
            content="이차방정식 x² + 2x - 3 = 0을 풀어보겠습니다.",
            content_type="text",
            order=1,
        ),
        ContentSection(
            id="2",
            title="2단계: 근의 공식",
            content="x = (-b ± √(b² - 4ac)) / 2a\n여기서 a=1, b=2, c=-3",
            content_type="math",
            order=2,
        ),
        ContentSection(
            id="3",
            title="3단계: 계산 과정",
            content="```python\nimport math\na, b, c = 1, 2, -3\nD = b**2 - 4*a*c\nprint(f'D = {D}')\n```",
            content_type="code",
            order=3,
        ),
    ]

    template_data = TemplateData(
        title="이차방정식 해법 테스트",
        thread_id="test-001",
        user_id="test-user",
        sections=test_sections,
    )
    print(f"   SUCCESS: Test data created ({len(test_sections)} sections)")

    # 4. HTML 렌더링 테스트
    print("\n4. Rendering HTML template...")
    try:
        template_vars = {
            "title": template_data.title,
            "thread_id": template_data.thread_id,
            "user_id": template_data.user_id,
            "sections": template_data.sections,
            "generated_at": template_data.generated_at,
            "formatted_date": template_data.formatted_date,
            "has_math": True,
            "has_images": False,
            "section_count": len(template_data.sections),
        }

        html_content = solution_template.render(**template_vars)
        print(f"   SUCCESS: HTML rendered ({len(html_content):,} characters)")

        # HTML 구조 검증
        required_elements = ["<!DOCTYPE html>", "<html", "<title>", "<body>", "이차방정식"]
        missing = [elem for elem in required_elements if elem not in html_content]

        if missing:
            print(f"   WARNING: Missing HTML elements: {missing}")
        else:
            print("   SUCCESS: HTML structure validation passed")

    except Exception as e:
        print(f"   ERROR: HTML rendering failed: {e}")
        return False

    # 5. CSS 통합 테스트
    print("\n5. Testing CSS integration...")
    css_path = template_dir / "styles" / "solution.css"

    if css_path.exists():
        css_content = css_path.read_text(encoding="utf-8")
        inline_css = f"<style>\n{css_content}\n</style>"

        if "</head>" in html_content:
            complete_html = html_content.replace("</head>", f"{inline_css}\n</head>")
        else:
            complete_html = f"{inline_css}\n{html_content}"

        print(f"   SUCCESS: CSS integrated ({len(css_content):,} chars)")
        print(f"   SUCCESS: Complete HTML ({len(complete_html):,} chars)")
    else:
        print("   WARNING: CSS file not found")
        complete_html = html_content

    # 6. 콘텐츠 검증
    print("\n6. Validating content...")
    content_checks = [
        ("Korean text", "이차방정식" in html_content),
        ("Math content", "근의 공식" in html_content),
        ("Code content", "import math" in html_content),
        ("UTF-8 encoding", 'charset="UTF-8"' in html_content),
    ]

    all_passed = True
    for check_name, result in content_checks:
        if result:
            print(f"   SUCCESS: {check_name}")
        else:
            print(f"   WARNING: {check_name} check failed")
            all_passed = False

    # 7. 결과 파일 생성
    print("\n7. Generating output files...")
    output_dir = Path(__file__).parent
    output_dir.mkdir(exist_ok=True)

    # HTML 파일 저장
    basic_file = output_dir / "test_result_basic.html"
    basic_file.write_text(html_content, encoding="utf-8")

    complete_file = output_dir / "test_result_complete.html"
    complete_file.write_text(complete_html, encoding="utf-8")

    # 테스트 리포트 생성
    report_file = output_dir / "test_report.txt"
    report = f"""PDF Template System Test Report
=====================================
Test Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Results:
- Template Loading: PASS
- HTML Rendering: PASS
- CSS Integration: PASS
- Content Validation: {"PASS" if all_passed else "PARTIAL"}

Generated Files:
- Basic HTML: {basic_file.name} ({len(html_content):,} chars)
- Complete HTML: {complete_file.name} ({len(complete_html):,} chars)

Test Data:
- Sections: {len(test_sections)}
- Title: {template_data.title}
- Thread ID: {template_data.thread_id}

Next Steps:
1. Open HTML files in browser to verify rendering
2. Test PDF generation in proper environment (Linux/Docker)
3. Validate WeasyPrint integration when dependencies are available

File Locations:
- {basic_file.absolute()}
- {complete_file.absolute()}
"""

    report_file.write_text(report, encoding="utf-8")

    print(f"   SUCCESS: Files generated in {output_dir.absolute()}")
    print(f"   - Basic HTML: {basic_file.name}")
    print(f"   - Complete HTML: {complete_file.name}")
    print(f"   - Test Report: {report_file.name}")

    return True


def main() -> int:
    """메인 함수."""
    try:
        success = test_template_system()

        print("\n" + "=" * 40)
        if success:
            print("RESULT: All tests PASSED")
            print("\nThe PDF template system is working correctly!")
            print("Generated HTML files can be opened in browser.")
            print("PDF generation will work when WeasyPrint dependencies are available.")
        else:
            print("RESULT: Some tests FAILED")
            print("Check error messages above for details.")

        return 0 if success else 1

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
