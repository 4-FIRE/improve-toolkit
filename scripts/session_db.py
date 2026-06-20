#!/usr/bin/env python3
"""
Session and conversation logger for improve-toolkit.
Records session metadata and full conversation history to SQLite database.
"""

import json
import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_home() -> Path:
    """Return the project directory ($CLAUDE_PROJECT_DIR/.claude)."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude"


def get_db_path() -> Path:
    """Return the path to the session database."""
    return get_home() / "sessions" / "sessions.db"


def init_database(db_path: Path) -> None:
    """Initialize the database schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    need_init = not db_path.exists()
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    if need_init:
        import os
        os.chmod(str(db_path), 0o644)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            start_time TEXT NOT NULL,
            end_time TEXT,
            workspace TEXT,
            status TEXT DEFAULT 'active',
            metadata TEXT,
            transcript_path TEXT,
            cwd TEXT,
            permission_mode TEXT,
            agent_type TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            metadata TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            line_number INTEGER NOT NULL,
            line_data TEXT NOT NULL,
            timestamp TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_session_id 
        ON conversations(session_id)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_timestamp 
        ON conversations(timestamp)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_content 
        ON conversations(content)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_transcripts_session_id 
        ON transcripts(session_id)
    """)
    
    conn.commit()
    conn.close()


def get_db_connection() -> sqlite3.Connection:
    """Get a database connection, initializing if necessary."""
    db_path = get_db_path()
    init_database(db_path)
    
    if db_path.exists():
        try:
            subprocess.run(['xattr', '-c', str(db_path)], check=False, capture_output=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
    
    return sqlite3.connect(str(db_path))


def record_session_start(
    session_id: str, 
    workspace: str, 
    metadata: Optional[dict] = None,
    transcript_path: Optional[str] = None,
    cwd: Optional[str] = None,
    permission_mode: Optional[str] = None,
    agent_type: Optional[str] = None
) -> None:
    """Record the start of a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    
    cursor.execute("""
        INSERT OR REPLACE INTO sessions 
        (id, start_time, workspace, status, metadata, transcript_path, cwd, permission_mode, agent_type)
        VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)
    """, (session_id, now, workspace, metadata_json, transcript_path, cwd, permission_mode, agent_type))
    
    conn.commit()
    conn.close()


def save_transcript(session_id: str, transcript_path: str) -> None:
    """Save transcript file content to database."""
    if not transcript_path or not Path(transcript_path).exists():
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM transcripts WHERE session_id = ?", (session_id,))
    
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        timestamp = data.get('timestamp')
                    except json.JSONDecodeError:
                        timestamp = None
                    
                    cursor.execute("""
                        INSERT INTO transcripts (session_id, line_number, line_data, timestamp)
                        VALUES (?, ?, ?, ?)
                    """, (session_id, line_num, line, timestamp))
    except (OSError, IOError):
        pass
    
    conn.commit()
    conn.close()


def record_session_end(session_id: str, metadata: Optional[dict] = None) -> None:
    """Record the end of a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    
    cursor.execute("""
        UPDATE sessions 
        SET end_time = ?, status = 'completed', metadata = COALESCE(?, metadata)
        WHERE id = ?
    """, (now, metadata_json, session_id))
    
    conn.commit()
    conn.close()


def record_conversation(
    session_id: str, 
    role: str, 
    content: str, 
    metadata: Optional[dict] = None
) -> None:
    """Record a conversation message."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    
    cursor.execute("""
        INSERT INTO conversations (session_id, timestamp, role, content, metadata)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, now, role, content, metadata_json))
    
    conn.commit()
    conn.close()


def search_conversations(
    query: str, 
    session_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
    """Search conversations by content."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    search_pattern = f"%{query}%"
    
    if session_id:
        cursor.execute("""
            SELECT c.id, c.session_id, c.timestamp, c.role, c.content, c.metadata,
                   s.workspace
            FROM conversations c
            LEFT JOIN sessions s ON c.session_id = s.id
            WHERE c.session_id = ? AND c.content LIKE ?
            ORDER BY c.timestamp DESC
            LIMIT ? OFFSET ?
        """, (session_id, search_pattern, limit, offset))
    else:
        cursor.execute("""
            SELECT c.id, c.session_id, c.timestamp, c.role, c.content, c.metadata,
                   s.workspace
            FROM conversations c
            LEFT JOIN sessions s ON c.session_id = s.id
            WHERE c.content LIKE ?
            ORDER BY c.timestamp DESC
            LIMIT ? OFFSET ?
        """, (search_pattern, limit, offset))
    
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            "id": row[0],
            "session_id": row[1],
            "timestamp": row[2],
            "role": row[3],
            "content": row[4],
            "metadata": json.loads(row[5]) if row[5] else None,
            "workspace": row[6]
        })
    
    return results


def get_session_history(session_id: str) -> list[dict]:
    """Get all conversations for a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, session_id, timestamp, role, content, metadata
        FROM conversations
        WHERE session_id = ?
        ORDER BY timestamp ASC
    """, (session_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            "id": row[0],
            "session_id": row[1],
            "timestamp": row[2],
            "role": row[3],
            "content": row[4],
            "metadata": json.loads(row[5]) if row[5] else None
        })
    
    return results


def list_sessions(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
    """List sessions with optional filtering."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if status:
        cursor.execute("""
            SELECT id, start_time, end_time, workspace, status, metadata,
                   transcript_path, cwd, permission_mode, agent_type
            FROM sessions
            WHERE status = ?
            ORDER BY start_time DESC
            LIMIT ? OFFSET ?
        """, (status, limit, offset))
    else:
        cursor.execute("""
            SELECT id, start_time, end_time, workspace, status, metadata,
                   transcript_path, cwd, permission_mode, agent_type
            FROM sessions
            ORDER BY start_time DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
    
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            "id": row[0],
            "start_time": row[1],
            "end_time": row[2],
            "workspace": row[3],
            "status": row[4],
            "metadata": json.loads(row[5]) if row[5] else None,
            "transcript_path": row[6],
            "cwd": row[7],
            "permission_mode": row[8],
            "agent_type": row[9]
        })
    
    return results


def get_transcript(session_id: str) -> list[dict]:
    """Get transcript data for a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT line_number, line_data, timestamp
        FROM transcripts
        WHERE session_id = ?
        ORDER BY line_number ASC
    """, (session_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        try:
            line_data = json.loads(row[1])
        except json.JSONDecodeError:
            line_data = row[1]
        
        results.append({
            "line_number": row[0],
            "line_data": line_data,
            "timestamp": row[2]
        })
    
    return results
