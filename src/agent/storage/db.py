import pathlib
import sqlite3

DB_PATH = pathlib.Path(__file__).parent / "agent_persistence.db"

def init_db():
    '''
    Esure db is created, connected to and the required tables are created on the fly.
    '''
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id INTEGER PRIMARY KEY NOT NULL,
                summary VARCHAR,
                model VARCHAR NOT NULL,
                total_tokens INT DEFAULT 0,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP DEFAULT NULL,
                status TEXT DEFAULT 'active',
                approx_cost REAL DEFAULT 0.0
                )
            '''
            )

        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY NOT NULL,
                conversation_id INTEGER REFERENCES conversations(conversation_id),
                role VARCHAR,
                content VARCHAR NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''
            )

        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS tool_calls (
                tool_id INTEGER PRIMARY KEY NOT NULL,
                message_id INTEGER REFERENCES messages(message_id),
                tool_name VARCHAR,
                tool_args VARCHAR,
                tool_output VARCHAR
            )
            '''
            )

        conn.commit()