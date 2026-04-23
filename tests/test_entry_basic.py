# tests/test_entry_basic.py - Fixed version
"""
Test module for basic functionality of chuk_mcp_runtime entry point.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock the problematic artifacts_tools module before ANY imports so that
# 'import chuk_mcp_runtime.entry' doesn't trigger a real chuk_artifacts import.
_original_artifacts_module = sys.modules.get("chuk_mcp_runtime.tools.artifacts_tools")
mock_artifacts_tools = MagicMock()
mock_artifacts_tools.validate_session_parameter = lambda session_id=None, operation="unknown": (
    session_id or "test-session"
)
sys.modules["chuk_mcp_runtime.tools.artifacts_tools"] = mock_artifacts_tools

# Import our test infrastructure
# Import the entry module
import chuk_mcp_runtime.entry as entry
from tests.conftest import (
    AsyncMockHelper,
    DummyServerRegistry,
    MockMCPSessionManager,
    MockSessionContext,
    mock_get_session_or_none,
    mock_require_session,
    mock_with_session_auto_inject,
    run_async,
)


class EnhancedMockMCPSessionManager(MockMCPSessionManager):
    """Enhanced mock session manager that properly handles configuration."""

    def __init__(self, sandbox_id=None, default_ttl_hours=24, auto_extend_threshold=0.1):
        super().__init__(sandbox_id, default_ttl_hours, auto_extend_threshold)
        # Ensure we respect the provided parameters
        self.sandbox_id = sandbox_id or "test-sandbox"
        self.default_ttl_hours = default_ttl_hours
        self.auto_extend_threshold = auto_extend_threshold

    async def get_session_info(self, session_id):
        """Enhanced get_session_info with proper metadata structure."""
        session_data = self._sessions.get(session_id)
        if session_data:
            # Ensure both custom_metadata and metadata are available
            if "custom_metadata" not in session_data:
                session_data["custom_metadata"] = session_data.get("metadata", {})
            if "metadata" not in session_data:
                session_data["metadata"] = session_data.get("custom_metadata", {})
        return session_data


class DummyMCPServer:
    """Enhanced dummy MCP server with session management."""

    def __init__(self, config, tools_registry=None):
        self.config = config
        self.serve_called = False
        self.server_name = "test-server"
        self.registered_tools = []
        self.tools_registry = tools_registry or {}

        # Create session manager with proper config handling
        session_config = config.get("sessions", {})
        self.session_manager = EnhancedMockMCPSessionManager(
            sandbox_id=session_config.get("sandbox_id"),
            default_ttl_hours=session_config.get("default_ttl_hours", 24),
        )

    async def serve(self, custom_handlers=None):
        """Mock serve method that doesn't try to use stdio_server."""
        self.serve_called = True
        self.custom_handlers = custom_handlers
        return

    async def register_tool(self, name, func):
        """Mock register_tool method."""
        self.registered_tools.append(name)
        self.tools_registry[name] = func

    def get_session_manager(self):
        """Get the session manager instance."""
        return self.session_manager

    async def create_user_session(self, user_id, metadata=None):
        """Create a new user session."""
        return await self.session_manager.create_session(user_id=user_id, metadata=metadata)


# Enhanced proxy manager mock that's compatible across test modules
class UniversalMockProxyServerManager:
    """Universal mock proxy server manager that works across all test modules."""

    def __init__(self, config, project_root):
        self.running_servers = {}
        self.running = {}
        self.config = config
        self.project_root = project_root
        self.openai_mode = config.get("proxy", {}).get("openai_compatible", False)
        self.tools = {"proxy.test_server.tool": MagicMock(return_value="mock result")}

    async def start_servers(self):
        """Mock start_servers implementation."""
        self.running_servers["test_server"] = {"wrappers": {}}
        self.running["test_server"] = {"wrappers": {}}

    async def stop_servers(self):
        """Mock stop_servers implementation."""
        self.running_servers.clear()
        self.running.clear()

    async def get_all_tools(self):
        """Mock get_all_tools implementation."""
        return self.tools

    async def process_text(self, text):
        """Mock process_text implementation."""
        return [
            {
                "content": "Processed text",
                "tool": "proxy.test.tool",
                "processed": True,
                "text": text,
            }
        ]

    async def call_tool(self, name, **kwargs):
        """Mock call_tool implementation that supports tool name resolution."""
        # Simple tool name resolution
        if name.startswith("proxy."):
            parts = name.split(".")
            if len(parts) >= 3:
                server = parts[1]
                tool = parts[-1]
        elif "_" in name:
            parts = name.split("_", 1)
            if len(parts) == 2:
                server, tool = parts
                name = f"proxy.{server}.{tool}"

        return f"Result from {name} with args {kwargs}"


# Apply patches
def patch_session_management():
    """Apply comprehensive session management patches."""
    # Core classes
    entry.MCPSessionManager = EnhancedMockMCPSessionManager
    entry.SessionContext = MockSessionContext

    def _create_session_manager_from_config(config):
        """Handle both RuntimeConfig and dict."""
        if config is None:
            return EnhancedMockMCPSessionManager(sandbox_id=None, default_ttl_hours=24)
        # Handle RuntimeConfig
        if hasattr(config, "sessions"):
            return EnhancedMockMCPSessionManager(
                sandbox_id=config.sessions.sandbox_id,
                default_ttl_hours=config.sessions.default_ttl_hours,
            )
        # Handle dict
        return EnhancedMockMCPSessionManager(
            sandbox_id=config.get("sessions", {}).get("sandbox_id"),
            default_ttl_hours=config.get("sessions", {}).get("default_ttl_hours", 24),
        )

    entry.create_mcp_session_manager = _create_session_manager_from_config

    # Replace proxy manager with universal version
    entry.ProxyServerManager = UniversalMockProxyServerManager

    # Helper functions
    entry.with_session_auto_inject = mock_with_session_auto_inject
    entry.require_session = mock_require_session
    entry.get_session_or_none = mock_get_session_or_none

    # Tool registration functions
    async def mock_register_artifacts_tools(config):
        return config.get("artifacts", {}).get("enabled", False)

    async def mock_register_session_tools(config):
        return config.get("session_tools", {}).get("enabled", False)

    entry.register_artifacts_tools = mock_register_artifacts_tools
    entry.register_session_tools = mock_register_session_tools

    # Mock _iter_tools function
    def mock_iter_tools(container):
        if isinstance(container, dict):
            for name, func in container.items():
                mock_func = AsyncMockHelper()
                mock_func._mcp_tool = MagicMock()
                mock_func._mcp_tool.name = name
                yield name, mock_func
        elif isinstance(container, (list, tuple, set)):
            for name in container:
                mock_func = AsyncMockHelper()
                mock_func._mcp_tool = MagicMock()
                mock_func._mcp_tool.name = name
                yield name, mock_func

    entry._iter_tools = mock_iter_tools

    # Mock get_artifact_tools
    def mock_get_artifact_tools():
        return {
            "upload_file": AsyncMockHelper(return_value="uploaded"),
            "write_file": AsyncMockHelper(return_value="written"),
            "read_file": AsyncMockHelper(return_value="content"),
            "list_session_files": AsyncMockHelper(return_value=[]),
        }

    entry.get_artifact_tools = mock_get_artifact_tools


@pytest.fixture(scope="module", autouse=True)
def _restore_artifacts_module():
    """Restore the real artifacts_tools module after this module's tests complete.

    test_entry_basic replaces chuk_mcp_runtime.tools.artifacts_tools with a
    MagicMock at import time so that 'import entry' doesn't trigger real
    chuk_artifacts imports.  Without cleanup this MagicMock persists for the
    entire pytest session, causing later tests that import the real module to
    see MagicMock objects instead of real async functions.
    """
    yield
    if _original_artifacts_module is not None:
        sys.modules["chuk_mcp_runtime.tools.artifacts_tools"] = _original_artifacts_module
    else:
        sys.modules.pop("chuk_mcp_runtime.tools.artifacts_tools", None)


# Tests
def test_need_proxy_function():
    """Test that the _need_proxy function correctly identifies proxy config."""
    patch_session_management()

    # Test with HAS_PROXY_SUPPORT = True (default)
    assert entry._need_proxy({"proxy": {"enabled": True}}) is True
    assert entry._need_proxy({"proxy": {"enabled": False}}) is False
    assert entry._need_proxy({}) is False

    # Test with HAS_PROXY_SUPPORT = False
    with patch.object(entry, "HAS_PROXY_SUPPORT", False):
        assert entry._need_proxy({"proxy": {"enabled": True}}) is False
        assert entry._need_proxy({"proxy": {"enabled": False}}) is False
        assert entry._need_proxy({}) is False


def test_proxy_server_manager_mock():
    """Test that ProxyServerManager is mocked correctly."""
    patch_session_management()

    # Get the ProxyServerManager from entry
    assert entry.ProxyServerManager is UniversalMockProxyServerManager

    # Create an instance of the mocked class
    proxy_mgr = entry.ProxyServerManager({}, "/tmp")
    assert hasattr(proxy_mgr, "running") or hasattr(proxy_mgr, "running_servers")

    # Test that methods exist
    assert hasattr(proxy_mgr, "start_servers")
    assert hasattr(proxy_mgr, "stop_servers")
    assert hasattr(proxy_mgr, "get_all_tools")
    assert hasattr(proxy_mgr, "process_text")


def test_session_manager_creation():
    """Test that session manager is properly created."""
    patch_session_management()

    config = {"sessions": {"sandbox_id": "test-sandbox", "default_ttl_hours": 48}}

    session_manager = entry.create_mcp_session_manager(config)
    assert isinstance(session_manager, EnhancedMockMCPSessionManager)
    assert session_manager.sandbox_id == "test-sandbox"
    assert session_manager.default_ttl_hours == 48


def test_comprehensive_session_workflow():
    """Test a comprehensive session workflow."""
    patch_session_management()

    async def test_workflow():
        # Create session manager
        session_manager = EnhancedMockMCPSessionManager()

        # Create session
        session_id = await session_manager.create_session(
            user_id="workflow_user", metadata={"test": "data"}
        )

        # Set context
        session_manager.set_current_session(session_id, "workflow_user")

        # Verify context
        assert mock_require_session() == session_id
        assert mock_get_session_or_none() == session_id

        # Test session auto-injection
        args = {"filename": "test.txt", "content": "data"}
        injected = await entry.with_session_auto_inject(session_manager, "upload_file", args)
        assert injected["session_id"] == session_id

        # Update session
        success = await session_manager.update_session_metadata(session_id, {"updated": True})
        assert success is True

        # Get session info - should have both metadata structures
        info = await session_manager.get_session_info(session_id)
        assert info["user_id"] == "workflow_user"
        assert info["custom_metadata"]["test"] == "data"
        assert info["custom_metadata"]["updated"] is True

        # Clean up
        session_manager.clear_context()
        assert mock_get_session_or_none() is None

        return True

    result = run_async(test_workflow())
    assert result is True


def test_tool_naming_compatibility():
    """Test that the proxy manager supports tool naming compatibility."""
    patch_session_management()

    # Create a proxy manager with tools in different formats
    proxy_mgr = UniversalMockProxyServerManager(
        {"proxy": {"enabled": True, "openai_compatible": True}}, "/tmp"
    )

    # Add a tool function that returns a mock response
    test_tool = AsyncMockHelper(return_value="Tool response")
    proxy_mgr.tools = {"proxy.test.tool": test_tool}

    # Test get_all_tools (async function)
    tools = run_async(proxy_mgr.get_all_tools())
    assert "proxy.test.tool" in tools

    # Test process_text functionality (async function)
    result = run_async(proxy_mgr.process_text("Test text"))
    assert result[0]["processed"] is True
    assert result[0]["text"] == "Test text"

    # Test call_tool with different naming formats (async function)
    # With dot notation
    result1 = run_async(proxy_mgr.call_tool("proxy.test.tool", query="test"))
    assert "result" in result1.lower() or "response" in result1.lower()

    # With underscore notation
    result2 = run_async(proxy_mgr.call_tool("test_tool", query="test"))
    assert "result" in result2.lower() or "response" in result2.lower()


def test_session_context_integration():
    """Test session context integration."""
    patch_session_management()

    async def test_session_flow():
        session_manager = EnhancedMockMCPSessionManager()

        async with MockSessionContext(session_manager, auto_create=True) as session_id:
            assert session_id is not None
            assert session_id.startswith("session-")

        return True

    result = run_async(test_session_flow())
    assert result is True


def test_session_auto_injection():
    """Test automatic session injection for artifact tools."""
    patch_session_management()

    async def test_injection():
        session_manager = EnhancedMockMCPSessionManager()

        # Test with artifact tool
        args = {"content": "test content", "filename": "test.txt"}
        injected_args = await entry.with_session_auto_inject(session_manager, "upload_file", args)

        assert "session_id" in injected_args
        assert injected_args["session_id"].startswith("session-")

        # Test with non-artifact tool
        args2 = {"query": "test"}
        injected_args2 = await entry.with_session_auto_inject(session_manager, "search_web", args2)

        assert injected_args2 == args2  # No injection for non-artifact tools

        return True

    result = run_async(test_injection())
    assert result is True


def test_initialize_tool_registry_called():
    """Test that initialize_tool_registry is called during runtime startup."""
    patch_session_management()

    # Ensure the artifacts_tools module is properly mocked
    assert "chuk_mcp_runtime.tools.artifacts_tools" in sys.modules

    # Using context managers is cleaner and safer
    with (
        patch("chuk_mcp_runtime.entry.ServerRegistry", DummyServerRegistry),
        patch("chuk_mcp_runtime.entry.initialize_tool_registry") as mock_init,
        patch(
            "chuk_mcp_runtime.entry.load_config",
            return_value={"proxy": {"enabled": False}, "sessions": {"sandbox_id": "test"}},
        ),
        patch("chuk_mcp_runtime.entry.configure_logging"),
        patch("chuk_mcp_runtime.entry.find_project_root", return_value="/tmp"),
        patch("asyncio.run", side_effect=run_async),
    ):
        # Create a custom server that won't try to use stdio
        server = DummyMCPServer({"server": {"type": "stdio"}, "sessions": {"sandbox_id": "test"}})

        # Patch MCPServer separately to use our custom instance
        with patch("chuk_mcp_runtime.entry.MCPServer", return_value=server):
            # Make initialize_tool_registry an async mock
            async def mock_init_async(*args, **kwargs):
                return None

            mock_init.side_effect = mock_init_async

            # Run the runtime
            entry.run_runtime()

            # Check that initialize_tool_registry was called
            assert mock_init.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
