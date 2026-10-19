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
    print("URL:", page.url)
    print("listitems:", page.locator("div[role='listitem']").count())

    tree = page.evaluate(
        """
        () => {
          const card = document.querySelector("div[role='listitem']");
          if (!card) return null;
          const walk = (el, depth) => {
            if (depth > 7) return null;
            const out = {
              tag: el.tagName,
              role: el.getAttribute('role'),
              cls: String(el.className || '').slice(0, 90),
              text: (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 140),
              href: el.getAttribute('href'),
              aria: el.getAttribute('aria-label'),
              children: []
            };
            for (const child of Array.from(el.children).slice(0, 12)) {
              const item = walk(child, depth + 1);
              if (item) out.children.push(item);
            }
            return out;
          };
          return walk(card, 0);
        }
        """
    )
    dump = Path(__file__).resolve().parent / "card_tree.json"
    dump.write_text(json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8")
    print("tree bytes:", dump.stat().st_size, "->", dump)

    card_html = page.locator("div[role='listitem']").first.evaluate("el => el.outerHTML")
    html_dump = Path(__file__).resolve().parent / "card_dump.html"
    html_dump.write_text(card_html, encoding="utf-8")
    print("card html bytes:", len(card_html), "->", html_dump)
