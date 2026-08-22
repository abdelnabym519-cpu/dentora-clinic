"""DB-free tests for the Media application boundary."""

from typing import Any

import pytest

from app.modules.media.application import MediaApplication


class FakeMediaGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...], dict[str, Any]]] = []

    async def invoke(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self.calls.append((target, operation, args, kwargs))
        return {"target": target, "operation": operation}

    def invoke_sync(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self.calls.append((target, operation, args, kwargs))
        return {"target": target, "operation": operation}


@pytest.mark.asyncio
async def test_media_application_delegates_to_injected_gateway() -> None:
    gateway = FakeMediaGateway()
    app = MediaApplication(gateway)

    result = await app.invoke("DocumentService", "get_document", "db", "clinic", "document")

    assert result == {"target": "DocumentService", "operation": "get_document"}
    assert gateway.calls == [("DocumentService", "get_document", ("db", "clinic", "document"), {})]


def test_media_application_preserves_sync_contract() -> None:
    gateway = FakeMediaGateway()
    app = MediaApplication(gateway)

    result = app.invoke_sync("DocumentService", "generate_storage_path", "clinic", "patient", "x.pdf")

    assert result == {"target": "DocumentService", "operation": "generate_storage_path"}
    assert gateway.calls[0][0:2] == ("DocumentService", "generate_storage_path")


@pytest.mark.asyncio
async def test_media_application_preserves_keyword_arguments() -> None:
    gateway = FakeMediaGateway()
    app = MediaApplication(gateway)

    await app.invoke(
        "PhotoService",
        "list_photos",
        "db",
        "clinic",
        "patient",
        page=2,
        page_size=25,
    )

    assert gateway.calls[0][3] == {"page": 2, "page_size": 25}
