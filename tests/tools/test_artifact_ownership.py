# tests/tools/test_artifact_ownership.py
"""
Tests for per-user / per-session access control on artifact tools.

Verifies that copy_file, move_file, get_file_metadata, and get_presigned_url
(the four tools that previously lacked ownership checks) all enforce the same
ownership model that read_file and delete_file already did:

  - user scope  → caller's user_id must match metadata.owner_id
  - session scope → caller's session_id must match metadata.session_id
  - sandbox scope → always readable (admin-write only)

Also includes regression tests for read_file / delete_file to confirm their
existing checks still pass.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import ArtifactMetadata, ArtifactNotFoundError, mock_session_ctx, mock_user_ctx

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(metadata: ArtifactMetadata, *, raise_not_found: bool = False) -> MagicMock:
    """Return a mock ArtifactStore whose metadata() returns *metadata*."""
    store = MagicMock()
    if raise_not_found:
        store.metadata = AsyncMock(side_effect=ArtifactNotFoundError("not found"))
    else:
        store.metadata = AsyncMock(return_value=metadata)
    store.copy_file = AsyncMock(return_value="new-artifact-id")
    store.move_file = AsyncMock(return_value=None)
    store.delete = AsyncMock(return_value=True)
    store.retrieve = AsyncMock(return_value=b"file content")
    store.presign_short = AsyncMock(return_value="https://s3.example.com/short")
    store.presign_medium = AsyncMock(return_value="https://s3.example.com/medium")
    store.presign_long = AsyncMock(return_value="https://s3.example.com/long")
    return store


def _patches(store):
    """Patch get_artifact_store and disable the tool-enabled guard."""
    return [
        patch(
            "chuk_mcp_runtime.tools.artifacts_tools.get_artifact_store",
            AsyncMock(return_value=store),
        ),
        patch("chuk_mcp_runtime.tools.artifacts_tools._check_tool_enabled", return_value=None),
    ]


# Pytest fixtures for common scenarios
@pytest.fixture(autouse=True)
def clear_context():
    """Reset session/user context before and after every test."""
    mock_session_ctx.set(None)
    mock_user_ctx.set(None)
    yield
    mock_session_ctx.set(None)
    mock_user_ctx.set(None)


# ---------------------------------------------------------------------------
# copy_file
# ---------------------------------------------------------------------------


class TestCopyFileOwnership:
    @pytest.mark.asyncio
    async def test_user_scope_allowed_for_owner(self):
        meta = ArtifactMetadata(artifact_id="a1", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("alice")
        mock_session_ctx.set("session-alice")

        from chuk_mcp_runtime.tools.artifacts_tools import copy_file

        with _patches(store)[0], _patches(store)[1]:
            result = await copy_file("a1", new_filename="copy.txt")
        assert "new-artifact-id" in result

    @pytest.mark.asyncio
    async def test_user_scope_denied_for_wrong_user(self):
        meta = ArtifactMetadata(artifact_id="a1", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("bob")  # wrong user
        mock_session_ctx.set("session-bob")

        from chuk_mcp_runtime.tools.artifacts_tools import copy_file

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await copy_file("a1", new_filename="copy.txt")

    @pytest.mark.asyncio
    async def test_user_scope_denied_when_no_user_context(self):
        meta = ArtifactMetadata(artifact_id="a1", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_session_ctx.set("session-x")
        # mock_user_ctx remains None

        from chuk_mcp_runtime.tools.artifacts_tools import copy_file

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await copy_file("a1", new_filename="copy.txt")

    @pytest.mark.asyncio
    async def test_session_scope_allowed_for_same_session(self):
        meta = ArtifactMetadata(artifact_id="a2", scope="session", session_id="sess-1")
        store = _make_store(meta)
        mock_session_ctx.set("sess-1")

        from chuk_mcp_runtime.tools.artifacts_tools import copy_file

        with _patches(store)[0], _patches(store)[1]:
            result = await copy_file("a2", new_filename="copy.txt")
        assert "new-artifact-id" in result

    @pytest.mark.asyncio
    async def test_session_scope_denied_for_different_session(self):
        meta = ArtifactMetadata(artifact_id="a2", scope="session", session_id="sess-1")
        store = _make_store(meta)
        mock_session_ctx.set("sess-2")  # different session

        from chuk_mcp_runtime.tools.artifacts_tools import copy_file

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await copy_file("a2", new_filename="copy.txt")


# ---------------------------------------------------------------------------
# move_file
# ---------------------------------------------------------------------------


class TestMoveFileOwnership:
    @pytest.mark.asyncio
    async def test_user_scope_allowed_for_owner(self):
        meta = ArtifactMetadata(artifact_id="a3", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("alice")
        mock_session_ctx.set("session-alice")

        from chuk_mcp_runtime.tools.artifacts_tools import move_file

        with _patches(store)[0], _patches(store)[1]:
            result = await move_file("a3", new_filename="moved.txt")
        assert "moved successfully" in result

    @pytest.mark.asyncio
    async def test_user_scope_denied_for_wrong_user(self):
        meta = ArtifactMetadata(artifact_id="a3", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("charlie")
        mock_session_ctx.set("session-charlie")

        from chuk_mcp_runtime.tools.artifacts_tools import move_file

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await move_file("a3", new_filename="moved.txt")

    @pytest.mark.asyncio
    async def test_session_scope_allowed_for_same_session(self):
        meta = ArtifactMetadata(artifact_id="a4", scope="session", session_id="sess-A")
        store = _make_store(meta)
        mock_session_ctx.set("sess-A")

        from chuk_mcp_runtime.tools.artifacts_tools import move_file

        with _patches(store)[0], _patches(store)[1]:
            result = await move_file("a4", new_filename="moved.txt")
        assert "moved successfully" in result

    @pytest.mark.asyncio
    async def test_session_scope_denied_for_different_session(self):
        meta = ArtifactMetadata(artifact_id="a4", scope="session", session_id="sess-A")
        store = _make_store(meta)
        mock_session_ctx.set("sess-B")

        from chuk_mcp_runtime.tools.artifacts_tools import move_file

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await move_file("a4", new_filename="moved.txt")


# ---------------------------------------------------------------------------
# get_file_metadata
# ---------------------------------------------------------------------------


class TestGetFileMetadataOwnership:
    @pytest.mark.asyncio
    async def test_user_scope_allowed_for_owner(self):
        meta = ArtifactMetadata(artifact_id="a5", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("alice")
        mock_session_ctx.set("s1")

        from chuk_mcp_runtime.tools.artifacts_tools import get_file_metadata

        with _patches(store)[0], _patches(store)[1]:
            result = await get_file_metadata("a5")
        assert result["artifact_id"] == "a5"

    @pytest.mark.asyncio
    async def test_user_scope_denied_for_wrong_user(self):
        meta = ArtifactMetadata(artifact_id="a5", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("dave")
        mock_session_ctx.set("s1")

        from chuk_mcp_runtime.tools.artifacts_tools import get_file_metadata

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await get_file_metadata("a5")

    @pytest.mark.asyncio
    async def test_session_scope_allowed_for_same_session(self):
        meta = ArtifactMetadata(artifact_id="a6", scope="session", session_id="sess-Q")
        store = _make_store(meta)
        mock_session_ctx.set("sess-Q")

        from chuk_mcp_runtime.tools.artifacts_tools import get_file_metadata

        with _patches(store)[0], _patches(store)[1]:
            result = await get_file_metadata("a6")
        assert result["artifact_id"] == "a6"

    @pytest.mark.asyncio
    async def test_session_scope_denied_for_different_session(self):
        meta = ArtifactMetadata(artifact_id="a6", scope="session", session_id="sess-Q")
        store = _make_store(meta)
        mock_session_ctx.set("sess-R")

        from chuk_mcp_runtime.tools.artifacts_tools import get_file_metadata

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await get_file_metadata("a6")


# ---------------------------------------------------------------------------
# get_presigned_url
# ---------------------------------------------------------------------------


class TestGetPresignedUrlOwnership:
    @pytest.mark.asyncio
    async def test_user_scope_allowed_for_owner(self):
        meta = ArtifactMetadata(artifact_id="a7", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("alice")
        mock_session_ctx.set("s1")

        from chuk_mcp_runtime.tools.artifacts_tools import get_presigned_url

        with _patches(store)[0], _patches(store)[1]:
            url = await get_presigned_url("a7", expires_in="medium")
        assert url.startswith("https://")

    @pytest.mark.asyncio
    async def test_user_scope_denied_for_wrong_user(self):
        meta = ArtifactMetadata(artifact_id="a7", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("eve")
        mock_session_ctx.set("s1")

        from chuk_mcp_runtime.tools.artifacts_tools import get_presigned_url

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await get_presigned_url("a7")

    @pytest.mark.asyncio
    async def test_session_scope_allowed_for_same_session(self):
        meta = ArtifactMetadata(artifact_id="a8", scope="session", session_id="sess-P")
        store = _make_store(meta)
        mock_session_ctx.set("sess-P")

        from chuk_mcp_runtime.tools.artifacts_tools import get_presigned_url

        with _patches(store)[0], _patches(store)[1]:
            url = await get_presigned_url("a8", expires_in="short")
        assert url.startswith("https://")

    @pytest.mark.asyncio
    async def test_session_scope_denied_for_different_session(self):
        meta = ArtifactMetadata(artifact_id="a8", scope="session", session_id="sess-P")
        store = _make_store(meta)
        mock_session_ctx.set("sess-Z")

        from chuk_mcp_runtime.tools.artifacts_tools import get_presigned_url

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await get_presigned_url("a8")


# ---------------------------------------------------------------------------
# Regression: read_file (pre-existing checks still pass)
# ---------------------------------------------------------------------------


class TestReadFileOwnershipRegression:
    @pytest.mark.asyncio
    async def test_user_scope_allowed(self):
        meta = ArtifactMetadata(artifact_id="r1", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("alice")
        mock_session_ctx.set("s1")

        from chuk_mcp_runtime.tools.artifacts_tools import read_file

        with _patches(store)[0], _patches(store)[1]:
            result = await read_file("r1", as_text=True)
        assert result == "file content"

    @pytest.mark.asyncio
    async def test_user_scope_denied_for_wrong_user(self):
        meta = ArtifactMetadata(artifact_id="r1", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("mallory")
        mock_session_ctx.set("s1")

        from chuk_mcp_runtime.tools.artifacts_tools import read_file

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await read_file("r1")

    @pytest.mark.asyncio
    async def test_session_scope_denied_for_different_session(self):
        meta = ArtifactMetadata(artifact_id="r2", scope="session", session_id="sess-1")
        store = _make_store(meta)
        mock_session_ctx.set("sess-9")

        from chuk_mcp_runtime.tools.artifacts_tools import read_file

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await read_file("r2")


# ---------------------------------------------------------------------------
# Regression: delete_file (pre-existing checks still pass)
# ---------------------------------------------------------------------------


class TestDeleteFileOwnershipRegression:
    @pytest.mark.asyncio
    async def test_user_scope_allowed(self):
        meta = ArtifactMetadata(artifact_id="d1", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("alice")
        mock_session_ctx.set("s1")

        from chuk_mcp_runtime.tools.artifacts_tools import delete_file

        with _patches(store)[0], _patches(store)[1]:
            result = await delete_file("d1")
        assert "deleted" in result.lower()

    @pytest.mark.asyncio
    async def test_user_scope_denied_for_wrong_user(self):
        meta = ArtifactMetadata(artifact_id="d1", scope="user", owner_id="alice")
        store = _make_store(meta)
        mock_user_ctx.set("mallory")
        mock_session_ctx.set("s1")

        from chuk_mcp_runtime.tools.artifacts_tools import delete_file

        with _patches(store)[0], _patches(store)[1]:
            with pytest.raises(ValueError, match="Access denied"):
                await delete_file("d1")


# ---------------------------------------------------------------------------
# Sandbox scope is always readable
# ---------------------------------------------------------------------------


class TestSandboxScope:
    @pytest.mark.asyncio
    async def test_sandbox_scope_readable_without_user(self):
        meta = ArtifactMetadata(artifact_id="sb1", scope="sandbox")
        store = _make_store(meta)
        # No user or session context set

        from chuk_mcp_runtime.tools.artifacts_tools import read_file

        with _patches(store)[0], _patches(store)[1]:
            result = await read_file("sb1", as_text=True)
        assert result == "file content"
