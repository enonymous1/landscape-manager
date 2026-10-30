import re

from landscape_manager.freeze import freeze


def test_freeze_produces_pages_with_banner_and_relative_links(tmp_path):
    output = tmp_path / "docs"
    written = freeze(output)
    assert (output / "index.html").exists()
    assert (output / "clients" / "index.html").exists()
    assert (output / "jobs" / "index.html").exists()
    assert (output / "services" / "index.html").exists()
    assert (output / "quotes" / "index.html").exists()
    assert (output / "invoices" / "index.html").exists()
    assert (output / "static" / "style.css").exists()
    assert (output / ".nojekyll").exists()
    assert len(written) >= 20

    home = (output / "index.html").read_text()
    assert "Static demo" in home
    assert "Alex Rivera" in home or "Landscaping" in home
    # No root-relative internal links left on the home page.
    assert 'href="/' not in home
    assert 'href="clients/"' in home
    assert 'href="static/style.css"' in home

    deep = (output / "clients" / "1" / "index.html").read_text()
    assert "Static demo" in deep
    # From clients/1/, the dashboard and static CSS are two levels up.
    assert 'href="../../"' in deep or 'href="../"' in deep
    assert 'href="../../static/style.css"' in deep


def test_freeze_disables_forms_but_not_theme_picker(tmp_path):
    output = tmp_path / "docs"
    freeze(output)
    new_client = (output / "clients" / "new" / "index.html").read_text()
    assert "Static demo" in new_client
    # Form controls are disabled.
    assert re.search(r"<input[^>]*disabled", new_client)
    assert re.search(r'<form[^>]*onsubmit="return false;"', new_client)
    # The theme picker is outside any form, so it stays usable.
    picker = re.search(r'<select id="theme-picker"[^>]*>', new_client)
    assert picker is not None
    assert "disabled" not in picker.group(0)
