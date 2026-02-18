# CHUK MCP Runtime Examples

This directory contains focused examples demonstrating key features of the CHUK MCP Runtime.

## Configuration

**All artifact examples automatically load settings from `.env` file!** You can also pass environment variables directly.

Copy `.env.example` to `.env` and configure your preferred storage provider:
```bash
cp .env.example .env
# Edit .env with your credentials
```

See [.env.example](../.env.example) for complete configuration examples.

## Quick Start

### Basic MCP Server
**`mcp_minimal.py`** - Minimal MCP server with basic tool registration
```bash
uv run python examples/mcp_minimal.py
```

## Artifacts Storage

Artifacts examples demonstrate file storage with **4 backend providers** (memory, filesystem, s3, ibm_cos). Each example includes session management and shows the `write_file` and `list_session_files` tools in action.

### 1. Memory Storage (Default)
**`artifacts_memory.py`** - In-memory session storage
- ⚡ **Zero configuration needed** - works out of the box!
- Fast, ephemeral storage in RAM
- Perfect for development, testing, and demos

```bash
# No .env needed! Just run it:
uv run python examples/artifacts_memory.py

# Or explicitly set:
ARTIFACT_SESSION_PROVIDER=memory uv run python examples/artifacts_memory.py
```

**Output:** Shows 3 files created and listed in same session
```
✅ Created (session: sess-xxx)
📋 Files in session:
  • README.md (39 bytes)
  • config.json (30 bytes)
  • notes.txt (49 bytes)
```

### 2. Filesystem Storage
**`artifacts_filesystem.py`** - Local filesystem persistence
- 💾 Persistent storage on disk
- Files survive server restarts
- Easy inspection of stored files
- Great for local development and debugging

```bash
# Uses .env if configured, or runs with defaults:
uv run python examples/artifacts_filesystem.py
```

**Output:** Shows files in session + actual filesystem paths
```
📋 Files in session: deployment.yaml, data.json, report.md
📁 Filesystem Contents: 6 files on disk (data + metadata)
```

### 3. AWS S3 Storage (Production)
**`artifacts_s3.py`** - Amazon S3 and S3-compatible storage
- ☁️ **Supports AWS S3, Tigris, MinIO, and more**
- Scalable, durable (99.999999999% - 11 nines!)
- Multi-region support
- **Automatically loads credentials from `.env`**

**Setup `.env`:**
```bash
ARTIFACT_STORAGE_PROVIDER=s3
ARTIFACT_BUCKET=my-bucket
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
# For Tigris/MinIO, add:
# S3_ENDPOINT_URL=https://fly.storage.tigris.dev
```

```bash
# Run with .env:
uv run python examples/artifacts_s3.py

# Or override with environment variables:
ARTIFACT_BUCKET=my-bucket uv run python examples/artifacts_s3.py
```

**Output:**
```
🪣 S3 Bucket: my-bucket
🌎 Region: us-east-1
📋 Files in S3:
  • cloudformation.yaml (87 bytes)
  • metrics.json (53 bytes)
  • analysis.md (127 bytes)
```

### 4. IBM Cloud Object Storage (Enterprise)
**`artifacts_ibm_cos.py`** - IBM COS for enterprise deployments
- 🏢 Enterprise-grade SLA and compliance
- GDPR, HIPAA, SOC 2, ISO certifications
- Immutable Object Storage support
- **Supports both S3-compatible HMAC and native IAM credentials**
- **Automatically loads credentials from `.env`**

**Setup `.env` (Method 1 - S3-Compatible HMAC):**
```bash
ARTIFACT_STORAGE_PROVIDER=s3  # Uses S3 provider with IBM endpoint
ARTIFACT_BUCKET=my-cos-bucket
S3_ENDPOINT_URL=https://s3.us-south.cloud-object-storage.appdomain.cloud
AWS_ACCESS_KEY_ID=<hmac-access-key>
AWS_SECRET_ACCESS_KEY=<hmac-secret-key>
AWS_REGION=us-south
```

**Setup `.env` (Method 2 - Native IAM):**
```bash
ARTIFACT_STORAGE_PROVIDER=ibm_cos
ARTIFACT_BUCKET=my-cos-bucket
IBM_COS_ENDPOINT=https://s3.us-south.cloud-object-storage.appdomain.cloud
IBM_COS_APIKEY=<api-key>
IBM_COS_INSTANCE_CRN=crn:v1:bluemix:...
```

```bash
# Run with .env:
uv run python examples/artifacts_ibm_cos.py

# Or override:
ARTIFACT_BUCKET=my-bucket uv run python examples/artifacts_ibm_cos.py
```

**Output:**
```
🪣 Bucket: my-cos-bucket
🔑 Auth: AWS S3 credentials (recommended)
📋 Files in IBM COS:
  • terraform.tf (112 bytes)
  • compliance.json (67 bytes)
  • architecture.md (122 bytes)
```

## Feature Demos

### Resources
**`resources_e2e_demo.py`** - End-to-end demonstration of MCP resources
- Custom resources with `@mcp_resource` decorator
- Artifact resources integration
- Resource listing and reading via `resources/list` and `resources/read`

```bash
# Requires artifacts provider configuration
ARTIFACT_SESSION_PROVIDER=memory uv run python examples/resources_e2e_demo.py
```

Configuration: `resources_demo_config.yaml`

### Proxy Integration
**`proxy_server_example.py`** - Proxy server integration demo
- Boots external MCP servers via ProxyServerManager
- Tool namespace management (dot notation vs underscore)
- Registry inspection and tool execution

```bash
uv run python examples/proxy_server_example.py
```

Configuration: `proxy_config.yaml`

### OpenAI Compatibility
**`openai_compatibility_demo.py`** - OpenAI-compatible tool naming
- Underscore-based tool names for OpenAI API compatibility
- ProxyServerManager in OpenAI-only mode

```bash
uv run python examples/openai_compatibility_demo.py --only-openai-tools
```

Configuration: `openai_compatible_config.yaml`

### Progress Tracking
**`progress_e2e_demo.py`** - Progress notification demonstration
- Server-sent progress updates
- Integration with MCP progress protocol

```bash
uv run python examples/progress_e2e_demo.py
```

### Session Management
**`session_demo.py`** - Session ID management and lifecycle
- Automatic session creation on first operation
- Capturing and reusing session IDs
- Managing files within a session
- Session-based file listing

```bash
uv run python examples/session_demo.py
```

**`session_isolation_demo.py`** - Session isolation testing
- Creating multiple independent sessions
- Testing file isolation between sessions
- Understanding isolation behavior by provider
- Memory vs persistent storage isolation differences

```bash
uv run python examples/session_isolation_demo.py
```

**Note:** With memory provider, files are visible across all sessions. For true isolation, use Redis session provider or persistent storage configuration.

### Streaming
**`stream_demo.py`** - Server-Sent Events (SSE) streaming
- Token-by-token streaming responses
- JSON-RPC handshake over /messages endpoint
- Real-time event streaming via /sse

```bash
uv run python examples/stream_demo.py
```

## Simple Server

The `simple_server/` directory contains a minimal MCP server implementation useful as a reference or starting point for your own server.

```bash
cd examples/simple_server
uv run python main.py
```

## Configuration Files

- `proxy_config.yaml` - Proxy server configuration
- `openai_compatible_config.yaml` - OpenAI compatibility settings
- `resources_demo_config.yaml` - Resources and artifacts configuration

## Running Examples

All examples can be run using `uv`:

```bash
# From the repository root
uv run python examples/<example_name>.py

# Or with environment variables
ARTIFACT_SESSION_PROVIDER=memory uv run python examples/resources_e2e_demo.py
```

## Environment Variables

**💡 Tip:** All artifact examples automatically load variables from `.env` file in the project root. See [.env.example](../.env.example) for complete configuration templates.

### Quick Reference

**Storage Providers - Required Variables:**

| Provider | Variables Required | Optional |
|----------|-------------------|----------|
| **Memory** | None (default) | `ARTIFACT_STORAGE_PROVIDER=memory`<br>`ARTIFACT_SESSION_PROVIDER=memory` |
| **Filesystem** | `ARTIFACT_STORAGE_PROVIDER=filesystem` | `ARTIFACT_FS_ROOT=./artifacts`<br>`ARTIFACT_BUCKET=local-artifacts`<br>`ARTIFACT_SESSION_PROVIDER=memory` |
| **S3 (AWS)** | `ARTIFACT_STORAGE_PROVIDER=s3`<br>`ARTIFACT_BUCKET=my-bucket`<br>`AWS_ACCESS_KEY_ID=...`<br>`AWS_SECRET_ACCESS_KEY=...` | `AWS_REGION=us-east-1` (default)<br>`ARTIFACT_SESSION_PROVIDER=redis` |
| **S3 (Tigris/MinIO)** | `ARTIFACT_STORAGE_PROVIDER=s3`<br>`ARTIFACT_BUCKET=my-bucket`<br>`S3_ENDPOINT_URL=https://...`<br>`AWS_ACCESS_KEY_ID=...`<br>`AWS_SECRET_ACCESS_KEY=...` | `AWS_REGION=auto`<br>`ARTIFACT_SESSION_PROVIDER=memory` |
| **IBM COS (HMAC)** | `ARTIFACT_STORAGE_PROVIDER=s3`<br>`ARTIFACT_BUCKET=my-bucket`<br>`S3_ENDPOINT_URL=https://s3.us-south...`<br>`AWS_ACCESS_KEY_ID=...`<br>`AWS_SECRET_ACCESS_KEY=...` | `AWS_REGION=us-south`<br>`ARTIFACT_SESSION_PROVIDER=memory` |
| **IBM COS (IAM)** | `ARTIFACT_STORAGE_PROVIDER=ibm_cos`<br>`ARTIFACT_BUCKET=my-bucket`<br>`IBM_COS_ENDPOINT=https://...`<br>`IBM_COS_APIKEY=...`<br>`IBM_COS_INSTANCE_CRN=crn:v1...` | `ARTIFACT_SESSION_PROVIDER=memory` |

**Session Providers:**

| Provider | Variables Required | Optional |
|----------|-------------------|----------|
| **Memory** | None (default) | `ARTIFACT_SESSION_PROVIDER=memory` |
| **Redis** | `ARTIFACT_SESSION_PROVIDER=redis`<br>`REDIS_URL=redis://localhost:6379/0` | `REDIS_TLS_INSECURE=1` (disable cert check) |

### Storage Providers

**Memory (Default):**
```bash
# No configuration needed - uses memory by default
ARTIFACT_STORAGE_PROVIDER=memory
ARTIFACT_SESSION_PROVIDER=memory
```

**Filesystem:**
```bash
ARTIFACT_STORAGE_PROVIDER=filesystem
ARTIFACT_SESSION_PROVIDER=memory
ARTIFACT_FS_ROOT=./artifacts
ARTIFACT_BUCKET=local-dev
```

**AWS S3 / S3-Compatible (Tigris, MinIO):**
```bash
ARTIFACT_STORAGE_PROVIDER=s3
ARTIFACT_BUCKET=my-mcp-artifacts
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
# Optional for S3-compatible services:
S3_ENDPOINT_URL=https://fly.storage.tigris.dev
```

**IBM Cloud Object Storage:**
```bash
# Method 1: S3-compatible HMAC (recommended)
ARTIFACT_STORAGE_PROVIDER=s3
ARTIFACT_BUCKET=my-cos-bucket
S3_ENDPOINT_URL=https://s3.us-south.cloud-object-storage.appdomain.cloud
AWS_ACCESS_KEY_ID=<hmac-access-key>
AWS_SECRET_ACCESS_KEY=<hmac-secret-key>
AWS_REGION=us-south

# Method 2: Native IAM credentials
ARTIFACT_STORAGE_PROVIDER=ibm_cos
ARTIFACT_BUCKET=my-cos-bucket
IBM_COS_ENDPOINT=https://s3.us-south.cloud-object-storage.appdomain.cloud
IBM_COS_APIKEY=<api-key>
IBM_COS_INSTANCE_CRN=crn:v1:bluemix:...
```

### Session Providers

**Memory (Default):**
```bash
ARTIFACT_SESSION_PROVIDER=memory
```

**Redis (Production):**
```bash
ARTIFACT_SESSION_PROVIDER=redis
REDIS_URL=redis://localhost:6379/0
# Or with TLS:
REDIS_URL=rediss://prod-redis:6379/0
REDIS_TLS_INSECURE=0
```

### Additional Settings

**General:**
- `CHUK_MCP_LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)
- `MCP_SANDBOX_ID` - Sandbox identifier for multi-tenant isolation
- `SESSION_TTL_HOURS` - Session lifetime in hours (default: 24)

**Artifact Tuning:**
- `ARTIFACT_METADATA_TTL` - Metadata cache TTL in seconds (default: 900)
- `ARTIFACT_PRESIGN_EXPIRES` - Presigned URL expiry in seconds (default: 3600)

## Learn More

For detailed documentation, see the main [README.md](../README.md) in the repository root.
