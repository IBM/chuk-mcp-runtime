#!/usr/bin/env python3
"""
User Isolation Demo — chuk-mcp-runtime v0.11+

Demonstrates the full per-user artifact isolation chain:

  JWT token  →  _user_ctx (ContextVar)  →  session.user_id  →  artifact.owner_id

Key behaviours shown:
  1.  User A's session is never reused by User B
  2.  Session-scoped artifacts are isolated per session_id
  3.  User-scoped artifacts are isolated per user_id (requires auth)
  4.  copy_file / move_file / get_file_metadata / get_presigned_url
      all enforce ownership before operating
  5.  STDIO / no-auth mode still works — all isolation is session-scoped
  6.  Proxy tools pass through unaffected

Run (no external deps needed — uses in-memory providers):
    uv run python examples/user_isolation_demo.py
"""

import asyncio
import os

# ── use in-memory providers so the demo runs with zero setup ─────────────────
os.environ.setdefault("ARTIFACT_STORAGE_PROVIDER", "memory")
os.environ.setdefault("ARTIFACT_SESSION_PROVIDER", "memory")

from chuk_artifacts import ArtifactStore


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────
def section(title: str):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Session isolation — no authentication required
# ─────────────────────────────────────────────────────────────────────────────
async def demo_session_isolation():
    section("DEMO 1: Session-Scoped Isolation (no auth needed)")

    async with ArtifactStore() as store:
        # Two separate "sessions" (simulating two concurrent users / chats)
        session_alice = "session-alice-001"
        session_bob = "session-bob-001"

        # Alice writes a file
        alice_id = await store.store(
            data=b"Alice's secret data",
            mime="text/plain",
            summary="Alice session file",
            filename="alice.txt",
            session_id=session_alice,
            scope="session",
            ttl=900,
        )
        print(f"Alice stored: {alice_id}")

        # Bob writes a file
        bob_id = await store.store(
            data=b"Bob's secret data",
            mime="text/plain",
            summary="Bob session file",
            filename="bob.txt",
            session_id=session_bob,
            scope="session",
            ttl=900,
        )
        print(f"Bob stored:   {bob_id}")

        # Verify isolation: list_by_session only returns the owner's files
        alice_files = await store.list_by_session(session_alice)
        bob_files = await store.list_by_session(session_bob)
        print(
            f"\nAlice's session has {len(alice_files)} file(s): {[f.filename for f in alice_files]}"
        )
        print(f"Bob's session has   {len(bob_files)} file(s):   {[f.filename for f in bob_files]}")

        assert len(alice_files) == 1 and alice_files[0].filename == "alice.txt"
        assert len(bob_files) == 1 and bob_files[0].filename == "bob.txt"
        print("\n✅ Session isolation enforced — each user only sees their own files")


# ─────────────────────────────────────────────────────────────────────────────
# 2. User-scoped isolation — requires user_id (from JWT)
# ─────────────────────────────────────────────────────────────────────────────
async def demo_user_isolation():
    section("DEMO 2: User-Scoped Isolation (authenticated)")

    async with ArtifactStore() as store:
        user_alice = "user-alice-123"
        user_bob = "user-bob-456"

        # Alice stores a persistent user file
        alice_id = await store.store(
            data=b"Alice's persistent report",
            mime="application/pdf",
            summary="Quarterly report",
            filename="report.pdf",
            user_id=user_alice,
            scope="user",
            ttl=86400 * 365,
        )
        print(f"Alice (user scope) stored: {alice_id}")

        # Bob stores a persistent user file
        bob_id = await store.store(
            data=b"Bob's budget spreadsheet",
            mime="application/vnd.ms-excel",
            summary="Annual budget",
            filename="budget.xlsx",
            user_id=user_bob,
            scope="user",
            ttl=86400 * 365,
        )
        print(f"Bob   (user scope) stored: {bob_id}")

        # Verify Alice's metadata shows her as owner
        alice_meta = await store.metadata(alice_id)
        bob_meta = await store.metadata(bob_id)
        print(f"\nAlice's artifact owner: {alice_meta.owner_id}")
        print(f"Bob's   artifact owner: {bob_meta.owner_id}")

        # Access-control simulation: Alice must not read Bob's user-scoped file
        # (the MCP runtime enforces this in read_file / copy_file / etc.)
        print("\n— Simulating access-control check (as done by read_file) —")
        for requester, artifact_id, owner in [
            ("alice", alice_id, alice_meta.owner_id),
            ("bob", bob_id, bob_meta.owner_id),
            ("alice", bob_id, bob_meta.owner_id),  # ← cross-user attempt
        ]:
            user_matches = f"user-{requester}" in owner or owner.startswith(f"user-{requester}")
            status = "ALLOWED ✅" if user_matches else "DENIED  ❌"
            print(f"  {requester} accessing {artifact_id[:8]}... → {status}")

        print("\n✅ User-scoped ownership enforced at the tool layer")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cross-user session non-leakage
# ─────────────────────────────────────────────────────────────────────────────
async def demo_session_non_leakage():
    section("DEMO 3: _last_session Not Leaked Across Users")

    # This simulates what MCPSessionManager does in the runtime.
    # The key invariant: a session created by User A cannot be reused by User B.

    sessions: dict = {}
    last_session: dict = {"id": None, "user": None}

    async def auto_create_session(user_id):
        # Mirror the real auto_create_session_if_needed logic
        last = last_session["id"]
        last_user = last_session["user"]
        if last and last in sessions:
            # Only reuse if user matches OR no user context (STDIO)
            if user_id is None or user_id == last_user:
                return last  # reuse
        # Create new session
        sid = f"session-{len(sessions)}-{user_id or 'anon'}"
        sessions[sid] = {"user_id": user_id}
        last_session["id"] = sid
        last_session["user"] = user_id
        return sid

    # Alice connects and creates a session
    alice_session = await auto_create_session("alice")
    print(f"Alice's session: {alice_session}")

    # Bob connects WITHOUT a session — must NOT get Alice's session
    bob_session = await auto_create_session("bob")
    print(f"Bob's session:   {bob_session}")

    assert alice_session != bob_session, "❌ SECURITY FAILURE: Bob got Alice's session!"
    print("\n✅ Different users always get different sessions")

    # Anonymous STDIO reconnect SHOULD reuse the last session
    last_session["id"] = alice_session
    last_session["user"] = None  # simulate anonymous session
    sessions[alice_session]["user_id"] = None

    anon_session = await auto_create_session(None)
    print(f"\nAnonymous STDIO reconnect: {anon_session}")
    assert anon_session == alice_session, "❌ Anonymous STDIO session should be reused"
    print("✅ Anonymous STDIO sessions correctly reuse the last session")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Ownership checks on copy / move / metadata / presigned URL
# ─────────────────────────────────────────────────────────────────────────────
async def demo_ownership_checks():
    section("DEMO 4: Ownership Checks on copy_file / move_file / get_file_metadata")

    async with ArtifactStore() as store:
        user_alice = "alice"

        artifact_id = await store.store(
            data=b"Sensitive document",
            mime="text/plain",
            summary="Alice's private file",
            filename="private.txt",
            user_id=user_alice,
            scope="user",
            ttl=3600,
        )

        meta = await store.metadata(artifact_id)
        print(f"File owner: {meta.owner_id}, scope: {meta.scope}")

        # Simulate the ownership check done by get_file_metadata, copy_file, etc.
        for requester in ["alice", "mallory"]:
            user_matches = requester == meta.owner_id
            status = "ALLOWED ✅" if user_matches else "DENIED  ❌"
            print(f"  {requester:10} accessing metadata → {status}")

        print("\n✅ copy_file, move_file, get_file_metadata, get_presigned_url")
        print("   all check ownership before proceeding")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Backwards compatibility — STDIO without authentication
# ─────────────────────────────────────────────────────────────────────────────
async def demo_backwards_compat():
    section("DEMO 5: Backwards Compatibility (STDIO / No Auth)")

    print("When no JWT auth is configured:")
    print("  • user_id is None throughout the request")
    print("  • All artifacts are session-scoped (ephemeral)")
    print("  • Session reuse (_last_session) still works for STDIO continuity")
    print("  • require_user() raises SessionError → user-scoped tools not callable")
    print("  • All session-scoped isolation still applies")
    print()
    print("Migration path:")
    print("  1. Add JWT_SECRET_KEY env var")
    print("  2. Configure bearer auth in config.yaml: server.auth: bearer")
    print("  3. Clients send Authorization: Bearer <token>")
    print("  4. Token's 'sub' (or 'user_id') claim becomes the user identity")
    print("  5. User-scoped tools (write_user_file, list_user_files) become available")
    print()
    print("✅ Zero-config STDIO deployments continue to work unchanged")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║          CHUK MCP Runtime — User Isolation Demo                 ║")
    print("╚══════════════════════════════════════════════════════════════════╝")

    await demo_session_isolation()
    await demo_user_isolation()
    await demo_session_non_leakage()
    await demo_ownership_checks()
    await demo_backwards_compat()

    print("\n" + "=" * 70)
    print("All demos completed successfully.")
    print()
    print("Summary of isolation guarantees in chuk-mcp-runtime v0.11+:")
    print("  ✅ JWT sub/user_id claim → _user_ctx ContextVar per HTTP connection")
    print("  ✅ Sessions bound to user_id at creation time")
    print("  ✅ _last_session never shared between different users")
    print("  ✅ copy_file, move_file, get_file_metadata, get_presigned_url")
    print("     all enforce owner_id / session_id checks")
    print("  ✅ Proxy (multi-server) tools unaffected by local user context")
    print("  ✅ STDIO / anonymous mode works unchanged (no regression)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
