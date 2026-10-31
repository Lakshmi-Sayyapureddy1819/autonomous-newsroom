"""Browser-based responsive-layout check (optional).

Loads each page at real device widths in a headless browser and asserts nothing overflows
horizontally. It is skipped automatically when Playwright or a browser is not installed, so
it never breaks CI. To run it locally:

    uv run --project app --with playwright pytest app/tests/test_responsive.py
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from newsroom.db import get_connection, init_db  # noqa: E402
from newsroom.main import app  # noqa: E402

WIDTHS = [(320, 700), (360, 740), (375, 800), (414, 860), (768, 1024), (1024, 768), (1440, 900)]
PAGES = ["/", "/?page=2", "/?tag=Policy", "/?q=zzzznomatch", "/runs", "/no-such-page"]

OVERFLOW_JS = """
() => {
  const vw = document.documentElement.clientWidth;
  const bad = [];
  document.querySelectorAll('body *').forEach(el => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.position === 'fixed') return;
    if (el.closest('.ticker, .aurora, .hero-canvas, .chart-tip, .to-top, .table-wrap')) return;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && (r.right > vw + 1 || r.left < -1))
      bad.push(el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0]);
  });
  return { vw, sw: document.documentElement.scrollWidth, bad: [...new Set(bad)].slice(0, 8) };
}
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory):
    db = tmp_path_factory.mktemp("resp") / "n.sqlite3"
    mp = pytest.MonkeyPatch()
    mp.setenv("NEWSROOM_DB", str(db))
    init_db(db)
    conn = get_connection(db)
    tags = ["Policy", "Tools", "Research", "Industry", "LLMs", "Other"]
    with conn:
        for i in range(45):
            conn.execute(
                "INSERT INTO articles "
                "(url, title, source, published_at, summary, summary_model, tag) "
                "VALUES (?, ?, ?, ?, ?, 'm', ?)",
                (
                    f"https://example.com/{i}",
                    f"Headline number {i} about artificial intelligence and its effects on work",
                    f"Source {i % 7}",
                    f"2026-10-{(i // 24) + 1:02d}T{i % 24:02d}:00:00+00:00",
                    "A one line summary of the story that is reasonably descriptive.",
                    tags[i % 6],
                ),
            )
        # Stress cases: an unbreakable title and a very long source name.
        conn.execute(
            "INSERT INTO articles (url, title, source, published_at, summary, tag) "
            "VALUES (?,?,?,?,?,?)",
            (
                "https://example.com/long",
                "A" * 120,
                "The Extremely Long Named News Source Daily Gazette",
                "2026-10-31T12:00:00+00:00",
                "B" * 100,
                "Policy",
            ),
        )
        conn.execute(
            "INSERT INTO runs "
            "(started_at, finished_at, status, fetched, inserted, summarized, error) "
            "VALUES ('2026-10-31T11:00:00+00:00', '2026-10-31T11:00:05+00:00', "
            "'success', 9, 9, 0, NULL)"
        )
    conn.close()

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    mp.undo()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        launched = None
        for kwargs in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
            try:
                launched = p.chromium.launch(headless=True, **kwargs)
                break
            except Exception:  # browser not installed
                continue
        if launched is None:
            pytest.skip("no Chromium-based browser available for Playwright")
        yield launched
        launched.close()


@pytest.mark.parametrize("width,height", WIDTHS)
def test_no_horizontal_overflow(site: str, browser, width: int, height: int) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height}, reduced_motion="reduce"
    )
    page = context.new_page()
    page.set_default_timeout(20000)
    page.route("**/fonts.g*/**", lambda route: route.abort())  # keep the test offline-friendly
    try:
        for path in PAGES:
            page.goto(site + path, wait_until="load")
            result = page.evaluate(OVERFLOW_JS)
            assert result["sw"] <= result["vw"] + 1, (
                f"{path} @ {width}px scrolls sideways: {result}"
            )
            assert not result["bad"], (
                f"{path} @ {width}px has overflowing elements: {result['bad']}"
            )
    finally:
        context.close()

