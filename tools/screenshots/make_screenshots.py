"""Render the README screenshots of the panel from invented demo data.

Usage: python make_screenshots.py OUTPUT_DIR [FONT_DIR]

Needs Playwright with Chromium. FONT_DIR may hold Roboto woff2 files
(roboto-latin-400/500/700-normal.woff2). Map tiles are not loaded here;
OpenStreetMap only serves tiles to pages with a referrer, so the map
screenshots are taken from a self-contained copy of demo.html served by
Home Assistant (``/config/www`` -> ``/local/...``; remove it afterwards).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright

HERE = Path(__file__).parent


def _fonts(font_dir: Path | None) -> str:
    if font_dir is None:
        return ""
    rules = []
    for weight in (400, 500, 700):
        path = font_dir / f"roboto-latin-{weight}-normal.woff2"
        if path.exists():
            rules.append(
                f"@font-face {{ font-family: Roboto; font-weight: {weight}; "
                f"src: url('{path.as_uri()}') format('woff2'); }}"
            )
    return "\n".join(rules)


async def _shot(page: Page, path: Path, script: str, wait: int = 400) -> None:
    await page.evaluate(script)
    await page.wait_for_timeout(wait)
    await page.screenshot(path=str(path))


async def main(out: Path, font_dir: Path | None) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        # The map is not part of these shots: block tile requests.
        await page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
        await page.goto((HERE / "demo.html").as_uri())
        await page.add_style_tag(content=_fonts(font_dir))
        await page.wait_for_timeout(600)
        await _shot(
            page,
            out / "panel-chat.png",
            "panel._setTab('chat'); panel._openConversation('group:262')",
        )
        await _shot(page, out / "panel-nodes.png", "panel._setTab('nodes')")
        await browser.close()


if __name__ == "__main__":
    Path(sys.argv[1]).mkdir(parents=True, exist_ok=True)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None))
