# chuk_mcp_runtime/session/native_session_management.py
"""
Native chuk-sessions integration for CHUK MCP Runtime.

This module replaces the bridge pattern with direct chuk-sessions usage,
providing cleaner, more efficient session management.
"""

from __future__ import annotations

import os
import time
from contextvars import ContextVar
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional, Union

from chuk_sessions import SessionManager
from chuk_sessions.models import SessionMetadata

from chuk_mcp_runtime.server.logging_config import get_logger

if TYPE_CHECKING:
    from chuk_mcp_runtime.types import RuntimeConfig

logger = get_logger("chuk_mcp_runtime.session.native")

# ───────────────────────── Context Variables ──────────────────────────
_session_ctx: ContextVar[Optional[str]] = ContextVar("session_context", default=None)
_user_ctx: ContextVar[Optional[str]] = ContextVar("user_context", default=None)


# ───────────────────────── Exception Types ─────────────────────────────
class SessionError(Exception):
    """Base exception for session-related errors."""

    pass


class SessionNotFoundError(SessionError):
    """Session does not exist or has expired."""

    pass


class SessionValidationError(SessionError):
    """Session validation failed."""

    pass


# ───────────────────────── Native Session Manager ──────────────────────
class MCPSessionManager:
    """
    Native session manager for MCP Runtime using chuk-sessions.

    Provides clean, efficient session management without bridge complexity.
    """

    def __init__(
        self,
        sandbox_id: Optional[str] = None,
        default_ttl_hours: int = 24,
        auto_extend_threshold: float = 0.1,  # Extend when 10% of TTL remains
    ):
        self.sandbox_id = sandbox_id or self._infer_sandbox_id()
        self.default_ttl_hours = default_ttl_hours
        self.auto_extend_threshold = auto_extend_threshold
        self._last_session: Optional[str] = None  # Track last used session for auto-reuse
        self._last_session_user: Optional[str] = None  # Track which user owns _last_session

        # Create the underlying SessionManager
        self._session_manager = SessionManager(
            sandbox_id=self.sandbox_id, default_ttl_hours=default_ttl_hours
        )

        logger.debug(f"Initialized MCPSessionManager for sandbox: {self.sandbox_id}")

    def _infer_sandbox_id(self) -> str:
        """Infer sandbox ID from environment or generate one."""
        sandbox = (
            os.getenv("MCP_SANDBOX_ID")
            or os.getenv("CHUK_SANDBOX_ID")
            or os.getenv("SANDBOX_ID")
            or os.getenv("POD_NAME")
            or f"mcp-runtime-{int(time.time())}"
        )
        return sandbox

    # ─────────────────── Session Lifecycle ───────────────────────

    async def create_session(
        self,
        user_id: Optional[str] = None,
        ttl_hours: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Create a new session with optional user and metadata."""
        session_id = await self._session_manager.allocate_session(
            user_id=user_id,
            ttl_hours=ttl_hours or self.default_ttl_hours,
            custom_metadata=metadata or {},
        )

        logger.debug(f"Created session {session_id} for user {user_id}")
        return session_id

    async def get_session_info(self, session_id: str) -> dict[str, Any]:
        """
        Get complete session information.

        Returns session info as a dict for backwards compatibility.
        Use get_session_metadata() for typed SessionMetadata return.
        """
        info = await self._session_manager.get_session_info(session_id)
        if not info:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return info

    async def get_session_metadata(self, session_id: str) -> SessionMetadata:
        """
        Get complete session information as typed SessionMetadata.

        This is the typed version that returns the Pydantic model directly.
        For backwards compatibility, use get_session_info() which returns dict.
        """
        # Use the public method from chuk-sessions
        metadata = await self._session_manager.get_session_metadata(session_id)
        if not metadata:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return metadata

    async def validate_session(self, session_id: str) -> bool:
        """Validate that a session exists and hasn't expired."""
        return await self._session_manager.validate_session(session_id)

    async def extend_session(self, session_id: str, additional_hours: int = None) -> bool:
        """Extend session TTL."""
        hours = additional_hours or self.default_ttl_hours
        return await self._session_manager.extend_session_ttl(session_id, hours)

    async def update_session_metadata(self, session_id: str, metadata: dict[str, Any]) -> bool:
        """Update session metadata."""
        return await self._session_manager.update_session_metadata(session_id, metadata)

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        success = await self._session_manager.delete_session(session_id)
        if success:
            logger.debug(f"Deleted session {session_id}")
        return success

    # ─────────────────── Context Management ───────────────────────

    def set_current_session(self, session_id: str, user_id: Optional[str] = None):
        """Set the current session context."""
        _session_ctx.set(session_id)
        if user_id:
            _user_ctx.set(user_id)
        logger.debug(f"Set session context to {session_id}")

    def get_current_session(self) -> Optional[str]:
        """Get the current session ID from context."""
        return _session_ctx.get()

    def get_current_user(self) -> Optional[str]:
        """Get the current user ID from context."""
        return _user_ctx.get()

    def clear_context(self):
        """Clear session and user context."""
        _session_ctx.set(None)
        _user_ctx.set(None)
        logger.debug("Cleared session context")

    async def auto_create_session_if_needed(self, user_id: Optional[str] = None) -> str:
        """Auto-create session if none exists in context."""
        current = self.get_current_session()

        if current and await self.validate_session(current):
            # Check if session needs extension
            await self._maybe_extend_session(current)
            self._last_session = current
            return current

        # Try to reuse last session if still valid (for stdio requests without context vars).
        # Never reuse across users: a session owned by user A must not be given to user B.
        if self._last_session and await self.validate_session(self._last_session):
            if user_id is None or user_id == self._last_session_user:
                logger.debug(f"Reusing last session {self._last_session}")
                self.set_current_session(self._last_session, user_id)
                return self._last_session

        # Create new session
        session_id = await self.create_session(
            user_id=user_id,
            metadata={
                "auto_created": True,
                "created_at": time.time(),
                "mcp_version": "0.2.0",
            },
        )

        self.set_current_session(session_id, user_id)
        self._last_session = session_id
        self._last_session_user = user_id
        logger.debug(f"Auto-created session {session_id} for user {user_id}")
        return session_id

    async def _maybe_extend_session(self, session_id: str):
        """Extend session if it's close to expiring."""
        try:
            info = await self.get_session_info(session_id)
            expires_at = info.get("expires_at")
            created_at = info.get("created_at")

            if expires_at and created_at:
                # Convert to Unix timestamp if they're ISO format strings
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(
                        expires_at.replace("Z", "+00:00")
                    ).timestamp()
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    ).timestamp()

                # Calculate remaining time as percentage
                total_ttl = expires_at - created_at
                remaining = expires_at - time.time()
                remaining_ratio = remaining / total_ttl

                if remaining_ratio < self.auto_extend_threshold:
                    await self.extend_session(session_id)
                    logger.debug(f"Auto-extended session {session_id}")

        except Exception as e:
            logger.warning(f"Failed to check/extend session {session_id}: {e}")

    # ─────────────────── Admin & Monitoring ───────────────────────

    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions."""
        return await self._session_manager.cleanup_expired_sessions()

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return self._session_manager.get_cache_stats()

    async def list_active_sessions(self) -> dict[str, Any]:
        """List active sessions (admin function)."""
        stats = self.get_cache_stats()
        return {
            "sandbox_id": self.sandbox_id,
            "active_sessions": stats.get("cache_size", 0),
            "cache_stats": stats,
        }


# ───────────────────────── Context Managers ─────────────────────────────


class SessionContext:
    """Async context manager for session operations."""

    def __init__(
        self,
        session_manager: MCPSessionManager,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        auto_create: bool = True,
    ):
        self.session_manager = session_manager
        self.session_id = session_id
        self.user_id = user_id
        self.auto_create = auto_create
        self.previous_session: str | None = None
        self.previous_user: str | None = None
        self.created_new_session = False  # Track if we created a new session

    async def __aenter__(self) -> str:
        # Save previous context
        self.previous_session = self.session_manager.get_current_session()
        self.previous_user = self.session_manager.get_current_user()
        logger.debug(f"[SessionContext.__aenter__] previous_session={self.previous_session}")

        # Set new context
        if self.session_id:
            # Use provided session
            if not await self.session_manager.validate_session(self.session_id):
                raise SessionValidationError(f"Session {self.session_id} is invalid")
            self.session_manager.set_current_session(self.session_id, self.user_id)
            logger.debug(f"[SessionContext.__aenter__] Using provided session {self.session_id}")
            return self.session_id
        elif self.auto_create:
            # Auto-create session
            current_before = self.session_manager.get_current_session()
            session_id = await self.session_manager.auto_create_session_if_needed(self.user_id)
            # Track if we created a new session (vs reusing existing)
            self.created_new_session = current_before is None
            logger.debug(
                f"[SessionContext.__aenter__] Auto-created/reused session {session_id}, "
                f"created_new={self.created_new_session}"
            )
            return session_id
        else:
            raise SessionError("No session provided and auto_create=False")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Restore previous context
        current = self.session_manager.get_current_session()
        logger.debug(
            f"[SessionContext.__aexit__] current={current}, previous={self.previous_session}, "
            f"created_new={self.created_new_session}"
        )

        # Only restore/clear if we had a previous session (nested context)
        # Otherwise, keep the current session for subsequent requests
        if self.previous_session and self.previous_session != current:
            # Nested context - restore the outer session
            self.session_manager.set_current_session(self.previous_session, self.previous_user)
            logger.debug(
                f"[SessionContext.__aexit__] Restored previous session {self.previous_session}"
            )
        else:
            # Top-level context - keep the session for next request
            logger.debug(f"[SessionContext.__aexit__] Keeping current session {current}")


# ───────────────────────── Tool Integration Helpers ─────────────────────


def require_session() -> str:
    """Get current session or raise error."""
    session_id = _session_ctx.get()
    if not session_id:
        raise SessionError("No session context available")
    return session_id


def require_user() -> str:
    """Get current user or raise error."""
    user_id = _user_ctx.get()
    if not user_id:
        raise SessionError("No user context available - authentication required")
    return user_id


def get_session_or_none() -> Optional[str]:
    """Get current session or None."""
    return _session_ctx.get()


def get_user_or_none() -> Optional[str]:
    """Get current user or None."""
    return _user_ctx.get()


def set_user_context(user_id: Optional[str]) -> Any:
    """Set the user context. Returns a ContextVar token for later reset."""
    return _user_ctx.set(user_id)


def reset_user_context(token: Any) -> None:
    """Reset the user context to its previous value using the token from set_user_context."""
    _user_ctx.reset(token)


def _is_proxy_tool(func: Any) -> bool:
    """
    Check if a tool is a proxy tool (forwards to remote MCP server).

    Proxy tools have _proxy_server attribute set by create_proxy_tool().
    """
    return hasattr(func, "_proxy_server")


async def with_session_auto_inject(
    session_manager: MCPSessionManager,
    tool_name: str,
    arguments: dict[str, Any],
    tool_func: Any = None,
) -> dict[str, Any]:
    """
    Auto-inject session_id into tool arguments if needed.

    Session management strategy:
    1. **Proxy tools** (remote MCP servers): NO injection - use MCP protocol sessions
    2. **Context-based tools** (artifacts, etc.): NO injection - use require_session()
    3. **Legacy internal tools**: Only inject if explicitly needed

    Args:
        session_manager: The session manager instance
        tool_name: Name of the tool being called
        arguments: Tool arguments
        tool_func: Optional tool function to inspect signature
    """
    # PROXY TOOLS: Never inject session_id - use MCP protocol sessions
    if tool_func and _is_proxy_tool(tool_func):
        logger.debug(
            f"Skipping session_id injection for proxy tool '{tool_name}' - "
            "using MCP protocol session management"
        )
        # Still ensure session context is set for runtime
        await session_manager.auto_create_session_if_needed()
        return arguments

    # ALL artifact tools now use context-based session management
    # List all artifact tools that DON'T need session_id injection
    CONTEXT_BASED_TOOLS = {
        # All artifact tools use context (NO injection needed):
        "upload_file",  # uses require_session/get_session_or_none
        "write_file",  # uses require_session/get_session_or_none
        "read_file",  # uses get_session_or_none
        "delete_file",  # uses get_session_or_none
        "list_session_files",  # uses require_session
        "list_directory",  # uses require_session
        "copy_file",  # uses require_session
        "move_file",  # uses require_session
        "get_file_metadata",  # uses require_session
        "get_presigned_url",  # uses require_session
        "get_storage_stats",  # uses get_session_or_none/get_user_or_none
        "upload_session_file",  # uses require_session
        "write_session_file",  # uses require_session
        "upload_user_file",  # uses require_user
        "write_user_file",  # uses require_user
        "list_user_files",  # uses require_user
    }

    if tool_name in CONTEXT_BASED_TOOLS:
        # These tools use context - no injection needed
        return arguments

    # If session_id already provided, use it
    if "session_id" in arguments:
        session_id = arguments["session_id"]
        if session_id and await session_manager.validate_session(session_id):
            session_manager.set_current_session(session_id)
            return arguments

    # For any other tools, just ensure session context exists
    # Don't inject unless explicitly needed
    await session_manager.auto_create_session_if_needed()
    return arguments


# ───────────────────────── Decorators ─────────────────────────────────


def session_required(func):
    """Decorator to require valid session context."""

    async def wrapper(*args, **kwargs):
        session_id = get_session_or_none()
        if not session_id:
            raise SessionError(f"Tool '{func.__name__}' requires session context")
        return await func(*args, **kwargs)

    return wrapper


def session_optional(func):
    """Decorator for tools that can work with or without session."""

    async def wrapper(*args, **kwargs):
        # Just pass through - tools can check context themselves
        return await func(*args, **kwargs)

    return wrapper


# ───────────────────────── Factory Function ─────────────────────────────


def create_mcp_session_manager(
    config: Optional[Union[RuntimeConfig, dict[str, Any]]] = None,
) -> MCPSessionManager:
    """
    Factory function to create session manager from config.

    Args:
        config: RuntimeConfig instance or dict (for backwards compatibility)

    Returns:
        MCPSessionManager instance
    """
    if config is None:
        # Import here to avoid circular dependency
        from chuk_mcp_runtime.types import RuntimeConfig

        config = RuntimeConfig()
    elif isinstance(config, dict):
        # Convert dict to RuntimeConfig for backwards compatibility
        from chuk_mcp_runtime.types import RuntimeConfig

        config = RuntimeConfig.from_dict(config)

    return MCPSessionManager(
        sandbox_id=config.sessions.sandbox_id,
        default_ttl_hours=config.sessions.default_ttl_hours,
        auto_extend_threshold=config.sessions.auto_extend_threshold,
    )


# ───────────────────────── Backwards Compatibility ─────────────────────


# Keep these for existing code that imports from session_management
def set_session_context(session_id: str):
    """Legacy compatibility function."""
    _session_ctx.set(session_id)


def get_session_context() -> Optional[str]:
    """Legacy compatibility function."""
    return _session_ctx.get()


def clear_session_context():
    """Legacy compatibility function."""
    _session_ctx.set(None)


def validate_session_parameter(
    session_id: Optional[str],
    operation: str,
    session_manager: Optional[MCPSessionManager] = None,
) -> str:
    """Legacy compatibility with auto-creation."""
    if session_id:
        return session_id

    current = get_session_context()
    if current:
        return current

    if session_manager:
        # This would need to be made async in the calling code
        raise SessionError(f"Operation '{operation}' requires session_id or session manager")

    raise SessionError(f"Operation '{operation}' requires valid session_id")
