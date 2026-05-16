import argparse
from werkzeug.security import generate_password_hash
from db import get_db, init_db

def create_user(username, password):
    init_db()
    conn = get_db()
    existing_user = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing_user:
        print("User already exists.")
        return
    password_hash = generate_password_hash(password)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (nextval('user_id_seq'), ?, ?)", (username, password_hash))
    print(f"User {username} created successfully.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create a Nasypeasy user.')
    parser.add_argument('username', type=str, help='The username')
    parser.add_argument('password', type=str, help='The password')
    args = parser.parse_args()
    create_user(args.username, args.password)
