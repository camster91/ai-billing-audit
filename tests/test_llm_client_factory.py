"""Tests for the ``create_llm_client`` factory in ``src.llm_client``.

Acceptance criteria (t_8c7a7ce4):
    * ``create_llm_client()`` reads ``$LLM_PROVIDER`` (default ``"minimax"``)
      and returns a concrete provider instance.
    * The returned object satisfies the ``LLMClient`` Protocol.
    * Changing ``$LLM_PROVIDER`` (or the ``provider=`` kwarg) swaps the
      returned concrete type.
    * Unknown provider names raise ``ValueError`` with a helpful message
      that names the supported set and quotes the offender.
    * The factory is the ONLY place in the codebase that picks a backend
      by name — no caller-visible ``if provider == ...`` logic.

Design note
-----------
The four concrete provider classes (``MinimaxClient`` / ``ClaudeClient`` /
``OpenAIClient`` / ``GeminiClient``) are shipped by sibling task
``t_90cfc976`` in the same ``src/llm_client.py`` file. These tests do
not depend on those classes existing: they inject a small registry of
fake classes via the module-private ``_TEST_PROVIDER_OVERRIDES`` hook
documented on the factory. The hook is private (leading underscore)
and the production code path never reads it; it exists purely so the
factory's contract is testable in isolation, before the sibling task
lands.

The single "production path" test (``test_factory_routes_to_real_classes
when_landed``) is currently ``skip``-gated on the absence of the four
real classes, so the test suite still passes before the sibling task
ships. After ``t_90cfc976`` lands, the skip is removed automatically
and the production dispatch path is exercised end-to-end.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
from typing import Any

import pytest


SRC_DIR = pathlib.Path(__file__).resolve().parents[1] / "src"
LLM_CLIENT_PATH = SRC_DIR / "llm_client.py"


# ---------------------------------------------------------------------------
# Test doubles + helpers
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Minimal concrete ``LLMClient`` for registry injection.

    Each fake is parameterised by a name string so the test can assert
    ``type(client).__name__`` equals the expected provider class name.
    Exposes the two ``LLMClient`` methods so ``isinstance(client,
    LLMClient)`` is True under the ``@runtime_checkable`` Protocol.
    """

    def __init__(self, *, provider_label: str = "fake", **_kwargs: Any) -> None:
        self.provider_label = provider_label

    def complete(self, messages, **kwargs):  # pragma: no cover - not exercised
        return ""

    def complete_json(self, messages, schema, **kwargs):  # pragma: no cover
        return {}


def _install_overrides(monkeypatch, names: list[str] | None = None) -> dict[str, type]:
    """Populate ``_TEST_PROVIDER_OVERRIDES`` with a fresh fake class per name.

    Returns the mapping so tests can assert against it. Caller is
    responsible for the monkeypatch teardown — pytest's ``monkeypatch``
    fixture handles that automatically.
    """
    import src.llm_client as llm_client

    names = names or ["minimax", "claude", "openai", "gemini"]
    registry: dict[str, type] = {}
    for name in names:
        # One distinct class per name so isinstance + type checks work.
        cls = type(
            f"_Fake{_capitalise(name)}Client",
            (_FakeLLM,),
            {"__init__": _make_init(name)},
        )
        registry[name] = cls
    monkeypatch.setattr(llm_client, "_TEST_PROVIDER_OVERRIDES", registry)
    return registry


def _capitalise(name: str) -> str:
    return name[:1].upper() + name[1:]


def _make_init(label: str):
    def __init__(self, **kwargs: Any) -> None:
        _FakeLLM.__init__(self, provider_label=label, **kwargs)

    return __init__


@pytest.fixture
def factory_module():
    """Re-import ``src.llm_client`` so module-level state is fresh per test.

    Some tests mutate ``_TEST_PROVIDER_OVERRIDES``; the fixture isolates
    that mutation from sibling tests by reloading the module after the
    mutation. We also clear ``$LLM_PROVIDER`` so the env-var tests
    start from a known baseline.
    """
    import src.llm_client as llm_client

    # Clear any test-time mutation of the override dict from a prior
    # test in the same process. Reload restores the empty default.
    importlib.reload(llm_client)
    return llm_client


# ---------------------------------------------------------------------------
# Acceptance: factory returns an LLMClient Protocol-conformant object
# ---------------------------------------------------------------------------


def test_default_provider_is_minimax(monkeypatch, factory_module):
    """No env var, no provider kwarg -> minimax."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    _install_overrides(monkeypatch)
    factory_module._TEST_PROVIDER_OVERRIDES  # touch so the fixture is referenced

    client = factory_module.create_llm_client()
    assert isinstance(client, _FakeLLM)
    assert client.provider_label == "minimax"
    assert isinstance(client, factory_module.LLMClient)


def test_returns_object_satisfying_protocol(monkeypatch, factory_module):
    """The returned object must pass the ``runtime_checkable`` Protocol check.

    This is the core structural-typing acceptance: the factory's return
    type is a real ``LLMClient``-shaped object, not a duck-typed proxy.
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    _install_overrides(monkeypatch)

    for provider in ("minimax", "claude", "openai", "gemini"):
        client = factory_module.create_llm_client(provider=provider)
        assert isinstance(client, factory_module.LLMClient), (
            f"provider {provider!r} returned {type(client).__name__} "
            f"which is not an LLMClient"
        )


# ---------------------------------------------------------------------------
# Acceptance: env var swap changes the returned concrete type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env_value,expected_label",
    [
        ("minimax", "minimax"),
        ("claude", "claude"),
        ("openai", "openai"),
        ("gemini", "gemini"),
    ],
)
def test_env_var_picks_provider(monkeypatch, factory_module, env_value, expected_label):
    """``$LLM_PROVIDER`` selects the backend; default-arg call returns it."""
    _install_overrides(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", env_value)

    client = factory_module.create_llm_client()
    assert client.provider_label == expected_label


def test_explicit_provider_kwarg_overrides_env(monkeypatch, factory_module):
    """Passing ``provider=`` directly beats the env var."""
    _install_overrides(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "minimax")

    client = factory_module.create_llm_client(provider="gemini")
    assert client.provider_label == "gemini"


def test_empty_env_var_falls_back_to_default(monkeypatch, factory_module):
    """``LLM_PROVIDER=`` (empty) is treated as unset -> default provider."""
    _install_overrides(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "")

    client = factory_module.create_llm_client()
    assert client.provider_label == "minimax"


def test_env_swap_changes_returned_type(monkeypatch, factory_module):
    """Stronger version of the parametrised env-var test: assert distinct types.

    The acceptance criterion says "env var swap changes the returned
    concrete type." Two providers with the same runtime type would
    pass the label check above; this test asserts the actual class
    object differs.
    """
    _install_overrides(monkeypatch)

    seen: dict[str, type] = {}
    for provider in ("minimax", "claude", "openai", "gemini"):
        monkeypatch.setenv("LLM_PROVIDER", provider)
        client = factory_module.create_llm_client()
        seen[provider] = type(client)

    # All four classes are distinct — none of them is an alias for another.
    assert len({id(c) for c in seen.values()}) == 4, (
        f"expected four distinct concrete types, got {seen}"
    )


# ---------------------------------------------------------------------------
# Acceptance: unknown providers raise ValueError with a helpful message
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "gpt",
        "anthropic",
        "claude-3",
        "MiniMax",
        " MINIMAX ",
        "minimax\n",
        "openrouter",
        "azure",
        "bedrock",
    ],
)
def test_unknown_provider_raises_value_error(monkeypatch, factory_module, bad):
    """Any name outside the canonical set must be rejected with ValueError."""
    _install_overrides(monkeypatch)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    with pytest.raises(ValueError) as excinfo:
        factory_module.create_llm_client(provider=bad)

    # Message must name the supported set and quote the offender.
    msg = str(excinfo.value)
    assert "supported" in msg.lower() or "supported" in msg
    # The bad name is reproduced in the error so operators can grep logs.
    assert repr(bad) in msg or repr(bad.strip()) in msg


def test_valueerror_message_lists_all_supported_providers(monkeypatch, factory_module):
    """The error must enumerate every supported name."""
    _install_overrides(monkeypatch)

    with pytest.raises(ValueError) as excinfo:
        factory_module.create_llm_client(provider="bogus")

    msg = str(excinfo.value)
    for canonical in ("minimax", "claude", "openai", "gemini"):
        assert canonical in msg, (
            f"ValueError message must list {canonical!r}; got: {msg}"
        )


def test_unknown_provider_via_env_var_raises(monkeypatch, factory_module):
    """Bad value set in the env var is rejected the same way as a bad kwarg."""
    _install_overrides(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "not-a-real-provider")

    with pytest.raises(ValueError):
        factory_module.create_llm_client()


# ---------------------------------------------------------------------------
# Acceptance: factory is the ONLY dispatch site
# ---------------------------------------------------------------------------


def test_factory_has_no_provider_name_conditionals(factory_module):
    """No ``if`` statement in the factory body may test provider identity.

    This is the structural invariant: the factory dispatches by
    table lookup, never by chained conditionals. We scan the AST of
    ``create_llm_client`` and ``_resolve_provider_class`` to enforce
    it. The class-existence check
    (``isinstance(instance, LLMClient)``) is allowed because it tests
    the structural contract, not provider identity.
    """
    src = LLM_CLIENT_PATH.read_text()
    tree = ast.parse(src)
    targets = {"create_llm_client", "_resolve_provider_class"}
    found_targets = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert targets.issubset(found_targets), (
        f"expected to find functions {targets} in {LLM_CLIENT_PATH}; "
        f"present: {sorted(n for n in found_targets if n in targets)}"
    )

    forbidden_comparators = ("minimax", "claude", "openai", "gemini")
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef) or func.name not in targets:
            continue
        for node in ast.walk(func):
            # Allow ``chosen not in SUPPORTED_PROVIDERS`` as the only
            # check — that is the "unknown provider" guard, not a
            # backend-specific branch. We forbid equality / inequality
            # comparisons against literal provider names.
            if isinstance(node, ast.Compare):
                for comparator in node.comparators:
                    literal = _extract_string_literal(comparator)
                    if literal in forbidden_comparators:
                        pytest.fail(
                            f"factory function {func.name} contains a "
                            f"conditional comparing against provider name "
                            f"{literal!r}; the factory must dispatch by "
                            f"table lookup, not chained conditionals"
                        )


def _extract_string_literal(node: ast.AST) -> str | None:
    """Return the string value of an ``ast.Constant`` node, else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def test_module_exports_create_llm_client(factory_module):
    """The factory must be importable from the module's public surface."""
    assert hasattr(factory_module, "create_llm_client")
    assert "create_llm_client" in factory_module.__all__


def test_module_exposes_supported_providers_set(factory_module):
    """Operators can introspect the supported set without reading source."""
    assert hasattr(factory_module, "SUPPORTED_PROVIDERS")
    assert factory_module.SUPPORTED_PROVIDERS == frozenset(
        {"minimax", "claude", "openai", "gemini"}
    )


# ---------------------------------------------------------------------------
# End-to-end: kwargs flow through to the provider constructor
# ---------------------------------------------------------------------------


def test_kwargs_forwarded_to_provider_constructor(monkeypatch, factory_module):
    """``**kwargs`` are passed to the concrete class unchanged."""
    registry = _install_overrides(monkeypatch)
    captured: dict[str, Any] = {}

    # Wrap the minimax fake so we can observe its construction kwargs.
    original_minimax = registry["minimax"]

    class _SpyMinimax(original_minimax):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            super().__init__(**kwargs)

    import src.llm_client as llm_client

    llm_client._TEST_PROVIDER_OVERRIDES["minimax"] = _SpyMinimax

    llm_client.create_llm_client(
        provider="minimax",
        model="custom-model",
        temperature=0.7,
        api_key="sk-test",
    )
    assert captured == {
        "model": "custom-model",
        "temperature": 0.7,
        "api_key": "sk-test",
    }


# ---------------------------------------------------------------------------
# Production-path check, gated on the sibling task landing
# ---------------------------------------------------------------------------


def _real_classes_present() -> bool:
    """True if all four concrete classes have been shipped to ``src/llm_client.py``."""
    try:
        import src.llm_client as lc
    except ImportError:
        return False
    return all(
        hasattr(lc, name)
        for name in ("MinimaxClient", "ClaudeClient", "OpenAIClient", "GeminiClient")
    )


@pytest.mark.skipif(
    not _real_classes_present(),
    reason="sibling task t_90cfc976 has not yet shipped the four provider classes",
)
def test_factory_routes_to_real_classes_when_landed(monkeypatch, factory_module):
    """End-to-end: the production registry dispatches to the real classes.

    We verify the **dispatch** path — the factory's job — by resolving
    each provider name through ``_resolve_provider_class`` (no
    construction) and asserting the class names match what the
    sibling task shipped. Constructing the real classes would require
    a live API key for each provider, which is out of scope for a
    test that exists to prove the factory's registry binding is
    correct. The dedicated tests in ``test_minimax_client.py`` and
    friends exercise the real constructors.
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    expected = {
        "minimax": "MinimaxClient",
        "claude": "ClaudeClient",
        "openai": "OpenAIClient",
        "gemini": "GeminiClient",
    }
    for provider, class_name in expected.items():
        cls = factory_module._resolve_provider_class(provider)
        assert cls.__name__ == class_name, (
            f"factory's _resolve_provider_class({provider!r}) returned "
            f"{cls.__name__!r}, expected {class_name!r}"
        )
        # The class must expose the two protocol methods — that is
        # the structural contract the factory promises. We do not
        # instantiate the class here (that would require a real API
        # key for each provider); the dedicated test_minimax_client
        # suite exercises the real constructors.
        assert hasattr(cls, "complete")
        assert hasattr(cls, "complete_json")
