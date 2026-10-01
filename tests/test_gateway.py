"""Unit tests for the ModelGateway and Registry."""

from myagentos.gateway import (
    LLMMessage,
    MockProviderAdapter,
    ModelEntry,
    ModelGateway,
    ModelRegistry,
)


def test_model_registry_registration_and_filtering() -> None:
    registry = ModelRegistry()

    gpt = ModelEntry(
        provider="openai",
        platform="api",
        model_id="gpt-4o",
        capabilities=["code_generation", "structured_output", "tool_use"],
        lifecycle="active",
    )
    old_gpt = ModelEntry(
        provider="openai",
        platform="api",
        model_id="gpt-3.5-turbo",
        capabilities=["code_generation"],
        lifecycle="retired",
    )
    gemini = ModelEntry(
        provider="google",
        platform="api",
        model_id="gemini-2.5-flash",
        capabilities=["code_generation", "structured_output"],
        lifecycle="active",
    )

    registry.register(gpt)
    registry.register(old_gpt)
    registry.register(gemini)

    # Filter active models with structured_output
    matches = registry.find_by_capabilities(["structured_output"])
    assert len(matches) == 2
    assert {m.model_id for m in matches} == {"gpt-4o", "gemini-2.5-flash"}

    # Retired model should not be returned
    all_code = registry.find_by_capabilities(["code_generation"])
    assert "gpt-3.5-turbo" not in {m.model_id for m in all_code}


def test_model_gateway_dispatch_mock() -> None:
    gateway = ModelGateway()
    mock_adapter = MockProviderAdapter()
    mock_adapter.set_response("generate plan", '{"plan_id": "p-100"}')

    gateway.register_adapter("mock", mock_adapter)

    response = gateway.generate(
        messages=[LLMMessage(role="user", content="Please generate plan for user")],
        model_id="mock-planner-v1",
        provider="mock",
    )

    assert response.content == '{"plan_id": "p-100"}'
    assert response.input_tokens > 0
    assert len(mock_adapter.call_history) == 1


def test_mock_conversation_returns_dialogue_not_patch_proposal() -> None:
    adapter = MockProviderAdapter()
    response = adapter.generate(
        messages=[LLMMessage(role="user", content="Hola")],
        model_id="mock-mya",
    )

    assert response.content == "Hola. ¿Qué tienes en mente?"
    assert "propose_patch" not in response.content


def test_mock_conversation_preset_takes_precedence() -> None:
    adapter = MockProviderAdapter()
    adapter.set_response("proyectos tenemos", "Tienes alpha y beta registrados.")
    response = adapter.generate(
        messages=[LLMMessage(role="user", content="¿Qué proyectos tenemos?")],
        model_id="mock-mya",
    )

    assert response.content == "Tienes alpha y beta registrados."
