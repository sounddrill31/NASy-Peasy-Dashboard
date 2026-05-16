import sys
import os

from db import init_db, get_db


def main():
    if len(sys.argv) < 2:
        print("Usage: pixi run add-shared-dir <path>")
        sys.exit(1)

    path = os.path.abspath(sys.argv[1])

    if not os.path.isdir(path):
        print(f"Error: '{path}' is not a valid directory.")
        sys.exit(1)

    init_db()
    db = get_db()

    try:
        db.execute(
            'INSERT INTO shared_dirs (id, path) VALUES (nextval(\'shared_dir_id_seq\'), ?)',
            [path]
        )
        print(f"Shared directory added: {path}")
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            print(f"Shared directory already exists: {path}")
        else:
            print(f"Error adding shared directory: {e}")
            sys.exit(1)


if __name__ == '__main__':
    main()
