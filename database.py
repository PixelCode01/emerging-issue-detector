import sqlite3
import logging
import numpy as np

logger = logging.getLogger(__name__)

DB_PATH = "tickets.db"

# Tradeoff: Using standard sqlite3 without ORMs or connection pooling 
# keeps things simple, direct, and performant enough for a weekend project scope.
def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    """Initialize the database schema if it doesn't exist."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    text TEXT,
                    timestamp DATETIME,
                    sdk_version TEXT,
                    region TEXT,
                    user_tier TEXT,
                    source TEXT,
                    embedding BLOB,
                    cluster_id INTEGER
                )
            ''')
            conn.commit()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

def insert_ticket(ticket_id, text, timestamp, sdk_version, region, user_tier, source, embedding):
    """
    Insert a ticket into the database.
    Tradeoff: Serializing numpy arrays directly to bytes for sqlite BLOB columns.
    This is efficient and avoids adding a vector database dependency footprint.
    """
    try:
        # Convert numpy array to bytes
        embedding_bytes = embedding.tobytes() if embedding is not None else None
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tickets (id, text, timestamp, sdk_version, region, user_tier, source, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (ticket_id, text, timestamp, sdk_version, region, user_tier, source, embedding_bytes))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to insert ticket {ticket_id}: {e}")

def get_unclustered_tickets():
    """Fetch tickets that do not have a cluster_id assigned yet."""
    try:
        with get_connection() as conn:
            # Return rows as dictionaries for easier access downstream
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM tickets WHERE cluster_id IS NULL')
            rows = cursor.fetchall()
            
            tickets = []
            for row in rows:
                ticket_dict = dict(row)
                # Hydrate numpy array from bytes. 
                # Tradeoff: hardcoding float32 assuming embedding generation produces it.
                if ticket_dict['embedding'] is not None:
                    ticket_dict['embedding'] = np.frombuffer(ticket_dict['embedding'], dtype=np.float32)
                tickets.append(ticket_dict)
            return tickets
    except Exception as e:
        logger.error(f"Failed to fetch unclustered tickets: {e}")
        # Graceful degradation logic: Return empty list on failure rather than crashing out
        return []

def update_cluster_labels(cluster_updates):
    """
    Update cluster IDs for a batch of tickets.
    cluster_updates is a list of tuples: (cluster_id, ticket_id)
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                UPDATE tickets SET cluster_id = ? WHERE id = ?
            ''', cluster_updates)
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to update cluster labels: {e}")
