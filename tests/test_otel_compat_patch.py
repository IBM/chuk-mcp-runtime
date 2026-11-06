# tests/test_otel_compat_patch.py
"""
Tests for the best-effort tracer wrapper in entry.py.

Instana AutoTrace can leave a tracer whose ``start_as_current_span`` has no ``context``
parameter (Instana Python < 3.12). mcp 2.x always passes ``context=``, which used to raise
``TypeError`` inside ``initialize``. These tests exercise the call sites mcp really uses
(``mcp.server._otel`` and ``mcp.shared.jsonrpc_dispatcher`` bind ``otel_span`` by name), not
just ``mcp.shared._otel.otel_span``.
"""

from __future__ import annotations

from contextlib import contextmanager

import mcp.server._otel as server_otel
import mcp.shared._otel as mcp_otel
import mcp.shared.jsonrpc_dispatcher as dispatcher
import pytest
from opentelemetry.trace import SpanKind

from chuk_mcp_runtime.entry import _BestEffortTracer, _patch_mcp_otel_compatibility

CALL_SITES = [
    pytest.param(lambda: mcp_otel.otel_span, id="shared._otel"),
    pytest.param(lambda: server_otel.otel_span, id="server middleware"),
    pytest.param(lambda: dispatcher.otel_span, id="client dispatcher"),
]


class _Span:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


class _OldTracer:
    """Like Instana < 3.12: ``span_context`` instead of ``context``."""

    def __init__(self):
        self.calls = []

    @contextmanager
    def start_as_current_span(
        self,
        name,
        span_context=None,
        kind=None,
        attributes=None,
        record_exception=True,
        set_status_on_exception=True,
    ):
        self.calls.append(dict(name=name, kind=kind, attributes=attributes))
        yield _Span()


class _BrokenTracer:
    def start_as_current_span(self, name, **kwargs):
        raise RuntimeError("agent unavailable")


class _BrokenCloseTracer:
    @contextmanager
    def start_as_current_span(self, name, **kwargs):
        yield _Span()
        raise RuntimeError("export failed")


class _BrokenSpanTracer:
    @contextmanager
    def start_as_current_span(self, name, **kwargs):
        class Span:
            def set_attribute(self, *a, **k):
                raise RuntimeError("span broken")

        yield Span()


@pytest.fixture
def install(monkeypatch):
    def _install(tracer):
        monkeypatch.setattr(mcp_otel, "_tracer", tracer)
        _patch_mcp_otel_compatibility()
        return tracer

    return _install


def _enter(fn, body=lambda span: span.set_attribute("k", "v")):
    with fn("initialize", kind=SpanKind.SERVER, attributes={"a": 1}, context=None) as span:
        body(span)
    return "ok"


@pytest.mark.parametrize("get_fn", CALL_SITES)
class TestAllCallSites:
    def test_tracer_without_context_param(self, install, get_fn):
        tracer = install(_OldTracer())
        assert _enter(get_fn()) == "ok"
        assert tracer.calls and tracer.calls[0]["attributes"] == {"a": 1}  # span still recorded

    def test_tracer_that_always_fails(self, install, get_fn):
        install(_BrokenTracer())
        assert _enter(get_fn()) == "ok"

    def test_failure_when_closing_span(self, install, get_fn):
        install(_BrokenCloseTracer())
        assert _enter(get_fn()) == "ok"

    def test_failing_span_method(self, install, get_fn):
        install(_BrokenSpanTracer())
        assert _enter(get_fn()) == "ok"

    @pytest.mark.parametrize("tracer", [_OldTracer, _BrokenTracer, _BrokenCloseTracer])
    def test_request_exception_still_propagates(self, install, get_fn, tracer):
        install(tracer())

        def boom(span):
            raise ValueError("tool failed")

        with pytest.raises(ValueError, match="tool failed"):
            _enter(get_fn(), boom)


class TestPatch:
    def test_idempotent(self, install):
        install(_OldTracer())
        wrapped = mcp_otel._tracer
        _patch_mcp_otel_compatibility()
        assert mcp_otel._tracer is wrapped
        assert isinstance(wrapped, _BestEffortTracer)
        assert not isinstance(wrapped._tracer, _BestEffortTracer)

    def test_standard_tracer_receives_context(self, install):
        seen = {}

        class Standard:
            @contextmanager
            def start_as_current_span(
                self, name, *, kind=None, attributes=None, context=None, **kw
            ):
                seen["context"] = context
                yield _Span()

        install(Standard())
        sentinel = object()
        with mcp_otel.otel_span("x", kind=SpanKind.SERVER, context=sentinel):
            pass
        assert seen["context"] is sentinel  # nothing dropped when the tracer supports it

    def test_unrelated_type_error_from_tracer_is_not_retried_forever(self, install):
        class Odd:
            def start_as_current_span(self, name, **kwargs):
                raise TypeError("something else entirely")

        install(Odd())
        assert _enter(mcp_otel.otel_span) == "ok"  # falls back to a no-op span

    def test_missing_otel_module_is_ignored(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "mcp.shared._otel", None)
        _patch_mcp_otel_compatibility()  # must not raise
