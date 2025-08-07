import sqlite3
import os
from config import get_config

config = get_config()

def setup_db():
    try:
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    upload_time TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    file_location TEXT NOT NULL,
                    download_count INTEGER DEFAULT 0
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON uploads(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_upload_time ON uploads(upload_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_filename ON uploads(filename)')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS shared_uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    upload_id INTEGER NOT NULL,
                    shared_by TEXT NOT NULL,
                    shared_with TEXT NOT NULL,
                    shared_time TEXT NOT NULL,
                    FOREIGN KEY(upload_id) REFERENCES uploads(id)
                )
            ''')
            conn.commit()
            print(f"Database initialized at {config.DB_PATH}")
    except Exception as e:
        print(f"Failed to initialize database: {e}")

if __name__ == "__main__":
    setup_db()
