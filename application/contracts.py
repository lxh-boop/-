from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class ApplicationError:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ApplicationResult(Generic[T]):
    success: bool
    data: T | None = None
    error: ApplicationError | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, data: T, **metadata: Any) -> "ApplicationResult[T]":
        return cls(success=True, data=data, metadata=dict(metadata))

    @classmethod
    def fail(
        cls,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        **metadata: Any,
    ) -> "ApplicationResult[T]":
        return cls(
            success=False,
            error=ApplicationError(code=code, message=message, details=details or {}),
            metadata=dict(metadata),
        )
