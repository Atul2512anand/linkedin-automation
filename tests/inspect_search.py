from pathlib import Path
import json
import sys
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from la.browser import browser_session, open_url
from la.config import load_config

params = {
    "keywords": "technical recruiter",
    "geoUrn": '["101355337"]',
    "origin": "GLOBAL_SEARCH_HEADER",
}
url = "https://www.linkedin.com/search/results/people/?" + urlencode(params)

cfg = load_config()
with browser_session(cfg) as (page, context):
    open_url(page, url, 4.0, 6.0)
    print("URL:  ", page.url)

    ancestors = page.evaluate(
        """
        () => {
          const link = document.querySelector("a[href*='/in/']");
          if (!link) return [];
          const out = [];
          let node = link;
          for (let i = 0; i < 10 && node; i++) {
            out.push({
              i,
              tag: node.tagName,
              cls: String(node.className || '').slice(0, 140),
              role: node.getAttribute('role'),
              testid: node.getAttribute('data-testid'),
              buttons: node.querySelectorAll('button').length,
              profileLinks: node.querySelectorAll("a[href*='/in/']").length,
              text: (node.innerText || '').replace(/\\s+/g, ' ').slice(0, 100)
            });
            node = node.parentElement;
          }
          return out;
        }
        """
    )
    print(json.dumps(ancestors, indent=2, ensure_ascii=False)[:8000])

    controls = page.evaluate(
        """
        () => Array.from(document.querySelectorAll("button, a, [role='button']"))
          .filter(n => (n.innerText || '').trim() === 'Connect')
          .slice(0, 5)
          .map(n => ({
            tag: n.tagName,
            cls: String(n.className || '').slice(0, 160),
            role: n.getAttribute('role'),
            aria: n.getAttribute('aria-label'),
            outer: n.outerHTML.slice(0, 500)
          }))
        """
    )
    print("\nCONNECT CONTROLS:")
    print(json.dumps(controls, indent=2, ensure_ascii=False)[:6000])

    column_html = page.locator("div[data-testid='lazy-column']").first.evaluate(
        "el => el.outerHTML"
    )
    dump = Path(__file__).resolve().parent / "search_dump.html"
    dump.write_text(column_html, encoding="utf-8")
    print("\nColumn HTML bytes:", len(column_html), "->", dump)
