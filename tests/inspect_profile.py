from pathlib import Path
import json
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from la.browser import browser_session, open_url
from la.config import load_config, project_path

cfg = load_config()
db_path = project_path(cfg["storage"]["database"])
con = sqlite3.connect(db_path)
row = con.execute("SELECT profile_url, name FROM contacts WHERE id = 1").fetchone()
con.close()
print("Contact:", row)

with browser_session(cfg) as (page, context):
    open_url(page, row[0], 3.0, 5.0)
    print("URL:", page.url)
    print("TITLE:", page.title())

    main = page.locator("main")
    print("main count:", main.count())
    if main.count():
        text = main.first.inner_text(timeout=8000)
        print("\nMAIN TEXT (first 900 chars):\n")
        print(text[:900])

    controls = page.evaluate(
        """
        () => {
          const out = [];
          for (const el of document.querySelectorAll("button, a, [role='button']")) {
            const t = (el.innerText || el.getAttribute('aria-label') || '')
              .replace(/\\s+/g, ' ').trim();
            if (!t) continue;
            out.push({
              tag: el.tagName,
              role: el.getAttribute('role'),
              aria: el.getAttribute('aria-label'),
              text: t.slice(0, 70),
              cls: String(el.className || '').slice(0, 70)
            });
          }
          return out.slice(0, 80);
        }
        """
    )
    print("\nCONTROLS:")
    print(json.dumps(controls, indent=2, ensure_ascii=False)[:7000])

    shot = project_path(cfg["storage"]["screenshots"]) / "profile_state_debug.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shot))
    print("\nScreenshot:", shot)
