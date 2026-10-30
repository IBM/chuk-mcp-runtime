# tests/test_otel_compat_patch.py
"""
Tests for the Instana / non-standard OTel tracer compatibility patch in entry.py.

The patch wraps mcp.shared._otel.otel_span so that tracers whose
start_as_current_span does NOT accept a 'context' keyword argument no longer
cause a TypeError crash at runtime.
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StandardTracer:
    """Mimics a fully-compliant OTel tracer (accepts 'context')."""

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        *,
        kind=None,
        attributes=None,
        context=None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
    ):
        span = MagicMock()
        yield span


class _InstanaTracer:
    """Mimics InstanaTracer: start_as_current_span has NO 'context' param."""

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        *,
        kind=None,
        attributes=None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
    ):
        span = MagicMock()
        yield span


def _reload_entry_with_tracer(tracer):
    """Reload entry module with mcp_otel._tracer set to *tracer*."""
    import mcp.shared._otel as mcp_otel

    original_tracer = mcp_otel._tracer
    mcp_otel._tracer = tracer
    try:
        import chuk_mcp_runtime.entry as entry_mod

        importlib.reload(entry_mod)
        return entry_mod, mcp_otel
    finally:
        mcp_otel._tracer = original_tracer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPatchMcpOtelCompatibility:
    def test_no_op_for_standard_tracer(self):
        """Patch must NOT replace otel_span when tracer already accepts context."""
        import mcp.shared._otel as mcp_otel

        original_otel_span = mcp_otel.otel_span
        mcp_otel._tracer = _StandardTracer()
        try:
            import chuk_mcp_runtime.entry as entry_mod

            entry_mod._patch_mcp_otel_compatibility()
            # Should still be the original function, not replaced
            assert mcp_otel.otel_span is original_otel_span
        finally:
            mcp_otel.otel_span = original_otel_span

    def test_patch_applied_for_instana_tracer(self):
        """Patch MUST replace otel_span when tracer lacks 'context' param."""
        import mcp.shared._otel as mcp_otel

        original_otel_span = mcp_otel.otel_span
        original_tracer = mcp_otel._tracer
        mcp_otel._tracer = _InstanaTracer()
        try:
            import chuk_mcp_runtime.entry as entry_mod

            entry_mod._patch_mcp_otel_compatibility()
            assert mcp_otel.otel_span is not original_otel_span, (
                "otel_span should have been replaced with the shim"
            )
        finally:
            mcp_otel.otel_span = original_otel_span
            mcp_otel._tracer = original_tracer

    def test_shim_accepts_context_kwarg_without_error(self):
        """The shim must accept 'context' without raising TypeError."""
        import mcp.shared._otel as mcp_otel
        from opentelemetry.trace import SpanKind

        original_otel_span = mcp_otel.otel_span
        original_tracer = mcp_otel._tracer
        mcp_otel._tracer = _InstanaTracer()
        try:
            import chuk_mcp_runtime.entry as entry_mod

            entry_mod._patch_mcp_otel_compatibility()

            # Simulate what mcp internals do: call otel_span with context=...
            with mcp_otel.otel_span(
                "test-span",
                kind=SpanKind.CLIENT,
                attributes={"key": "value"},
                context=MagicMock(),  # <-- this must NOT crash
            ) as span:
                assert span is not None
        finally:
            mcp_otel.otel_span = original_otel_span
            mcp_otel._tracer = original_tracer

    def test_shim_forwards_other_kwargs_to_tracer(self):
        """The shim must pass name, kind, attributes, record_exception, etc. through."""
        import mcp.shared._otel as mcp_otel
        from opentelemetry.trace import SpanKind

        captured: dict[str, Any] = {}

        class _CapturingTracer:
            @contextmanager
            def start_as_current_span(
                self,
                name,
                *,
                kind=None,
                attributes=None,
                record_exception=True,
                set_status_on_exception=True,
            ):
                captured.update(
                    dict(
                        name=name,
                        kind=kind,
                        attributes=attributes,
                        record_exception=record_exception,
                        set_status_on_exception=set_status_on_exception,
                    )
                )
                yield MagicMock()

        original_otel_span = mcp_otel.otel_span
        original_tracer = mcp_otel._tracer
        mcp_otel._tracer = _CapturingTracer()
        try:
            import chuk_mcp_runtime.entry as entry_mod

            entry_mod._patch_mcp_otel_compatibility()

            with mcp_otel.otel_span(
                "my-op",
                kind=SpanKind.SERVER,
                attributes={"http.method": "GET"},
                record_exception=False,
                set_status_on_exception=False,
            ):
                pass

            assert captured["name"] == "my-op"
            assert captured["kind"] == SpanKind.SERVER
            assert captured["attributes"] == {"http.method": "GET"}
            assert captured["record_exception"] is False
            assert captured["set_status_on_exception"] is False
        finally:
            mcp_otel.otel_span = original_otel_span
            mcp_otel._tracer = original_tracer

    def test_patch_survives_missing_mcp_otel(self):
        """_patch_mcp_otel_compatibility must not raise if mcp is not importable."""
        import chuk_mcp_runtime.entry as entry_mod

        with patch.dict("sys.modules", {"mcp.shared._otel": None}):
            # Should return silently without raising
            entry_mod._patch_mcp_otel_compatibility()
