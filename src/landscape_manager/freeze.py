"""Freeze a read-only static demo of landscape-manager for GitHub Pages.

Guardrail by construction: this module takes no database argument. It always
boots a fresh temporary database, seeds only the fictional demo data, and
crawls the app with Flask's test client. Real business data cannot be frozen
by mistake.

Output layout (``docs/`` by default for a local preview; CI freezes to
``frozen-demo/`` and deploys that as the GitHub Pages artifact, so
generated output is never committed):

- Every page as ``<path>/index.html`` (``/`` as ``index.html``).
- Static assets copied to ``static/``.
- A ``.nojekyll`` file so Pages serves the output as-is.

Post-processing, applied to every frozen page:

- Internal links are rewritten from root-relative (``/clients``) to relative
  (``clients/``, ``../jobs/``), so the site works both from a project Pages
  subpath (``.../landscape-manager/``) and from a local static server.
  Links to routes that are not frozen become ``#``.
- A "Static demo" banner is inserted after the header.
- Every control inside a ``<form>`` is disabled and forms cannot submit, so
  the demo cannot look interactive when it is not. Controls outside forms —
  notably the theme picker — are left alone, so theme switching still works.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from . import create_app
from .db import connect, init_db
from .demo import seed_demo

BANNER = (
    '<div class="static-banner">Static demo — browsing only. '
    "Forms are disabled and nothing you enter here is saved. "
    "Run the Flask app locally for the full, working version.</div>"
)

STATIC_ROUTES = [
    "/",
    "/clients",
    "/clients/new",
    "/jobs",
    "/jobs/new",
    "/services",
    "/quotes",
    "/quotes/new",
    "/invoices",
    "/invoices/new",
    "/properties/new",
    "/settings",
]


def frozen_path(route: str) -> Path:
    """Output path for a route (``/clients/1`` -> ``clients/1/index.html``)."""
    stripped = route.strip("/")
    if not stripped:
        return Path("index.html")
    if stripped.startswith("static/"):
        return Path(stripped)
    return Path(stripped) / "index.html"


def collect_routes(conn: sqlite3.Connection) -> list[str]:
    """All GET routes to freeze, from the demo database plus static routes."""
    routes = list(STATIC_ROUTES)
    for table, prefix in [
        ("clients", "clients"),
        ("jobs", "jobs"),
        ("quotes", "quotes"),
        ("invoices", "invoices"),
    ]:
        for row in conn.execute(f"SELECT id FROM {table} ORDER BY id").fetchall():
            routes.append(f"/{prefix}/{row['id']}")
    for row in conn.execute("SELECT id FROM clients ORDER BY id").fetchall():
        routes.append(f"/clients/{row['id']}/edit")
    for row in conn.execute("SELECT id FROM properties ORDER BY id").fetchall():
        routes.append(f"/properties/{row['id']}/edit")
    return routes


def relative_url(page_route: str, target: str, frozen: set[str]) -> str:
    """Relative URL from a frozen page to a frozen target, or ``#``."""
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return target
    path = target.split("?", 1)[0].split("#", 1)[0]
    if not path:
        return "#"
    if path not in frozen and not path.startswith("/static/"):
        return "#"
    page_dir = frozen_path(page_route).parent
    target_path = frozen_path(path)
    if target_path.name == "index.html":
        target_dir = target_path.parent
        rel = os.path.relpath(str(target_dir), start=str(page_dir))
        if rel == ".":
            return "./"
        return rel.replace(os.sep, "/") + "/"
    rel = os.path.relpath(str(target_path), start=str(page_dir))
    return rel.replace(os.sep, "/")


class _FrozenPageParser(HTMLParser):
    """Rewrite links, disable form controls, and insert the demo banner."""

    def __init__(self, page_route: str, frozen: set[str]):
        super().__init__(convert_charrefs=False)
        self.page_route = page_route
        self.frozen = frozen
        self.out: list[str] = []
        self.in_form = False

    def _render_attrs(self, attrs, tag: str) -> str:
        attrs = list(attrs)
        names = {name for name, _ in attrs}
        if tag == "form" and "onsubmit" not in names:
            attrs.append(("onsubmit", "return false;"))
        if (
            self.in_form
            and tag in ("input", "select", "textarea", "button")
            and "disabled" not in names
        ):
            attrs.append(("disabled", ""))
        rendered = ""
        for name, value in attrs:
            if value is None:
                rendered += f" {name}"
            else:
                escaped = value.replace("&", "&amp;").replace('"', "&quot;")
                rendered += f' {name}="{escaped}"'
        return rendered

    def handle_decl(self, decl: str) -> None:
        self.out.append(f"<!{decl}>")

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "form":
            self.in_form = True
        if tag == "a" or tag == "link":
            attrs = [
                (name, relative_url(self.page_route, value, self.frozen))
                if name == "href" and value.startswith("/")
                else (name, value)
                for name, value in attrs
            ]
        if tag == "script":
            attrs = [
                (name, relative_url(self.page_route, value, self.frozen))
                if name == "src" and value.startswith("/")
                else (name, value)
                for name, value in attrs
            ]
        self.out.append(f"<{tag}{self._render_attrs(attrs, tag)}>")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in ("link",):
            attrs = [
                (name, relative_url(self.page_route, value, self.frozen))
                if name == "href" and value.startswith("/")
                else (name, value)
                for name, value in attrs
            ]
        self.out.append(f"<{tag}{self._render_attrs(attrs, tag)} />")

    def handle_endtag(self, tag: str) -> None:
        self.out.append(f"</{tag}>")
        if tag == "form":
            self.in_form = False
        if tag == "header":
            self.out.append(BANNER)

    def handle_data(self, data: str) -> None:
        self.out.append(data)

    def handle_comment(self, data: str) -> None:
        self.out.append(f"<!--{data}-->")

    def handle_entityref(self, name: str) -> None:
        self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.out.append(f"&#{name};")


def process_page(html: str, page_route: str, frozen: set[str]) -> str:
    parser = _FrozenPageParser(page_route, frozen)
    parser.feed(html)
    return "".join(parser.out)


def freeze(output_dir: str | Path) -> list[Path]:
    """Freeze the demo app into ``output_dir``. Returns written files."""
    output = Path(output_dir)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "landscape.db")
        conn = connect(db_path)
        init_db(conn)
        seed_demo(conn)
        routes = collect_routes(conn)
        conn.close()
        app = create_app({"DATABASE": db_path, "TESTING": True})
        frozen = set(routes)
        client = app.test_client()
        written: list[Path] = []
        for route in routes:
            response = client.get(route)
            if response.status_code != 200:
                raise RuntimeError(f"Freeze failed: {route} returned {response.status_code}")
            html = process_page(response.get_data(as_text=True), route, frozen)
            dest = output / frozen_path(route)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(html, encoding="utf-8")
            written.append(dest)
        static_src = Path(app.static_folder)
        if static_src.is_dir():
            shutil.copytree(static_src, output / "static")
            written.extend(sorted((output / "static").rglob("*")))
    (output / ".nojekyll").write_text("", encoding="utf-8")
    written.append(output / ".nojekyll")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze a static demo for GitHub Pages")
    parser.add_argument(
        "output", nargs="?", default="docs", help="Output directory (default: docs)"
    )
    args = parser.parse_args()
    written = freeze(args.output)
    print(f"Froze {len(written)} files into {args.output}/")


if __name__ == "__main__":
    main()
