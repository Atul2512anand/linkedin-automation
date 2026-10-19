from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from la.outreach import BATCH_OVERLAY_JS

HTML = """
<html>
<body style="margin:0;background:#f3f4f6;font-family:system-ui,Segoe UI,Arial,sans-serif">
  <div style="max-width:900px;margin:40px auto;background:#fff;padding:32px;border-radius:12px">
    <div style="width:96px;height:96px;border-radius:50%;background:#d1d5db"></div>
    <h1 style="margin:18px 0 4px">Jane Doe</h1>
    <p style="margin:0;color:#4b5563">Recruiter at Acme</p>
    <p style="color:#6b7280">Bengaluru, Karnataka, India</p>
    <button style="background:#0a66c2;color:#fff;border:0;border-radius:16px;padding:8px 18px;font-weight:600">Connect</button>
  </div>
</body>
</html>
"""

out = Path(__file__).resolve().parents[1] / "data" / "screenshots" / "overlay_preview.png"
out.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.set_content(HTML)
    page.evaluate(
        BATCH_OVERLAY_JS,
        {
            "label": "1. Jane Doe",
            "subtitle": "Recruiter | Acme",
            "note": (
                "Hi Jane, I'm exploring Data Scientist roles at Acme. "
                "I'd value connecting and learning from your experience. Thanks!"
            ),
        },
    )
    page.screenshot(path=str(out))
    browser.close()

print(out)
