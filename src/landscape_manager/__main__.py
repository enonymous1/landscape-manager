"""Entry point: ``python -m landscape_manager`` or ``landscape-manager``.

Two commands, one entry point, kept backward compatible:

- ``landscape-manager [--demo] [--db ...] [--host ...] [--port ...]``
  serves the Flask app (the default, and the documented command).
- ``landscape-manager freeze [output]`` freezes the static demo.

The freeze dispatch used to mutate ``sys.argv`` in place and rely on a
late import; it now passes the remaining arguments explicitly to
``freeze.main``. That keeps ``--help`` honest for both commands and
makes the entry point testable without touching process state.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import create_app
from .db import connect, init_db
from .demo import seed_demo


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "freeze":
        from .freeze import main as freeze_main

        freeze_main(argv[1:])
        return
    parser = argparse.ArgumentParser(description="Landscape Manager web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--db", default=os.environ.get("LANDSCAPE_DB", "landscape.db"))
    parser.add_argument("--demo", action="store_true", help="Seed fictional demo data if empty")
    args = parser.parse_args(argv)
    app = create_app({"DATABASE": args.db})
    if args.demo:
        conn = connect(args.db)
        init_db(conn)
        print("Seeded demo data." if seed_demo(conn) else "Database already has data.")
        conn.close()
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
