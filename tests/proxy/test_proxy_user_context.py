# tests/proxy/test_proxy_user_context.py
"""
Tests verifying that proxy (multi-server) tools continue to work correctly
when a user context is set, and that local session injection is correctly
skipped for proxy tools.

Proxy tools forward calls to remote MCP servers via their own protocol;
they must not have a local session_id injected and must not be affected
by the local user_id context variable.
"""

from unittest.mock import MagicMock

import pytest

from tests.conftest import MockMCPSessionManager, mock_session_ctx, mock_user_ctx


class TestProxyToolsWithUserContext:
    @pytest.mark.asyncio
    async def test_proxy_tool_executes_with_user_context_set(self):
        """Proxy tools must execute successfully even when _user_ctx is set."""
        from chuk_mcp_runtime.session.native_session_management import with_session_auto_inject

        mock_session = MockMCPSessionManager()
        mock_session_ctx.set(None)
        mock_user_ctx.set("alice")

        # A proxy tool has _proxy_server attribute
        proxy_func = MagicMock()
        proxy_func._proxy_server = "remote-server"

        args = {"query": "hello"}
        result = await with_session_auto_inject(
            mock_session, "proxy.remote.search", args, proxy_func
        )

        # Proxy tools: arguments must be returned unmodified (no session_id injected)
        assert result == args
        assert "session_id" not in result

    @pytest.mark.asyncio
    async def test_local_tool_args_pass_through(self):
        """Non-proxy local tools: args pass through and no session_id is injected."""
        from chuk_mcp_runtime.session.native_session_management import with_session_auto_inject

        mock_session = MockMCPSessionManager()
        mock_session_ctx.set(None)
        mock_user_ctx.set("bob")

        local_func = MagicMock(spec=[])  # no _proxy_server attribute

        args = {"param": "value"}
        result = await with_session_auto_inject(mock_session, "some_local_tool", args, local_func)

        # Non-artifact local tools: args returned unchanged, no session_id added
        assert "param" in result

    @pytest.mark.asyncio
    async def test_proxy_session_injection_skipped_regardless_of_user(self):
        """session_id injection is always skipped for proxy tools."""
        from chuk_mcp_runtime.session.native_session_management import with_session_auto_inject

        mock_session = MockMCPSessionManager()
        sid = await mock_session.create_session(user_id="carol")
        mock_session.set_current_session(sid, "carol")
        mock_user_ctx.set("carol")

        proxy_func = MagicMock()
        proxy_func._proxy_server = "another-server"

        original_args = {"param": "value"}
        result = await with_session_auto_inject(
            mock_session, "proxy.svc.do_thing", original_args, proxy_func
        )

        assert result == original_args, "Proxy tool args must pass through unchanged"

    @pytest.mark.asyncio
    async def test_user_context_unchanged_after_artifact_tool_injection(self):
        """User context must survive any session injection logic."""
        from chuk_mcp_runtime.session.native_session_management import (
            get_user_or_none,
            with_session_auto_inject,
        )

        mock_session = MockMCPSessionManager()
        sid = await mock_session.create_session(user_id="dave")
        mock_session.set_current_session(sid, "dave")
        mock_user_ctx.set("dave")

        local_func = MagicMock(spec=[])
        args = {"content": "hello", "filename": "test.txt"}

        await with_session_auto_inject(mock_session, "write_file", args, local_func)

        # User context must not be cleared or changed by injection logic
        assert get_user_or_none() == "dave"

    @pytest.mark.asyncio
    async def test_multiple_proxy_servers_independent(self):
        """Multiple proxy servers can coexist with different user contexts."""
        from tests.conftest import MockProxyServerManager

        config = {"proxy": {"enabled": True, "openai_compatible": False}}
        proxy_mgr = MockProxyServerManager(config, "/tmp")
        await proxy_mgr.start_servers()

        # Set user context
        mock_user_ctx.set("eve")

        # Proxy manager should still return its tools
        tools = await proxy_mgr.get_all_tools()
        assert len(tools) > 0

        # Clean up
        await proxy_mgr.stop_servers()
        mock_user_ctx.set(None)
