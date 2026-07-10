import sys
import os

# Ensure the project root is in PYTHONPATH
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from src.mcp_server import summarize_file, hibernate_session

print("=== TESTING SUMMARIZE FILE ===")
try:
    summary = summarize_file("src/lmstudio_client.py", project_name="FourTIndex")
    print(summary)
except Exception as e:
    print(f"Error in summarize_file: {e}")

print("\n=== TESTING HIBERNATE SESSION ===")
try:
    hibernate_res = hibernate_session(
        current_task="Testing hibernate feature",
        next_steps="Verify .fourtindex_handoff.md creation",
        uncommitted_changes="No uncommitted changes",
        project_name="FourTIndex"
    )
    print(hibernate_res)
except Exception as e:
    print(f"Error in hibernate_session: {e}")
