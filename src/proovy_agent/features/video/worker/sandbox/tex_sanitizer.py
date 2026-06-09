"""TeX command audit for render templates."""

from __future__ import annotations

from dataclasses import dataclass
import re

_DANGEROUS_COMMAND_CODES: dict[str, str] = {
    "input": "latex_file_read",
    "include": "latex_file_read",
    "includegraphics": "latex_file_read",
    "openin": "latex_file_read",
    "openout": "latex_file_write",
    "read": "latex_file_read",
    "write": "latex_file_write",
    "write18": "latex_shell_escape",
    "ShellEscape": "latex_shell_escape",
    "DelayedShellEscape": "latex_shell_escape",
}
_DANGEROUS_PACKAGE_CODES: dict[str, str] = {
    "catchfile": "latex_file_read_package",
    "catchfilebetweentags": "latex_file_read_package",
    "currfile": "latex_file_access_package",
    "epstopdf": "latex_shell_escape_package",
    "import": "latex_file_read_package",
    "minted": "latex_shell_escape_package",
    "pythontex": "latex_shell_escape_package",
    "shellesc": "latex_shell_escape_package",
    "subfiles": "latex_file_read_package",
}
_COMMAND_PATTERN = re.compile(
    r"\\(?P<command>input|includegraphics|include|openin|openout|read|write18|write|"
    r"ShellEscape|DelayedShellEscape)(?![A-Za-z])"
)
_USEPACKAGE_PATTERN = re.compile(r"\\usepackage(?:\[[^\]]*])?\{(?P<packages>[^}]*)}")


@dataclass(frozen=True, slots=True)
class LatexValidationIssue:
    """JSON-safe LaTeX validation issue."""

    message: str
    line: int
    column: int
    error_code: str
    severity: str
    original_snippet: str

    def as_diagnostics(self) -> dict[str, object]:
        """Return the diagnostics contract expected by render callers."""
        return {
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "error_code": self.error_code,
            "severity": self.severity,
            "original_snippet": self.original_snippet,
        }


def audit_latex_source(source: str) -> list[dict[str, object]]:
    """Return dangerous TeX command findings for a Manim source string."""
    issues: list[LatexValidationIssue] = []
    for match in _COMMAND_PATTERN.finditer(source):
        command = match.group("command")
        issues.append(
            _issue(
                source,
                match.start(),
                error_code=_DANGEROUS_COMMAND_CODES[command],
                message=f"LaTeX command \\{command} is not allowed in render templates.",
            )
        )

    for match in _USEPACKAGE_PATTERN.finditer(source):
        raw_packages = match.group("packages")
        for package in _split_packages(raw_packages):
            code = _DANGEROUS_PACKAGE_CODES.get(package.casefold())
            if code is None:
                continue
            issues.append(
                _issue(
                    source,
                    match.start(),
                    error_code=code,
                    message=f"LaTeX package {package!r} is not allowed in render templates.",
                )
            )

    return [issue.as_diagnostics() for issue in issues]


def _split_packages(raw_packages: str) -> list[str]:
    return [package.strip() for package in raw_packages.split(",") if package.strip()]


def _issue(source: str, offset: int, *, error_code: str, message: str) -> LatexValidationIssue:
    line_start = source.rfind("\n", 0, offset) + 1
    line_end = source.find("\n", offset)
    if line_end == -1:
        line_end = len(source)
    return LatexValidationIssue(
        message=message,
        line=source.count("\n", 0, offset) + 1,
        column=offset - line_start + 1,
        error_code=error_code,
        severity="error",
        original_snippet=source[line_start:line_end].strip()[:200],
    )
