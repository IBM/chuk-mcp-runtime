# tests/conftest.py - Final Fixed Version
"""
Enhanced conftest.py with properly working mocks for all components.
"""

# Mock imports need to happen before ANY imports
import sys
from contextvars import ContextVar
from unittest.mock import MagicMock

# Create mocks for all the modules we need before they get imported
mock_modules = {
    "chuk_tool_processor": MagicMock(),
    "chuk_tool_processor.mcp": MagicMock(),
    "chuk_tool_processor.registry": MagicMock(),
    "chuk_tool_processor.models": MagicMock(),
    "chuk_tool_processor.models.tool_call": MagicMock(),
    # Note: chuk_sessions is now a real dependency, not mocked
}

# Add them to sys.modules
for mod_name, mock in mock_modules.items():
    sys.modules[mod_name] = mock

# Mock context variables for session management
mock_session_ctx = ContextVar("session_context", default=None)
mock_user_ctx = ContextVar("user_context", default=None)


# ---------------------------------------------------------------------------
# Artifact helpers - real exception + metadata class so ownership tests work
# ---------------------------------------------------------------------------


class ArtifactNotFoundError(Exception):
    """Real exception so 'except ArtifactNotFoundError' works in tool functions."""

    pass


class ArtifactMetadata:
    """Minimal metadata object matching chuk_artifacts.models.ArtifactMetadata."""

    def __init__(
        self,
        artifact_id="artifact-1",
        scope="session",
        owner_id=None,
        session_id=None,
        filename="test.txt",
        mime="text/plain",
        bytes=0,
        summary="",
        stored_at="",
        ttl=900,
    ):
        self.artifact_id = artifact_id
        self.scope = scope
        self.owner_id = owner_id
        self.session_id = session_id
        self.filename = filename
        self.mime = mime
        self.bytes = bytes
        self.summary = summary
        self.stored_at = stored_at
        self.ttl = ttl

    def model_dump(self):
        return {
            "artifact_id": self.artifact_id,
            "scope": self.scope,
            "owner_id": self.owner_id,
            "session_id": self.session_id,
            "filename": self.filename,
            "mime": self.mime,
            "bytes": self.bytes,
            "summary": self.summary,
            "stored_at": self.stored_at,
        }


class MockArtifactStore:
    """Mock artifact store that doesn't cause await errors."""

    def __init__(self, storage_provider=None, session_provider=None, bucket=None):
        self.storage_provider = storage_provider
        self.session_provider = session_provider
        self.bucket = bucket

    async def validate_configuration(self):
        return {"session": {"status": "ok"}, "storage": {"status": "ok"}}

    async def close(self):
        pass


# Create the mock module - expose real exception and metadata so tool imports work
mock_artifacts_mod = MagicMock()
mock_artifacts_mod.ArtifactStore = MockArtifactStore
mock_artifacts_mod.ArtifactNotFoundError = ArtifactNotFoundError
mock_artifacts_mod.ArtifactMetadata = ArtifactMetadata
sys.modules["chuk_artifacts"] = mock_artifacts_mod

# Also register chuk_artifacts.models so 'from chuk_artifacts.models import ArtifactMetadata' works
mock_artifacts_models = MagicMock()
mock_artifacts_models.ArtifactMetadata = ArtifactMetadata
sys.modules["chuk_artifacts.models"] = mock_artifacts_models


# Enhanced Native Session Management Mocks
class MockMCPSessionManager:
    """Enhanced mock native session manager with full context variable support."""

    def __init__(self, sandbox_id=None, default_ttl_hours=24, auto_extend_threshold=0.1):
        self.sandbox_id = sandbox_id or "test-sandbox"
        self.default_ttl_hours = default_ttl_hours
        self.auto_extend_threshold = auto_extend_threshold
        self._sessions = {}
        self._current_session = None
        self._last_session = None
        self._last_session_user = None

    async def create_session(self, user_id=None, ttl_hours=None, metadata=None):
        session_id = f"session-{len(self._sessions)}-{user_id or 'anon'}"
        self._sessions[session_id] = {
            "user_id": user_id,
            "custom_metadata": metadata or {},
            "metadata": metadata or {},  # Both formats for compatibility
            "created_at": 1640995200.0,
            "expires_at": 1640995200.0 + (ttl_hours or self.default_ttl_hours) * 3600,
        }
        return session_id

    async def get_session_info(self, session_id):
        """Get session info - this method was missing in original mock"""
        return self._sessions.get(session_id)

    async def validate_session(self, session_id):
        return session_id in self._sessions

    async def extend_session(self, session_id, additional_hours=None):
        if session_id in self._sessions:
            hours = additional_hours or self.default_ttl_hours
            self._sessions[session_id]["expires_at"] += hours * 3600
            return True
        return False

    async def update_session_metadata(self, session_id, metadata):
        if session_id in self._sessions:
            self._sessions[session_id]["custom_metadata"].update(metadata)
            self._sessions[session_id]["metadata"].update(metadata)  # Update both
            return True
        return False

    async def delete_session(self, session_id):
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def set_current_session(self, session_id, user_id=None):
        self._current_session = session_id
        # CRITICAL: Update the actual context variables used by require_session()
        mock_session_ctx.set(session_id)
        if user_id:
            mock_user_ctx.set(user_id)

    def get_current_session(self):
        # Get from context variable first, then fallback to instance variable
        return mock_session_ctx.get() or self._current_session

    def get_current_user(self):
        # Get from context variable first
        user_from_ctx = mock_user_ctx.get()
        if user_from_ctx:
            return user_from_ctx

        if self._current_session and self._current_session in self._sessions:
            return self._sessions[self._current_session].get("user_id")
        return None

    def clear_context(self):
        self._current_session = None
        # CRITICAL: Clear the actual context variables
        mock_session_ctx.set(None)
        mock_user_ctx.set(None)

    async def auto_create_session_if_needed(self, user_id=None):
        current = self.get_current_session()
        if current and await self.validate_session(current):
            self._last_session = current
            return current

        # Mirror real behaviour: only reuse _last_session for the same user
        if self._last_session and await self.validate_session(self._last_session):
            if user_id is None or user_id == self._last_session_user:
                self.set_current_session(self._last_session, user_id)
                return self._last_session

        session_id = await self.create_session(user_id=user_id, metadata={"auto_created": True})
        self.set_current_session(session_id, user_id)
        self._last_session = session_id
        self._last_session_user = user_id
        return session_id

    def get_cache_stats(self):
        return {"cache_size": len(self._sessions), "sandbox_id": self.sandbox_id}

    async def list_active_sessions(self):
        return {
            "sandbox_id": self.sandbox_id,
            "active_sessions": len(self._sessions),
            "cache_stats": self.get_cache_stats(),
        }

    async def cleanup_expired_sessions(self):
        """Clean up expired sessions."""
        import time

        current_time = time.time()
        expired = [
            sid for sid, info in self._sessions.items() if info.get("expires_at", 0) < current_time
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)


class MockSessionContext:
    """Enhanced mock session context manager with proper context variable handling."""

    def __init__(self, session_manager, session_id=None, user_id=None, auto_create=True):
        self.session_manager = session_manager
        self.session_id = session_id
        self.user_id = user_id
        self.auto_create = auto_create
        self.previous_session = None
        self.previous_user = None

    async def __aenter__(self):
        # Save previous context - CRITICAL: Save from context vars, not manager
        self.previous_session = mock_session_ctx.get()
        self.previous_user = mock_user_ctx.get()

        if self.session_id:
            if not await self.session_manager.validate_session(self.session_id):
                raise ValueError(f"Session {self.session_id} is invalid")
            self.session_manager.set_current_session(self.session_id, self.user_id)
            return self.session_id
        elif self.auto_create:
            session_id = await self.session_manager.auto_create_session_if_needed(self.user_id)
            return session_id
        else:
            raise ValueError("No session provided and auto_create=False")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Restore previous context - CRITICAL: Restore to context vars AND manager
        if self.previous_session:
            mock_session_ctx.set(self.previous_session)
            mock_user_ctx.set(self.previous_user)
            self.session_manager._current_session = self.previous_session
        else:
            mock_session_ctx.set(None)
            mock_user_ctx.set(None)
            self.session_manager._current_session = None


# Mock session helper functions with proper context variable access
def mock_require_session():
    """Mock require_session that uses the actual context variables."""
    session_id = mock_session_ctx.get()
    if not session_id:
        # Import the actual exception class
        from tests.conftest import MockSessionError

        raise MockSessionError("No session context available")
    return session_id


def mock_get_session_or_none():
    """Mock get_session_or_none that uses context variables."""
    return mock_session_ctx.get()


def mock_get_user_or_none():
    """Mock get_user_or_none that uses context variables."""
    return mock_user_ctx.get()


def mock_require_user():
    """Mock require_user that uses the actual user context variable."""
    user_id = mock_user_ctx.get()
    if not user_id:
        from tests.conftest import MockSessionError

        raise MockSessionError("No user context available - authentication required")
    return user_id


def mock_set_user_context(user_id):
    """Mock set_user_context - sets mock_user_ctx and returns a reset token."""
    return mock_user_ctx.set(user_id)


def mock_reset_user_context(token):
    """Mock reset_user_context - resets mock_user_ctx using the token."""
    mock_user_ctx.reset(token)


# Mock session auto-injection helper
async def mock_with_session_auto_inject(session_manager, tool_name, args, tool_func=None):
    """Mock session injection for artifact tools."""
    artifact_tools = {
        "upload_file",
        "write_file",
        "read_file",
        "delete_file",
        "list_session_files",
        "list_directory",
        "copy_file",
        "move_file",
        "get_file_metadata",
        "get_presigned_url",
        "get_storage_stats",
    }

    if tool_name in artifact_tools and "session_id" not in args:
        session_id = await session_manager.auto_create_session_if_needed()
        return {**args, "session_id": session_id}
    return args


# Mock the decorators
def mock_session_required(func):
    """Mock session_required decorator."""

    async def wrapper(*args, **kwargs):
        session_id = mock_get_session_or_none()
        if not session_id:
            from tests.conftest import MockSessionError

            raise MockSessionError(f"Tool '{func.__name__}' requires session context")
        return await func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


def mock_session_optional(func):
    """Mock session_optional decorator."""

    async def wrapper(*args, **kwargs):
        return await func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


# Exception classes
class MockSessionError(Exception):
    """Mock SessionError for testing."""

    pass


class MockSessionNotFoundError(MockSessionError):
    """Mock SessionNotFoundError for testing."""

    pass


class MockSessionValidationError(MockSessionError):
    """Mock SessionValidationError for testing."""

    pass


# Mock the validate_session_parameter function for artifacts_tools.py
def mock_validate_session_parameter(session_id=None, operation="unknown"):
    """Mock validate_session_parameter for artifact tools."""
    if session_id:
        return session_id

    current = mock_get_session_or_none()
    if current:
        return current

    raise MockSessionError(f"Operation '{operation}' requires valid session_id or session context")


# Create session management module mock with all components
session_mgmt_mod = MagicMock()
session_mgmt_mod.MCPSessionManager = MockMCPSessionManager
session_mgmt_mod.SessionContext = MockSessionContext


def _create_mock_session_manager(config):
    """Create mock session manager from RuntimeConfig or dict."""
    if config is None:
        return MockMCPSessionManager(sandbox_id=None, default_ttl_hours=24)

    # Handle RuntimeConfig
    if hasattr(config, "sessions"):
        return MockMCPSessionManager(
            sandbox_id=config.sessions.sandbox_id,
            default_ttl_hours=config.sessions.default_ttl_hours,
        )

    # Handle dict
    return MockMCPSessionManager(
        sandbox_id=config.get("sessions", {}).get("sandbox_id"),
        default_ttl_hours=config.get("sessions", {}).get("default_ttl_hours", 24),
    )


session_mgmt_mod.create_mcp_session_manager = _create_mock_session_manager

# Add context variables and helper functions
session_mgmt_mod._session_ctx = mock_session_ctx
session_mgmt_mod._user_ctx = mock_user_ctx
session_mgmt_mod.require_session = mock_require_session
session_mgmt_mod.require_user = mock_require_user
session_mgmt_mod.get_session_or_none = mock_get_session_or_none
session_mgmt_mod.get_user_or_none = mock_get_user_or_none
session_mgmt_mod.set_user_context = mock_set_user_context
session_mgmt_mod.reset_user_context = mock_reset_user_context
session_mgmt_mod.with_session_auto_inject = mock_with_session_auto_inject
session_mgmt_mod.session_required = mock_session_required
session_mgmt_mod.session_optional = mock_session_optional
session_mgmt_mod.SessionError = MockSessionError
session_mgmt_mod.SessionNotFoundError = MockSessionNotFoundError
session_mgmt_mod.SessionValidationError = MockSessionValidationError
session_mgmt_mod.validate_session_parameter = mock_validate_session_parameter

# Register the session management module
sys.modules["chuk_mcp_runtime.session.native_session_management"] = session_mgmt_mod


# Mock proxy manager
class MockProxyServerManager:
    """Mock implementation of ProxyServerManager for testing."""

    def __init__(self, config, project_root):
        self.running_servers = {}
        self.running = {}  # Add this for compatibility
        self.config = config
        self.project_root = project_root
        # Handle both RuntimeConfig and dict
        if hasattr(config, "proxy"):
            self.openai_mode = config.proxy.openai_compatible
        else:
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


# Create a proxy manager module with the mock class
proxy_manager_mod = MagicMock()
proxy_manager_mod.ProxyServerManager = MockProxyServerManager
sys.modules["chuk_mcp_runtime.proxy.manager"] = proxy_manager_mod

# Import necessary modules for testing
import asyncio

import pytest


# Other mock classes for server components
class DummyServerRegistry:
    def __init__(self, project_root, config):
        self.project_root = project_root
        self.config = config
        self.bootstrap_called = False

    async def load_server_components(self):
        self.bootstrap_called = True
        return {}


class DummyMCPServer:
    def __init__(self, config, tools_registry=None):
        self.config = config
        self.serve_called = False
        self.server_name = "test-server"
        self.registered_tools = []
        self.tools_registry = tools_registry or {}
        # Add session manager with proper configuration - handle both RuntimeConfig and dict
        if hasattr(config, "sessions"):
            self.session_manager = MockMCPSessionManager(
                sandbox_id=config.sessions.sandbox_id,
                default_ttl_hours=config.sessions.default_ttl_hours,
            )
        else:
            session_config = config.get("sessions", {})
            self.session_manager = MockMCPSessionManager(
                sandbox_id=session_config.get("sandbox_id"),
                default_ttl_hours=session_config.get("default_ttl_hours", 24),
            )

    async def serve(self, custom_handlers=None):
        self.serve_called = True
        self.custom_handlers = custom_handlers

    async def register_tool(self, name, func):
        self.registered_tools.append(name)
        self.tools_registry[name] = func

    def get_session_manager(self):
        return self.session_manager

    async def create_user_session(self, user_id, metadata=None):
        return await self.session_manager.create_session(user_id=user_id, metadata=metadata)


# Helper function to safely run async code in tests
def run_async(coro):
    """Run an async coroutine in tests safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)


class AsyncMockHelper(MagicMock):
    """MagicMock subclass with async __call__ / context-manager support.

    Named AsyncMockHelper (not TestAsyncMock) so pytest does not mistake it
    for a test class and emit PytestCollectionWarning.
    """

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)

    async def __aenter__(self, *args, **kwargs):
        return self.__enter__(*args, **kwargs)

    async def __aexit__(self, *args, **kwargs):
        return self.__exit__(*args, **kwargs)


# Pytest fixtures
@pytest.fixture(scope="session", autouse=True)
def ensure_mocked_modules():
    """Ensure that all required modules are mocked."""
    yield
    # Clean up mocks after tests
    for module in list(sys.modules.keys()):
        if module.startswith(("chuk_tool_processor", "chuk_sessions", "chuk_artifacts")):
            del sys.modules[module]


@pytest.fixture
def clear_tools_registry():
    """Clear the tools registry before and after tests."""
    from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY

    # Clear before test
    saved_registry = dict(TOOLS_REGISTRY)
    TOOLS_REGISTRY.clear()

    yield

    # Restore after test
    TOOLS_REGISTRY.clear()
    TOOLS_REGISTRY.update(saved_registry)


@pytest.fixture
def mock_session_manager():
    """Provide a mock session manager for tests."""
    return MockMCPSessionManager()


@pytest.fixture
def mock_session_context():
    """Provide a mock session context factory."""

    def _create_context(session_manager, session_id=None, user_id=None, auto_create=True):
        return MockSessionContext(session_manager, session_id, user_id, auto_create)

    return _create_context


@pytest.fixture
def mock_proxy_manager():
    """Provide a mock proxy manager for tests."""

    def _create_proxy(config=None, project_root="/tmp"):
        return MockProxyServerManager(config or {}, project_root)

    return _create_proxy


@pytest.fixture
def session_context_manager():
    """Provide a session context manager that properly handles context variables."""

    async def create_session_context(
        session_manager, session_id=None, user_id=None, auto_create=True
    ):
        context = MockSessionContext(session_manager, session_id, user_id, auto_create)
        return context

    return create_session_context


@pytest.fixture
def clean_session_context():
    """Clean session context before and after tests."""
    # Clear context before test
    mock_session_ctx.set(None)
    mock_user_ctx.set(None)

    yield

    # Clear context after test
    mock_session_ctx.set(None)
    mock_user_ctx.set(None)


@pytest.fixture
def create_test_server():
    """Factory fixture for creating test servers."""

    def _create_server(config=None):
        default_config = {
            "sessions": {"sandbox_id": "test-server"},
            "artifacts": {"enabled": False},
            "proxy": {"enabled": False},
        }
        if config:
            default_config.update(config)
        return DummyMCPServer(default_config)

    return _create_server


# Export commonly used classes for test modules
__all__ = [
    "ArtifactNotFoundError",
    "ArtifactMetadata",
    "MockArtifactStore",
    "MockMCPSessionManager",
    "MockSessionContext",
    "MockProxyServerManager",
    "DummyMCPServer",
    "DummyServerRegistry",
    "AsyncMockHelper",
    "run_async",
    "mock_require_session",
    "mock_require_user",
    "mock_get_session_or_none",
    "mock_get_user_or_none",
    "mock_set_user_context",
    "mock_reset_user_context",
    "mock_session_required",
    "mock_session_optional",
    "MockSessionError",
    "MockSessionNotFoundError",
    "MockSessionValidationError",
    "mock_session_ctx",
    "mock_user_ctx",
]
