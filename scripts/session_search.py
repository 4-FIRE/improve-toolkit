#!/usr/bin/env python3
"""
Session search utility.
Search and display conversation history from the session database.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from session_db import (
    search_conversations,
    get_session_history,
    list_sessions,
    get_db_path,
    get_transcript
)


SESSION_SEARCH_SCHEMA = {
    "name": "session_search",
    "description": (
        "Search your long-term memory of past conversations, or browse recent sessions. This is your recall -- "
        "every past session is searchable, and this tool summarizes what happened.\n\n"
        "TWO MODES:\n"
        "1. Recent sessions (no query): Call with no arguments to see what was worked on recently. "
        "Returns titles, previews, and timestamps. Zero LLM cost, instant. "
        "Start here when the user asks what were we working on or what did we do recently.\n"
        "2. Keyword search (with query): Search for specific topics across all past sessions. "
        "Returns LLM-generated summaries of matching sessions.\n\n"
        "USE THIS PROACTIVELY when:\n"
        "- The user says 'we did this before', 'remember when', 'last time', 'as I mentioned'\n"
        "- The user asks about a topic you worked on before but don't have in current context\n"
        "- The user references a project, person, or concept that seems familiar but isn't in memory\n"
        "- You want to check if you've solved a similar problem before\n"
        "- The user asks 'what did we do about X?' or 'how did we fix Y?'\n\n"
        "Don't hesitate to search when it is actually cross-session -- it's fast and cheap. "
        "Better to search and confirm than to guess or ask the user to repeat themselves.\n\n"
        "Search syntax: keywords joined with OR for broad recall (elevenlabs OR baseten OR funding), "
        "phrases for exact match (\"docker networking\"), boolean (python NOT java), prefix (deploy*). "
        "IMPORTANT: Use OR between keywords for best results — FTS5 defaults to AND which misses "
        "sessions that only mention some terms. If a broad OR query returns nothing, try individual "
        "keyword searches in parallel. Returns summaries of the top matching sessions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — keywords, phrases, or boolean expressions to find in past sessions. Omit this parameter entirely to browse recent sessions instead (returns titles, previews, timestamps with no LLM cost).",
            },
            "role_filter": {
                "type": "string",
                "description": "Optional: only search messages from specific roles (comma-separated). E.g. 'user,assistant' to skip tool outputs.",
            },
            "limit": {
                "type": "integer",
                "description": "Max sessions to summarize (default: 3, max: 5).",
                "default": 3,
            },
        },
        "required": [],
    },
}


SESSION_HISTORY_SCHEMA = {
    "name": "session_history",
    "description": (
        "Get the full conversation history for a specific session. "
        "Returns all messages (user, assistant, tool outputs) in chronological order.\n\n"
        "Use this when:\n"
        "- You need to see the complete context of a specific session\n"
        "- You want to review the full conversation flow\n"
        "- You found a session via session_search and want to see all details"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session ID to retrieve history for.",
            },
        },
        "required": ["session_id"],
    },
}


def session_search_tool(
    query: str | None = None,
    role_filter: str | None = None,
    limit: int = 3,
) -> str:
    """
    MCP tool for session search.
    
    Two modes:
    1. Recent sessions (no query): Returns list of recent sessions with titles, previews, timestamps
    2. Keyword search (with query): Searches conversations and returns summaries
    """
    limit = min(max(limit, 1), 5)
    
    if not query:
        sessions = list_sessions(limit=limit)
        return _format_recent_sessions(sessions)
    
    results = search_conversations(query=query, limit=limit * 10)
    
    if role_filter:
        allowed_roles = [r.strip().lower() for r in role_filter.split(',')]
        results = [r for r in results if r['role'].lower() in allowed_roles]
    
    session_summaries = _summarize_search_results(results, limit)
    
    return json.dumps(session_summaries, ensure_ascii=False, indent=2)


def session_history_tool(session_id: str) -> str:
    """
    MCP tool for getting session history.
    
    Returns the full conversation history for a specific session.
    """
    history = get_session_history(session_id)
    
    if not history:
        return json.dumps({
            "error": f"No conversation history found for session: {session_id}",
            "session_id": session_id
        }, ensure_ascii=False, indent=2)
    
    simplified_history = [
        {
            "timestamp": msg["timestamp"],
            "role": msg["role"],
            "content": msg.get("content", "")
        }
        for msg in history
    ]
    
    return json.dumps({
        "session_id": session_id,
        "message_count": len(simplified_history),
        "history": simplified_history
    }, ensure_ascii=False, indent=2)


def _format_recent_sessions(sessions: list[dict]) -> str:
    """Format recent sessions for display."""
    if not sessions:
        return "No recent sessions found."
    
    output = []
    output.append(f"Recent Sessions ({len(sessions)} total)\n")
    output.append("=" * 80)
    
    for session in sessions:
        session_id = session['id']
        start_time = format_timestamp(session['start_time'])
        end_time = format_timestamp(session['end_time']) if session['end_time'] else "ongoing"
        workspace = session.get('workspace', 'N/A')
        status = session.get('status', 'unknown')
        
        history = get_session_history(session_id)
        preview = _get_session_preview(history)
        
        output.append(f"\nSession: {session_id}")
        output.append(f"  Started: {start_time}")
        output.append(f"  Ended: {end_time}")
        output.append(f"  Status: {status}")
        output.append(f"  Workspace: {workspace}")
        if preview:
            output.append(f"  Preview: {preview}")
    
    return "\n".join(output)


def _get_session_preview(history: list[dict], max_length: int = 150) -> str:
    """Get a preview of the session from the first user message."""
    for msg in history:
        if msg['role'] == 'user' and msg.get('content'):
            content = msg['content']
            if len(content) > max_length:
                return content[:max_length] + "..."
            return content
    return ""


def _summarize_search_results(results: list[dict], limit: int) -> dict:
    """Summarize search results grouped by session."""
    sessions_map = {}
    
    for result in results:
        session_id = result['session_id']
        if session_id not in sessions_map:
            sessions_map[session_id] = {
                'session_id': session_id,
                'timestamp': result['timestamp'],
                'workspace': result.get('workspace'),
                'matches': []
            }
        sessions_map[session_id]['matches'].append({
            'timestamp': result['timestamp'],
            'role': result['role'],
            'content': result.get('content', '')[:300]
        })
    
    sorted_sessions = sorted(
        sessions_map.values(),
        key=lambda x: x['timestamp'],
        reverse=True
    )[:limit]
    
    return {
        'total_sessions': len(sessions_map),
        'returned_sessions': len(sorted_sessions),
        'sessions': sorted_sessions
    }


def format_timestamp(ts_str: str) -> str:
    """Format ISO timestamp to readable format."""
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ts_str


def print_search_results(results: list[dict], show_content: bool = True) -> None:
    """Print search results in a formatted way."""
    if not results:
        print("No results found.")
        return
    
    print(f"\n{'='*80}")
    print(f"Found {len(results)} result(s)")
    print(f"{'='*80}\n")
    
    for i, result in enumerate(results, 1):
        print(f"[{i}] Session: {result['session_id']}")
        print(f"    Time: {format_timestamp(result['timestamp'])}")
        print(f"    Role: {result['role']}")
        if result.get('workspace'):
            print(f"    Workspace: {result['workspace']}")
        
        if show_content and result.get('content'):
            content = result['content']
            if len(content) > 200:
                content = content[:200] + "..."
            print(f"    Content: {content}")
        print()


def print_session_history(history: list[dict]) -> None:
    """Print session history in a formatted way."""
    if not history:
        print("No conversation history found for this session.")
        return
    
    print(f"\n{'='*80}")
    print(f"Session History ({len(history)} messages)")
    print(f"{'='*80}\n")
    
    for msg in history:
        timestamp = format_timestamp(msg['timestamp'])
        role = msg['role'].upper()
        content = msg.get('content', '')
        
        print(f"[{timestamp}] {role}:")
        print(f"{content}")
        print("-" * 40)


def print_sessions_list(sessions: list[dict]) -> None:
    """Print list of sessions."""
    if not sessions:
        print("No sessions found.")
        return
    
    print(f"\n{'='*80}")
    print(f"Sessions ({len(sessions)} total)")
    print(f"{'='*80}\n")
    
    for session in sessions:
        start = format_timestamp(session['start_time'])
        end = format_timestamp(session['end_time']) if session['end_time'] else "ongoing"
        status = session['status']
        workspace = session.get('workspace', 'N/A')
        cwd = session.get('cwd', 'N/A')
        permission_mode = session.get('permission_mode', 'N/A')
        agent_type = session.get('agent_type', 'N/A')
        transcript_path = session.get('transcript_path', 'N/A')
        
        print(f"Session: {session['id']}")
        print(f"  Started: {start}")
        print(f"  Ended: {end}")
        print(f"  Status: {status}")
        print(f"  Workspace: {workspace}")
        print(f"  CWD: {cwd}")
        print(f"  Permission Mode: {permission_mode}")
        print(f"  Agent Type: {agent_type}")
        print(f"  Transcript Path: {transcript_path}")
        print()


def cmd_search(args):
    """Handle search command."""
    results = search_conversations(
        query=args.query,
        session_id=args.session_id,
        limit=args.limit,
        offset=args.offset
    )
    
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_search_results(results, show_content=not args.brief)


def cmd_history(args):
    """Handle history command."""
    history = get_session_history(args.session_id)
    
    if args.json:
        print(json.dumps(history, ensure_ascii=False, indent=2))
    else:
        print_session_history(history)


def cmd_list(args):
    """Handle list command."""
    sessions = list_sessions(
        status=args.status,
        limit=args.limit,
        offset=args.offset
    )
    
    if args.json:
        print(json.dumps(sessions, ensure_ascii=False, indent=2))
    else:
        print_sessions_list(sessions)


def cmd_info(args):
    """Handle info command."""
    db_path = get_db_path()
    print(f"Database path: {db_path}")
    print(f"Database exists: {db_path.exists()}")
    
    if db_path.exists():
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM sessions")
        session_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM conversations")
        conv_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM sessions WHERE status = 'active'")
        active_count = cursor.fetchone()[0]
        
        conn.close()
        
        print(f"Total sessions: {session_count}")
        print(f"Active sessions: {active_count}")
        print(f"Total conversations: {conv_count}")


def cmd_transcript(args):
    """Handle transcript command."""
    transcript = get_transcript(args.session_id)
    
    if not transcript:
        print("No transcript data found for this session.")
        return
    
    if args.json:
        print(json.dumps(transcript, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*80}")
        print(f"Transcript for session: {args.session_id}")
        print(f"Total lines: {len(transcript)}")
        print(f"{'='*80}\n")
        
        for line in transcript:
            line_num = line['line_number']
            line_data = line['line_data']
            timestamp = line.get('timestamp')
            
            if args.raw:
                if isinstance(line_data, dict):
                    print(json.dumps(line_data, ensure_ascii=False))
                else:
                    print(line_data)
            else:
                print(f"[Line {line_num}]")
                if timestamp:
                    print(f"  Timestamp: {format_timestamp(timestamp)}")
                
                if isinstance(line_data, dict):
                    line_type = line_data.get('type', 'unknown')
                    print(f"  Type: {line_type}")
                    
                    if line_type == 'user':
                        message = line_data.get('message', {})
                        content = message.get('content', '')
                        if content:
                            print(f"  User Message: {content[:200]}...")
                    
                    elif line_type == 'assistant':
                        message = line_data.get('message', {})
                        content = message.get('content', [])
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict):
                                    block_type = block.get('type')
                                    if block_type == 'text':
                                        text = block.get('text', '')
                                        print(f"  Assistant Text: {text[:200]}...")
                                    elif block_type == 'tool_use':
                                        tool_name = block.get('name', 'unknown')
                                        print(f"  Tool Use: {tool_name}")
                else:
                    print(f"  Data: {str(line_data)[:200]}...")
                
                print()


def main():
    parser = argparse.ArgumentParser(
        description="Session search and management utility"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    search_parser = subparsers.add_parser("search", help="Search conversations")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-s", "--session-id", help="Filter by session ID")
    search_parser.add_argument("-l", "--limit", type=int, default=50, help="Limit results")
    search_parser.add_argument("-o", "--offset", type=int, default=0, help="Offset results")
    search_parser.add_argument("-j", "--json", action="store_true", help="Output as JSON")
    search_parser.add_argument("-b", "--brief", action="store_true", help="Brief output")
    search_parser.set_defaults(func=cmd_search)
    
    history_parser = subparsers.add_parser("history", help="Show session history")
    history_parser.add_argument("session_id", help="Session ID")
    history_parser.add_argument("-j", "--json", action="store_true", help="Output as JSON")
    history_parser.set_defaults(func=cmd_history)
    
    list_parser = subparsers.add_parser("list", help="List sessions")
    list_parser.add_argument("-s", "--status", help="Filter by status (active/completed)")
    list_parser.add_argument("-l", "--limit", type=int, default=50, help="Limit results")
    list_parser.add_argument("-o", "--offset", type=int, default=0, help="Offset results")
    list_parser.add_argument("-j", "--json", action="store_true", help="Output as JSON")
    list_parser.set_defaults(func=cmd_list)
    
    info_parser = subparsers.add_parser("info", help="Show database info")
    info_parser.set_defaults(func=cmd_info)
    
    transcript_parser = subparsers.add_parser("transcript", help="Show session transcript")
    transcript_parser.add_argument("session_id", help="Session ID")
    transcript_parser.add_argument("-j", "--json", action="store_true", help="Output as JSON")
    transcript_parser.add_argument("-r", "--raw", action="store_true", help="Raw output (one JSON per line)")
    transcript_parser.set_defaults(func=cmd_transcript)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return
    
    args.func(args)


if __name__ == "__main__":
    main()
