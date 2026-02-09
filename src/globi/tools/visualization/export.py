"""Export helpers for chart download (e.g. HTML to PNG)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


def render_html_to_png(html: str, width: int = 800, height: int = 500) -> bytes | None:
    """Render chart HTML to PNG bytes using playwright if available."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as f:
        f.write(html)
        path = Path(f.name)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(f"file://{path.resolve()}")
            page.wait_for_timeout(500)
            png_bytes = page.screenshot(type="png", full_page=True)
            browser.close()
    except Exception:
        return None
    else:
        return png_bytes
    finally:
        path.unlink(missing_ok=True)
