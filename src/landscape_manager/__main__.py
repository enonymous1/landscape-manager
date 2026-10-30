"""Entry point: ``python -m landscape_manager`` or ``landscape-manager``."""

from __future__ import annotations

import argparse
import os

from . import create_app
from .db import connect, init_db
from .demo import seed_demo


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "freeze":
        from .freeze import main as freeze_main

        sys.argv = [sys.argv[0]] + sys.argv[2:]
        freeze_main()
        return
    parser = argparse.ArgumentParser(description="Landscape Manager web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--db", default=os.environ.get("LANDSCAPE_DB", "landscape.db"))
    parser.add_argument("--demo", action="store_true", help="Seed fictional demo data if empty")
    args = parser.parse_args()
    app = create_app({"DATABASE": args.db})
    if args.demo:
        conn = connect(args.db)
        init_db(conn)
        print("Seeded demo data." if seed_demo(conn) else "Database already has data.")
        conn.close()
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
