"""
CHUK MCP Runtime Types

Pydantic models for type-safe configuration and data structures.
All models are async-native and designed for library consumers.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ─────────────────────────── Enums ──────────────────────────────


class ServerType(str, Enum):
    """MCP server transport type."""

    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


class LogLevel(str, Enum):
    """Logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class StorageProvider(str, Enum):
    """Artifact storage providers."""

    FILESYSTEM = "filesystem"
    S3 = "s3"
    IBM_COS = "ibm-cos"
    MEMORY = "memory"


class SessionProvider(str, Enum):
    """Session management providers."""

    MEMORY = "memory"
    REDIS = "redis"
    DYNAMODB = "dynamodb"


class AuthType(str, Enum):
    """Authentication types."""

    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"


# ─────────────────────────── Configuration Models ──────────────────────────────


class HostConfig(BaseModel):
    """Host configuration."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    name: str = Field(default="generic-mcp-server", description="Server name")
    log_level: LogLevel = Field(default=LogLevel.INFO, description="Host log level")


class LoggingConfig(BaseModel):
    """Logging configuration."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    level: LogLevel = Field(default=LogLevel.INFO, description="Log level")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format string",
    )
    reset_handlers: bool = Field(
        default=True, description="Reset existing handlers on initialization"
    )
    quiet_libraries: bool = Field(
        default=True, description="Suppress noisy third-party library logs"
    )
    loggers: dict[str, str] = Field(default_factory=dict, description="Per-logger level overrides")


class ServerConfig(BaseModel):
    """Server transport configuration."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    type: ServerType = Field(default=ServerType.STDIO, description="Transport type")
    auth: Optional[AuthType] = Field(default=None, description="Authentication type")


# Large enough for tool arguments carrying base64 files or images; None disables the limit
DEFAULT_MAX_REQUEST_BODY_SIZE = 50 * 1024 * 1024


class SSEConfig(BaseModel):
    """SSE transport configuration."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    host: str = Field(default="0.0.0.0", description="SSE server host")  # nosec B104
    port: int = Field(default=8000, description="SSE server port", ge=1, le=65535)
    sse_path: str = Field(default="/sse", description="SSE endpoint path")
    message_path: str = Field(default="/messages/", description="Message endpoint path")
    health_path: str = Field(default="/health", description="Health check path")
    log_level: Optional[str] = Field(default=None, description="Server-specific log level")
    access_log: bool = Field(default=False, description="Enable access logging")
    max_request_body_size: Optional[int] = Field(
        default=DEFAULT_MAX_REQUEST_BODY_SIZE,
        description="Max POST body in bytes (None = no limit)",
        gt=0,
    )


class StreamableHTTPConfig(BaseModel):
    """Streamable HTTP transport configuration."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    host: str = Field(default="127.0.0.1", description="HTTP server host")
    port: int = Field(default=3000, description="HTTP server port", ge=1, le=65535)
    mcp_path: str = Field(default="/mcp", description="MCP endpoint path")
    json_response: bool = Field(default=True, description="Use JSON responses")
    stateless: bool = Field(default=True, description="Stateless mode")
    health_path: Optional[str] = Field(default=None, description="Health check path")
    log_level: Optional[str] = Field(default=None, description="Server-specific log level")
    access_log: bool = Field(default=False, description="Enable access logging")
    max_request_body_size: Optional[int] = Field(
        default=DEFAULT_MAX_REQUEST_BODY_SIZE,
        description="Max request body in bytes (None = no limit)",
        gt=0,
    )
    # Stateful sessions only (stateless: false); None keeps mcp 1.x behaviour
    session_idle_timeout: Optional[float] = Field(
        default=None, description="Close stateful sessions idle for this many seconds", gt=0
    )
    max_sessions: Optional[int] = Field(
        default=None, description="Max concurrent stateful sessions (None = no limit)", gt=0
    )


class ToolsConfig(BaseModel):
    """Tools registry configuration."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    registry_module: str = Field(
        default="chuk_mcp_runtime.common.mcp_tool_decorator",
        description="Module containing tools registry",
    )
    registry_attr: str = Field(default="TOOLS_REGISTRY", description="Registry attribute name")
    timeout: Optional[float] = Field(
        default=None, description="Global tool timeout in seconds", ge=0
    )


class ProxyConfig(BaseModel):
    """Proxy configuration for remote MCP servers."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    enabled: bool = Field(default=False, description="Enable proxy functionality")
    namespace: str = Field(default="proxy", description="Proxy tool namespace")
    keep_root_aliases: bool = Field(default=False, description="Keep root-level tool aliases")
    openai_compatible: bool = Field(
        default=False, description="Generate OpenAI-compatible tool definitions"
    )
    only_openai_tools: bool = Field(
        default=False, description="Only expose OpenAI-compatible tools"
    )

    @field_validator("only_openai_tools")
    @classmethod
    def validate_only_openai_tools(cls, v: bool, info) -> bool:
        """Ensure only_openai_tools is false if openai_compatible is false."""
        if v and not info.data.get("openai_compatible", False):
            return False
        return v


class SessionsConfig(BaseModel):
    """Session management configuration."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    sandbox_id: Optional[str] = Field(default=None, description="Sandbox identifier")
    default_ttl_hours: int = Field(default=24, description="Default session TTL in hours", ge=1)
    auto_extend_threshold: float = Field(
        default=0.1,
        description="Auto-extend threshold (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )


class ArtifactsConfig(BaseModel):
    """Artifacts storage configuration."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    enabled: bool = Field(default=False, description="Enable artifact storage")
    storage_provider: StorageProvider = Field(
        default=StorageProvider.FILESYSTEM, description="Storage backend"
    )
    session_provider: SessionProvider = Field(
        default=SessionProvider.MEMORY, description="Session provider"
    )
    bucket: Optional[str] = Field(default=None, description="Storage bucket name")
    filesystem_root: Optional[str] = Field(
        default=None, description="Filesystem storage root directory"
    )
    tools: dict[str, Any] = Field(default_factory=dict, description="Per-tool configuration")


class MCPServerConfig(BaseModel):
    """Remote MCP server configuration.

    Supports both STDIO and SSE server types with flexible configuration.
    Uses extra="allow" to support custom fields like url, api_key, etc.
    """

    model_config = ConfigDict(extra="allow", frozen=False)

    # Common fields
    command: str = Field(default="", description="Command to start the server")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables")
    location: Optional[str] = Field(default=None, description="Working directory for the server")
    type: str = Field(default="stdio", description="Server type (stdio, sse, etc.)")
    enabled: bool = Field(default=True, description="Whether the server is enabled")

    # SSE-specific fields (optional, via extra="allow")
    url: Optional[str] = Field(default=None, description="SSE endpoint URL")
    api_key: Optional[str] = Field(default=None, description="API key for authentication")

    # Component configurations (tools, resources, prompts)
    tools: Optional[dict[str, Any]] = Field(default=None, description="Tools configuration")
    resources: Optional[dict[str, Any]] = Field(default=None, description="Resources configuration")
    prompts: Optional[dict[str, Any]] = Field(default=None, description="Prompts configuration")


class RuntimeConfig(BaseModel):
    """Complete MCP runtime configuration."""

    model_config = ConfigDict(extra="allow", frozen=False)

    host: HostConfig = Field(default_factory=HostConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    artifacts: ArtifactsConfig = Field(default_factory=ArtifactsConfig)
    sse: SSEConfig = Field(default_factory=SSEConfig)
    streamable_http: StreamableHTTPConfig = Field(
        default_factory=StreamableHTTPConfig, alias="streamable-http"
    )
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
    session_tools: dict[str, Any] = Field(
        default_factory=dict, description="Session tools configuration"
    )

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> RuntimeConfig:
        """Create from legacy dict config (backwards compatibility)."""
        return cls.model_validate(config)

    def to_dict(self) -> dict[str, Any]:
        """Export to dict (backwards compatibility)."""
        return self.model_dump(by_alias=True, exclude_none=True)


# ─────────────────────────── Session Models ──────────────────────────────


class SessionInfo(BaseModel):
    """Session information."""

    model_config = ConfigDict(extra="allow", frozen=False)

    session_id: str = Field(description="Session identifier")
    user_id: Optional[str] = Field(default=None, description="User identifier")
    created_at: float = Field(description="Creation timestamp")
    expires_at: float = Field(description="Expiration timestamp")
    last_accessed: float = Field(description="Last access timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Session metadata")


class SessionStats(BaseModel):
    """Session statistics."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    sandbox_id: str = Field(description="Sandbox identifier")
    active_sessions: int = Field(description="Number of active sessions", ge=0)
    cache_size: int = Field(description="Cache size", ge=0)
    cache_hits: int = Field(default=0, description="Cache hits", ge=0)
    cache_misses: int = Field(default=0, description="Cache misses", ge=0)


# ─────────────────────────── Tool Models ──────────────────────────────


class ToolMetadata(BaseModel):
    """Tool metadata."""

    model_config = ConfigDict(extra="allow", frozen=False)

    name: str = Field(description="Tool name")
    description: str = Field(description="Tool description")
    input_schema: dict[str, Any] = Field(description="Input JSON schema")
    timeout: Optional[float] = Field(default=None, description="Tool-specific timeout", ge=0)


class ToolCallResult(BaseModel):
    """Result from a tool call."""

    model_config = ConfigDict(extra="allow", frozen=False)

    content: Any = Field(description="Tool result content")
    is_error: bool = Field(default=False, description="Whether result is an error")
    error: Optional[str] = Field(default=None, description="Error message if is_error=True")
    session_id: Optional[str] = Field(default=None, description="Session ID if applicable")
    meta: Optional[dict[str, Any]] = Field(default=None, description="Additional metadata")


# ─────────────────────────── Request Context Models ──────────────────────────────


class MCPRequestContext(BaseModel):
    """MCP request context for progress notifications."""

    model_config = ConfigDict(extra="allow", frozen=False, arbitrary_types_allowed=True)

    session: Optional[Any] = Field(default=None, description="MCP session object")
    progress_token: Optional[str] = Field(default=None, description="Progress token")
    meta: Optional[Any] = Field(default=None, description="Request metadata")


# ─────────────────────────── Artifact Models ──────────────────────────────


class ArtifactMetadata(BaseModel):
    """Artifact metadata."""

    model_config = ConfigDict(extra="allow", frozen=False)

    artifact_id: str = Field(description="Artifact identifier")
    filename: str = Field(description="Original filename")
    mime: str = Field(default="application/octet-stream", description="MIME type")
    size: int = Field(description="File size in bytes", ge=0)
    session_id: Optional[str] = Field(default=None, description="Session ID")
    user_id: Optional[str] = Field(default=None, description="User ID")
    created_at: float = Field(description="Creation timestamp")
    summary: str = Field(default="", description="Artifact description")


class StorageStats(BaseModel):
    """Storage statistics."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    total_artifacts: int = Field(description="Total number of artifacts", ge=0)
    total_size: int = Field(description="Total size in bytes", ge=0)
    session_artifacts: int = Field(default=0, description="Session-specific artifacts", ge=0)
    session_size: int = Field(default=0, description="Session-specific size", ge=0)


# ─────────────────────────── Export All Types ──────────────────────────────


__all__ = [
    # Enums
    "ServerType",
    "LogLevel",
    "StorageProvider",
    "SessionProvider",
    "AuthType",
    # Configuration
    "HostConfig",
    "LoggingConfig",
    "ServerConfig",
    "SSEConfig",
    "StreamableHTTPConfig",
    "ToolsConfig",
    "ProxyConfig",
    "SessionsConfig",
    "ArtifactsConfig",
    "MCPServerConfig",
    "RuntimeConfig",
    # Sessions
    "SessionInfo",
    "SessionStats",
    # Tools
    "ToolMetadata",
    "ToolCallResult",
    # Request Context
    "MCPRequestContext",
    # Artifacts
    "ArtifactMetadata",
    "StorageStats",
]
