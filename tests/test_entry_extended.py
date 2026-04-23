# tests/test_entry_extended.py
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

import chuk_mcp_runtime.entry as entry
from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY
from tests.conftest import MockProxyServerManager, run_async


class MockMCPSessionManager:
    """Mock native session manager."""

    def __init__(self, sandbox_id=None, default_ttl_hours=24, auto_extend_threshold=0.1):
        self.sandbox_id = sandbox_id or "test-sandbox"
        self.default_ttl_hours = default_ttl_hours
        self.auto_extend_threshold = auto_extend_threshold
        self._sessions = {}
        self._current_session = None

    async def create_session(self, user_id=None, ttl_hours=None, metadata=None):
        session_id = f"session-{len(self._sessions)}"
        self._sessions[session_id] = {
            "user_id": user_id,
            "metadata": metadata or {},
            "created_at": 1640995200.0,
        }
        return session_id

    def set_current_session(self, session_id, user_id=None):
        self._current_session = session_id

    def get_current_session(self):
        return self._current_session

    async def auto_create_session_if_needed(self, user_id=None):
        if self._current_session:
            return self._current_session
        session_id = await self.create_session(user_id=user_id)
        self.set_current_session(session_id, user_id)
        return session_id

    def get_cache_stats(self):
        return {"cache_size": len(self._sessions), "sandbox_id": self.sandbox_id}


class MockSessionContext:
    """Mock session context manager."""

    def __init__(self, session_manager, session_id=None, user_id=None, auto_create=True):
        self.session_manager = session_manager
        self.session_id = session_id
        self.user_id = user_id
        self.auto_create = auto_create

    async def __aenter__(self):
        if self.session_id:
            return self.session_id
        elif self.auto_create:
            return await self.session_manager.auto_create_session_if_needed(self.user_id)
        return "test-session"

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class DummyServerRegistry:
    def __init__(self, project_root, config):
        self.project_root = project_root
        self.config = config
        self.bootstrap_called = False

    async def load_server_components(self):
        """Async version of load_server_components."""
        self.bootstrap_called = True
        return {}


class DummyMCPServer:
    def __init__(self, config, tools_registry=None):
        self.config = config
        self.serve_called = False
        self.server_name = "test-server"
        self.registered_tools = []
        self.tools_registry = tools_registry or {}
        # Add native session manager
        self.session_manager = MockMCPSessionManager()

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


class MockArtifactTools:
    """Mock artifact tools module for testing."""

    @staticmethod
    def get_artifact_tools():
        return ["upload_file", "write_file", "read_file", "list_session_files"]

    @staticmethod
    async def upload_file(**kwargs):
        return "Mock upload result"

    @staticmethod
    async def write_file(**kwargs):
        return "Mock write result"


@pytest.fixture(autouse=True)
def patch_entry(monkeypatch):
    """Set up common patches for entry module tests."""
    # Clear TOOLS_REGISTRY before each test
    TOOLS_REGISTRY.clear()

    # Mock configuration and logging
    monkeypatch.setattr(
        entry,
        "load_config",
        lambda paths, default: {
            "proxy": {"enabled": True},
            "artifacts": {"enabled": True},
            "sessions": {"sandbox_id": "test-sandbox"},
        },
    )
    monkeypatch.setattr(entry, "configure_logging", lambda cfg: None)
    monkeypatch.setattr(entry, "find_project_root", lambda *a, **kw: "/tmp")

    # Mock native session management
    # Only patch attributes that actually exist in the current entry.py.
    # MCPSessionManager and SessionContext were removed from entry.py imports;
    # the whole session module is already mocked via conftest.
    monkeypatch.setattr(entry, "create_mcp_session_manager", lambda config: MockMCPSessionManager())
    # Guard optional attributes so tests run against both old and new entry.py
    for _attr, _val in [
        ("MCPSessionManager", MockMCPSessionManager),
        ("SessionContext", MockSessionContext),
        ("with_session_auto_inject", None),
    ]:
        if hasattr(entry, _attr):
            monkeypatch.setattr(entry, _attr, _val)

    # Mock the server classes
    monkeypatch.setattr(entry, "ServerRegistry", DummyServerRegistry)
    monkeypatch.setattr(entry, "MCPServer", DummyMCPServer)

    # Mock the proxy manager
    monkeypatch.setattr(entry, "ProxyServerManager", MockProxyServerManager)

    # Mock initialize_tool_registry and other tool functions
    mock_init_registry = AsyncMock()
    monkeypatch.setattr(entry, "initialize_tool_registry", mock_init_registry)

    # Mock the artifact tools registration
    mock_register_artifacts = AsyncMock(return_value=True)
    monkeypatch.setattr(entry, "register_artifacts_tools", mock_register_artifacts)

    # Mock the session tools registration
    mock_register_session = AsyncMock(return_value=True)
    monkeypatch.setattr(entry, "register_session_tools", mock_register_session)

    # Mock get_artifact_tools function
    def mock_get_artifact_tools():
        return {
            "upload_file": MockArtifactTools.upload_file,
            "write_file": MockArtifactTools.write_file,
            "read_file": AsyncMock(return_value="mock file content"),
            "list_session_files": AsyncMock(return_value=[]),
        }

    monkeypatch.setattr(entry, "get_artifact_tools", mock_get_artifact_tools)

    # Mock the _iter_tools function
    def mock_iter_tools(container):
        if isinstance(container, dict):
            for name, func in container.items():
                # Create a mock function with _mcp_tool attribute
                mock_func = AsyncMock()
                mock_func._mcp_tool = MagicMock()
                mock_func._mcp_tool.name = name
                yield name, mock_func
        elif isinstance(container, (list, tuple, set)):
            for name in container:
                mock_func = AsyncMock()
                mock_func._mcp_tool = MagicMock()
                mock_func._mcp_tool.name = name
                yield name, mock_func

    monkeypatch.setattr(entry, "_iter_tools", mock_iter_tools)

    # Mock openai compatibility
    mock_init_openai = AsyncMock()
    monkeypatch.setattr(entry, "initialize_openai_compatibility", mock_init_openai)

    # Mock asyncio.run to use our run_async helper
    monkeypatch.setattr(asyncio, "run", run_async)

    # Mock stdio_server
    async def dummy_stdio_server():
        class DummyStream:
            async def read(self, n=-1):
                return b""

            async def write(self, data):
                return len(data)

            async def close(self):
                pass

        read_stream = DummyStream()
        write_stream = DummyStream()

        try:
            yield (read_stream, write_stream)
        finally:
            pass

    # Create a mock mcp.server.stdio module
    mock_stdio = MagicMock()
    mock_stdio.stdio_server = dummy_stdio_server
    sys.modules["mcp.server.stdio"] = mock_stdio

    # Reset environment variables
    yield

    # Clean up
    os.environ.pop("NO_BOOTSTRAP", None)
    if "mcp.server.stdio" in sys.modules:
        del sys.modules["mcp.server.stdio"]

    # Clear registry after test
    TOOLS_REGISTRY.clear()


def test_run_runtime_default_bootstrap(monkeypatch):
    """Test runtime with default bootstrap enabled."""
    # Create a server spy to track calls
    served = {}

    class SpyServer(DummyMCPServer):
        async def serve(self, custom_handlers=None):
            served["ok"] = True
            self.serve_called = True
            self.custom_handlers = custom_handlers

    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    # Run the runtime
    entry.run_runtime()

    # Verify the server was started
    assert served.get("ok", False) is True


def test_run_runtime_skip_bootstrap_flag(monkeypatch):
    """Test that NO_BOOTSTRAP env var prevents bootstrap."""
    # Set the environment variable
    os.environ["NO_BOOTSTRAP"] = "1"

    # Create a registry spy
    registry_called = {}

    class SpyRegistry(DummyServerRegistry):
        async def load_server_components(self):
            registry_called["bootstrap"] = True
            return {}

    monkeypatch.setattr(entry, "ServerRegistry", SpyRegistry)

    # Run with bootstrap_components=True
    entry.run_runtime(bootstrap_components=True)

    # Should not have called load_server_components
    assert "bootstrap" not in registry_called


def test_run_runtime_no_bootstrap_arg(monkeypatch):
    """Test that bootstrap_components=False prevents bootstrap."""
    # Create a registry spy
    registry_called = {}

    class SpyRegistry(DummyServerRegistry):
        async def load_server_components(self):
            registry_called["bootstrap"] = True
            return {}

    monkeypatch.setattr(entry, "ServerRegistry", SpyRegistry)

    # Run with bootstrap_components=False
    entry.run_runtime(bootstrap_components=False)

    # Should not have called load_server_components
    assert "bootstrap" not in registry_called


def test_session_manager_integration(monkeypatch):
    """Test session manager integration with the MCP server."""
    # Create a spy server to track session manager usage
    server_instance = None

    class SpyServer(DummyMCPServer):
        def __init__(self, config, tools_registry=None):
            super().__init__(config, tools_registry)
            nonlocal server_instance
            server_instance = self

    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    # Run the runtime
    entry.run_runtime()

    # Verify that the server has a session manager
    assert server_instance is not None
    assert hasattr(server_instance, "session_manager")
    assert isinstance(server_instance.session_manager, MockMCPSessionManager)
    assert server_instance.session_manager.sandbox_id == "test-sandbox"


def test_proxy_integration(monkeypatch):
    """Test proxy tool registration with the MCP server."""
    # Create a spy server to track tool registration
    server_instance = None

    class SpyServer(DummyMCPServer):
        def __init__(self, config, tools_registry=None):
            super().__init__(config, tools_registry)
            nonlocal server_instance
            server_instance = self

    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    # Create a test proxy manager with get_all_tools method
    class TestProxyManager(MockProxyServerManager):
        async def get_all_tools(self):
            return {"proxy.test_server.tool": AsyncMock(return_value="test result")}

        async def start_servers(self):
            self.running = {"test_server": {"status": "running"}}

    monkeypatch.setattr(entry, "ProxyServerManager", TestProxyManager)

    # Run the runtime
    entry.run_runtime()

    # Verify that the proxy tool was registered
    assert server_instance is not None
    assert server_instance.registered_tools, "No tools were registered"
    assert "proxy.test_server.tool" in server_instance.registered_tools


def test_artifacts_integration(monkeypatch):
    """Test artifact tools registration with the MCP server."""
    # Create a spy server to track tool registration
    server_instance = None

    class SpyServer(DummyMCPServer):
        def __init__(self, config, tools_registry=None):
            super().__init__(config, tools_registry)
            nonlocal server_instance
            server_instance = self

    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    # Run the runtime
    entry.run_runtime()

    # Verify that artifact tools were registered
    assert server_instance is not None
    assert server_instance.registered_tools, "No tools were registered"

    # Check for some expected artifact tools
    expected_tools = ["upload_file", "write_file", "read_file", "list_session_files"]
    registered_tool_names = server_instance.registered_tools

    # At least some artifact tools should be registered
    assert any(tool in registered_tool_names for tool in expected_tools), (
        f"Expected some of {expected_tools} in {registered_tool_names}"
    )


def test_session_tools_integration(monkeypatch):
    """Test session tools registration with the MCP server."""
    # Mock session tools registration to return True
    session_tools_registered = False

    async def mock_register_session_tools(config):
        nonlocal session_tools_registered
        session_tools_registered = True
        return True

    monkeypatch.setattr(entry, "register_session_tools", mock_register_session_tools)

    # Run the runtime
    entry.run_runtime()

    # Verify that session tools registration was called
    assert session_tools_registered


def test_tools_registry_population(monkeypatch):
    """Test that TOOLS_REGISTRY is properly populated and passed to MCPServer."""
    # Mock some tools in the registry
    mock_tool_func = AsyncMock()
    mock_tool_func._mcp_tool = MagicMock()
    mock_tool_func._mcp_tool.name = "test_tool"

    TOOLS_REGISTRY["test_tool"] = mock_tool_func

    # Create a spy server to track the tools_registry parameter
    server_instance = None

    class SpyServer(DummyMCPServer):
        def __init__(self, config, tools_registry=None):
            super().__init__(config, tools_registry)
            nonlocal server_instance
            server_instance = self

    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    # Run the runtime
    entry.run_runtime()

    # Verify that the server was initialized with the tools registry
    assert server_instance is not None
    assert server_instance.tools_registry is not None
    assert "test_tool" in server_instance.tools_registry


def test_openai_compatibility_initialization(monkeypatch):
    """Test that OpenAI compatibility is properly initialized."""
    init_openai_called = False

    async def mock_init_openai():
        nonlocal init_openai_called
        init_openai_called = True

    monkeypatch.setattr(entry, "initialize_openai_compatibility", mock_init_openai)

    # Run the runtime
    entry.run_runtime()

    # Verify that OpenAI compatibility was initialized
    assert init_openai_called


def test_custom_handlers_proxy_text(monkeypatch):
    """Test that proxy text handler is properly set up when proxy is available."""

    # Create a test proxy manager with process_text method
    class TestProxyManager(MockProxyServerManager):
        async def process_text(self, text):
            return [{"content": f"Processed: {text}"}]

        async def start_servers(self):
            self.running = {"test_server": {"status": "running"}}

    monkeypatch.setattr(entry, "ProxyServerManager", TestProxyManager)

    # Create a spy server to track custom handlers
    server_instance = None

    class SpyServer(DummyMCPServer):
        def __init__(self, config, tools_registry=None):
            super().__init__(config, tools_registry)
            nonlocal server_instance
            server_instance = self

    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    # Run the runtime
    entry.run_runtime()

    # Verify that custom handlers were set
    assert server_instance is not None
    assert server_instance.custom_handlers is not None
    assert "handle_proxy_text" in server_instance.custom_handlers


def test_session_context_in_tool_execution(monkeypatch):
    """Test that session context is properly used in tool execution."""
    # Create a tracking tool
    tool_calls = []

    async def tracking_tool(**kwargs):
        tool_calls.append(kwargs)
        return "Tool result"

    # Mock get_artifact_tools to return our tracking tool
    def mock_get_artifact_tools():
        return {"upload_file": tracking_tool}

    monkeypatch.setattr(entry, "get_artifact_tools", mock_get_artifact_tools)

    # Run the runtime
    entry.run_runtime()

    # The session manager should have been created
    assert len(tool_calls) == 0  # No calls yet, but system is set up


def test_main_success(monkeypatch, capsys):
    """Test successful execution of main function."""

    # Stub out run_runtime_async to prevent errors
    async def mock_run_runtime_async(*args, **kwargs):
        return None

    monkeypatch.setattr(entry, "run_runtime_async", mock_run_runtime_async)

    # Set command line arguments
    monkeypatch.setattr(sys, "argv", ["prog", "cfg.yaml"])

    # Run main
    entry.main(default_config={})

    # Should not have any errors
    captured = capsys.readouterr()
    assert captured.err == ""


def test_main_failure(monkeypatch, capsys):
    """Test handling of errors in main function."""

    # Create a mock that raises an exception
    async def mock_run_runtime_error(*args, **kwargs):
        raise RuntimeError("bang")

    monkeypatch.setattr(entry, "run_runtime_async", mock_run_runtime_error)

    # Set command line arguments
    monkeypatch.setattr(sys, "argv", ["prog"])

    # Should exit with code 1
    with pytest.raises(SystemExit) as ei:
        entry.main(default_config={})

    assert ei.value.code == 1

    # Should print the error message
    captured = capsys.readouterr()
    assert "Error starting CHUK MCP server: bang" in captured.err


def test_config_path_handling(monkeypatch):
    """Test various config path handling scenarios."""
    config_calls = []

    def mock_load_config(paths, default):
        config_calls.append(paths)
        return {"proxy": {"enabled": False}}

    monkeypatch.setattr(entry, "load_config", mock_load_config)

    # Test with no config path
    monkeypatch.setattr(sys, "argv", ["prog"])
    entry.main()

    # Should have called with None for paths
    assert len(config_calls) == 1
    assert config_calls[0] is None

    # Test with -c flag
    config_calls.clear()
    monkeypatch.setattr(sys, "argv", ["prog", "-c", "test.yaml"])
    entry.main()

    assert len(config_calls) == 1
    assert config_calls[0] == ["test.yaml"]


def test_keyboard_interrupt_handling(monkeypatch):
    """Test that KeyboardInterrupt is handled gracefully."""

    async def mock_run_runtime_interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(entry, "run_runtime_async", mock_run_runtime_interrupt)

    # Should not raise an exception, just exit gracefully
    entry.run_runtime()


def test_proxy_disabled(monkeypatch):
    """Test behavior when proxy is disabled."""
    # Mock config with proxy disabled
    monkeypatch.setattr(
        entry,
        "load_config",
        lambda paths, default: {
            "proxy": {"enabled": False},
            "sessions": {"sandbox_id": "test"},
        },
    )

    # Create a spy server
    server_instance = None

    class SpyServer(DummyMCPServer):
        def __init__(self, config, tools_registry=None):
            super().__init__(config, tools_registry)
            nonlocal server_instance
            server_instance = self

    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    # Run the runtime
    entry.run_runtime()

    # Should still work
    assert server_instance is not None
    assert server_instance.serve_called


def test_proxy_has_support_false(monkeypatch):
    """Test behavior when HAS_PROXY_SUPPORT is False."""
    # Disable proxy support
    monkeypatch.setattr(entry, "HAS_PROXY_SUPPORT", False)

    # Create a spy server
    server_instance = None

    class SpyServer(DummyMCPServer):
        def __init__(self, config, tools_registry=None):
            super().__init__(config, tools_registry)
            nonlocal server_instance
            server_instance = self

    monkeypatch.setattr(entry, "MCPServer", SpyServer)

    # Run the runtime
    entry.run_runtime()

    # Should still work, just without proxy
    assert server_instance is not None
    assert server_instance.serve_called
