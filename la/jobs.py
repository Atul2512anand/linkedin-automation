from __future__ import annotations

import csv
import json
import os
import random
import re
import sqlite3
from collections import Counter
from datetime import datetime

from .browser import SafetyStop, assert_safe_page, dismiss_cookies, open_url
from .config import project_path
from .db import count_actions, log_action
from .util import now_iso, print_table, random_pause, today_start_iso

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


JOB_HELPER_JS = r"""
(data) => {
  const old = document.getElementById('la-job-panel');
  if (old) old.remove();

  const copyValue = async (value, button) => {
    const original = button.textContent;
    try {
      await navigator.clipboard.writeText(value);
    } catch (err) {
      const area = document.createElement('textarea');
      area.value = value;
      area.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    }
    button.textContent = 'Copied';
    setTimeout(() => { button.textContent = original; }, 1400);
  };

  const buildRows = () => {
    const wrap = document.createElement('div');
    for (const field of data.fields) {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:6px;margin:4px 0';

      const label = document.createElement('div');
      label.textContent = field.label;
      label.style.cssText =
        'flex:0 0 76px;color:#9ca3af;font-size:10px;text-transform:uppercase;letter-spacing:.04em';

      const value = document.createElement('div');
      value.textContent = field.value || 'not set';
      value.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' +
        (field.value ? 'color:#f3f4f6' : 'color:#6b7280;font-style:italic');

      row.append(label, value);

      if (field.value) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = 'Copy';
        button.style.cssText =
          'background:#1f2937;color:#e5e7eb;border:1px solid #374151;border-radius:5px;' +
          'padding:3px 7px;font-size:11px;cursor:pointer';
        button.onclick = (event) => {
          event.preventDefault();
          event.stopPropagation();
          copyValue(field.value, button);
        };
        row.appendChild(button);
      }
      wrap.appendChild(row);
    }
    return wrap;
  };

  const panel = document.createElement('div');
  panel.id = 'la-job-panel';
  panel.style.cssText = [
    'position:fixed', 'left:18px', 'bottom:18px', 'z-index:2147483647',
    'width:360px', 'max-width:calc(100vw - 36px)',
    'background:#111827', 'color:#f9fafb', 'border:1px solid #374151',
    'border-radius:10px', 'padding:14px', 'box-shadow:0 12px 32px rgba(0,0,0,.35)',
    'font:13px/1.45 system-ui,Segoe UI,Arial,sans-serif'
  ].join(';');

  const header = document.createElement('div');
  header.textContent = data.title || 'Application details';
  header.style.cssText = 'font-weight:700;font-size:13px;margin-bottom:6px';
  panel.appendChild(header);

  const hint = document.createElement('div');
  hint.textContent = 'Copy a value, then paste it into the form.';
  hint.style.cssText = 'color:#9ca3af;font-size:11px;margin-bottom:6px';
  panel.appendChild(hint);

  panel.appendChild(buildRows());
  document.body.appendChild(panel);

  const injectIntoDialog = () => {
    document.querySelectorAll("div[role='dialog']").forEach((dialog) => {
      if (dialog.querySelector('.la-job-helper')) return;
      if (!dialog.querySelector('input, textarea, select, form')) return;

      const details = document.createElement('details');
      details.className = 'la-job-helper';
      details.style.cssText =
        'margin:8px 0;border:1px solid #374151;border-radius:8px;padding:8px 10px;' +
        'background:#111827;color:#e5e7eb;font:12px system-ui,Segoe UI,Arial,sans-serif';

      const summary = document.createElement('summary');
      summary.textContent = 'Application details - click to open';
      summary.style.cssText = 'cursor:pointer;font-weight:600';
      details.appendChild(summary);
      details.appendChild(buildRows());
      dialog.prepend(details);
    });
  };

  const observer = new MutationObserver(injectIntoDialog);
  observer.observe(document.body, { childList: true, subtree: true });
  injectIntoDialog();
}
"""

PROFILE_FIELDS = (
    ("Full name", "full_name"),
    ("Email", "email"),
    ("Phone", "phone"),
    ("Location", "location"),
    ("LinkedIn", "linkedin"),
    ("GitHub", "github"),
    ("Portfolio", "portfolio"),
)

DESCRIPTION_SELECTORS = (
    "div.description__text",
    "div[class*='jobs-description__content']",
    "div[class*='jobs-description-content']",
    "section[class*='jobs-description']",
    "article[class*='jobs-description']",
)

STOPWORDS = {
    "and", "the", "for", "with", "you", "your", "our", "are", "will", "have", "has",
    "that", "this", "from", "they", "their", "them", "not", "but", "can", "all",
    "any", "who", "what", "when", "where", "how", "why", "job", "role", "work",
    "working", "team", "teams", "company", "candidate", "candidates", "experience",
    "years", "year", "skills", "skill", "ability", "able", "strong", "good", "great",
    "must", "should", "would", "could", "about", "into", "more", "most", "other",
    "than", "then", "there", "these", "those", "was", "were", "been", "being",
    "its", "it's", "as", "at", "by", "in", "on", "of", "or", "to", "is", "be",
    "we", "us", "an", "a", "if", "up", "out", "new", "including", "include",
    "well", "also", "across", "within", "using", "use", "used", "help", "join",
    "looking", "seeking", "ideal", "plus", "preferred", "required", "requirements",
    "responsibilities", "description", "benefits", "salary", "apply", "applicants",
    "opportunity", "position", "full", "time", "part", "remote", "hybrid", "onsite",
}


def _fill(text: str, values: dict) -> str:
    """Replace {placeholders} while keeping line breaks intact."""
    def replace(match: re.Match) -> str:
        return str(values.get(match.group(1), "") or "")

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", replace, text or "")


def _profile_fields(cfg: dict) -> list[dict]:
    profile = cfg.get("profile", {}) or {}
    return [
        {"label": label, "value": str(profile.get(key, "") or "")}
        for label, key in PROFILE_FIELDS
    ]


def extract_description(page) -> str:
    text = _text(page, DESCRIPTION_SELECTORS)
    if text:
        return text

    try:
        body = page.locator("main").inner_text(timeout=6000)
    except Exception:
        return ""

    match = re.search(
        r"About the job(.+?)(?:About the company|Set alert|Show more|Similar jobs|$)",
        body,
        flags=re.S | re.I,
    )
    if match:
        return " ".join(match.group(1).split())
    return ""


def keywords_from(text: str, limit: int = 12) -> list[str]:
    tokens = [
        token.strip(".-+")
        for token in re.findall(r"[A-Za-z][A-Za-z+#.\-]{1,}", text or "")
        if token.strip(".-+")
    ]
    words = [token.lower() for token in tokens if len(token) >= 3 and token.lower() not in STOPWORDS]

    unigrams = Counter(words)
    bigrams = Counter(
        f"{first} {second}"
        for first, second in zip(words, words[1:])
        if first not in STOPWORDS and second not in STOPWORDS
    )

    picked: list[str] = []
    for phrase, count in bigrams.most_common(limit):
        if count >= 2 and len(phrase) <= 40:
            picked.append(phrase)
        if len(picked) >= limit // 2:
            break

    for word, _count in unigrams.most_common(limit * 2):
        if any(word in phrase.split() for phrase in picked):
            continue
        picked.append(word)
        if len(picked) >= limit:
            break
    return picked[:limit]


def build_prep_pack(cfg: dict, job, description: str = "") -> str:
    profile = cfg.get("profile", {}) or {}
    title = job["title"] or "(untitled role)"
    company = job["company"] or "(company)"

    keywords = keywords_from(description, 12)
    summary = str(profile.get("summary") or "").strip()
    headline = str(profile.get("headline") or "").strip()
    if summary:
        intro = summary
    elif headline:
        intro = f"My background is in {headline}."
    else:
        intro = "My background and recent projects line up with the skills this role asks for."

    phone = str(profile.get("phone") or "").strip()
    linkedin = str(profile.get("linkedin") or "").strip()
    values = {
        "title": title,
        "company": company,
        "full_name": str(profile.get("full_name") or ""),
        "email": str(profile.get("email") or ""),
        "phone_line": f" | {phone}" if phone else "",
        "linkedin_line": f"\n{linkedin}" if linkedin else "",
        "intro": intro,
    }
    template = cfg["templates"].get("cover_letter", "")
    letter = _fill(template, values).strip()

    lines = [
        f"# Application pack - {title} @ {company}",
        "",
        f"- Location: {job['location'] or '-'}",
        f"- Posted: {job['posted'] or '-'}",
        f"- Status: {job['status']}",
        f"- URL: {job['url']}",
        f"- Collected: {job['collected_at']}",
        "",
        "## Keywords from the posting",
        ", ".join(keywords) if keywords else "_run `jobs prep --fetch` to pull the posting text_",
        "",
        "## Cover letter draft",
        "",
        "```text",
        letter,
        "```",
        "",
        "## Answers to prepare",
        f"- Notice period: {profile.get('notice_period') or '(not set - edit config.yaml)'}",
        f"- Expected salary: {profile.get('expected_salary') or '(not set - edit config.yaml)'}",
        f"- Work authorization: {profile.get('work_authorization') or '(not set - edit config.yaml)'}",
        f"- Relocation: {profile.get('relocation') or '(not set - edit config.yaml)'}",
        "",
        "## Posting excerpt",
        (description[:900] + "...") if len(description) > 900 else (description or "-"),
        "",
        "## Before you submit",
        "- [ ] Resume mirrors the top three keywords above",
        "- [ ] Replaced the placeholder paragraph in the cover letter",
        "- [ ] Answered the screening questions in the form",
        "- [ ] Logged the application",
        "",
    ]
    return "\n".join(lines)


def prep_jobs(
    con: sqlite3.Connection,
    cfg: dict,
    page,
    limit: int,
    status: str = "",
    job_id: str = "",
    fetch: bool = False,
) -> list:
    if job_id:
        rows = con.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchall()
    else:
        query = "SELECT * FROM jobs"
        params: list = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC, job_id DESC LIMIT ?"
        params.append(limit)
        rows = con.execute(query, tuple(params)).fetchall()

    if not rows:
        print("No jobs matched. Collect some first:  jobs collect --url \"<search URL>\"")
        return []

    folder = project_path(cfg["storage"]["exports"]) / "prep"
    folder.mkdir(parents=True, exist_ok=True)

    paths = []
    for row in rows:
        description = ""
        if fetch and page is not None:
            open_url(page, row["url"], 2.5, 4.5)
            description = extract_description(page)
            if not description:
                print(f"  [prep] no description found for {row['job_id']}")
            random_pause(cfg["jobs"], label="prep")

        text = build_prep_pack(cfg, row, description)
        slug = re.sub(r"[^a-z0-9]+", "-", f"{row['company']}-{row['title']}".lower()).strip("-")
        slug = slug[:60] or str(row["job_id"])
        path = folder / f"{row['job_id']}_{slug}.md"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
        print(f"  [prep] {row['title']} @ {row['company']} -> {path.name}")

    return paths


def parse_selection(choice: str, total: int) -> list[int]:
    choice = (choice or "").strip().lower()
    if choice in ("", "none", "n", "no", "q"):
        return []
    if choice in ("all", "a", "yes", "y"):
        return list(range(1, total + 1))

    picked: set[int] = set()
    for part in re.split(r"[,\s]+", choice):
        if part.isdigit():
            value = int(part)
            if 1 <= value <= total:
                picked.add(value)
    return sorted(picked)


def run_job_batch(
    con: sqlite3.Connection,
    cfg: dict,
    page,
    limit: int,
    status: str = "shortlisted",
    keep_open: bool = False,
) -> dict | None:
    rows = con.execute(
        "SELECT * FROM jobs WHERE status = ? ORDER BY updated_at DESC, job_id DESC LIMIT ?",
        (status, limit),
    ).fetchall()
    if not rows:
        print(f"No jobs with status '{status}'.")
        print("Shortlist a few first:  .\\run.cmd jobs status <job_id> shortlisted")
        return None

    cap = int(cfg["jobs"].get("apply_daily_cap", 10))
    used = count_actions(con, "apply", "sent", today_start_iso())
    if used + len(rows) > cap:
        print(
            f"Warning: {len(rows)} applications would put you at {used + len(rows)} today "
            f"(cap {cap}). Manual applications still count once logged."
        )

    fields = _profile_fields(cfg)
    missing = [field["label"] for field in fields if not field["value"]]
    if missing:
        print(f"Note: not set in config.yaml -> {', '.join(missing)}")

    batch = []
    for index, row in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] opening {row['title']} @ {row['company']}")
        tab = page.context.new_page()
        try:
            open_url(tab, row["url"], 2.5, 4.5)
            tab.evaluate(
                JOB_HELPER_JS,
                {
                    "title": f"{index}. {row['title']} @ {row['company']}",
                    "fields": fields,
                },
            )
        except SafetyStop:
            tab.close()
            raise
        except Exception as exc:  # noqa: BLE001 - skip a broken posting, keep the batch
            print(f"  could not open tab: {exc}")
            tab.close()
            continue

        batch.append({"row": row, "tab": tab})
        if index < len(rows):
            page.wait_for_timeout(int(random.uniform(2500, 5000)))

    if not batch:
        print("No tabs opened.")
        return None

    print()
    print(f"{len(batch)} job tabs are open. Apply using the panel on each page.")
    answer = input("Press Enter here when done, or type q to skip: ").strip().lower()
    if answer == "q":
        print("Skipped. Tabs left open, statuses unchanged.")
        return None

    print()
    for index, item in enumerate(batch, start=1):
        row = item["row"]
        print(f"  {index}. {row['title']} @ {row['company']}")

    choice = input(
        "Which did you apply to? all / none / numbers (e.g. 1 3 5): "
    )
    applied = set(parse_selection(choice, len(batch)))

    summary = {"applied": 0, "skipped": 0}
    for index, item in enumerate(batch, start=1):
        row = item["row"]
        tab = item["tab"]
        if index in applied:
            con.execute(
                "UPDATE jobs SET status = 'applied', updated_at = ? WHERE job_id = ?",
                (now_iso(), row["job_id"]),
            )
            con.commit()
            log_action(con, "apply", row["url"], "sent", "manual batch")
            summary["applied"] += 1
            print(f"[{index}] applied: {row['title']} @ {row['company']}")
        else:
            summary["skipped"] += 1
            print(f"[{index}] skipped: {row['title']} @ {row['company']}")

        if not keep_open:
            try:
                tab.close()
            except Exception:
                pass

    return summary
