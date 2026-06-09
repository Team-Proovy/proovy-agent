"""LaTeX safety audit tests for video render templates."""

from proovy_agent.features.video.worker.sandbox import audit_latex_source


def test_tex_sanitizer_accepts_cjk_math_template_preamble() -> None:
    source = r'''
from manim import *

CJK_TEX_TEMPLATE = TexTemplate(tex_compiler="xelatex", output_format=".xdv")
CJK_TEX_TEMPLATE.add_to_preamble(r"""
\usepackage{xeCJK}
\setmainfont{Noto Sans CJK KR}
""")

class SafeScene(Scene):
    def construct(self):
        self.add(MathTex(r"2x + 1 = 7", tex_template=CJK_TEX_TEMPLATE))
'''

    assert audit_latex_source(source) == []


def test_tex_sanitizer_reports_dangerous_file_and_shell_commands() -> None:
    source = r"""
\usepackage{shellesc}
\includegraphics{/etc/passwd}
MathTex(r"\input{/etc/passwd}")
MathTex(r"\immediate\write18{curl https://example.test}")
MathTex(r"\openout1=/tmp/leak")
"""

    errors = audit_latex_source(source)
    codes = {error["error_code"] for error in errors}

    assert {
        "latex_file_read",
        "latex_file_write",
        "latex_shell_escape",
        "latex_shell_escape_package",
    }.issubset(codes)
    for error in errors:
        assert isinstance(error["message"], str)
        assert isinstance(error["line"], int)
        assert isinstance(error["column"], int)
        assert error["severity"] == "error"
        assert isinstance(error["original_snippet"], str)
