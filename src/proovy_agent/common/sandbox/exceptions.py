"""Sandbox exception hierarchy."""


class SandboxError(Exception):
    """샌드박스 관련 기본 예외."""


class SandboxCreationError(SandboxError):
    """샌드박스 생성 실패."""


class SandboxUnavailableError(SandboxError):
    """checkpoint/resume 후 sandbox context가 사라진 경우."""


class CodeExecutionError(SandboxError):
    """코드 실행 실패 (런타임 에러 등)."""


class SandboxTimeoutError(CodeExecutionError):
    """코드 실행 타임아웃."""
