from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pages_workflow_deploys_frozen_demo():
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text()
    assert "deploy-pages" in workflow
    assert "upload-pages-artifact" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "landscape_manager freeze frozen-demo" in workflow
    assert "branches: [main]" in workflow


def test_generated_freeze_output_is_gitignored():
    gitignore = (ROOT / ".gitignore").read_text()
    assert "docs/" in gitignore
    assert "frozen-demo/" in gitignore
