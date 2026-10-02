"""用真实 SDK 异常验证适配层到 Worker 的分类，不调用外部模型。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from app.common.errors import InfrastructureError
from app.infrastructure.llm.openai_errors import normalize_openai_error
from app.infrastructure.memory.embedding import OpenAIEmbeddingProvider
from app.infrastructure.memory.extraction import OpenAISemanticMemoryExtractor
from app.workers.consumer import _classify


@pytest.mark.parametrize(
    "status,retryable",
    [
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (422, False),
        (408, True),
        (409, True),
        (429, True),
        (500, True),
        (503, True),
    ],
)
@pytest.mark.parametrize("adapter", ["embedding", "extraction"])
async def test_adapter_preserves_status_classification(status: int, retryable: bool, adapter: str):
    request = httpx.Request("POST", "https://example.invalid")
    error = APIStatusError(
        "private provider details", response=httpx.Response(status, request=request), body=None
    )
    create = AsyncMock(side_effect=error)
    client = SimpleNamespace(
        embeddings=SimpleNamespace(create=create),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    with pytest.raises(InfrastructureError) as caught:
        if adapter == "embedding":
            await OpenAIEmbeddingProvider(client=client, model="test", version="1").embed(("run",))
        else:
            await OpenAISemanticMemoryExtractor(client=client, model="test").extract(
                user_message=SimpleNamespace(content="周三休息"),
                assistant_message=SimpleNamespace(content="收到"),
                committed_at=datetime(2026, 10, 2, tzinfo=UTC),
                supported_types=(),
            )
    code = "memory_embedding_failed" if adapter == "embedding" else "memory_extraction_failed"
    assert _classify(caught.value) == (code, retryable)
    assert caught.value.__cause__ is error
    assert "private provider details" not in str(caught.value)


@pytest.mark.parametrize("error_type", [APIConnectionError, APITimeoutError])
def test_transport_errors_are_retryable(error_type):
    error = error_type(request=httpx.Request("POST", "https://example.invalid"))
    assert _classify(normalize_openai_error(error, code="provider_failed")) == (
        "provider_failed",
        True,
    )


def test_unknown_sdk_and_unclassified_infrastructure_errors_are_not_retried():
    error = APIError("unknown", request=httpx.Request("POST", "https://example.invalid"), body=None)
    assert _classify(normalize_openai_error(error, code="provider_failed")) == (
        "provider_failed",
        False,
    )
    assert _classify(InfrastructureError("unknown_infrastructure")) == (
        "unknown_infrastructure",
        False,
    )
    assert _classify(InfrastructureError("episode_detector_not_configured")) == (
        "episode_detector_not_configured",
        False,
    )
