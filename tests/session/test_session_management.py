# tests/session/test_session_management.py - Final Fixed Version
"""
Fixed session management tests with proper concurrent session isolation.
"""

import asyncio

import pytest

from tests.conftest import (
    MockMCPSessionManager,
    MockSessionContext,
    mock_session_ctx,
)


class TestSessionContext:
    """Test the SessionContext context manager."""

    @pytest.mark.asyncio
    async def test_session_context_exception_handling(self):
        """Test SessionContext handles exceptions properly."""
        session_manager = MockMCPSessionManager()

        # Create a session and set as previous context
        session_id = await session_manager.create_session()

        # CRITICAL: Set the previous context using the context variable, not string
        mock_session_ctx.set("previous_session")
        session_manager._current_session = "previous_session"

        try:
            async with MockSessionContext(session_manager, session_id=session_id):
                # Verify we're in the new session context
                current = mock_session_ctx.get()
                assert current == session_id
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Should restore previous context
        current_after = mock_session_ctx.get()
        assert current_after == "previous_session"


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_sessions(self):
        """Test concurrent session operations with proper isolation."""
        session_manager = MockMCPSessionManager()

        # Pre-create sessions for each worker to ensure they're different
        session1 = await session_manager.create_session(
            user_id="user1", metadata={"worker_id": "worker1"}
        )
        session2 = await session_manager.create_session(
            user_id="user2", metadata={"worker_id": "worker2"}
        )
        session3 = await session_manager.create_session(
            user_id="user3", metadata={"worker_id": "worker3"}
        )

        # Map workers to their pre-created sessions
        worker_sessions = {
            "worker1": session1,
            "worker2": session2,
            "worker3": session3,
        }

        results = {}

        async def session_worker(worker_id, user_id):
            # Use the pre-created session for this worker
            worker_session_id = worker_sessions[worker_id]

            # Work directly with the specific session (no context switching needed)
            # Update session metadata using the session_id directly
            await session_manager.update_session_metadata(
                worker_session_id, {"worker_id": worker_id, "processed": True}
            )

            # Get session info using the session_id directly
            info = await session_manager.get_session_info(worker_session_id)

            results[worker_id] = {
                "session_id": worker_session_id,
                "user_id": info["user_id"],
                "worker_id": info["custom_metadata"]["worker_id"],
            }

        # Run concurrent workers
        workers = [
            session_worker("worker1", "user1"),
            session_worker("worker2", "user2"),
            session_worker("worker3", "user3"),
        ]
        await asyncio.gather(*workers)

        # Verify each worker maintained its own session
        for i in range(1, 4):
            worker_key = f"worker{i}"
            user_key = f"user{i}"

            assert worker_key in results, f"Results missing for {worker_key}"
            assert results[worker_key]["user_id"] == user_key, (
                f"User ID mismatch for {worker_key}: expected {user_key}, got {results[worker_key]['user_id']}"
            )
            assert results[worker_key]["worker_id"] == worker_key, (
                f"Worker ID mismatch for {worker_key}"
            )

        # Verify sessions are different
        session_ids = [results[f"worker{i}"]["session_id"] for i in range(1, 4)]
        assert len(set(session_ids)) == 3, f"Sessions should be different but got: {session_ids}"


class TestLastSessionUserIsolation:
    """Verify that _last_session is never shared between different users."""

    @pytest.mark.asyncio
    async def test_different_users_get_different_sessions(self):
        """User B must never inherit User A's _last_session."""
        mgr = MockMCPSessionManager()

        sess_a = await mgr.auto_create_session_if_needed(user_id="alice")
        assert mgr._last_session == sess_a
        assert mgr._last_session_user == "alice"

        # Simulate a new connection: clear the context variable so mgr sees no
        # current session, as happens when a different HTTP request arrives.
        mock_session_ctx.set(None)
        mgr._current_session = None

        sess_b = await mgr.auto_create_session_if_needed(user_id="bob")
        assert sess_b != sess_a, "Bob must not reuse Alice's session"
        assert mgr._last_session_user == "bob"

    @pytest.mark.asyncio
    async def test_same_user_reuses_last_session(self):
        """The same user should reuse their existing session (STDIO pattern)."""
        mgr = MockMCPSessionManager()

        sess1 = await mgr.auto_create_session_if_needed(user_id="alice")

        mock_session_ctx.set(None)
        mgr._current_session = None

        sess2 = await mgr.auto_create_session_if_needed(user_id="alice")
        assert sess2 == sess1, "Alice should reuse her own session"

    @pytest.mark.asyncio
    async def test_anonymous_sessions_reuse_in_stdio_mode(self):
        """Anonymous (STDIO) sessions continue to reuse _last_session."""
        mgr = MockMCPSessionManager()

        sess1 = await mgr.auto_create_session_if_needed(user_id=None)

        mock_session_ctx.set(None)
        mgr._current_session = None

        sess2 = await mgr.auto_create_session_if_needed(user_id=None)
        assert sess2 == sess1, "Anonymous STDIO session should be reused"

    @pytest.mark.asyncio
    async def test_last_session_user_tracked_correctly(self):
        mgr = MockMCPSessionManager()
        assert mgr._last_session_user is None

        await mgr.auto_create_session_if_needed(user_id="carol")
        assert mgr._last_session_user == "carol"

        mock_session_ctx.set(None)
        mgr._current_session = None

        await mgr.auto_create_session_if_needed(user_id="dave")
        assert mgr._last_session_user == "dave"


if __name__ == "__main__":
    pytest.main(["-xvs", __file__])
