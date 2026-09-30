"""Tests for ClaudeAdapter and Anthropic integration in Model Gateway."""

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from myagentos.core.errors import MyAgentOSError
from myagentos.gateway import ClaudeAdapter, LLMMessage, ModelGateway


class DummyOutputSchema(BaseModel):
    summary: str
    confidence: float


def test_claude_adapter_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    adapter = ClaudeAdapter()
    with pytest.raises(MyAgentOSError, match="ANTHROPIC_API_KEY is not set"):
        adapter.generate(
            messages=[LLMMessage(role="user", content="hello")],
            model_id="claude-3-5-sonnet-latest",
        )


def test_claude_adapter_text_generation() -> None:
    mock_client = MagicMock()
    mock_resp = MagicMock()

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Hello from Claude!"
    mock_resp.content = [text_block]
    mock_resp.usage.input_tokens = 15
    mock_resp.usage.output_tokens = 8

    mock_client.messages.create.return_value = mock_resp

    adapter = ClaudeAdapter(api_key="test-key", client=mock_client)
    res = adapter.generate(
        messages=[
            LLMMessage(role="system", content="System instruction"),
            LLMMessage(role="user", content="Say hello"),
        ],
        model_id="claude-3-5-sonnet-latest",
    )

    assert res.content == "Hello from Claude!"
    assert res.input_tokens == 15
    assert res.output_tokens == 8
    assert res.model_id == "claude-3-5-sonnet-latest"

    # Verify call arguments to Anthropic messages.create
    mock_client.messages.create.assert_called_once()
    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["model"] == "claude-3-5-sonnet-latest"
    assert kwargs["system"] == "System instruction"
    assert kwargs["messages"] == [{"role": "user", "content": "Say hello"}]


def test_claude_adapter_structured_output() -> None:
    mock_client = MagicMock()
    mock_resp = MagicMock()

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.name = "record_structured_output"
    tool_use_block.input = {"summary": "Analysis complete", "confidence": 0.98}
    mock_resp.content = [tool_use_block]
    mock_resp.usage.input_tokens = 25
    mock_resp.usage.output_tokens = 12

    mock_client.messages.create.return_value = mock_resp

    adapter = ClaudeAdapter(api_key="test-key", client=mock_client)
    res = adapter.generate(
        messages=[LLMMessage(role="user", content="Analyze project")],
        model_id="claude-3-5-sonnet-latest",
        response_schema=DummyOutputSchema,
    )

    assert '"summary": "Analysis complete"' in res.content
    assert '"confidence": 0.98' in res.content

    _, kwargs = mock_client.messages.create.call_args
    assert "tools" in kwargs
    assert kwargs["tools"][0]["name"] == "record_structured_output"
    assert kwargs["tool_choice"] == {
        "type": "tool",
        "name": "record_structured_output",
    }


def test_model_gateway_resolves_claude_to_anthropic() -> None:
    gateway = ModelGateway()
    mock_adapter = MagicMock()
    mock_adapter.generate.return_value = MagicMock(content="ok", input_tokens=1, output_tokens=1)
    gateway.register_adapter("anthropic", mock_adapter)

    res = gateway.generate(
        messages=[LLMMessage(role="user", content="Hi")],
        model_id="claude-3-5-haiku-latest",
    )
    assert res.content == "ok"
    mock_adapter.generate.assert_called_once()
