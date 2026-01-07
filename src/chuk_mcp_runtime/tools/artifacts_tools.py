# chuk_mcp_runtime/tools/artifacts_tools.py
"""
Configurable MCP Tools Integration for chuk_artifacts

This module provides configurable MCP tools that can be enabled/disabled
and customized via config.yaml settings.

NOTE: These tools are DISABLED by default and must be explicitly enabled
in configuration to be available.
"""

import base64
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union

# chuk-artifacts pydantic models
from chuk_artifacts import ArtifactNotFoundError, ArtifactStore
from chuk_artifacts.models import ArtifactMetadata

from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY, mcp_tool
from chuk_mcp_runtime.server.logging_config import get_logger

# logger
logger = get_logger("chuk_mcp_runtime.tools.artifacts")

# Global artifact store instance and configuration
_artifact_store: Optional[ArtifactStore] = None
_artifacts_config: Dict[str, Any] = {}
_enabled_tools: Set[str] = set()
_store_lock: Optional[Any] = None  # Initialized on first use (asyncio.Lock)

# FIXED: Default tool configuration - DISABLED by default
DEFAULT_TOOL_CONFIG = {
    "enabled": False,  # DISABLED by default - must be explicitly enabled in config
    "tools": {
        # General tools with scope parameter (backward compatible, default=session)
        "upload_file": {
            "enabled": False,
            "description": "Upload file (scope: session or user, default=session)",
        },
        "write_file": {
            "enabled": False,
            "description": "Write file (scope: session or user, default=session)",
        },
        "read_file": {"enabled": False, "description": "Read file (auto access control)"},
        "delete_file": {"enabled": False, "description": "Delete file (auto access control)"},
        "list_directory": {"enabled": False, "description": "List directory contents"},
        "copy_file": {"enabled": False, "description": "Copy files within session"},
        "move_file": {"enabled": False, "description": "Move/rename files"},
        "get_file_metadata": {"enabled": False, "description": "Get file metadata"},
        "get_presigned_url": {
            "enabled": False,
            "description": "Generate presigned URLs",
        },
        "get_storage_stats": {
            "enabled": False,
            "description": "Get storage statistics",
        },
        # Explicit session-scoped tools (v0.8)
        "write_session_file": {
            "enabled": False,
            "description": "Write file to session storage (ephemeral)",
        },
        "upload_session_file": {
            "enabled": False,
            "description": "Upload file to session storage (ephemeral)",
        },
        "list_session_files": {
            "enabled": False,
            "description": "List files in current session",
        },
        # Explicit user-scoped tools (v0.8)
        "write_user_file": {
            "enabled": False,
            "description": "Write file to user storage (persistent)",
        },
        "upload_user_file": {
            "enabled": False,
            "description": "Upload file to user storage (persistent)",
        },
        "list_user_files": {
            "enabled": False,
            "description": "List user's persistent files",
        },
    },
}


def configure_artifacts_tools(config: Dict[str, Any]) -> None:
    """Configure artifacts tools based on config.yaml settings."""
    global _artifacts_config, _enabled_tools

    # Get artifacts configuration
    _artifacts_config = config.get("artifacts", {})

    # Determine which tools are enabled
    _enabled_tools.clear()

    # Check if artifacts tools are enabled globally
    if not _artifacts_config.get("enabled", False):
        logger.debug(
            "Artifact tools disabled in configuration - use 'artifacts.enabled: true' to enable"
        )
        return

    # Process individual tool configuration
    tool_settings = _artifacts_config.get("tools", DEFAULT_TOOL_CONFIG["tools"])

    # Loop through each tool and see if we should enable it
    for tool_name, tool_config in tool_settings.items():
        if tool_config.get("enabled", False):
            _enabled_tools.add(tool_name)
            logger.debug(f"Enabled artifact tool: {tool_name}")
        else:
            logger.debug(
                f"Disabled artifact tool: {tool_name} - use 'artifacts.tools.{tool_name}.enabled: true' to enable"
            )

    # Log the results
    if _enabled_tools:
        logger.debug(
            f"Configured {len(_enabled_tools)} artifact tools: {', '.join(sorted(_enabled_tools))}"
        )
    else:
        logger.debug("No artifact tools enabled - all tools require explicit configuration")


def is_tool_enabled(tool_name: str) -> bool:
    """Check if a specific tool is enabled."""
    return tool_name in _enabled_tools


async def get_artifact_store() -> ArtifactStore:
    """Get or create the global artifact store instance with thread-safe initialization."""
    global _artifact_store, _store_lock
    import asyncio

    # Initialize lock on first call
    if _store_lock is None:
        _store_lock = asyncio.Lock()

    if _artifact_store is None:
        async with _store_lock:
            # Double-check after acquiring lock
            if _artifact_store is None:
                # Use configuration or environment variables or sensible defaults
                storage_provider = _artifacts_config.get("storage_provider") or os.getenv(
                    "ARTIFACT_STORAGE_PROVIDER", "filesystem"
                )
                session_provider = _artifacts_config.get("session_provider") or os.getenv(
                    "ARTIFACT_SESSION_PROVIDER", "memory"
                )
                bucket = _artifacts_config.get("bucket") or os.getenv(
                    "ARTIFACT_BUCKET", "mcp-runtime"
                )

                # Set up filesystem root if using filesystem storage
                if storage_provider == "filesystem":
                    fs_root = (
                        _artifacts_config.get("filesystem_root")
                        or os.getenv("ARTIFACT_FS_ROOT")
                        or os.path.expanduser("~/.chuk_mcp_artifacts")
                    )
                    os.environ["ARTIFACT_FS_ROOT"] = fs_root

                _artifact_store = ArtifactStore(
                    storage_provider=storage_provider,
                    session_provider=session_provider,
                    bucket=bucket,
                )

                logger.info(
                    f"Initialized artifact store: {storage_provider}/{session_provider} -> {bucket}"
                )

    return _artifact_store


def _check_availability():
    """Check if chuk_artifacts is available and raise helpful error if not."""
    return True


def _check_tool_enabled(tool_name: str):
    """Check if a tool is enabled and raise error if not."""
    if not is_tool_enabled(tool_name):
        raise ValueError(
            f"Tool '{tool_name}' is disabled in configuration - use 'artifacts.tools.{tool_name}.enabled: true' to enable"
        )


# ============================================================================
# Artifact Management Tools - All decorated with @mcp_tool
# ============================================================================


@mcp_tool(name="upload_file", description="Upload files with base64 content")
async def upload_file(
    content: str,
    filename: str,
    mime: str = "application/octet-stream",
    summary: str = "File uploaded via MCP",
    scope: str = "session",
    ttl: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Upload a file with base64 encoded content to the artifact store.
    Reports progress notifications if client provides a progress token.

    Args:
        content: Base64 encoded file content
        filename: Name of the file to create
        mime: MIME type of the file (default: application/octet-stream)
        summary: Description of the file (default: File uploaded via MCP)
        scope: Storage scope - 'session' (ephemeral) or 'user' (persistent)
        ttl: Time to live in seconds (optional, defaults based on scope)
        meta: Additional metadata for the file (optional)

    Returns:
        Success message with artifact ID
    """
    _check_tool_enabled("upload_file")

    # Get session and user from context (NEVER from parameters!)
    from chuk_mcp_runtime.server.request_context import send_progress
    from chuk_mcp_runtime.session.native_session_management import (
        get_session_or_none,
        get_user_or_none,
        require_session,
        require_user,
    )

    # Determine required context based on scope
    user_id: Optional[str]
    session_id: Optional[str]

    if scope == "user":
        user_id = require_user()  # Must be authenticated
        session_id = get_session_or_none()
        default_ttl = ttl or 86400 * 365  # 1 year
    elif scope == "sandbox":
        raise ValueError("Sandbox scope not allowed for uploads (admin only)")
    else:  # session (default)
        user_id = get_user_or_none()
        session_id = require_session()  # Must have session
        default_ttl = ttl or 900  # 15 minutes

    store = await get_artifact_store()

    try:
        # Report progress: Decoding base64
        await send_progress(1, 4, f"Decoding {filename}...")
        file_data = base64.b64decode(content)
        file_size = len(file_data)

        # Report progress: Preparing upload
        await send_progress(2, 4, f"Preparing upload ({file_size:,} bytes)...")
        upload_meta = {
            "uploaded_via": "mcp",
            "upload_time": datetime.now().isoformat(),
            "scope": scope,
            **(meta or {}),
        }

        # Report progress: Uploading
        await send_progress(3, 4, f"Uploading to {scope} storage...")
        artifact_id = await store.store(
            data=file_data,
            mime=mime,
            summary=summary,
            filename=filename,
            user_id=user_id,
            session_id=session_id,
            scope=scope,
            ttl=default_ttl,
            meta=upload_meta,
        )

        # Report progress: Complete
        await send_progress(4, 4, f"Upload complete: {artifact_id}")

        return f"File uploaded to {scope} storage. Artifact ID: {artifact_id}"

    except Exception as e:
        raise ValueError(f"Failed to upload file: {str(e)}")


@mcp_tool(name="write_file", description="Create or update text files")
async def write_file(
    content: str,
    filename: str,
    mime: str = "text/plain",
    summary: str = "File created via MCP",
    scope: str = "session",
    ttl: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Create or update a text file in the artifact store.
    Reports progress notifications if client provides a progress token.

    Args:
        content: Text content of the file
        filename: Name of the file to create
        mime: MIME type of the file (default: text/plain)
        summary: Description of the file (default: File created via MCP)
        scope: Storage scope - 'session' (ephemeral) or 'user' (persistent)
        ttl: Time to live in seconds (optional, defaults based on scope)
        meta: Additional metadata for the file (optional)

    Returns:
        Success message with artifact ID
    """
    _check_tool_enabled("write_file")

    # Get session and user from context (NEVER from parameters!)
    from chuk_mcp_runtime.server.request_context import send_progress
    from chuk_mcp_runtime.session.native_session_management import (
        get_session_or_none,
        get_user_or_none,
        require_session,
        require_user,
    )

    # Determine required context based on scope
    user_id: Optional[str]
    session_id: Optional[str]

    if scope == "user":
        user_id = require_user()  # Must be authenticated
        session_id = get_session_or_none()
        default_ttl = ttl or 86400 * 365  # 1 year
    elif scope == "sandbox":
        raise ValueError("Sandbox scope not allowed for writes (admin only)")
    else:  # session (default)
        user_id = get_user_or_none()
        session_id = require_session()  # Must have session
        default_ttl = ttl or 900  # 15 minutes

    logger.info(f"[ARTIFACT] write_file: scope={scope}, session={session_id}, user={user_id}")

    store = await get_artifact_store()

    try:
        # Report progress: Preparing
        await send_progress(1, 3, f"Preparing to write {filename}...")
        write_meta = {
            "created_via": "mcp",
            "creation_time": datetime.now().isoformat(),
            "scope": scope,
            **(meta or {}),
        }

        # Convert content to bytes if needed
        if isinstance(content, str):
            data = content.encode("utf-8")
        else:
            data = content

        # Report progress: Writing
        await send_progress(2, 3, f"Writing to {scope} storage...")
        artifact_id = await store.store(
            data=data,
            mime=mime,
            summary=summary,
            filename=filename,
            user_id=user_id,
            session_id=session_id,
            scope=scope,
            ttl=default_ttl,
            meta=write_meta,
        )

        # Report progress: Complete
        await send_progress(3, 3, f"File created: {artifact_id}")

        return f"File created in {scope} storage. Artifact ID: {artifact_id}"

    except Exception as e:
        raise ValueError(f"Failed to write file: {str(e)}")


@mcp_tool(name="read_file", description="Read file contents")
async def read_file(artifact_id: str, as_text: bool = True) -> Union[str, Dict[str, Any]]:
    """
    Read the content of a file from the artifact store.
    Automatically enforces access control based on file scope.

    Args:
        artifact_id: Unique identifier of the file to read
        as_text: Whether to return content as text (default: True) or as binary with metadata

    Returns:
        File content as text, or dictionary with content and metadata if as_text=False
    """
    _check_tool_enabled("read_file")

    # Get session and user from context (NEVER from parameters!)
    from chuk_mcp_runtime.session.native_session_management import (
        get_session_or_none,
        get_user_or_none,
    )

    user_id = get_user_or_none()
    session_id = get_session_or_none()

    store = await get_artifact_store()

    try:
        # Get metadata to check scope and ownership (returns pydantic ArtifactMetadata)
        metadata: ArtifactMetadata = await store.metadata(artifact_id)

        # Access control based on scope
        if metadata.scope == "user":
            # User scope: Must be the owner
            if not user_id or user_id != metadata.owner_id:
                raise ValueError(f"Access denied: file belongs to user {metadata.owner_id}")
            data = await store.retrieve(artifact_id, user_id=user_id)

        elif metadata.scope == "session":
            # Session scope: Must be same session
            if not session_id or session_id != metadata.session_id:
                raise ValueError("Access denied: file belongs to different session")
            data = await store.retrieve(artifact_id, session_id=session_id)

        elif metadata.scope == "sandbox":
            # Sandbox scope: Anyone can read
            data = await store.retrieve(artifact_id)

        else:
            raise ValueError(f"Unknown scope: {metadata.scope}")

        if as_text:
            return data.decode()
        else:
            # Use pydantic model with additional runtime data
            return {
                "content": base64.b64encode(data).decode(),
                "filename": metadata.filename or "unknown",
                "mime": metadata.mime,
                "size": len(data),
                "scope": metadata.scope,
                "owner": metadata.owner_id,
                "metadata": metadata.model_dump(),  # Serialize pydantic model
            }

    except ArtifactNotFoundError:
        raise ValueError(f"File not found: {artifact_id}")
    except Exception as e:
        raise ValueError(f"Failed to read file: {str(e)}")


@mcp_tool(name="list_session_files", description="List files in current session")
async def list_session_files(include_metadata: bool = False) -> List[Dict[str, Any]]:
    """
    List all files in the current session (ephemeral scope only).

    Args:
        include_metadata: Whether to include full metadata for each file (default: False)

    Returns:
        List of files in the session with basic or full metadata
    """
    _check_tool_enabled("list_session_files")

    # Get session from context (NEVER from parameters!)
    from chuk_mcp_runtime.session.native_session_management import require_session

    session_id = require_session()

    logger.info(f"[ARTIFACT] list_session_files: session={session_id}")

    store = await get_artifact_store()

    try:
        # Returns List[ArtifactMetadata] - pydantic models with dict compatibility
        files: List[ArtifactMetadata] = await store.list_by_session(session_id)

        if include_metadata:
            # Serialize pydantic models to dicts
            return [f.model_dump() for f in files]
        else:
            # Return simplified view using pydantic attributes
            return [
                {
                    "artifact_id": f.artifact_id,
                    "filename": f.filename or "unknown",
                    "mime": f.mime,
                    "bytes": f.bytes,
                    "summary": f.summary,
                    "scope": f.scope,
                    "created": f.stored_at,
                }
                for f in files
            ]

    except Exception as e:
        raise ValueError(f"Failed to list files: {str(e)}")


@mcp_tool(name="delete_file", description="Delete files")
async def delete_file(artifact_id: str) -> str:
    """
    Delete a file from the artifact store.
    Automatically enforces access control based on file scope.

    Args:
        artifact_id: Unique identifier of the file to delete

    Returns:
        Success or failure message
    """
    _check_tool_enabled("delete_file")

    # Get session and user from context (NEVER from parameters!)
    from chuk_mcp_runtime.session.native_session_management import (
        get_session_or_none,
        get_user_or_none,
    )

    user_id = get_user_or_none()
    session_id = get_session_or_none()

    store = await get_artifact_store()

    try:
        # Get metadata to check scope and ownership (returns pydantic ArtifactMetadata)
        metadata: ArtifactMetadata = await store.metadata(artifact_id)

        # Access control based on scope
        if metadata.scope == "user":
            # User scope: Must be the owner
            if not user_id or user_id != metadata.owner_id:
                raise ValueError(f"Access denied: file belongs to user {metadata.owner_id}")
            deleted = await store.delete(artifact_id, user_id=user_id)

        elif metadata.scope == "session":
            # Session scope: Must be same session
            if not session_id or session_id != metadata.session_id:
                raise ValueError("Access denied: file belongs to different session")
            deleted = await store.delete(artifact_id, session_id=session_id)

        elif metadata.scope == "sandbox":
            # Sandbox scope: Admin only
            raise ValueError("Cannot delete sandbox files (admin only)")

        else:
            raise ValueError(f"Unknown scope: {metadata.scope}")

        if deleted:
            return f"File deleted successfully: {artifact_id}"
        else:
            return f"File not found or already deleted: {artifact_id}"

    except ArtifactNotFoundError:
        raise ValueError(f"File not found: {artifact_id}")
    except Exception as e:
        raise ValueError(f"Failed to delete file: {str(e)}")


@mcp_tool(name="list_directory", description="List directory contents")
async def list_directory(directory_path: str) -> List[Dict[str, Any]]:
    """
    List files in a specific directory within the current session.

    Args:
        directory_path: Path to the directory to list

    Returns:
        List of files in the specified directory
    """
    _check_tool_enabled("list_directory")

    # Get session from context (NEVER from parameters!)
    from chuk_mcp_runtime.session.native_session_management import require_session

    session_id = require_session()

    store = await get_artifact_store()

    try:
        # Returns List[ArtifactMetadata] or similar structure
        files = await store.get_directory_contents(session_id, directory_path)

        return [
            {
                "artifact_id": f.artifact_id if hasattr(f, "artifact_id") else f.get("artifact_id"),
                "filename": f.filename if hasattr(f, "filename") else f.get("filename", "unknown"),
                "mime": f.mime if hasattr(f, "mime") else f.get("mime", "unknown"),
                "bytes": f.bytes if hasattr(f, "bytes") else f.get("bytes", 0),
                "summary": f.summary if hasattr(f, "summary") else f.get("summary", ""),
            }
            for f in files
        ]

    except Exception as e:
        raise ValueError(f"Failed to list directory: {str(e)}")


@mcp_tool(name="copy_file", description="Copy files within session")
async def copy_file(
    artifact_id: str,
    new_filename: str,
    new_summary: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Copy a file within the current session.

    Args:
        artifact_id: Unique identifier of the file to copy
        new_filename: Name for the copied file
        new_summary: Description for the copied file (optional)
        meta: Additional metadata for the copied file (optional)

    Returns:
        Success message with new artifact ID
    """
    _check_tool_enabled("copy_file")

    # Get session from context (NEVER from parameters!)
    from chuk_mcp_runtime.session.native_session_management import require_session

    require_session()  # Validate session exists

    store = await get_artifact_store()

    try:
        copy_meta = {
            "copied_via": "mcp",
            "copy_time": datetime.now().isoformat(),
            "original_artifact_id": artifact_id,
            **(meta or {}),
        }

        # Use the actual API parameters that work
        new_artifact_id = await store.copy_file(
            artifact_id, new_filename=new_filename, new_meta=copy_meta
        )

        return f"File copied successfully. New artifact ID: {new_artifact_id}"

    except Exception as e:
        raise ValueError(f"Failed to copy file: {str(e)}")


@mcp_tool(name="move_file", description="Move/rename files")
async def move_file(
    artifact_id: str,
    new_filename: str,
    new_summary: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Move/rename a file within the current session.

    Args:
        artifact_id: Unique identifier of the file to move/rename
        new_filename: New name for the file
        new_summary: New description for the file (optional)
        meta: Additional metadata for the moved file (optional)

    Returns:
        Success message confirming the move
    """
    _check_tool_enabled("move_file")

    # Get session from context (NEVER from parameters!)
    from chuk_mcp_runtime.session.native_session_management import require_session

    require_session()  # Validate session exists

    store = await get_artifact_store()

    try:
        move_meta = {
            "moved_via": "mcp",
            "move_time": datetime.now().isoformat(),
            **(meta or {}),
        }

        await store.move_file(artifact_id, new_filename=new_filename, new_meta=move_meta)

        return f"File moved successfully: {artifact_id} -> {new_filename}"

    except Exception as e:
        raise ValueError(f"Failed to move file: {str(e)}")


@mcp_tool(name="get_file_metadata", description="Get file metadata")
async def get_file_metadata(artifact_id: str) -> Dict[str, Any]:
    """
    Get detailed metadata for a file in the current session.

    Args:
        artifact_id: Unique identifier of the file

    Returns:
        Dictionary containing file metadata (size, type, creation date, etc.)
    """
    _check_tool_enabled("get_file_metadata")

    # Get session from context (NEVER from parameters!)
    from chuk_mcp_runtime.session.native_session_management import require_session

    require_session()  # Validate session exists

    store = await get_artifact_store()

    try:
        # Returns pydantic ArtifactMetadata model
        metadata: ArtifactMetadata = await store.metadata(artifact_id)
        # Serialize pydantic model to dict for JSON response
        return metadata.model_dump()

    except ArtifactNotFoundError:
        raise ValueError(f"File not found: {artifact_id}")
    except Exception as e:
        raise ValueError(f"Failed to get metadata: {str(e)}")


@mcp_tool(name="get_presigned_url", description="Generate presigned URLs")
async def get_presigned_url(artifact_id: str, expires_in: str = "medium") -> str:
    """
    Get a presigned URL for downloading a file in the current session.

    Args:
        artifact_id: Unique identifier of the file
        expires_in: URL expiration time - 'short', 'medium', or 'long' (default: medium)

    Returns:
        Presigned URL for downloading the file
    """
    _check_tool_enabled("get_presigned_url")

    # Get session from context (NEVER from parameters!)
    from chuk_mcp_runtime.session.native_session_management import require_session

    require_session()  # Validate session exists

    store = await get_artifact_store()

    try:
        if expires_in == "short":
            url = await store.presign_short(artifact_id)
        elif expires_in == "long":
            url = await store.presign_long(artifact_id)
        else:  # medium (default)
            url = await store.presign_medium(artifact_id)

        return url

    except ArtifactNotFoundError:
        raise ValueError(f"File not found: {artifact_id}")
    except Exception as e:
        raise ValueError(f"Failed to generate presigned URL: {str(e)}")


@mcp_tool(name="get_storage_stats", description="Get storage statistics")
async def get_storage_stats() -> Dict[str, Any]:
    """
    Get statistics about the artifact store for current session/user.

    Returns:
        Dictionary with storage statistics including file count and total bytes
    """
    _check_tool_enabled("get_storage_stats")

    # Get session and user from context (NEVER from parameters!)
    from chuk_mcp_runtime.session.native_session_management import (
        get_session_or_none,
        get_user_or_none,
    )

    session_id = get_session_or_none()
    user_id = get_user_or_none()

    store = await get_artifact_store()

    try:
        stats = await store.get_stats()

        # Add session stats if available
        if session_id:
            session_files: List[ArtifactMetadata] = await store.list_by_session(session_id)
            stats["session_id"] = session_id
            stats["session_file_count"] = len(session_files)
            stats["session_total_bytes"] = sum(f.bytes for f in session_files)

        # Add user stats if available
        if user_id:
            try:
                user_files = await store.search(user_id=user_id, scope="user")
                stats["user_id"] = user_id
                stats["user_file_count"] = len(user_files)
                # user_files may be dicts or pydantic models depending on provider
                stats["user_total_bytes"] = sum(
                    f.bytes if hasattr(f, "bytes") else f.get("bytes", 0) for f in user_files
                )
            except Exception:
                # search may not be available on all providers
                pass

        return stats

    except Exception as e:
        raise ValueError(f"Failed to get storage stats: {str(e)}")


# ============================================================================
# Explicit Session-Scoped Tools (v0.8)
# ============================================================================


@mcp_tool(name="write_session_file", description="Write file to session storage (ephemeral)")
async def write_session_file(
    content: str,
    filename: str,
    mime: str = "text/plain",
    summary: str = "Session file",
    ttl: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Write file to session storage (ephemeral, expires with session)."""
    return await write_file(content, filename, mime, summary, scope="session", ttl=ttl, meta=meta)


@mcp_tool(name="upload_session_file", description="Upload file to session storage (ephemeral)")
async def upload_session_file(
    content: str,
    filename: str,
    mime: str = "application/octet-stream",
    summary: str = "Session upload",
    ttl: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Upload file to session storage (ephemeral, expires with session)."""
    return await upload_file(content, filename, mime, summary, scope="session", ttl=ttl, meta=meta)


# ============================================================================
# Explicit User-Scoped Tools (v0.8)
# ============================================================================


@mcp_tool(name="write_user_file", description="Write file to user storage (persistent)")
async def write_user_file(
    content: str,
    filename: str,
    mime: str = "text/plain",
    summary: str = "User file",
    ttl: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Write file to user's persistent storage (survives sessions)."""
    return await write_file(content, filename, mime, summary, scope="user", ttl=ttl, meta=meta)


@mcp_tool(name="upload_user_file", description="Upload file to user storage (persistent)")
async def upload_user_file(
    content: str,
    filename: str,
    mime: str = "application/octet-stream",
    summary: str = "User upload",
    ttl: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Upload file to user's persistent storage (survives sessions)."""
    return await upload_file(content, filename, mime, summary, scope="user", ttl=ttl, meta=meta)


@mcp_tool(name="list_user_files", description="List user's persistent files")
async def list_user_files(
    mime_prefix: Optional[str] = None,
    meta_filter: Optional[Dict[str, Any]] = None,
    include_metadata: bool = False,
) -> List[Dict[str, Any]]:
    """
    List files in user's persistent storage.

    Args:
        mime_prefix: Filter by MIME type prefix (e.g., 'image/', 'application/pdf')
        meta_filter: Filter by metadata key-value pairs
        include_metadata: Whether to include full metadata for each file

    Returns:
        List of user's files
    """
    _check_tool_enabled("list_user_files")

    # User REQUIRED
    from chuk_mcp_runtime.session.native_session_management import require_user

    user_id = require_user()

    store = await get_artifact_store()

    try:
        # Search user's files - returns List[ArtifactMetadata] or dicts depending on provider
        files = await store.search(
            user_id=user_id, scope="user", mime_prefix=mime_prefix, meta_filter=meta_filter
        )

        if include_metadata:
            # Serialize pydantic models to dicts if needed
            return [f.model_dump() if hasattr(f, "model_dump") else f for f in files]
        else:
            # Return simplified view - handle both pydantic models and dicts
            return [
                {
                    "artifact_id": f.artifact_id
                    if hasattr(f, "artifact_id")
                    else f.get("artifact_id"),
                    "filename": (f.filename if hasattr(f, "filename") else f.get("filename"))
                    or "unknown",
                    "mime": f.mime if hasattr(f, "mime") else f.get("mime", "unknown"),
                    "bytes": f.bytes if hasattr(f, "bytes") else f.get("bytes", 0),
                    "summary": f.summary if hasattr(f, "summary") else f.get("summary", ""),
                    "scope": "user",
                    "created": f.stored_at if hasattr(f, "stored_at") else f.get("stored_at", ""),
                }
                for f in files
            ]

    except Exception as e:
        raise ValueError(f"Failed to list user files: {str(e)}")


# ============================================================================
# Registration and Utility Functions
# ============================================================================

# Map of tool name to function
TOOL_FUNCTIONS = {
    # General tools with scope parameter (backward compatible)
    "upload_file": upload_file,
    "write_file": write_file,
    "read_file": read_file,
    "delete_file": delete_file,
    "list_directory": list_directory,
    "copy_file": copy_file,
    "move_file": move_file,
    "get_file_metadata": get_file_metadata,
    "get_presigned_url": get_presigned_url,
    "get_storage_stats": get_storage_stats,
    # Explicit session-scoped tools (v0.8)
    "write_session_file": write_session_file,
    "upload_session_file": upload_session_file,
    "list_session_files": list_session_files,
    # Explicit user-scoped tools (v0.8)
    "write_user_file": write_user_file,
    "upload_user_file": upload_user_file,
    "list_user_files": list_user_files,
}

# ============================================================================
# Registration function for artifact-management helpers
# ============================================================================


async def register_artifacts_tools(config: Dict[str, Any] | None = None) -> bool:
    """Register artifact helpers according to *config*."""
    art_cfg = (config or {}).get("artifacts", {})
    if not art_cfg.get("enabled", False):
        for t in TOOL_FUNCTIONS:
            TOOLS_REGISTRY.pop(t, None)
        logger.debug("Artifacts disabled - use 'artifacts.enabled: true' in config to enable")
        return False

    enabled_helpers = {n for n, tc in art_cfg.get("tools", {}).items() if tc.get("enabled", False)}
    if not enabled_helpers:
        for t in TOOL_FUNCTIONS:
            TOOLS_REGISTRY.pop(t, None)
        logger.debug(
            "All artifact tools disabled individually - use 'artifacts.tools.<tool_name>.enabled: true' to enable specific tools"
        )
        return False

    # 1) make sure store is OK
    await get_artifact_store()  # raises if mis-configured

    # 2) prune everything that might still be there
    for t in TOOL_FUNCTIONS:
        TOOLS_REGISTRY.pop(t, None)

    # ---- KEEP _enabled_tools IN-SYNC ---------------------------------
    _enabled_tools.clear()
    _enabled_tools.update(enabled_helpers)
    # ------------------------------------------------------------------

    # 3) register the wanted helpers
    registered = 0
    for name in enabled_helpers:
        tool_fn = TOOL_FUNCTIONS.get(name)
        if tool_fn is None:
            logger.error("Artifact tool %s not found in TOOL_FUNCTIONS", name)
            continue

        try:
            TOOLS_REGISTRY[name] = tool_fn
            registered += 1
            logger.debug("Registered artifact tool: %s", name)
        except Exception as e:
            logger.error("Failed to register artifact tool %s: %s", name, e)

    if registered > 0:
        logger.debug(
            "Registered %d artifact tool(s): %s",
            registered,
            ", ".join(sorted(enabled_helpers)),
        )
    else:
        logger.warning("No artifact tools were successfully registered")

    return bool(registered)


def get_artifacts_tools_info() -> Dict[str, Any]:
    """Get information about available and configured artifact tools."""
    all_tools = list(DEFAULT_TOOL_CONFIG["tools"].keys())

    return {
        "available": True,
        "configured": bool(_artifacts_config),
        "enabled_globally": _artifacts_config.get("enabled", False) if _artifacts_config else False,
        "enabled_tools": list(_enabled_tools),
        "disabled_tools": [t for t in all_tools if t not in _enabled_tools],
        "total_tools": len(all_tools),
        "enabled_count": len(_enabled_tools),
        "config": _artifacts_config,
        "default_state": "disabled",
        "enable_instructions": {
            "global": "Set 'artifacts.enabled: true' in configuration",
            "individual": "Set 'artifacts.tools.<tool_name>.enabled: true' for each desired tool",
        },
    }


def get_enabled_tools() -> List[str]:
    """Get list of currently enabled tools."""
    return list(_enabled_tools)


# Tool list for external reference (all possible tools)
ALL_ARTIFACT_TOOLS = list(DEFAULT_TOOL_CONFIG["tools"].keys())


def require_user() -> str:
    """Get user from context or raise (helper for user-scoped operations)."""
    from chuk_mcp_runtime.session.native_session_management import get_user_or_none

    user_id = get_user_or_none()
    if not user_id:
        raise ValueError("User context required - must be authenticated")
    return user_id


# Dynamic tool list based on configuration
def get_artifact_tools() -> List[str]:
    """Get currently enabled artifact tools."""
    return get_enabled_tools()


# Legacy property-style access (keeping for compatibility)
def ARTIFACT_TOOLS() -> List[str]:
    """Get currently enabled artifact tools."""
    return get_enabled_tools()


# Add the required CHUK_ARTIFACTS_AVAILABLE flag for compatibility
CHUK_ARTIFACTS_AVAILABLE = True
