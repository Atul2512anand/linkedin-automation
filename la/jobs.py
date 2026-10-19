from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime

from .browser import assert_safe_page, dismiss_cookies
from .config import project_path
from .util import print_table, random_pause

CARD_SELECTOR = "li[data-occludable-job-id], li[data-job-id]"

TITLE_SELECTORS = (
    "a.job-card-container__link strong",
    "a.job-card-list__title--link",
    "a.job-card-container__link",
    "strong",
)
COMPANY_SELECTORS = (
    ".artdeco-entity-lockup__subtitle",
    ".job-card-container__primary-description",
    ".job-card-container__company-name",
)
LOCATION_SELECTORS = (
    ".job-card-container__metadata-item",
    ".artdeco-entity-lockup__caption",
    ".job-card-container__metadata-wrapper li",
)
POSTED_SELECTORS = (
    "time",
    ".job-card-container__listed-time",
)


def _text(scope, selectors) -> str:
    for selector in selectors:
        try:
            locator = scope.locator(selector)
            if locator.count():
                text = locator.first.inner_text(timeout=2000)
                text = " ".join(text.split())
                if text:
                    return text
        except Exception:
            continue
    return ""


def extract_cards(page, found: dict) -> None:
    cards = page.locator(CARD_SELECTOR)
    count = cards.count()
    for index in range(count):
        try:
            card = cards.nth(index)
            job_id = (
                card.get_attribute("data-occludable-job-id")
                or card.get_attribute("data-job-id")
                or ""
            ).strip()

            link = card.locator("a[href*='/jobs/view/']").first
            href = link.get_attribute("href") if link.count() else None
            if not job_id and href:
                match = re.search(r"/jobs/view/(\d+)", href)
                if match:
                    job_id = match.group(1)
            if not job_id:
                continue

            title = _text(card, TITLE_SELECTORS)
            company = _text(card, COMPANY_SELECTORS)
            location = _text(card, LOCATION_SELECTORS)
            posted = _text(card, POSTED_SELECTORS)

            if href and href.startswith("/"):
                href = "https://www.linkedin.com" + href
            if href:
                href = href.split("?")[0]
            else:
                href = f"https://www.linkedin.com/jobs/view/{job_id}/"

            if job_id not in found and (title or company):
                found[job_id] = {
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": href,
                    "posted": posted,
                }
        except Exception:
            continue


def scroll_job_list(page) -> None:
    page.evaluate(
        """
        () => {
          const selectors = [
            '.jobs-search-results-list',
            'div.scaffold-layout__list',
            'div[class*="jobs-search-results-list"]'
          ];
          for (const selector of selectors) {
            const el = document.querySelector(selector);
            if (el && el.scrollHeight > el.clientHeight) {
              el.scrollTop = el.scrollHeight;
              return;
            }
          }
          window.scrollTo(0, document.body.scrollHeight);
        }
        """
    )


def collect_jobs(page, cfg: dict, url: str) -> list[dict]:
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    dismiss_cookies(page)
    assert_safe_page(page)

    found: dict[str, dict] = {}
    scrolls = int(cfg["jobs"].get("scrolls", 6))
    for index in range(scrolls + 1):
        extract_cards(page, found)
        print(f"  [jobs] page position {index + 1}/{scrolls + 1}: {len(found)} jobs seen")
        if index < scrolls:
            scroll_job_list(page)
            random_pause(cfg["jobs"], label="jobs")

    return list(found.values())


def list_jobs(con, status: str | None, limit: int):
    query = "SELECT * FROM jobs"
    params: tuple = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY collected_at DESC, job_id DESC LIMIT ?"
    params += (limit,)
    rows = con.execute(query, params).fetchall()
    print_table(rows, ["job_id", "title", "company", "location", "status"])
    return rows


def export_jobs(con, cfg: dict, fmt: str, out_path: str | None) -> str:
    rows = [dict(row) for row in con.execute("SELECT * FROM jobs ORDER BY collected_at DESC")]
    if out_path:
        path = project_path(out_path)
    else:
        folder = project_path(cfg["storage"]["exports"])
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = folder / f"jobs_{stamp}.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        fieldnames = [
            "job_id",
            "title",
            "company",
            "location",
            "url",
            "posted",
            "status",
            "notes",
            "collected_at",
            "updated_at",
        ]
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})

    return str(path)


def open_job(url: str) -> None:
    if os.name == "nt":
        os.startfile(url)  # noqa: S606 - user explicitly requested opening the URL
    else:
        import webbrowser

        webbrowser.open(url)
