import duckdb

DB_PATH = 'nasypeasy.db'
_conn = None

def get_db():
    global _conn
    if _conn is None:
        _conn = duckdb.connect(DB_PATH, read_only=False)
    return _conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username VARCHAR UNIQUE NOT NULL,
            password_hash VARCHAR NOT NULL
        )
    ''')
    conn.execute('CREATE SEQUENCE IF NOT EXISTS user_id_seq START 1')

if __name__ == '__main__':
    init_db()
    print("Database initialized.")
