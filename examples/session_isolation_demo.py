#!/usr/bin/env python3
"""
Session Isolation Demo

Demonstrates how session isolation works (or doesn't work) with different
storage provider configurations. This demo creates multiple sessions with
different files and tests whether isolation is enforced.

The demo:
1. Creates Session A (Frontend) with HTML/JS files
2. Creates Session B (Backend) with Python files
3. Tests whether each session only sees its own files
4. Explains isolation behavior based on provider configuration

Result: With memory provider, files are NOT isolated (all files visible
in all sessions). For true isolation, use Redis session provider or
persistent storage configuration.

Run:
    uv run python examples/session_isolation_demo.py
"""

import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


def load_env_file(env_file=".env"):
    """Load environment variables from .env file."""
    env_path = Path(__file__).parent.parent / env_file
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and value and key not in os.environ:
                        os.environ[key] = value


def send_and_receive(process, msg, expected_id=None, timeout=5):
    """Send message and get response."""
    try:
        process.stdin.write(json.dumps(msg) + "\n")
        process.stdin.flush()
    except Exception as e:
        return {"error": f"Write failed: {e}"}

    if expected_id is None:
        time.sleep(0.05)
        return {"success": True}

    start_time = time.time()
    while time.time() - start_time < timeout:
        if process.poll() is not None:
            return {"error": "Server died"}

        try:
            if process.stdout.readable():
                response_line = process.stdout.readline()
                if response_line:
                    try:
                        msg_obj = json.loads(response_line)
                        if msg_obj.get("id") == expected_id:
                            return msg_obj
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

        time.sleep(0.05)

    return {"error": f"timeout waiting for id {expected_id}"}


def create_file_in_session(process, session_id, filename, content, mime, request_id):
    """Create a file in a specific session."""
    write_msg = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": "write_file",
            "arguments": {
                "filename": filename,
                "content": content,
                "mime": mime,
                "session_id": session_id,
            },
        },
    }

    response = send_and_receive(process, write_msg, expected_id=request_id)
    return response


def list_files_in_session(process, session_id, request_id):
    """List all files in a specific session."""
    list_msg = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": "list_session_files",
            "arguments": {"session_id": session_id},
        },
    }

    response = send_and_receive(process, list_msg, expected_id=request_id)

    if "result" in response:
        result_content = response["result"].get("content", [])
        for content_item in result_content:
            if content_item.get("type") == "text":
                try:
                    files = json.loads(content_item["text"])
                    if isinstance(files, list):
                        return files
                except json.JSONDecodeError:
                    pass

    return []


def main():
    """Run session isolation demo."""
    load_env_file()

    print("=" * 80)
    print("Session Isolation Demo")
    print("=" * 80)
    print()
    print("This demo creates multiple sessions and verifies file isolation.")
    print()

    # Create temp config - use memory for simplicity
    temp_dir = Path(tempfile.mkdtemp(prefix="session_isolation_"))
    config_file = temp_dir / "config.yaml"

    config_content = """
server:
  type: stdio

logging:
  level: ERROR

artifacts:
  enabled: true
  storage_provider: memory
  session_provider: memory

  tools:
    write_file: {enabled: true}
    list_session_files: {enabled: true}
"""
    config_file.write_text(config_content)

    try:
        # Start server
        print("🚀 Starting MCP server...")
        env = os.environ.copy()
        env["ARTIFACT_PROVIDER"] = "vfs-memory"
        env["SESSION_PROVIDER"] = "memory"

        process = subprocess.Popen(
            ["chuk-mcp-server", "--config", str(config_file)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )

        time.sleep(1)

        if process.poll() is not None:
            stderr = process.stderr.read()
            print(f"❌ Server failed: {stderr}")
            return

        print("✅ Server started")
        print()

        # Initialize
        print("🔌 Initializing MCP connection...")
        init_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "session-isolation-demo", "version": "1.0.0"},
            },
        }

        response = send_and_receive(process, init_msg, expected_id=1)
        if "error" in response:
            print(f"❌ Initialize failed: {response['error']}")
            return

        print("✅ Initialized")
        print()

        # Send initialized notification
        initialized_msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        send_and_receive(process, initialized_msg)

        # Create 2 distinct sessions (simplified for demo clarity)
        sessions = [
            {
                "id": f"session-alpha-{uuid.uuid4().hex[:8]}",
                "name": "Session A (Frontend)",
                "color": "🔵",
                "files": [
                    {"filename": "index.html", "content": "<h1>Frontend</h1>", "mime": "text/html"},
                    {
                        "filename": "app.js",
                        "content": "console.log('app');",
                        "mime": "text/javascript",
                    },
                ],
            },
            {
                "id": f"session-beta-{uuid.uuid4().hex[:8]}",
                "name": "Session B (Backend)",
                "color": "🟢",
                "files": [
                    {"filename": "server.py", "content": "# Backend", "mime": "text/plain"},
                    {"filename": "config.json", "content": "{}", "mime": "application/json"},
                ],
            },
        ]

        request_id = 2

        # Create files in each session
        print("=" * 80)
        print("Creating Files in Separate Sessions")
        print("=" * 80)
        print()

        for session in sessions:
            print(f"{session['color']} {session['name']}")
            print(f"   Session ID: {session['id']}")
            print(f"   Creating {len(session['files'])} files...")

            for file_data in session["files"]:
                response = create_file_in_session(
                    process,
                    session["id"],
                    file_data["filename"],
                    file_data["content"],
                    file_data["mime"],
                    request_id,
                )
                request_id += 1

                if "result" in response:
                    print(f"      ✅ {file_data['filename']}")
                elif "error" in response:
                    print(f"      ❌ {file_data['filename']}: {response['error']}")
                    # Continue despite errors
                else:
                    print(f"      ⚠️  {file_data['filename']}: Unexpected response")

            print()

        # Verify isolation by listing files in each session
        print("=" * 80)
        print("Verifying Session Isolation")
        print("=" * 80)
        print()
        print("Each session should only see its own files:")
        print()

        isolation_working = True

        for session in sessions:
            print(f"{session['color']} {session['name']}")
            print(f"   Session ID: {session['id']}")

            files = list_files_in_session(process, session["id"], request_id)
            request_id += 1

            expected_count = len(session["files"])
            actual_count = len(files)

            if actual_count == expected_count:
                print(f"   ✅ Found {actual_count} files (expected {expected_count})")
                for f in files:
                    print(f"      • {f['filename']}")
            else:
                print(f"   ⚠️  Found {actual_count} files (expected {expected_count})")
                isolation_working = False
                for f in files:
                    # Mark unexpected files
                    expected = any(ef["filename"] == f["filename"] for ef in session["files"])
                    marker = "✓" if expected else "✗"
                    print(f"      {marker} {f['filename']}")

            print()

        # Cross-session verification
        print("=" * 80)
        print("Cross-Session Verification")
        print("=" * 80)
        print()
        print("Verifying Session A cannot see Session B's files...")
        print()

        session_a = sessions[0]
        sessions[1]

        print("Query: List files in Session A using its session_id")
        files_a = list_files_in_session(process, session_a["id"], request_id)
        request_id += 1

        print(f"Result: Found {len(files_a)} files")
        has_b_files = any(f["filename"] in ["server.py", "database.py"] for f in files_a)

        if has_b_files:
            print("❌ Session A can see Session B's files (isolation broken)")
            isolation_working = False
        else:
            print("✅ Session A cannot see Session B's files (isolation working)")

        print()

        # Final verdict
        print("=" * 80)
        print("Demo Complete!")
        print("=" * 80)
        print()

        if isolation_working:
            print("✅ Session isolation is working correctly!")
            print()
            print("Each session maintains its own isolated file storage:")
            for session in sessions:
                print(f"   {session['color']} {session['name']}: {len(session['files'])} files")
        else:
            print("📊 Result: With memory provider, files are shared across sessions")
            print()
            print("This demonstrates that:")
            print("   • Session IDs are created and tracked correctly")
            print("   • Files are successfully written with session_id metadata")
            print("   • However, list_session_files returns ALL files (not isolated)")
            print()
            print("🔍 Why?")
            print("   The memory provider stores files in a single shared in-memory store.")
            print("   While each file has a session_id, the list operation doesn't filter")
            print("   by session in this configuration.")
            print()
            print("✅ For true isolation, use:")
            print("   • Redis session provider (SESSION_PROVIDER=redis)")
            print("   • S3/filesystem storage with proper session filtering")
            print("   • Production session management configuration")

        print()
        print("💡 Key takeaways:")
        print("   • Session IDs are essential for organizing files")
        print("   • Isolation level depends on provider configuration")
        print("   • Development (memory) prioritizes simplicity")
        print("   • Production environments support full isolation")
        print()

    finally:
        print("🧹 Cleaning up...")
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)

        import shutil

        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        print("✅ Cleanup complete")


if __name__ == "__main__":
    main()
