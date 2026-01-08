#!/usr/bin/env python3
"""
Slack bot powered by Claude for project management and documentation.
Uses Claude to answer questions and edit project markdown files.
"""

import os
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import anthropic

# Session storage: {channel_id: {"messages": [...], "last_activity": timestamp}}
SESSIONS = {}
SESSION_TIMEOUT = 30 * 60  # 30 minutes in seconds

# Load environment variables
load_dotenv()

# Initialize clients
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))
claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Project root directory (parent of bot folder)
PROJECT_ROOT = Path(__file__).parent.parent

# Project directories - customize for your project
PROJECTS = {
    "project_alpha": "Project Alpha",
    "project_beta": "Project Beta",
    # Add your project directories here
}

# Channel-based access control (optional)
# Map Slack channel IDs to allowed directories
# Channels not listed here get full access
CHANNEL_ACCESS = {
    # "C0123456789": ["project_alpha"],  # #project-alpha channel
    # "C0987654321": ["project_beta"],   # #project-beta channel
}

def get_allowed_dirs(channel_id: str) -> list:
    """Get list of allowed directories for a channel. Returns None for full access."""
    return CHANNEL_ACCESS.get(channel_id, None)

SYSTEM_PROMPT = """You are a helpful assistant for project management and documentation.

## Available Skills

1. **Answer Questions** - Search and summarize information from project files
2. **Edit Files** - Use the edit_file tool to make changes to markdown files. Find the exact text you want to change, and replace it with new text.

## Guidelines
- Be concise and actionable
- Reference specific documents when available
- If you don't have information, say so clearly
- Use the edit_file tool when asked to update, add, or change anything in project files
- Always confirm what you changed after using a tool

## Memory
You have conversation memory within each channel/DM:
- 30 minute window: Memory resets after 30 minutes of inactivity
- 20 message limit: Keeps the last 20 exchanges before older messages are forgotten
- Each channel/DM has its own separate memory

## Weekly Update Command
When user asks for "weekly update", "recent updates", "what's new", or similar:
1. Use the get_recent_updates tool to fetch git history from the last 7 days
2. Summarize the changes by project/area and highlight key updates

## Slack Formatting
Use Slack mrkdwn format, NOT standard markdown:
- Bold: *text* (not **text**)
- Italic: _text_
- Strikethrough: ~text~
- Code: `text` or ```code block```
- Lists: Use * or - with plain text
- No headers (# doesn't work) - use *Bold* for emphasis instead
- Links: <url|text>

Current project files will be provided as context."""

# Tools available to the bot
TOOLS = [
    {
        "name": "edit_file",
        "description": "Edit a markdown file by finding and replacing text. Use this for ANY edit: updating todos, adding notes, modifying content, etc. The find_text must match exactly what's in the file. Can be called multiple times to make multiple edits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file relative to project root (e.g., 'project_alpha/todo.md')"
                },
                "find_text": {
                    "type": "string",
                    "description": "The exact text to find in the file (must match exactly, including whitespace)"
                },
                "replace_text": {
                    "type": "string",
                    "description": "The text to replace it with"
                }
            },
            "required": ["file_path", "find_text", "replace_text"]
        }
    },
    {
        "name": "get_recent_updates",
        "description": "Get git history of project changes from the last N days. Use this when user asks for 'weekly update', 'recent updates', 'what's new', or similar. Returns commit messages, changed files, and diffs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to look back (default: 7)",
                    "default": 7
                }
            },
            "required": []
        }
    }
]


def get_all_markdown_files(allowed_dirs: list = None):
    """Read all markdown files from the project.

    Args:
        allowed_dirs: List of directory names to include. None means all directories.
    """
    files_content = []

    # Get markdown files from root (only if full access)
    if allowed_dirs is None:
        for md_file in PROJECT_ROOT.glob("*.md"):
            if md_file.name != "CLAUDE.md":
                try:
                    content = md_file.read_text()
                    files_content.append(f"## File: {md_file.name}\n\n{content}")
                except Exception as e:
                    files_content.append(f"## File: {md_file.name}\n\nError reading file: {e}")

    # Get markdown files from each project directory
    for proj_dir, proj_name in PROJECTS.items():
        # Skip if not in allowed directories
        if allowed_dirs is not None and proj_dir not in allowed_dirs:
            continue

        proj_path = PROJECT_ROOT / proj_dir
        if proj_path.exists():
            for md_file in proj_path.glob("**/*.md"):
                try:
                    content = md_file.read_text()
                    relative_path = md_file.relative_to(PROJECT_ROOT)
                    files_content.append(f"## File: {relative_path} ({proj_name})\n\n{content}")
                except Exception as e:
                    files_content.append(f"## File: {md_file.name}\n\nError reading file: {e}")

    return "\n\n---\n\n".join(files_content) if files_content else "No project files found."


def edit_file(file_path: str, find_text: str, replace_text: str, allowed_dirs: list = None) -> str:
    """Edit a file by finding and replacing text."""
    full_path = PROJECT_ROOT / file_path

    # Check access permissions
    if allowed_dirs is not None:
        file_dir = file_path.split("/")[0] if "/" in file_path else None
        if file_dir not in allowed_dirs:
            return f"Error: You don't have access to edit files in '{file_dir}'. This channel can only access: {', '.join(allowed_dirs)}"

    if not full_path.exists():
        return f"Error: File '{file_path}' does not exist."

    if not full_path.suffix == ".md":
        return f"Error: Can only edit markdown (.md) files."

    content = full_path.read_text()

    if find_text not in content:
        return f"Error: Could not find the specified text in '{file_path}'. Make sure it matches exactly."

    new_content = content.replace(find_text, replace_text, 1)
    full_path.write_text(new_content)

    return f"Updated '{file_path}': replaced text successfully."


def get_recent_updates(days: int = 7) -> str:
    """Get git history of recent project changes."""
    try:
        since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # Get commit log with files changed
        log_result = subprocess.run(
            ["git", "log", f"--since={since_date}", "--pretty=format:%h|%s|%ad", "--date=short", "--name-only"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )

        if log_result.returncode != 0:
            return f"Error running git log: {log_result.stderr}"

        if not log_result.stdout.strip():
            return f"No commits found in the last {days} days."

        # Get summary stats
        stat_result = subprocess.run(
            ["git", "log", f"--since={since_date}", "--pretty=format:", "--shortstat"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )

        # Count commits
        count_result = subprocess.run(
            ["git", "rev-list", "--count", f"--since={since_date}", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        commit_count = count_result.stdout.strip() if count_result.returncode == 0 else "unknown"

        # Get list of all unique files changed
        files_result = subprocess.run(
            ["git", "log", f"--since={since_date}", "--pretty=format:", "--name-only"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        unique_files = set(f for f in files_result.stdout.strip().split("\n") if f)

        # Build response
        response = f"Git history for the last {days} days:\n\n"
        response += f"Total commits: {commit_count}\n"
        response += f"Files modified: {len(unique_files)}\n\n"
        response += "Commits:\n"
        response += log_result.stdout

        return response

    except Exception as e:
        return f"Error getting git history: {str(e)}"


def execute_tool(tool_name: str, tool_input: dict, allowed_dirs: list = None) -> str:
    """Execute a tool and return the result."""
    if tool_name == "edit_file":
        return edit_file(
            tool_input["file_path"],
            tool_input["find_text"],
            tool_input["replace_text"],
            allowed_dirs
        )
    elif tool_name == "get_recent_updates":
        return get_recent_updates(tool_input.get("days", 7))
    else:
        return f"Unknown tool: {tool_name}"


def get_session(channel_id: str) -> dict:
    """Get or create a session for a channel, clearing if expired."""
    now = time.time()

    # Clean up expired sessions
    expired = [cid for cid, session in SESSIONS.items()
               if now - session["last_activity"] > SESSION_TIMEOUT]
    for cid in expired:
        del SESSIONS[cid]

    # Get or create session
    if channel_id not in SESSIONS or now - SESSIONS[channel_id]["last_activity"] > SESSION_TIMEOUT:
        SESSIONS[channel_id] = {"messages": [], "last_activity": now}
    else:
        SESSIONS[channel_id]["last_activity"] = now

    return SESSIONS[channel_id]


def ask_claude(user_message: str, channel_id: str) -> str:
    """Send a message to Claude and get a response, handling tool use."""
    session = get_session(channel_id)
    allowed_dirs = get_allowed_dirs(channel_id)
    project_context = get_all_markdown_files(allowed_dirs)

    # Build context message (only include files on first message or if session is empty)
    if not session["messages"]:
        context_message = f"""Here are the current project files:

{project_context}

---

User request: {user_message}"""
    else:
        # Subsequent messages just reference the files are still available
        context_message = f"""(Project files still available from earlier in conversation)

User request: {user_message}"""

    # Add user message to session
    session["messages"].append({"role": "user", "content": context_message})

    # Use session messages for context
    messages = session["messages"].copy()

    try:
        # Initial request
        response = claude.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            system=SYSTEM_PROMPT + f"\n\nCurrent project files:\n{project_context}",
            tools=TOOLS,
            messages=messages
        )

        # Handle tool use loop
        while response.stop_reason == "tool_use":
            tool_results = []
            assistant_content = response.content

            for block in response.content:
                if block.type == "tool_use":
                    tool_result = execute_tool(block.name, block.input, allowed_dirs)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tool_result
                    })

            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})

            response = claude.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1024,
                system=SYSTEM_PROMPT + f"\n\nCurrent project files:\n{project_context}",
                tools=TOOLS,
                messages=messages
            )

        # Extract final text response
        response_text = None
        for block in response.content:
            if hasattr(block, "text"):
                response_text = block.text
                break

        if response_text is None:
            response_text = "I completed the action but have no additional message."

        # Save assistant response to session (simplified version)
        session["messages"].append({"role": "assistant", "content": response_text})

        # Keep session from growing too large (last 20 exchanges)
        if len(session["messages"]) > 40:
            session["messages"] = session["messages"][-40:]

        return response_text

    except Exception as e:
        return f"Sorry, I encountered an error: {str(e)}"


@app.event("app_mention")
def handle_mention(event, say, client):
    """Handle @bot mentions in channels."""
    user_message = event.get("text", "").split(">", 1)[-1].strip()
    channel = event.get("channel")
    if user_message:
        # Show typing indicator
        thinking_msg = client.chat_postMessage(channel=channel, text="_Thinking..._")

        response = ask_claude(user_message, channel)

        # Delete thinking message and post response
        client.chat_delete(channel=channel, ts=thinking_msg["ts"])
        say(response)
    else:
        say("Hi! Ask me anything about your project.")


@app.event("message")
def handle_dm(event, say, client):
    """Handle direct messages to the bot."""
    if event.get("bot_id") or event.get("channel_type") != "im":
        return

    user_message = event.get("text", "")
    channel = event.get("channel")
    if user_message:
        # Show typing indicator
        thinking_msg = client.chat_postMessage(channel=channel, text="_Thinking..._")

        response = ask_claude(user_message, channel)

        # Delete thinking message and post response
        client.chat_delete(channel=channel, ts=thinking_msg["ts"])
        say(response)


def main():
    """Start the bot."""
    print("Starting bot...")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Projects: {list(PROJECTS.keys())}")

    md_files = list(PROJECT_ROOT.glob("**/*.md"))
    print(f"Found {len(md_files)} markdown files")
    print("Tools: edit_file, get_recent_updates")

    handler = SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    print("Bot is running! Press Ctrl+C to stop.")
    handler.start()


if __name__ == "__main__":
    main()
