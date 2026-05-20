import pathlib
import sqlite3
from contextlib import contextmanager
from .db import init_db,DB_PATH

_DB_INITIALIZED = False


@contextmanager
def get_db_cursor() -> sqlite3.Cursor:
    """Context manager for database connections. Handles commit/rollback automatically."""

    global _DB_INITIALIZED

    if not _DB_INITIALIZED:
        init_db()
        _DB_INITIALIZED = True

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def start_conversation(model:str) -> int | None:
    """Create a single row before the conversation starts"""
    with get_db_cursor() as cursor:
        cursor.execute('''
        INSERT INTO conversations
        (model)
        VALUES (?)
        ''',
        (model,)
        )
        return cursor.lastrowid

def update_conversation_stats(conversation_id: int, total_tokens: int = 0, cost_per_token: dict = None):
    """Update token count and calculate approx cost for a conversation."""
    if cost_per_token is None:
        cost_per_token = {"deepseek/deepseek-v4-flash": 0.25, "deepseek/deepseek-v4-pro": 0.70}

    with get_db_cursor() as cursor:
        cursor.execute(
            '''
            SELECT model FROM conversations WHERE conversation_id = ?
            ''',
            (conversation_id,)
            )
        row = cursor.fetchone()

        if not row:
            return
        
        model = row["model"]

        approx_cost = cost_per_token.get(model,0.0) * total_tokens
        
        cursor.execute('''
        UPDATE conversations
        SET total_tokens = ?, approx_cost = ?
        WHERE conversation_id = ?
        ''',
        (total_tokens, approx_cost, conversation_id)
        )


def add_message(conversation_id:int, role:str, content:str) -> int | None:
    """
    Add message to a converation
    """
    with get_db_cursor() as cursor:
        cursor.execute(
            '''
            INSERT INTO messages 
            (conversation_id, role, content)
            VALUES (?, ?, ?)
            ''',
            (conversation_id,role,content),
        )
        return cursor.lastrowid

def add_tool_call(message_id: int, tool_name: str, tool_args: str, tool_output: str) -> int | None:
    """Log a tool invocation."""
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tool_calls (message_id, tool_name, tool_args, tool_output)
            VALUES (?, ?, ?, ?)
            """,
            (message_id, tool_name, tool_args, tool_output),
        )
        return cursor.lastrowid

def mark_conversation_completed(conversation_id: int, final_summary: str = None):
    """Mark a conversation as completed."""
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            UPDATE conversations 
            SET status = 'completed', ended_at = CURRENT_TIMESTAMP, summary = COALESCE(?, summary)
            WHERE conversation_id = ?
            """,
            (final_summary, conversation_id),
        )

def get_all_conversations():
    """Retrieve all conversations."""
    with get_db_cursor() as cursor:
        cursor.execute(
            '''
            SELECT * FROM conversations ORDER BY started_at DESC
            '''
        )
        return cursor.fetchall()

def get_conversation_messages(conversation_id: int):
    """Retrieve all messages in a conversations."""
    with get_db_cursor() as cursor:
        cursor.execute(
            '''
            SELECT * FROM messages WHERE conversation_id = ?
            ''',
            (conversation_id,),        
        )
        return cursor.fetchall()

def get_conversation(conversation_id:int):
    """Retrieve a single conversation to get baseline stats."""
    with get_db_cursor() as cursor:
        cursor.execute(
        '''
        SELECT * FROM conversations
        WHERE conversation_id = ?
        ''',
        (conversation_id,),
        )
        return cursor.fetchone()
    
def get_tool_calls_for_message(message_id:int):
    """Retrieve all tool calls for a given assistant message ID."""
    with get_db_cursor() as cursor:
        cursor.execute(
            '''
            SELECT * FROM tool_calls
            WHERE message_id = ?
            ORDER BY tool_id ASC
            ''',
            (message_id,),
        )
        return cursor.fetchall()
    
def resume_conversation(conversation_id: int):
    """Re-activate an existing conversation by setting status to active and clearing ended_at."""
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            UPDATE conversations 
            SET status = 'active', ended_at = NULL
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        )
