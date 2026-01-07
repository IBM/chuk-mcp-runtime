# CHUK MCP Runtime

**Version 0.10.4** - Pydantic-Native Artifact Integration

[![PyPI](https://img.shields.io/pypi/v/chuk-mcp-runtime.svg)](https://pypi.org/project/chuk-mcp-runtime/)
[![Test](https://github.com/chrishayuk/chuk-mcp-runtime/actions/workflows/test.yml/badge.svg)](https://github.com/chrishayuk/chuk-mcp-runtime/actions/workflows/test.yml)
![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Coverage](https://img.shields.io/badge/coverage-97%25-brightgreen)
![Official MCP SDK](https://img.shields.io/badge/built%20on-Official%20MCP%20SDK-blue)

A robust, production-ready runtime for the official Model Context Protocol (MCP) — adds proxying, session management, JWT auth, **persistent user storage with scopes**, and progress notifications.

> ✅ **Continuously tested against the latest official MCP SDK releases** for guaranteed protocol compatibility.

---

**CHUK MCP Runtime extends the official MCP SDK**, adding a battle-tested runtime layer for real deployments — without modifying or re-implementing the protocol.

## Architecture

```
┌──────────────────────────┐
│  Client / Agent          │
│  (Claude, OpenAI, etc.)  │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  CHUK MCP Runtime        │
│  - Proxy Manager         │
│  - Session Manager       │
│  - Artifact Storage      │
│  - Resource Provider     │
│  - JWT Auth & Progress   │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  MCP SDK Servers & Tools │
│  (Official MCP Protocol) │
└──────────────────────────┘
```

## Why CHUK MCP Runtime?

- 🔌 **Multi-Server Proxy** - Connect multiple MCP servers through one unified endpoint
- 🔐 **Secure by Default** - All built-in tools disabled unless explicitly enabled
- 🌐 **Universal Connectivity** - stdio, SSE, and HTTP transports supported
- 🔧 **OpenAI Compatible** - Transform MCP tools into OpenAI function calling format
- 📊 **Progress Notifications** - Real-time progress reporting for long operations
- ⚡ **Production Features** - Session isolation, timeout protection, JWT auth
- 📦 **Storage Scopes (NEW v0.9)** - Session (ephemeral), User (persistent), Sandbox (shared)

## Quick Start (30 seconds)

Run any official MCP server (like `mcp-server-time`) through the CHUK MCP Runtime proxy:

```bash
chuk-mcp-proxy --stdio time --command uvx -- mcp-server-time
```

That's it! You now have a running MCP proxy with tools like `proxy.time.get_current_time` (default 60s tool timeout).

> ℹ️ **Tip:** Everything after `--` is forwarded to the stdio child process (here: `mcp-server-time`).

> 💡 **Windows:** Install `uv` and use `uvx` from a shell with it on PATH, or replace `--command uvx -- mcp-server-time` with your Python launcher. Note that `mcp-server-time` may expose a Python module name like `mcp_server_time` depending on install method (e.g., `py -m mcp_server_time`).

### Hello World with Local Tools (10 seconds)

Create your first local MCP tool:

```python
# my_tools/tools.py
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool

@mcp_tool(name="greet", description="Say hi")
async def greet(name: str = "world") -> str:
    return f"Hello, {name}!"
```

```yaml
# config.yaml
server:
  type: "stdio"

mcp_servers:
  my_tools:
    enabled: true
    location: "./my_tools"
    tools:
      enabled: true
      module: "my_tools.tools"
```

```bash
# Run it (default 60s tool timeout)
chuk-mcp-server --config config.yaml
```

**Smoke test (stdio):**

```bash
# From a second terminal while chuk-mcp-server is running on stdio:
# Send tools/list over stdin and read stdout (minimal JSON-RPC roundtrip)
printf '%s\n' '{
  "jsonrpc":"2.0",
  "id": 1,
  "method":"tools/list",
  "params": {}
}'
```

## Installation

### Requirements
- Python 3.11+ (with `uv` recommended)
- On minimal distros/containers, install `tzdata` for timezone support
- (Optional) `jq` for pretty-printing JSON in curl examples

```bash
# Basic installation
uv pip install chuk-mcp-runtime

# With optional dependencies (installs dependencies for SSE/HTTP transports and development tooling)
uv pip install "chuk-mcp-runtime[websocket,dev]"

# Install tzdata for proper timezone support (containers, Alpine Linux)
uv pip install tzdata
```

## What Can You Build?

- **Multi-Server Gateway**: Expose multiple MCP servers (time, weather, GitHub, etc.) through one proxy
- **Enterprise MCP Services**: Add session management, persistent storage, and JWT auth to any MCP setup
- **OpenAI Bridge**: Transform any MCP server's tools into OpenAI-compatible function calls
- **Hybrid Architectures**: Run local Python tools alongside remote MCP servers
- **Progress-Aware Tools**: Build long-running operations with real-time client updates
- **Persistent User Files (NEW)**: Store user documents, prompts, and files that survive sessions

## Table of Contents

- [What's New in v0.10.4](#whats-new-in-v0104)
- [What's New in v0.9.0](#whats-new-in-v090)
- [Redis Cluster Support](#redis-cluster-support-new-in-v0104)
- [Key Concepts](#key-concepts)
- [Configuration Reference](#configuration-reference)
- [Proxy Configuration Examples](#proxy-configuration-examples)
- [Creating Local Tools](#creating-local-mcp-tools)
- [MCP Resources](#mcp-resources)
- [Progress Notifications](#progress-notifications)
- [Request Context & Headers](#request-context--headers)
- [Built-in Tools](#built-in-tool-categories)
- [Security Model](#security-model)
- [Environment Variables](#environment-variables)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

## What's New in v0.10.4

### 🎯 Pydantic-Native Artifact Integration

**Enhanced type safety and better developer experience** with full pydantic integration from `chuk-artifacts` 0.10.1+ (includes Redis Cluster support):

**Updated Dependencies**:
- `chuk-artifacts` 0.10.1 - Redis Cluster support, enhanced VFS providers
- `chuk-sessions` 0.6.0 - Redis Cluster support with automatic detection

#### ✅ Type-Safe Artifact Metadata

All artifact operations now use pydantic models internally:

```python
from chuk_artifacts.models import ArtifactMetadata

# Metadata is now a pydantic model with full validation
metadata: ArtifactMetadata = await store.metadata(artifact_id)

# Direct attribute access (type-safe)
print(f"Size: {metadata.bytes} bytes")
print(f"Type: {metadata.mime}")
print(f"Scope: {metadata.scope}")  # session | user | sandbox

# Pydantic serialization
metadata_dict = metadata.model_dump()  # Convert to dict
metadata_json = metadata.model_json()  # Convert to JSON
```

#### 🔧 What Changed

- **Internal improvements**: All artifact tools use pydantic models internally
- **Better performance**: Direct attribute access instead of dict lookups
- **Enhanced validation**: Automatic pydantic validation on all metadata
- **Zero breaking changes**: All existing code works unchanged (backward compatible)

#### 📊 Benefits

- ✅ **Type safety**: Full type hints with pydantic models
- ✅ **Better IDE support**: Autocomplete for all metadata fields
- ✅ **Automatic validation**: Pydantic ensures data integrity
- ✅ **Cleaner code**: Direct attribute access (`metadata.bytes` vs `metadata.get("bytes", 0)`)
- ✅ **100% backward compatible**: Dict-style access still works

#### 🔄 Compatibility

```python
# Both work - choose your style
size = metadata.bytes              # ✅ Pydantic (new, recommended)
size = metadata.get("bytes", 0)    # ✅ Dict-style (still works)
size = metadata["bytes"]           # ✅ Also works
```

## What's New in v0.9.0

### 🎉 Storage Scopes - The Game Changer

Three storage scopes for different use cases:

| Scope | Lifecycle | Use Case | Example |
|-------|-----------|----------|---------|
| **session** | Ephemeral (15min-24h) | Temporary work, caches | AI-generated code during chat |
| **user** | Persistent (1 year+) | User documents, saved files | Reports, custom prompts, uploads |
| **sandbox** | Shared (no expiry) | Templates, system files | Boilerplate, shared resources |

### 🔒 Security Enhancements

- ✅ Removed `session_id`/`user_id` parameters from all tools (prevents client impersonation)
- ✅ All identity from server-side context only
- ✅ Automatic scope-based access control in `read_file` and `delete_file`
- ✅ User files require authentication

### 🛠️ New Tools

**Explicit session tools** (ephemeral):
- `write_session_file` / `upload_session_file` - Always ephemeral
- `list_session_files` - List session files

**Explicit user tools** (persistent):
- `write_user_file` / `upload_user_file` - Always persistent
- `list_user_files` - Search/filter user's files

**General tools** (scope parameter):
- `write_file(scope="user")` / `upload_file(scope="user")` - Flexible scope selection

### ✅ 100% Backward Compatible

Existing code works unchanged - tools default to `scope="session"` (same behavior as v0.8.2).

**Quick comparison:**

```python
# v0.8.2 (still works in v0.9.0)
await write_file(content, filename)  # Ephemeral

# v0.9.0 - New capabilities
await write_user_file(content, filename)              # Persistent!
await write_file(content, filename, scope="user")     # Also persistent
files = await list_user_files(mime_prefix="text/*")   # Search user files
```

**See:** `CHANGELOG_V09.md` for complete release notes, `ARTIFACTS_V08_SUMMARY.md` for detailed guide.

## Redis Cluster Support (NEW in v0.10.4)

CHUK MCP Runtime now supports **Redis Cluster** for high availability and horizontal scaling through automatic cluster detection in `chuk-sessions` 0.6.0+ and `chuk-artifacts` 0.10.1+.

### Quick Start

**Standalone Redis** (existing):
```bash
export REDIS_URL=redis://localhost:6379
export ARTIFACT_SESSION_PROVIDER=redis
```

**Redis Cluster** (new):
```bash
# Comma-separated node list - automatic cluster detection
export REDIS_URL=redis://node1:7000,node2:7001,node3:7002
export ARTIFACT_SESSION_PROVIDER=redis
```

**With TLS**:
```bash
# Standalone with TLS
export REDIS_URL=rediss://secure-redis:6380
export REDIS_TLS_INSECURE=1  # For self-signed certificates

# Cluster with TLS
export REDIS_URL=rediss://node1:7000,node2:7001,node3:7002
export REDIS_TLS_INSECURE=1
```

### Environment Isolation

Prevent key collisions when multiple environments share the same Redis cluster:

```bash
# Development
export ENVIRONMENT=dev
export DEPLOYMENT_ID=local

# Staging
export ENVIRONMENT=staging
export DEPLOYMENT_ID=us-west-1
export SANDBOX_REGISTRY_TTL=3600  # 1 hour

# Production
export ENVIRONMENT=production
export DEPLOYMENT_ID=us-east-1
export SANDBOX_REGISTRY_TTL=86400  # 24 hours
```

This creates isolated namespaces:
- Dev: `dev:local:sbx:*`
- Staging: `staging:us-west-1:sbx:*`
- Production: `production:us-east-1:sbx:*`

### Configuration Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `REDIS_URL` | Redis connection URL (standalone or cluster) | `redis://localhost:6379` | `redis://n1:7000,n2:7001` |
| `REDIS_TLS_INSECURE` | Disable SSL certificate verification | `0` | `1` |
| `ENVIRONMENT` | Environment name for namespace isolation | `dev` | `production`, `staging` |
| `DEPLOYMENT_ID` | Deployment identifier for namespace isolation | `default` | `us-east-1`, `us-west-1` |
| `SANDBOX_REGISTRY_TTL` | Sandbox registry entry TTL in seconds | `86400` | `3600`, `7200` |

### Architecture Notes

**Automatic Detection:**
- Single host URL → Uses `redis.asyncio.Redis`
- Multi-host URL (comma-separated) → Uses `redis.asyncio.cluster.RedisCluster`
- Database selector (`/0`) is auto-removed for cluster compatibility

**Thread Safety:**
- All singletons use double-check locking with `asyncio.Lock`
- Safe for concurrent initialization in multi-instance deployments

**Namespace Isolation:**
- Keys are prefixed with `{ENVIRONMENT}:{DEPLOYMENT_ID}:sbx:`
- Prevents collisions when multiple environments share Redis
- Required for staging/production on same cluster

## Core Components Overview

| Component | Purpose |
|-----------|---------|
| **Proxy Manager** | Connects and namespaces multiple MCP servers |
| **Session Manager** | Maintains per-user state across tool calls |
| **Artifact Store** | Handles file persistence with 3 scopes (NEW: user, sandbox) |
| **Auth & Security** | Adds JWT validation, sandboxing, and access control |
| **Progress Engine** | Sends real-time status updates to clients |

## Key Concepts

### Sessions

**Sessions** provide stateful context for multi-turn interactions with MCP tools. Each session:

- Has a unique identifier (session ID)
- Persists across multiple tool calls
- Can store metadata (user info, preferences, etc.)
- Controls access to artifacts (files) within the session scope
- Has an optional TTL (time-to-live) for automatic cleanup

**When to use sessions:**
- Multi-step workflows that need to maintain state
- User-specific file storage (isolate files per user)
- Long-running operations that span multiple requests
- Workflows requiring authentication/authorization context

**Example:**
```python
# Session-aware tool automatically gets current session context
@mcp_tool(name="save_user_file")
async def save_user_file(filename: str, content: str) -> str:
    # Files are automatically scoped to the current session
    # User A's "data.txt" is separate from User B's "data.txt"

    # Note: artifact_store is available via runtime context when artifacts are enabled
    from chuk_mcp_runtime.tools.artifacts_tools import artifact_store
    await artifact_store.write_file(filename, content)
    return f"Saved {filename} to session"
```

### Sandboxes

**Sandboxes** are isolated execution environments that contain one or more sessions. Think of them as:

- **Namespace** - Groups related sessions together
- **Deployment unit** - One sandbox per deployment/pod/instance
- **Isolation boundary** - Sessions in different sandboxes don't interact

**Sandbox ID** is set via:
1. Config file: `sessions.sandbox_id: "my-app"`
2. Environment variable: `MCP_SANDBOX_ID=my-app`
3. Auto-detected: Pod name in Kubernetes (`POD_NAME`)

**Use cases:**
```
Single-tenant app:     sandbox_id = "myapp"
Multi-tenant SaaS:     sandbox_id = "tenant-{customer_id}"
Development/staging:   sandbox_id = "dev-alice" | "staging"
Kubernetes pod:        sandbox_id = $POD_NAME (auto)
```

### Sessions vs Sandboxes

```
Sandbox: "production-app"
├── Session: user-alice-2024
│   ├── File: report.pdf
│   └── File: data.csv
├── Session: user-bob-2024
│   └── File: notes.txt
└── Session: background-job-123
    └── File: results.json

Different Sandbox: "staging-app"
└── (completely isolated from production)
```

### Artifacts (NEW in v0.9: Storage Scopes)

**Artifacts** are files managed by the runtime with **three storage scopes** for different use cases:

#### Storage Scopes

| Scope | Lifecycle | TTL | Use Case | Access Control |
|-------|-----------|-----|----------|----------------|
| **session** | Ephemeral | 15min-24h | Temporary work, caches, generated code | Session-isolated |
| **user** | Persistent | 1 year+ | User documents, saved files, custom prompts | User-owned |
| **sandbox** | Shared | No expiry | Templates, shared resources, system files | Read-only (admin writes) |

**Key Features:**
- **Session isolation** - Files scoped to specific sessions or users
- **Storage backends** - Filesystem, S3, IBM Cloud Object Storage, VFS providers
- **Metadata tracking** - Size, timestamps, content type, ownership
- **Lifecycle management** - Auto-cleanup with TTL expiry
- **Security** - No client-side identity parameters, server context only
- **Search & filtering** - Find files by user, scope, MIME type, metadata

**Storage providers:**
- `vfs-filesystem` - Local disk with VFS support (development)
- `vfs-s3` - AWS S3 with streaming + multipart uploads (production)
- `vfs-sqlite` - SQLite with structured queries (embedded)
- `memory` - In-memory (testing, ephemeral)

### Progress Notifications

**Progress notifications** enable real-time feedback for long-running operations:

- Client provides `progressToken` in request
- Tool calls `send_progress(current, total, message)`
- Runtime sends `notifications/progress` to client
- Client displays progress bar/status

**Perfect for:**
- File processing (10 of 50 files)
- API calls (fetching data batches)
- Multi-step workflows (step 3 of 5)
- Long computations (75% complete)

## Configuration Reference

Complete YAML configuration structure with all available options:

```yaml
# ============================================
# HOST CONFIGURATION
# ============================================
host:
  name: "my-mcp-server"           # Server name (for logging/identification)
  log_level: "INFO"                # Global log level: DEBUG, INFO, WARNING, ERROR

# ============================================
# SERVER TRANSPORT
# ============================================
server:
  type: "stdio"                    # Transport: stdio | sse | streamable-http
  auth: "bearer"                   # Optional: bearer (JWT) | none

# SSE-specific settings (when type: "sse")
sse:
  host: "0.0.0.0"                  # Listen address
  port: 8000                       # Listen port
  sse_path: "/sse"                 # SSE endpoint path
  message_path: "/messages/"       # Message submission path
  health_path: "/health"           # Health check path

# HTTP-specific settings (when type: "streamable-http")
streamable-http:
  host: "127.0.0.1"                # Listen address
  port: 3000                       # Listen port
  mcp_path: "/mcp"                 # MCP endpoint path
  json_response: true              # Enable JSON responses
  stateless: true                  # Stateless mode

# ============================================
# LOGGING CONFIGURATION
# ============================================
logging:
  level: "INFO"                    # Default log level
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  reset_handlers: true             # Reset existing handlers
  quiet_libraries: true            # Suppress noisy library logs

  # Per-logger overrides
  loggers:
    "chuk_mcp_runtime.proxy": "DEBUG"
    "chuk_mcp_runtime.tools": "INFO"

# ============================================
# TOOL CONFIGURATION
# ============================================
tools:
  registry_module: "chuk_mcp_runtime.common.mcp_tool_decorator"
  registry_attr: "TOOLS_REGISTRY"
  timeout: 60                      # Global tool timeout (seconds)

# ============================================
# SESSION MANAGEMENT
# ============================================
sessions:
  sandbox_id: "my-app"             # Sandbox identifier (deployment unit)
  default_ttl_hours: 24            # Session time-to-live

# Session tools (disabled by default)
session_tools:
  enabled: false                   # Master switch for session tools
  tools:
    get_current_session: {enabled: false}
    set_session: {enabled: false}
    clear_session: {enabled: false}
    list_sessions: {enabled: false}
    get_session_info: {enabled: false}
    create_session: {enabled: false}

# ============================================
# ARTIFACT STORAGE
# ============================================
artifacts:
  enabled: false                   # Master switch for artifacts
  storage_provider: "filesystem"   # filesystem | s3 | ibm_cos
  session_provider: "memory"       # memory | redis
  bucket: "my-artifacts"           # Storage bucket/directory name

  # Artifact tools (disabled by default)
  tools:
    upload_file: {enabled: false}
    write_file: {enabled: false}
    read_file: {enabled: false}
    list_session_files: {enabled: false}
    delete_file: {enabled: false}
    list_directory: {enabled: false}
    copy_file: {enabled: false}
    move_file: {enabled: false}
    get_file_metadata: {enabled: false}
    get_presigned_url: {enabled: false}
    get_storage_stats: {enabled: false}

# ============================================
# PROXY CONFIGURATION
# ============================================
proxy:
  enabled: false                   # Enable proxy mode
  namespace: "proxy"               # Tool name prefix (e.g., "proxy.time.get_time")
  keep_root_aliases: false         # Keep original tool names
  openai_compatible: false         # Use underscores (time_get_time)
  only_openai_tools: false         # Register only underscore versions

# ============================================
# MCP SERVERS (Local & Remote)
# ============================================
mcp_servers:
  # Local Python tools
  my_tools:
    enabled: true
    location: "./my_tools"         # Directory containing tool modules
    tools:
      enabled: true
      module: "my_tools.tools"     # Python module path

  # Remote stdio server
  time:
    enabled: true
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time", "--local-timezone", "America/New_York"]
    cwd: "/optional/working/dir"   # Optional working directory

  # Remote SSE server
  weather:
    enabled: true
    type: "sse"
    url: "https://api.example.com/mcp"
    api_key: "your-api-key"        # Or set via API_KEY env var
```

### Configuration Priority

Settings are resolved in this order (highest to lowest):

1. **Command-line arguments** - `chuk-mcp-server --config custom.yaml`
2. **Environment variables** - `MCP_TOOL_TIMEOUT=120`
3. **Configuration file** - Values from YAML
4. **Default values** - Built-in defaults

### Minimal Configurations

**Stdio server with no sessions:**
```yaml
server:
  type: "stdio"
```

**SSE server (referenced in examples):**
```yaml
# sse_config.yaml
server:
  type: "sse"
  # For production: add auth: "bearer" and set JWT_SECRET_KEY

sse:
  host: "0.0.0.0"
  port: 8000
  sse_path: "/sse"
  message_path: "/messages/"
  health_path: "/health"
```

**Streamable HTTP server (referenced in examples):**
```yaml
# http_config.yaml
server:
  type: "streamable-http"
  # For production: add auth: "bearer" and set JWT_SECRET_KEY

streamable-http:
  host: "0.0.0.0"
  port: 3000
  mcp_path: "/mcp"
  json_response: true
  stateless: true
```

**Proxy only (no local tools):**
```yaml
proxy:
  enabled: true

mcp_servers:
  time:
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time"]
```

**Full-featured with sessions:**
```yaml
server:
  type: "stdio"

sessions:
  sandbox_id: "prod"

session_tools:
  enabled: true
  tools:
    get_current_session: {enabled: true}
    create_session: {enabled: true}

artifacts:
  enabled: true
  storage_provider: "s3"
  tools:
    write_file: {enabled: true}
    read_file: {enabled: true}
```

## Proxy Configuration Examples

The proxy layer allows you to expose tools from multiple MCP servers through a unified interface.

### Simple Command Line Proxy

```bash
# Basic proxy with dot notation (proxy.time.get_current_time)
chuk-mcp-proxy --stdio time --command uvx -- mcp-server-time --local-timezone America/New_York

# Multiple stdio servers (--stdio is repeatable)
chuk-mcp-proxy --stdio time --command uvx -- mcp-server-time \
               --stdio weather --command uvx -- mcp-server-weather

# Multiple SSE servers (--sse is repeatable)
chuk-mcp-proxy \
  --sse analytics --url https://example.com/mcp --api-key "$API_KEY" \
  --sse metrics   --url https://metrics.example.com/mcp --api-key "$METRICS_API_KEY"

# OpenAI-compatible with underscore notation (time_get_current_time)
chuk-mcp-proxy --stdio time --command uvx -- mcp-server-time --openai-compatible

# Streamable HTTP server (serves MCP over HTTP)
chuk-mcp-server --config http_config.yaml  # See minimal config example below
```

> ⚠️ **Security:** For SSE/HTTP network transports, enable `server.auth: bearer` and set `JWT_SECRET_KEY`.

### Multiple Servers with Config File

```yaml
# proxy_config.yaml
proxy:
  enabled: true
  namespace: "proxy"

mcp_servers:
  time:
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time", "--local-timezone", "America/New_York"]

  weather:
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-weather"]
```

```bash
chuk-mcp-proxy --config proxy_config.yaml
```

### OpenAI-Compatible Mode

```yaml
# openai_config.yaml
proxy:
  enabled: true
  namespace: "proxy"
  openai_compatible: true   # Enable underscore notation
  only_openai_tools: true   # Only register underscore-notation tools

mcp_servers:
  time:
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time"]
```

```bash
chuk-mcp-proxy --config openai_config.yaml
```

**OpenAI-Compatible Naming Matrix:**

| Setting | Example Exposed Name |
|---------|---------------------|
| Default (dot notation) | `proxy.time.get_current_time` |
| `openai_compatible: true` | `time_get_current_time` |
| `openai_compatible: true` + `only_openai_tools: true` | Only underscore versions registered |

> **OpenAI-compatible mode** converts dots to underscores (e.g., `proxy.time.get_current_time` → `time_get_current_time`). Namespacing behavior is controlled by `openai_compatible` + `only_openai_tools`.

**OpenAI-compatible demo with HTTP:**

```bash
# Start proxy with OpenAI-compatible naming
chuk-mcp-proxy --stdio time --command uvx -- mcp-server-time --openai-compatible

# Call the underscore tool name over HTTP
curl -s http://127.0.0.1:3000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"time_get_current_time","arguments":{"timezone":"UTC"}}}'
```

### Name Aliasing in Proxy Mode

By default, tools are exposed under `proxy.<server>.<tool>`.
Set `keep_root_aliases: true` to also expose the original tool names (no `proxy.` prefix).
This is useful when migrating existing clients gradually. **Root aliases are great for gradual migration, but disable in multi-tenant prod to avoid collisions.**

```yaml
proxy:
  enabled: true
  namespace: "proxy"
  keep_root_aliases: true  # Also expose tools without proxy. prefix
```

With this setting enabled, `proxy.time.get_current_time` is available as both:
- `proxy.time.get_current_time` (namespaced)
- `get_current_time` (root alias)

### Tool Naming Interplay

**Complete naming matrix when options combine:**

| Setting Combination | Registered Names |
|---------------------|------------------|
| Default | `proxy.<server>.<tool>` |
| `keep_root_aliases: true` | `proxy.<server>.<tool>`, **and** `<tool>` |
| `openai_compatible: true` | `<server>_<tool>` |
| `openai_compatible: true` + `only_openai_tools: true` | `<server>_<tool>` **only** |
| `openai_compatible: true` + `keep_root_aliases: true` | `<server>_<tool>`, **and** `<tool>` |

> ⚠️ **Root aliases are un-namespaced.** Use with care in multi-server setups to avoid tool name collisions.

## Security Model

**IMPORTANT**: CHUK MCP Runtime follows a **secure-by-default** approach:

- **All built-in tools are disabled by default**
- Session management tools require explicit enablement
- Artifact storage tools require explicit enablement
- Tools must be individually enabled in configuration
- This prevents unexpected tool exposure and reduces attack surface

## Creating Local MCP Tools

### 1. Create a custom tool

```python
# my_tools/tools.py
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool

@mcp_tool(name="get_current_time", description="Get the current time in a timezone")
async def get_current_time(timezone: str = "UTC") -> str:
    """
    Get the current time in the specified timezone.

    Args:
        timezone: Target timezone (e.g., 'UTC', 'America/New_York')
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")

@mcp_tool(name="calculate_sum", description="Calculate the sum of two numbers", timeout=10)
async def calculate_sum(a: int, b: int) -> dict:
    """
    Calculate the sum of two numbers.

    Args:
        a: First number
        b: Second number
    """
    # ⚠️ PRODUCTION WARNING: Never use eval() for math operations - always validate
    # and compute directly as shown here. eval() is a security risk.
    result = a + b
    return {
        "operation": "addition",
        "operands": [a, b],
        "result": result
    }
```

### 2. Create a config file

```yaml
# config.yaml
host:
  name: "my-mcp-server"
  log_level: "INFO"

server:
  type: "stdio"

# Global tool settings
tools:
  registry_module: "chuk_mcp_runtime.common.mcp_tool_decorator"
  registry_attr: "TOOLS_REGISTRY"
  timeout: 60  # Default timeout for all tools

# Session management (optional - disabled by default)
sessions:
  sandbox_id: "my-app"
  default_ttl_hours: 24

# Session tools (disabled by default - must enable explicitly)
session_tools:
  enabled: true  # Must explicitly enable
  tools:
    get_current_session: {enabled: true}
    set_session: {enabled: true}
    clear_session: {enabled: true}
    create_session: {enabled: true}

# Artifact storage (disabled by default - must enable explicitly)
artifacts:
  enabled: true  # Must explicitly enable
  storage_provider: "filesystem"
  session_provider: "memory"
  bucket: "my-artifacts"
  tools:
    upload_file: {enabled: true}
    write_file: {enabled: true}
    read_file: {enabled: true}
    list_session_files: {enabled: true}
    delete_file: {enabled: true}
    get_file_metadata: {enabled: true}

# Local tool modules
mcp_servers:
  my_tools:
    enabled: true
    location: "./my_tools"
    tools:
      enabled: true
      module: "my_tools.tools"
```

### 3. Run the server

```bash
chuk-mcp-server --config config.yaml
```

## MCP Resources

**MCP Resources** provide read-only access to data through the Model Context Protocol's `resources/list` and `resources/read` endpoints. Resources are perfect for exposing configuration, documentation, system information, and user files to AI agents.

### Resources vs Tools

| Feature | **Resources** | **Tools** |
|---------|--------------|-----------|
| **Purpose** | Read-only data access | Actions & state changes |
| **Use Cases** | Config, docs, files, metrics | Create, update, delete operations |
| **MCP Methods** | `resources/list`, `resources/read` | `tools/list`, `tools/call` |
| **Side Effects** | None (read-only) | May modify state |
| **Session Isolation** | Artifact resources only | Tool-dependent |

### Resource Types

CHUK MCP Runtime supports two types of resources:

#### 1. Custom Resources (@mcp_resource)

Custom resources expose application data, configuration, documentation, or any read-only content through simple Python functions.

**Creating custom resources:**

```python
# my_resources/resources.py
from chuk_mcp_runtime.common.mcp_resource_decorator import mcp_resource
import json
import os

@mcp_resource(
    uri="config://database",
    name="Database Configuration",
    description="Database connection settings",
    mime_type="application/json"
)
async def get_database_config():
    """Return database configuration as JSON."""
    config = {
        "host": "localhost",
        "port": 5432,
        "database": "myapp_db",
        "pool_size": 10
    }
    return json.dumps(config, indent=2)

@mcp_resource(
    uri="system://info",
    name="System Information",
    description="Current system status",
    mime_type="text/plain"
)
async def get_system_info():
    """Return system information."""
    return f"""System Information
Platform: {os.uname().sysname}
Node: {os.uname().nodename}
User: {os.getenv('USER', 'unknown')}
"""

@mcp_resource(
    uri="docs://api/overview",
    name="API Documentation",
    description="API endpoints guide",
    mime_type="text/markdown"
)
def get_api_docs():
    """Return API documentation (sync functions work too!)."""
    return """# API Documentation

## Authentication
All requests require Bearer token.

## Endpoints
- GET /api/users - List users
- POST /api/users - Create user
"""
```

**Configuration:**

```yaml
# config.yaml
server:
  type: "stdio"

# Import module containing custom resources
tools:
  modules_to_import:
    - my_resources.resources
```

**Custom resource features:**
- **Static or dynamic** - Return fixed data or compute on-demand
- **Sync or async** - Both function types supported
- **Any content type** - Text, JSON, binary, images, etc.
- **Custom URI schemes** - Use meaningful URIs like `config://`, `docs://`, `system://`

#### 2. Artifact Resources (Session-Isolated User Files)

Artifact resources provide **automatic, session-isolated access to user files** through the MCP resources protocol. When users create, upload, or modify files via artifact tools, those files are automatically exposed as resources with strong session isolation guarantees.

**Key Concepts:**

- **Automatic Exposure**: Files created via `write_file`, `upload_file`, etc. are automatically available via `resources/list` and `resources/read`
- **Session Isolation**: Users can only list and read their own files - cross-session access is blocked
- **Unified Protocol**: Access files through the same MCP resources protocol as custom resources
- **URI Format**: `artifact://{artifact_id}` where `artifact_id` is the unique file identifier

**How Artifact Resources Work:**

```python
# Step 1: User creates a file via an artifact tool
# This happens via MCP tool call: tools/call with name="write_file"

# Example tool call from AI agent:
{
  "method": "tools/call",
  "params": {
    "name": "write_file",
    "arguments": {
      "filename": "analysis.md",
      "content": "# Data Analysis\n\nKey findings...",
      "mime": "text/markdown",
      "summary": "Q3 analysis report"
    }
  }
}

# Step 2: File is stored with session association
# - artifact_id: "abc-123-def-456"
# - session_id: "session-alice"
# - filename: "analysis.md"
# - mime: "text/markdown"

# Step 3: File automatically appears in resources/list
{
  "method": "resources/list"
}
# Returns:
{
  "resources": [
    {
      "uri": "artifact://abc-123-def-456",
      "name": "analysis.md",
      "description": "Q3 analysis report",
      "mimeType": "text/markdown"
    }
  ]
}

# Step 4: Read the resource content
{
  "method": "resources/read",
  "params": {"uri": "artifact://abc-123-def-456"}
}
# Returns:
{
  "contents": [
    {
      "uri": "artifact://abc-123-def-456",
      "mimeType": "text/markdown",
      "text": "# Data Analysis\n\nKey findings..."
    }
  ]
}
```

**Session Isolation Example:**

```python
# Alice's session (session-alice)
# Creates: report.md -> artifact://file-alice-1

# Bob's session (session-bob)
# Creates: report.md -> artifact://file-bob-1

# When Alice calls resources/list:
# Returns ONLY: artifact://file-alice-1

# When Bob calls resources/list:
# Returns ONLY: artifact://file-bob-1

# If Alice tries to read Bob's file:
# resources/read {"uri": "artifact://file-bob-1"}
# Result: Error - Artifact not found (access blocked)
```

**Configuration:**

```yaml
# config.yaml
artifacts:
  enabled: true
  storage_provider: "filesystem"  # or "s3", "ibm_cos"
  session_provider: "memory"      # or "redis"

  # Storage configuration (for filesystem provider)
  filesystem:
    base_path: "./artifacts"

  # Enable artifact tools (users create files via these tools)
  tools:
    write_file: {enabled: true}         # Create/update text files
    upload_file: {enabled: true}        # Upload binary files
    read_file: {enabled: true}          # Read file content
    list_session_files: {enabled: true} # List user's files
    delete_file: {enabled: true}        # Delete files
```

**Supported File Operations:**

| Tool | Purpose | Creates Resource? |
|------|---------|-------------------|
| `write_file` | Create or update text file | ✅ Yes |
| `upload_file` | Upload binary file (images, PDFs, etc.) | ✅ Yes |
| `read_file` | Read file content by filename | No (uses resource instead) |
| `list_session_files` | List user's files | No (use `resources/list`) |
| `delete_file` | Delete a file | Removes resource |

**Text vs Binary Content:**

```python
# Text files (JSON, Markdown, code, etc.)
# Returned as "text" in resource content
{
  "uri": "artifact://text-123",
  "mimeType": "application/json",
  "text": '{"key": "value"}'
}

# Binary files (images, PDFs, etc.)
# Returned as base64-encoded "blob"
{
  "uri": "artifact://binary-456",
  "mimeType": "image/png",
  "blob": "iVBORw0KGgoAAAANSUhEUgAA..."  # base64 encoded
}
```

**Artifact Resource Metadata:**

Each artifact resource includes:
- **URI**: `artifact://{artifact_id}` - Unique resource identifier
- **Name**: Original filename (e.g., "report.pdf")
- **Description**: Summary/description provided during creation
- **MIME Type**: Content type (e.g., "application/pdf", "text/markdown")
- **Session ID**: Internal - used for access control (not exposed)

**Integration with Custom Resources:**

Artifact resources and custom resources work together seamlessly:

```python
# Both appear in the same resources/list response:
{
  "resources": [
    # Custom resources (global)
    {"uri": "config://database", "name": "Database Config", ...},
    {"uri": "docs://api", "name": "API Documentation", ...},

    # Artifact resources (session-isolated)
    {"uri": "artifact://abc-123", "name": "user-report.md", ...},
    {"uri": "artifact://def-456", "name": "analysis.pdf", ...}
  ]
}

# AI agents can access both types through the same protocol
```

**Security & Access Control:**

Artifact resources have **multi-layer security**:

1. **Session Validation**: Every `resources/read` call validates session ownership
2. **Metadata Verification**: Artifact metadata must match current session
3. **Access Blocking**: Cross-session reads return "not found" error
4. **Audit Trail**: All access attempts can be logged for compliance

**Common Use Cases:**

- **Document Generation**: AI creates reports, summaries, code files
- **Data Analysis**: AI processes data and saves results as artifacts
- **File Management**: Users upload files, AI analyzes and references them
- **Multi-step Workflows**: AI saves intermediate results as artifacts
- **Context Persistence**: Files remain accessible across conversation turns

**Artifact Resource Features:**
- ✅ **Session isolation** - Users only see their own files
- ✅ **Automatic exposure** - Files created via tools become resources immediately
- ✅ **URI scheme** - Consistent `artifact://{id}` format
- ✅ **Security** - Built-in access control and validation
- ✅ **Persistence** - Files survive server restarts (with filesystem/cloud storage)
- ✅ **Binary support** - Images, PDFs, archives via base64 encoding
- ✅ **Metadata** - Filenames, MIME types, descriptions included

### Resource URI Schemes

| URI Scheme | Type | Example | Use Case |
|------------|------|---------|----------|
| `config://` | Custom | `config://database` | Configuration data |
| `system://` | Custom | `system://info` | System information |
| `docs://` | Custom | `docs://api/overview` | Documentation |
| `data://` | Custom | `data://logo.png` | Static assets |
| `artifact://` | Artifact | `artifact://abc-123-def` | User files |

### Using Resources in AI Agents

Resources are designed for AI agents to retrieve contextual data:

```python
# AI agent workflow:
# 1. List available resources
response = await client.call("resources/list")
# Returns: config://database, system://info, artifact://report-123

# 2. Read specific resource
content = await client.call("resources/read", {"uri": "config://database"})
# Returns: {"host": "localhost", "port": 5432, ...}

# 3. Use data in decision making
# Agent now has config context for subsequent operations
```

### Complete Example

```python
# resources_example.py
from chuk_mcp_runtime.common.mcp_resource_decorator import mcp_resource
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
import json
from datetime import datetime

# Custom resource: Configuration
@mcp_resource(
    uri="config://app/settings",
    name="Application Settings",
    description="Current app configuration",
    mime_type="application/json"
)
async def get_app_settings():
    return json.dumps({
        "version": "1.0.0",
        "features": {"dark_mode": True},
        "limits": {"max_upload_mb": 100}
    })

# Custom resource: Dynamic status
@mcp_resource(
    uri="status://health",
    name="Health Status",
    description="Real-time health check",
    mime_type="application/json"
)
async def get_health_status():
    # Computed on each request
    return json.dumps({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime": get_uptime_seconds()
    })

# Tool: Create artifact resource
@mcp_tool(name="save_document")
async def save_document(filename: str, content: str):
    """Save a document (becomes artifact resource automatically)."""
    from chuk_mcp_runtime.tools.artifacts_tools import artifact_store
    artifact_id = await artifact_store.write_file(filename, content)
    return f"Saved as artifact://{artifact_id}"
```

**Config:**

```yaml
server:
  type: "stdio"

# Enable artifacts (provides artifact:// resources)
artifacts:
  enabled: true
  tools:
    write_file: {enabled: true}

# Import custom resources
tools:
  modules_to_import:
    - resources_example

mcp_servers:
  local:
    enabled: true
    location: "."
    tools:
      enabled: true
      module: "resources_example"
```

### Security & Access Control

**Custom resources:**
- No built-in access control (global to all users)
- Implement filtering in resource function if needed
- Don't expose sensitive data directly

**Artifact resources:**
- ✅ **Session-isolated** - Automatic access control
- ✅ **User-scoped** - Each user sees only their files
- ✅ **Validated** - URI and session verified on read

**Best practices:**
```python
# ❌ BAD: Expose sensitive config
@mcp_resource(uri="config://secrets")
def get_secrets():
    return {"api_key": "secret123"}  # Exposed to all users!

# ✅ GOOD: Expose non-sensitive config
@mcp_resource(uri="config://public")
def get_public_config():
    return {"app_name": "MyApp", "version": "1.0"}

# ✅ GOOD: Filter by session if needed
@mcp_resource(uri="config://user")
async def get_user_config():
    from chuk_mcp_runtime.session import get_current_session
    session = get_current_session()
    # Return user-specific config based on session
    return get_config_for_session(session)
```

### Examples

See complete working examples:
- `examples/custom_resources_demo.py` - Custom resources showcase
- `examples/resources_e2e_demo.py` - Full E2E demo with MCP protocol

Run examples:
```bash
# Standalone custom resources demo
uv run python examples/custom_resources_demo.py

# Full E2E demo (server + client)
uv run python examples/resources_e2e_demo.py
```

## Built-in Tool Categories

CHUK MCP Runtime provides two categories of built-in tools that can be optionally enabled:

### Session Management Tools

**Status**: Disabled by default - must be explicitly enabled

Tools for managing session context and lifecycle:

- `get_current_session`: Get information about the current session
- `set_session`: Set the session context for operations  
- `clear_session`: Clear the current session context
- `list_sessions`: List all active sessions
- `get_session_info`: Get detailed session information
- `create_session`: Create a new session with metadata

**Enable in config**:
```yaml
session_tools:
  enabled: true
  tools:
    get_current_session: {enabled: true}
    set_session: {enabled: true}
    # ... enable other tools as needed
```

### Artifact Storage Tools (NEW v0.9: Scopes)

**Status**: Disabled by default - must be explicitly enabled

Tools for file storage and management with **three storage scopes**:

**General tools** (scope parameter, default=session):
- `upload_file(scope="session"|"user")`: Upload files with scope selection
- `write_file(scope="session"|"user")`: Create/update files with scope selection
- `read_file`: Read file contents (auto access control)
- `delete_file`: Delete files (auto access control)

**Explicit session tools** (always ephemeral):
- `write_session_file`: Write to session storage
- `upload_session_file`: Upload to session storage
- `list_session_files`: List files in current session

**Explicit user tools** (always persistent, NEW v0.9):
- `write_user_file`: Write to persistent user storage
- `upload_user_file`: Upload to persistent user storage
- `list_user_files`: List/search user's persistent files

**Other tools**:
- `list_directory`: List directory contents
- `copy_file`: Copy files
- `move_file`: Move/rename files
- `get_file_metadata`: Get file metadata
- `get_presigned_url`: Generate presigned URLs
- `get_storage_stats`: Get storage statistics (session + user)

**Enable in config**:
```yaml
artifacts:
  enabled: true
  storage_provider: "vfs-filesystem"  # or "vfs-s3", "vfs-sqlite"
  session_provider: "memory"          # or "redis"

  tools:
    # General tools (flexible)
    write_file: {enabled: true}
    upload_file: {enabled: true}
    read_file: {enabled: true}
    delete_file: {enabled: true}

    # Explicit session tools
    write_session_file: {enabled: true}
    upload_session_file: {enabled: true}
    list_session_files: {enabled: true}

    # Explicit user tools (persistent)
    write_user_file: {enabled: true}
    upload_user_file: {enabled: true}
    list_user_files: {enabled: true}
```

## Tool Configuration

### Timeout Settings

CHUK MCP Runtime supports configurable timeouts for tools to handle long-running operations. The default timeout is **60 seconds** unless overridden.

```python
# Tool with custom timeout
@mcp_tool(
    name="api_call",
    description="Call external API", 
    timeout=30  # 30 second timeout
)
async def api_call(url: str) -> dict:
    """Call an external API with timeout protection."""
    # Implementation here
    pass
```

**Configuration priority** (highest to lowest):
1. Per-tool timeout in decorator: `@mcp_tool(timeout=30)`
2. Global timeout in config: `tools.timeout: 60`
3. Environment variable: `MCP_TOOL_TIMEOUT=60`
4. Default: 60 seconds

### Advanced Tool Features

Tools support:
- **Type hints** for automatic JSON schema generation
- **Docstring parsing** for parameter descriptions
- **Async execution** with timeout protection
- **Error handling** with graceful degradation
- **Session management** for stateful operations
- **Thread-safe initialization** with race condition protection
- **Progress notifications** for long-running operations

## Progress Notifications

CHUK MCP Runtime supports real-time progress notifications for long-running operations, allowing clients to display progress bars and status updates.

### How Progress Works

Progress notifications are sent over the MCP protocol using the `notifications/progress` message type. When a tool reports progress, the runtime automatically sends notifications to the client if:
1. The client provided a `progressToken` in the request
2. The tool uses the `send_progress()` function

> ℹ️ **Important:** Clients must send `_meta.progressToken` for progress to stream; otherwise updates are ignored by design.

### Using Progress in Tools

```python
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
from chuk_mcp_runtime.server.request_context import send_progress

@mcp_tool(name="process_files", description="Process multiple files with progress")
async def process_files(file_paths: list[str]) -> dict:
    """
    Process multiple files and report progress.

    Args:
        file_paths: List of file paths to process
    """
    total = len(file_paths)
    results = []

    for i, path in enumerate(file_paths, 1):
        # Send progress update
        await send_progress(
            progress=i,
            total=total,
            message=f"Processing {path}"
        )

        # Do the actual work
        result = await process_file(path)
        results.append(result)
        await asyncio.sleep(0.5)  # Simulate work

    return {"processed": len(results), "results": results}
```

### Progress Patterns

**Step-based progress** (N of total):
```python
await send_progress(
    progress=5,
    total=10,
    message="Processing item 5 of 10"
)
```

**Percentage-based progress** (0.0 to 1.0):
```python
await send_progress(
    progress=0.75,
    total=1.0,
    message="75% complete"
)
```

**Multi-stage operations**:
```python
# Stage 1: Preparation
await send_progress(progress=1, total=3, message="Preparing data...")
await prepare_data()

# Stage 2: Processing
await send_progress(progress=2, total=3, message="Processing...")
await process_data()

# Stage 3: Finalizing
await send_progress(progress=3, total=3, message="Finalizing...")
await finalize()
```

### Client Integration

Progress notifications are automatically sent when clients include `progressToken` in the request metadata:

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "id": 1,
  "params": {
    "name": "process_files",
    "arguments": {"file_paths": ["a.txt", "b.txt"]},
    "_meta": {
      "progressToken": "my-progress-123"
    }
  }
}
```

The client receives notifications like:

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/progress",
  "params": {
    "progressToken": "my-progress-123",
    "progress": 1,
    "total": 2,
    "message": "Processing a.txt"
  }
}
```

### Built-in Progress Support

Several built-in artifact tools include progress reporting out of the box:

**upload_file** - 4-step progress:
1. Decoding base64 content
2. Preparing upload (with file size)
3. Uploading to storage
4. Complete (with artifact ID)

**write_file** - 3-step progress:
1. Preparing to write
2. Writing to storage
3. Complete (with artifact ID)

These tools automatically report progress when the client provides a `progressToken`.

### Examples

See complete working examples:
- `examples/progress_demo.py` - Basic progress reporting with visual output
- `examples/progress_e2e_demo.py` - Full end-to-end test over MCP protocol
- `examples/artifacts_progress_demo.py` - **NEW**: Artifact file operations with progress bars

### Testing Progress Support

Run the E2E demos to see progress in action:

```bash
# General progress demo
uv run python examples/progress_e2e_demo.py

# Artifact file operations with progress
uv run python examples/artifacts_progress_demo.py
```

**artifacts_progress_demo.py** demonstrates:
- File upload progress with visual █ progress bars
- File write progress tracking
- Multiple file operations with progress
- Operations without progress tokens (graceful fallback)

**progress_e2e_demo.py** demonstrates:
- Step-based progress (counting 1-10)
- Batch processing with progress
- Percentage-based progress (file download simulation)
- Visual progress bars in the terminal

## Request Context & Headers

**Request context** provides tools with access to request metadata including session, progress token, request headers, and other contextual information from the MCP protocol layer.

### What is Request Context?

The `MCPRequestContext` object is automatically created for each tool invocation and contains:

- **Session** - The MCP session object for progress notifications
- **Progress Token** - Client-provided token for progress updates
- **Metadata** - Additional request metadata (headers, user info, etc.)

Request context is managed automatically by the runtime and made available to tools through context variables.

### Accessing Request Context in Tools

```python
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
from chuk_mcp_runtime.server.request_context import (
    get_request_context,
    send_progress
)

@mcp_tool(name="context_aware_tool")
async def context_aware_tool(data: str) -> dict:
    """Tool that accesses request context."""

    # Get the current request context
    ctx = get_request_context()

    if ctx:
        # Access session information
        has_session = ctx.session is not None

        # Access progress token
        can_report_progress = ctx.progress_token is not None

        # Access request metadata
        meta = ctx.meta

        # Send progress if token available
        if can_report_progress:
            await ctx.send_progress(
                progress=0.5,
                total=1.0,
                message="Halfway done"
            )

    return {"processed": data, "has_context": ctx is not None}
```

### Request Headers API

Tools can access HTTP headers from incoming requests to implement custom authentication, logging, or feature detection:

```python
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
from chuk_mcp_runtime.server.request_context import get_request_context

@mcp_tool(name="header_aware_tool")
async def header_aware_tool(action: str) -> dict:
    """Tool that reads request headers."""

    ctx = get_request_context()
    if not ctx:
        return {"error": "No request context available"}

    # Get all request headers (lowercase keys)
    headers = ctx.get_headers()

    # Access specific headers
    user_agent = headers.get("user-agent", "unknown")
    content_type = headers.get("content-type", "application/json")
    authorization = headers.get("authorization", "")

    # Custom headers (if client sends them)
    request_id = headers.get("x-request-id")
    client_version = headers.get("x-client-version")

    return {
        "action": action,
        "user_agent": user_agent,
        "content_type": content_type,
        "has_auth": bool(authorization),
        "request_id": request_id,
        "client_version": client_version
    }
```

### Context Manager for Manual Context Setup

For advanced scenarios (testing, custom integrations), you can manually manage request context:

```python
from chuk_mcp_runtime.server.request_context import RequestContext
from unittest.mock import AsyncMock

async def test_tool_with_context():
    """Example: Testing a tool with mocked context."""

    # Create a mock session
    mock_session = AsyncMock()
    mock_session.send_progress_notification = AsyncMock()

    # Use context manager to set up request context
    async with RequestContext(
        session=mock_session,
        progress_token="test-token-123",
        meta={"user_id": "alice", "headers": {"user-agent": "test-client"}}
    ) as ctx:
        # Tools called here have access to the context
        result = await my_tool("input")

        # Verify progress was sent
        assert mock_session.send_progress_notification.called
```

### Request Context Properties

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `session` | `Any` | MCP session object | Used for `send_progress()` |
| `progress_token` | `str \| int \| None` | Client progress token | `"progress-123"` |
| `meta` | `Any` | Request metadata | `{"user_id": "alice"}` |

### Getting Headers from Different Sources

The `get_headers()` method checks multiple sources in order:

1. **Meta attribute** - `ctx.meta.headers`
2. **Meta dict** - `ctx.meta["headers"]`
3. **Context variable** - Global headers from `set_request_headers()`
4. **Empty dict** - Returns `{}` if no headers available

```python
# Example: Headers from meta attribute
meta = Mock()
meta.headers = {"authorization": "Bearer token123"}
ctx = MCPRequestContext(meta=meta)
headers = ctx.get_headers()  # {"authorization": "Bearer token123"}

# Example: Headers from meta dict
meta = {"headers": {"content-type": "application/json"}}
ctx = MCPRequestContext(meta=meta)
headers = ctx.get_headers()  # {"content-type": "application/json"}

# Example: No headers available
ctx = MCPRequestContext()
headers = ctx.get_headers()  # {}
```

### Common Use Cases

**1. Custom Authentication/Authorization:**
```python
@mcp_tool(name="protected_action")
async def protected_action(resource: str) -> dict:
    """Tool with custom authorization check."""
    ctx = get_request_context()
    headers = ctx.get_headers()

    # Check custom auth header
    api_key = headers.get("x-api-key")
    if not api_key or not validate_api_key(api_key):
        raise PermissionError("Invalid API key")

    # Perform protected action
    return {"resource": resource, "status": "processed"}
```

**2. Request Logging/Tracing:**
```python
@mcp_tool(name="traced_operation")
async def traced_operation(data: str) -> dict:
    """Tool that logs request metadata."""
    ctx = get_request_context()
    headers = ctx.get_headers()

    # Extract tracing headers
    trace_id = headers.get("x-trace-id", generate_trace_id())
    span_id = headers.get("x-span-id", generate_span_id())

    logger.info(f"Operation started: trace={trace_id}, span={span_id}")

    # Do work...
    result = process_data(data)

    logger.info(f"Operation completed: trace={trace_id}")
    return {"result": result, "trace_id": trace_id}
```

**3. Feature Detection:**
```python
@mcp_tool(name="adaptive_tool")
async def adaptive_tool(query: str) -> dict:
    """Tool that adapts based on client capabilities."""
    ctx = get_request_context()
    headers = ctx.get_headers()

    # Check client version for feature support
    client_version = headers.get("x-client-version", "1.0")
    user_agent = headers.get("user-agent", "")

    # Enable advanced features for newer clients
    use_streaming = version_gte(client_version, "2.0")
    use_markdown = "claude" in user_agent.lower()

    result = process_query(query, streaming=use_streaming)

    if use_markdown:
        result["formatted"] = format_as_markdown(result)

    return result
```

**4. Session Context with Progress:**
```python
@mcp_tool(name="multi_step_task")
async def multi_step_task(items: list[str]) -> dict:
    """Tool using both session and progress features."""
    ctx = get_request_context()

    if not ctx:
        # Fallback when no context (CLI usage, tests)
        return {"items": items, "mode": "synchronous"}

    results = []
    total = len(items)

    for i, item in enumerate(items, 1):
        # Report progress if client supports it
        if ctx.progress_token:
            await ctx.send_progress(
                progress=i,
                total=total,
                message=f"Processing {item}"
            )

        result = await process_item(item)
        results.append(result)

    return {"results": results, "mode": "progressive"}
```

### Global Helper Functions

For convenience, the module provides global helper functions:

```python
from chuk_mcp_runtime.server.request_context import (
    get_request_context,
    set_request_context,
    get_request_headers,
    set_request_headers,
    send_progress
)

# Get current context
ctx = get_request_context()

# Get headers directly
headers = get_request_headers()  # Returns None if not set

# Send progress (uses current context automatically)
await send_progress(progress=50, total=100, message="Halfway")
```

### Testing with Request Context

```python
import pytest
from unittest.mock import AsyncMock
from chuk_mcp_runtime.server.request_context import (
    RequestContext,
    set_request_context,
    MCPRequestContext
)

@pytest.fixture
def mock_session():
    """Fixture providing a mock session."""
    session = AsyncMock()
    session.send_progress_notification = AsyncMock()
    return session

@pytest.mark.asyncio
async def test_tool_with_progress(mock_session):
    """Test tool progress reporting."""
    ctx = MCPRequestContext(
        session=mock_session,
        progress_token="test-123"
    )
    set_request_context(ctx)

    # Call your tool
    result = await my_progressive_tool(["a", "b", "c"])

    # Verify progress was reported
    assert mock_session.send_progress_notification.call_count == 3

    # Clean up
    set_request_context(None)

@pytest.mark.asyncio
async def test_tool_with_headers(mock_session):
    """Test tool header access."""
    async with RequestContext(
        session=mock_session,
        meta={"headers": {"x-api-key": "test-key"}}
    ):
        result = await my_authenticated_tool("data")
        assert result["authenticated"] is True
```

### Security Considerations

**Header Validation:**
```python
# ✅ GOOD: Validate headers before use
@mcp_tool(name="secure_tool")
async def secure_tool(data: str) -> dict:
    ctx = get_request_context()
    headers = ctx.get_headers()

    # Validate expected headers
    api_key = headers.get("x-api-key", "").strip()
    if not api_key or len(api_key) < 32:
        raise ValueError("Invalid API key format")

    # Sanitize user-controlled values
    user_agent = headers.get("user-agent", "unknown")[:200]

    return process_with_auth(data, api_key)

# ❌ BAD: Trust headers without validation
@mcp_tool(name="insecure_tool")
async def insecure_tool(data: str) -> dict:
    ctx = get_request_context()
    headers = ctx.get_headers()

    # Dangerous: using header value directly in SQL/commands
    user_id = headers.get("x-user-id")
    db.execute(f"SELECT * FROM users WHERE id = {user_id}")  # SQL injection!
```

**Session Access:**
```python
# ✅ GOOD: Check context availability
@mcp_tool(name="safe_tool")
async def safe_tool(data: str) -> dict:
    ctx = get_request_context()

    # Always check if context is available
    if not ctx or not ctx.session:
        # Fallback behavior for CLI/tests
        return {"data": data, "progress": "unavailable"}

    # Safe to use session features
    await ctx.send_progress(0.5, 1.0, "Processing")
    return {"data": data, "progress": "reported"}
```

### Best Practices

1. **Always check context availability** - Context may be `None` in tests or CLI usage
2. **Validate headers** - Don't trust client-provided headers without validation
3. **Use progress tokens** - Check `ctx.progress_token` before calling `send_progress()`
4. **Sanitize header values** - Limit lengths, escape special characters
5. **Handle missing headers gracefully** - Provide sensible defaults
6. **Don't store sensitive data** - Headers may be logged or cached

## Running a Combined Local + Proxy Server

You can run a single server that provides both local tools and proxied remote tools:

```yaml
# combined_config.yaml
host:
  name: "combined-server"
  log_level: "INFO"

# Local server configuration
server:
  type: "stdio"

# Session management
sessions:
  sandbox_id: "combined-app"

# Enable session tools
session_tools:
  enabled: true
  tools:
    get_current_session: {enabled: true}
    create_session: {enabled: true}

# Enable artifact tools
artifacts:
  enabled: true
  storage_provider: "filesystem"
  tools:
    write_file: {enabled: true}
    read_file: {enabled: true}
    list_session_files: {enabled: true}

# Local tools
mcp_servers:
  local_tools:
    enabled: true
    location: "./my_tools"
    tools:
      enabled: true
      module: "my_tools.tools"

# Proxy configuration
proxy:
  enabled: true
  namespace: "proxy"
  openai_compatible: false
  
# Remote servers (managed by proxy)
mcp_servers:
  time:
    enabled: true
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time", "--local-timezone", "America/New_York"]
  
  echo:
    enabled: true
    type: "stdio"
    command: "python"
    args: ["examples/echo_server/main.py"]
```

Start the combined server:

```bash
chuk-mcp-server --config combined_config.yaml
```

## Transport Options

CHUK MCP Runtime supports multiple transport mechanisms:

### stdio (Standard Input/Output)
```yaml
server:
  type: "stdio"
```

### Server-Sent Events (SSE)
```yaml
server:
  type: "sse"
  auth: "bearer"  # Enable JWT authentication for network transports

sse:
  host: "0.0.0.0"
  port: 8000
  sse_path: "/sse"
  message_path: "/messages/"
  health_path: "/health"
```

> ⚠️ **Security:** When exposing network transports, enable `server.auth: bearer`, set `JWT_SECRET_KEY`, and run behind TLS (reverse proxy / ingress).

**Health check:**
```bash
curl -sf http://127.0.0.1:8000/health && echo "healthy"
```

**SSE message submission example:**
```bash
# Post a message to the SSE message endpoint
curl -s "http://127.0.0.1:8000/messages/" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/call",
    "params":{"name":"proxy.time.get_current_time","arguments":{"timezone":"UTC"}}
  }'
```

**Kubernetes readiness/liveness probes:**
```yaml
# k8s probes (example)
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 2
  periodSeconds: 5
```

### Streamable HTTP
```yaml
server:
  type: "streamable-http"
  auth: "bearer"  # Enable JWT authentication for network transports

streamable-http:
  host: "127.0.0.1"
  port: 3000
  mcp_path: "/mcp"
  json_response: true
  stateless: true
```

> ⚠️ **Security:** When exposing network transports, enable `server.auth: bearer`, set `JWT_SECRET_KEY`, and run behind TLS (reverse proxy / ingress).

**Example: Call a tool over HTTP (stateless mode)**

```bash
# Call a tool via HTTP POST
curl -s http://127.0.0.1:3000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "proxy.time.get_current_time",
      "arguments": {"timezone": "UTC"},
      "_meta": {"progressToken": "curl-demo-1"}
    }
  }'
```

> If you enabled OpenAI-compatible mode, call `time_get_current_time` instead.

**Smoke test: List available tools**

```bash
# List available tools (verify wiring before calling)
curl -s http://127.0.0.1:3000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/list",
    "params": {}
  }' | jq '.result.tools[].name'
```

## Security Features & Hardening

**Hardening checklist (production):**

- ✅ `server.auth: bearer` and `JWT_SECRET_KEY` set via a secrets manager
- ✅ Rotate JWT secrets; set `JWT_LEEWAY` for clock drift
- ✅ Disable tools you don't need (default is off — keep it that way)
- ✅ Use namespacing (avoid `keep_root_aliases` in multi-tenant prod)
- ✅ Set conservative `tools.timeout` and per-tool overrides
- ✅ Run behind TLS (reverse proxy / ingress)
- ✅ Add network ACLs; restrict SSE/HTTP exposure

### Authentication

**Quick JWT setup for development:**

```bash
# Generate a quick dev token (HS256) with 1h expiry
python - <<'PY'
import jwt, time
print(jwt.encode({"exp": int(time.time())+3600, "sub":"dev-user"}, "dev-secret", algorithm="HS256"))
PY
```

```yaml
# Server config (excerpt)
server:
  type: "streamable-http"
  auth: "bearer"
```

```bash
# Environment
export JWT_SECRET_KEY="dev-secret"
```

Then include the token in requests:

```bash
curl -H "Authorization: Bearer <token>" ...
```

### Tool Security
- All built-in tools disabled by default
- Granular per-tool enablement
- Session isolation for artifact storage
- Input validation on all tool parameters
- Timeout protection against runaway operations

## Environment Variables

Environment variables provide flexible configuration for different deployment scenarios. They **override config file values** but are **overridden by command-line arguments**.

### Core Configuration

| Variable | Purpose | Example | When to Use |
|----------|---------|---------|-------------|
| `CHUK_MCP_CONFIG_PATH` | Path to YAML config | `/etc/mcp/config.yaml` | Docker containers, systemd services |
| `CHUK_MCP_LOG_LEVEL` | Global log level | `DEBUG`, `INFO`, `WARNING` | Debugging, production |
| `MCP_TOOL_TIMEOUT` | Default tool timeout (seconds) | `120` | Long-running tools, slow networks |
| `TOOL_TIMEOUT` | Alternative timeout variable | `60` | Compatibility with other tools |

**Use case:**
```bash
# Override config file logging level for debugging
CHUK_MCP_LOG_LEVEL=DEBUG chuk-mcp-server --config prod.yaml
```

### Session & Sandbox Configuration

| Variable | Purpose | Example | When to Use |
|----------|---------|---------|-------------|
| `MCP_SANDBOX_ID` | Sandbox identifier | `prod-api`, `tenant-acme` | Multi-tenant, environment separation |
| `CHUK_SANDBOX_ID` | Alternative sandbox ID | `staging` | Legacy compatibility |
| `SANDBOX_ID` | Another alternative | `dev-alice` | Simplest form |
| `POD_NAME` | Kubernetes pod name | `api-deployment-abc123` | **Auto-detected in K8s** |

### Redis Configuration (Session Storage)

| Variable | Purpose | Example | When to Use |
|----------|---------|---------|-------------|
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` | Standalone Redis |
| `REDIS_URL` | Redis Cluster URL | `redis://n1:7000,n2:7001,n3:7002` | **Cluster mode** (comma-separated nodes) |
| `REDIS_TLS_INSECURE` | Skip SSL cert verification | `1` | Self-signed certificates |
| `ENVIRONMENT` | Environment name for namespacing | `production`, `staging`, `dev` | Multi-environment isolation |
| `DEPLOYMENT_ID` | Deployment identifier | `us-east-1`, `us-west-1` | Prevent key collisions |
| `SANDBOX_REGISTRY_TTL` | Sandbox registry TTL (seconds) | `86400` | Customize expiration |

**Sandbox ID Resolution** (first match wins):
1. Config file: `sessions.sandbox_id`
2. `MCP_SANDBOX_ID` environment variable
3. `CHUK_SANDBOX_ID` environment variable
4. `SANDBOX_ID` environment variable
5. `POD_NAME` (Kubernetes auto-detection)
6. Default: `mcp-runtime-{timestamp}`

**Use cases:**
```bash
# Development: per-developer sandboxes
export MCP_SANDBOX_ID="dev-$USER"

# Production: multi-tenant SaaS
export MCP_SANDBOX_ID="tenant-${CUSTOMER_ID}"

# Kubernetes: automatic per-pod isolation
# POD_NAME is auto-detected, no config needed!
```

**Redis Cluster with Environment Isolation** (Kubernetes example):
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: chuk-mcp-runtime
spec:
  replicas: 3  # Safe to scale horizontally with Redis Cluster
  template:
    spec:
      containers:
      - name: app
        image: chuk-mcp-runtime:latest
        env:
          # Redis Cluster connection
          - name: REDIS_URL
            value: "redis://redis-0:7000,redis-1:7001,redis-2:7002"
          - name: ARTIFACT_SESSION_PROVIDER
            value: "redis"

          # Environment isolation
          - name: ENVIRONMENT
            value: "production"
          - name: DEPLOYMENT_ID
            value: "us-east-1"
          - name: SANDBOX_REGISTRY_TTL
            value: "86400"  # 24 hours
```

### Artifact Storage

Artifacts support **4 storage providers** (memory, filesystem, s3, ibm_cos) and **2 session providers** (memory, redis).

**📋 Environment Variables Quick Reference:**

| Provider | Required Variables | Optional Variables |
|----------|-------------------|-------------------|
| **Memory** | None | `ARTIFACT_STORAGE_PROVIDER=memory` (default)<br>`ARTIFACT_SESSION_PROVIDER=memory` (default) |
| **Filesystem** | `ARTIFACT_STORAGE_PROVIDER=filesystem` | `ARTIFACT_FS_ROOT=./artifacts` (default)<br>`ARTIFACT_BUCKET=local-artifacts`<br>`ARTIFACT_SESSION_PROVIDER=memory` (default) |
| **S3 (AWS)** | `ARTIFACT_STORAGE_PROVIDER=s3`<br>`ARTIFACT_BUCKET=my-bucket`<br>`AWS_ACCESS_KEY_ID`<br>`AWS_SECRET_ACCESS_KEY` | `AWS_REGION=us-east-1` (default)<br>`S3_ENDPOINT_URL` (uses AWS by default)<br>`ARTIFACT_SESSION_PROVIDER=redis` (recommended) |
| **S3 (Tigris/MinIO)** | `ARTIFACT_STORAGE_PROVIDER=s3`<br>`ARTIFACT_BUCKET=my-bucket`<br>`S3_ENDPOINT_URL=https://...`<br>`AWS_ACCESS_KEY_ID`<br>`AWS_SECRET_ACCESS_KEY` | `AWS_REGION=auto`<br>`ARTIFACT_SESSION_PROVIDER=memory` |
| **IBM COS (HMAC)** | `ARTIFACT_STORAGE_PROVIDER=s3`<br>`ARTIFACT_BUCKET=my-bucket`<br>`S3_ENDPOINT_URL=https://s3.us-south...`<br>`AWS_ACCESS_KEY_ID`<br>`AWS_SECRET_ACCESS_KEY` | `AWS_REGION=us-south`<br>`ARTIFACT_SESSION_PROVIDER=memory` |
| **IBM COS (IAM)** | `ARTIFACT_STORAGE_PROVIDER=ibm_cos`<br>`ARTIFACT_BUCKET=my-bucket`<br>`IBM_COS_ENDPOINT=https://...`<br>`IBM_COS_APIKEY`<br>`IBM_COS_INSTANCE_CRN` | `ARTIFACT_SESSION_PROVIDER=memory` |

**Session Providers:** `ARTIFACT_SESSION_PROVIDER=memory` (default) or `redis` (requires `REDIS_URL`)

**Common Settings:** See [.env.example](.env.example) for complete configuration templates.

**Storage Provider Options:**

**1. Memory (Default - Development):**
```bash
# No configuration needed! Uses memory by default
# Perfect for: Development, testing, demos
# Pros: Zero setup, fast | Cons: Ephemeral, RAM-limited
```

**2. Filesystem (Local Development):**
```bash
export ARTIFACT_STORAGE_PROVIDER=filesystem
export ARTIFACT_SESSION_PROVIDER=memory
export ARTIFACT_FS_ROOT=./artifacts
export ARTIFACT_BUCKET=local-dev
# Perfect for: Single-server, debugging, persistence
# Pros: Persistent, inspectable | Cons: Not scalable
```

**3. AWS S3 or S3-Compatible (Production):**
```bash
# AWS S3
export ARTIFACT_STORAGE_PROVIDER=s3
export ARTIFACT_BUCKET=my-mcp-artifacts
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1

# Tigris (S3-compatible on Fly.io)
export ARTIFACT_STORAGE_PROVIDER=s3
export ARTIFACT_BUCKET=my-bucket
export S3_ENDPOINT_URL=https://fly.storage.tigris.dev
export AWS_ACCESS_KEY_ID=tid_...
export AWS_SECRET_ACCESS_KEY=tsec_...
export AWS_REGION=auto

# MinIO (S3-compatible, self-hosted)
export ARTIFACT_STORAGE_PROVIDER=s3
export ARTIFACT_BUCKET=mcp-artifacts
export S3_ENDPOINT_URL=http://localhost:9000
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin
export AWS_REGION=us-east-1

# Perfect for: Production, multi-server, cloud-native
# Pros: Scalable, durable (11 nines) | Cons: AWS account, costs
```

**4. IBM Cloud Object Storage (Enterprise):**
```bash
# Method 1: S3-Compatible HMAC Credentials (RECOMMENDED)
export ARTIFACT_STORAGE_PROVIDER=s3
export ARTIFACT_BUCKET=mcp-prod
export S3_ENDPOINT_URL=https://s3.us-south.cloud-object-storage.appdomain.cloud
export AWS_ACCESS_KEY_ID=<hmac-access-key>
export AWS_SECRET_ACCESS_KEY=<hmac-secret-key>
export AWS_REGION=us-south

# Method 2: Native IAM Credentials
export ARTIFACT_STORAGE_PROVIDER=ibm_cos
export ARTIFACT_BUCKET=mcp-prod
export IBM_COS_ENDPOINT=https://s3.us-south.cloud-object-storage.appdomain.cloud
export IBM_COS_APIKEY=<api-key>
export IBM_COS_INSTANCE_CRN=crn:v1:bluemix:...

# Perfect for: Enterprise, compliance (GDPR/HIPAA/SOC2)
# Pros: Enterprise SLA, compliance certs | Cons: IBM Cloud account
```

**Redis Session Provider** (recommended for production):

Redis Standalone:
```bash
export ARTIFACT_SESSION_PROVIDER=redis
export REDIS_URL=redis://localhost:6379
# Or with TLS:
export REDIS_URL=rediss://prod-redis:6379
export REDIS_TLS_INSECURE=0  # Set to 1 for self-signed certs
```

**Redis Cluster** (NEW - for high availability and horizontal scaling):
```bash
# Comma-separated node list (automatic cluster detection)
export ARTIFACT_SESSION_PROVIDER=redis
export REDIS_URL=redis://node1:7000,node2:7001,node3:7002

# With TLS
export REDIS_URL=rediss://node1:7000,node2:7001,node3:7002
export REDIS_TLS_INSECURE=0  # Set to 1 for self-signed certs

# Environment isolation (prevents key collisions)
export ENVIRONMENT=production  # or staging, dev
export DEPLOYMENT_ID=us-east-1  # unique per deployment
```

**Environment Isolation**: When multiple environments share the same Redis cluster, use `ENVIRONMENT` and `DEPLOYMENT_ID` to create isolated namespaces:
- Dev: `dev:local:sbx:*`
- Staging: `staging:us-west:sbx:*`
- Production: `production:us-east:sbx:*`

**Complete Examples:** See `.env.example` for full configuration examples for each use case.

### Authentication

| Variable | Purpose | Example | When to Use |
|----------|---------|---------|-------------|
| `JWT_SECRET_KEY` | JWT signing secret | `your-256-bit-secret` | **Required for auth** |
| `JWT_ALGORITHM` | Signing algorithm | `HS256`, `RS256` | Default: HS256 |
| `JWT_ALLOWED_ALGORITHMS` | Accepted algorithms | `HS256,RS256` | Multi-algorithm support |
| `JWT_LEEWAY` | Clock drift tolerance (seconds) | `5` | Distributed systems |

**Use case:**
```bash
# Production: use secrets manager
export JWT_SECRET_KEY=$(cat /run/secrets/jwt_key)

# Development: simple secret
export JWT_SECRET_KEY="dev-secret-do-not-use-in-prod"
```

### Advanced: Distributed Deployments

For multi-node, hub-and-spoke architectures:

| Variable | Purpose | Example |
|----------|---------|---------|
| `HUB_ID` | Hub instance identifier | `hub-primary` |
| `HUB_URL` | Hub registration endpoint | `https://hub.internal/register` |
| `HUB_ADDR` | Hub communication address | `hub.internal:8080` |
| `HUB_TOKEN` | Hub authentication token | `eyJ...` |
| `POD_IP` | Pod IP for service discovery | `10.1.2.3` |
| `SBX_TRANSPORT` | Sandbox transport protocol | `http`, `grpc` |

**Typical setup:**
```bash
# Hub node
export HUB_ID=hub-us-east

# Worker nodes
export HUB_URL=https://hub.internal/api
export HUB_TOKEN=$HUB_AUTH_TOKEN
export POD_IP=$(hostname -i)
```

### Configuration Priority Summary

**Lowest → Highest Priority:**
```
Default values
    ↓
Config file (config.yaml)
    ↓
Environment variables (MCP_TOOL_TIMEOUT=120)
    ↓
Command-line arguments (--config custom.yaml)
```

> 💡 **Note:** Per-tool decorator timeout (`@mcp_tool(timeout=30)`) still beats all config/env settings.

**Example:**
```bash
# config.yaml has: tools.timeout: 60
# This overrides to 120:
MCP_TOOL_TIMEOUT=120 chuk-mcp-server --config config.yaml
```

### Example Environment Setup

```bash
# Basic configuration
export CHUK_MCP_LOG_LEVEL=INFO
export MCP_TOOL_TIMEOUT=60
export MCP_SANDBOX_ID=my-app

# Artifact storage with filesystem
export ARTIFACT_STORAGE_PROVIDER=filesystem
export ARTIFACT_FS_ROOT=/var/lib/mcp-artifacts

# Session management with Redis
export ARTIFACT_SESSION_PROVIDER=redis
export SESSION_REDIS_URL=redis://localhost:6379/0

# JWT authentication
export JWT_SECRET_KEY=your-secret-key-here

# Run the server
chuk-mcp-server --config config.yaml
```

### Docker Example

```dockerfile
FROM python:3.11-slim

# Install runtime
RUN pip install chuk-mcp-runtime

# Set environment variables
ENV CHUK_MCP_LOG_LEVEL=INFO
ENV MCP_TOOL_TIMEOUT=60
ENV ARTIFACT_STORAGE_PROVIDER=filesystem
ENV ARTIFACT_FS_ROOT=/app/artifacts
ENV MCP_SANDBOX_ID=docker-app

# Copy configuration
COPY config.yaml /app/config.yaml
WORKDIR /app

CMD ["chuk-mcp-server", "--config", "config.yaml"]
```

Environment variables take precedence in this order:
1. Command line arguments (highest)
2. Environment variables
3. Configuration file values
4. Default values (lowest)

## Command Reference

### chuk-mcp-proxy

```
chuk-mcp-proxy [OPTIONS]
```

Options:
- `--config FILE`: YAML config file (optional, can be combined with flags below)
- `--stdio NAME`: Add a local stdio MCP server (repeatable)
- `--sse NAME`: Add a remote SSE MCP server (repeatable)
- `--command CMD`: Executable for stdio servers (default: python)
- `--cwd DIR`: Working directory for stdio server
- `--args ...`: Additional args for the stdio command
- `--url URL`: SSE base URL
- `--api-key KEY`: SSE API key (or set API_KEY env var)
- `--openai-compatible`: Use OpenAI-compatible tool names (underscores)

### chuk-mcp-server

```
chuk-mcp-server [OPTIONS]
```

Options:
- `--config FILE`: YAML configuration file
- `-c FILE`: Short form of --config
- Environment variable: `CHUK_MCP_CONFIG_PATH`

## Troubleshooting

### Common Issues

**"Tool not found" errors**:
- Check that tools are properly enabled in configuration
- Verify tool registration in the specified module
- Ensure async function signatures are correct

**Session validation errors**:
- Verify session management is configured
- Check that session tools are enabled if using session features
- Ensure proper async/await usage in tool implementations

**Timeout errors**:
- Increase tool timeout settings
- Check for blocking operations in async tools
- Monitor resource usage during tool execution

### Common HTTP Error Shapes

**401 Unauthorized**: Missing/invalid `Authorization: Bearer <token>`.
Fix: set `server.auth: bearer` and export `JWT_SECRET_KEY`; include a valid JWT in requests.

**404 Not Found** (tool): The tool name isn't registered under the chosen naming scheme.
Fix: run `tools/list` and double-check `proxy` namespace, underscore vs dot, and `keep_root_aliases`.

**408/504 or timeout error**: Tool exceeded timeout.
Fix: raise `tools.timeout` or per-tool `@mcp_tool(timeout=...)`;  avoid blocking calls in async tools.

**422 Validation error**: Wrong arg types (schema is auto-generated from type hints).
Fix: confirm parameter names/types match the tool signature.

### Debug Logging

Enable detailed logging:

```yaml
logging:
  level: "DEBUG"
  loggers:
    "chuk_mcp_runtime.tools": "DEBUG"
    "chuk_mcp_runtime.session": "DEBUG"
    "chuk_mcp_runtime.proxy": "DEBUG"
```

## Examples

See the `examples/` directory for complete working examples:

**Artifact Storage (v0.9)**:
- `examples/artifacts_v08_demo.py` - **NEW**: Three tool patterns demo
- `examples/scoped_artifacts_demo.py` - **NEW**: Storage scopes demonstration
- `examples/artifacts_memory.py` - In-memory artifact storage
- `examples/artifacts_filesystem.py` - Filesystem storage

**Session & Resources**:
- `examples/session_demo.py` - Session management
- `examples/session_isolation_demo.py` - Session isolation
- `examples/resources_e2e_demo.py` - Resource management

**Progress & Proxy**:
- `examples/progress_demo.py` - Progress notifications
- `examples/progress_e2e_demo.py` - E2E progress demo
- `examples/artifacts_progress_demo.py` - **NEW**: Artifact file operations with progress
- Proxy configurations - See Configuration Reference

**Run examples**:
```bash
# Storage scopes demo
uv run python examples/artifacts_v08_demo.py

# Complete scopes demonstration
uv run python examples/scoped_artifacts_demo.py

# Artifact file operations with progress bars
uv run python examples/artifacts_progress_demo.py
```

## Development

### Quick Development Setup

```bash
# Clone the repository
git clone https://github.com/chrishayuk/chuk-mcp-runtime.git
cd chuk-mcp-runtime

# Install in development mode
make dev-install        # Install with dev dependencies
make dev-install-all    # Install with ALL optional dependencies (websocket, etc.)
```

### Available Make Commands

```bash
# Testing
make test              # Run tests
make test-cov          # Run tests with coverage report
make coverage-report   # Show current coverage summary

# Code Quality
make lint              # Check code with ruff
make format            # Auto-format code
make typecheck         # Run mypy type checking
make security          # Run bandit security checks
make check             # Run all checks (lint + typecheck + security + test)

# Cleaning
make clean             # Remove Python bytecode
make clean-build       # Remove build artifacts
make clean-test        # Remove test artifacts
make clean-all         # Deep clean everything

# Version Management
make version           # Show current version
make bump-patch        # Bump patch version (0.0.X)
make bump-minor        # Bump minor version (0.X.0)
make bump-major        # Bump major version (X.0.0)

# Release & Publishing (Automated via GitHub Actions)
make publish           # Create tag and trigger automated release
make publish-test      # Upload to TestPyPI for testing
make publish-manual    # Manually upload to PyPI (requires PYPI_TOKEN)
make build             # Build distribution packages
```

### Running Tests

```bash
# Run all tests
make test

# Run with coverage report
make test-cov

# Run specific test file
PYTHONPATH=src uv run pytest tests/server/test_config_loader.py

# Show coverage summary
make coverage-report
```

### Automated Release Workflow

This project uses an automated release workflow powered by GitHub Actions:

```bash
# 1. Bump the version
make bump-patch        # For bug fixes (0.10.3 → 0.10.4)
make bump-minor        # For new features (0.10.3 → 0.11.0)
make bump-major        # For breaking changes (0.10.3 → 1.0.0)

# 2. Review and commit the version change
git add pyproject.toml
git commit -m "Bump version to 0.10.4"
git push

# 3. Trigger automated release
make publish
# This will:
# - Create and push a git tag (e.g., v0.10.4)
# - Trigger GitHub Actions to:
#   → Create a GitHub Release with changelog
#   → Run tests on all platforms (Ubuntu, Windows, macOS)
#   → Build and publish to PyPI automatically
```

**What happens automatically:**
1. **`release.yml`** - Creates GitHub Release with auto-generated changelog
2. **`publish.yml`** - Runs full test suite, builds package, publishes to PyPI
3. **`test.yml`** - Multi-platform tests (Python 3.11, 3.12, 3.13)

**Alternative: Manual PyPI Upload**
```bash
make publish-manual    # Requires PYPI_TOKEN environment variable
```

### Code Quality Standards

The project maintains high quality standards:
- **97% test coverage** - All core modules fully tested
- **Type hints** - Full mypy type checking
- **Ruff linting** - Fast Python linter and formatter
- **Security scanning** - Bandit security checks
- **Multi-platform CI** - Tested on Ubuntu, Windows, macOS

> 🧠 Built and continuously tested against the latest [official MCP SDK](https://github.com/modelcontextprotocol), ensuring forward compatibility.

### Versioning & Compatibility

**Versioning:** SemVer. Continuously tested against the latest official MCP SDK.
**Breaking changes:** Only in `MAJOR` releases; see GitHub Releases for migration notes.
**CI/CD:** Automated testing and publishing via GitHub Actions.

### Docker Compose (Development)

```yaml
# docker-compose.yml (dev)
services:
  mcp:
    image: python:3.11-slim
    command: ["bash","-lc","pip install chuk-mcp-runtime tzdata && chuk-mcp-server --config /app/config.yaml"]
    environment:
      JWT_SECRET_KEY: dev-secret
      CHUK_MCP_LOG_LEVEL: INFO
    ports:
      - "3000:3000"
      - "8000:8000"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and checks (`make check`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Contribution Guidelines

- Maintain or improve test coverage (>90%)
- Follow existing code style (enforced by ruff)
- Add tests for new features
- Update documentation as needed
- Ensure all checks pass (`make check`)

## License

- **License:** MIT — see [LICENSE](./LICENSE)
- **Changelog:** Track releases and changes in [GitHub Releases](https://github.com/chrishayuk/chuk-mcp-runtime/releases)