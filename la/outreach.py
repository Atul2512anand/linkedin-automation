from __future__ import annotations

import csv
import json
import random
import re
import sqlite3
from datetime import datetime
from urllib.parse import urlencode

from .browser import SafetyStop, open_url, save_screenshot
from .config import project_path
from .db import count_actions, log_action
from .util import (
    now_iso,
    print_table,
    safe_format,
    today_start_iso,
    week_start_iso,
)

CONTACT_STATUSES = {
    "queued",
    "sent",
    "pending",
    "connected",
    "accepted",
    "replied",
    "messaged",
    "skipped",
    "failed",
}

BATCH_OVERLAY_JS = """
(data) => {
  const existing = document.getElementById('la-outreach-panel');
  if (existing) existing.remove();

  const panel = document.createElement('div');
  panel.id = 'la-outreach-panel';
  panel.style.cssText = [
    'position:fixed', 'left:18px', 'bottom:18px', 'z-index:2147483647',
    'width:340px', 'max-width:calc(100vw - 36px)',
    'background:#111827', 'color:#f9fafb', 'border:1px solid #374151',
    'border-radius:10px', 'padding:14px', 'box-shadow:0 12px 32px rgba(0,0,0,.35)',
    'font:13px/1.45 system-ui,Segoe UI,Arial,sans-serif'
  ].join(';');

  const header = document.createElement('div');
  header.textContent = data.label || 'Outreach';
  header.style.cssText = 'font-weight:700;font-size:13px;margin:0 26px 4px 0';

  const subtitle = document.createElement('div');
  subtitle.textContent = data.subtitle || '';
  subtitle.style.cssText = 'color:#9ca3af;font-size:12px;margin-bottom:8px';

  const note = document.createElement('div');
  note.textContent = data.note || '';
  note.style.cssText = 'color:#e5e7eb;margin-bottom:10px;white-space:pre-wrap';

  const copy = document.createElement('button');
  copy.textContent = 'Copy note';
  copy.style.cssText = [
    'background:#2563eb', 'color:#fff', 'border:0', 'border-radius:6px',
    'padding:7px 12px', 'font-weight:600', 'cursor:pointer', 'margin-right:6px'
  ].join(';');
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(data.note || '');
    } catch (err) {
      const area = document.createElement('textarea');
      area.value = data.note || '';
      area.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    }
    copy.textContent = 'Copied';
    setTimeout(() => { copy.textContent = 'Copy note'; }, 1600);
  };

  const hide = document.createElement('button');
  hide.textContent = 'Hide';
  hide.style.cssText = [
    'background:transparent', 'color:#9ca3af', 'border:1px solid #374151',
    'border-radius:6px', 'padding:7px 10px', 'cursor:pointer'
  ].join(';');
  hide.onclick = () => panel.remove();

  panel.appendChild(header);
  panel.appendChild(subtitle);
  panel.appendChild(note);
  panel.appendChild(copy);
  panel.appendChild(hide);
  document.body.appendChild(panel);

  const NOTE = data.note || '';
  const injectFillButton = () => {
    document.querySelectorAll("div[role='dialog']").forEach((dialog) => {
      if (dialog.querySelector('.la-fill-wrap')) return;
      const textarea = dialog.querySelector('textarea');
      if (!textarea || !textarea.parentElement) return;

      const wrap = document.createElement('div');
      wrap.className = 'la-fill-wrap';
      wrap.style.cssText = [
        'display:flex', 'gap:8px', 'align-items:center',
        'margin:8px 0', 'font:12px system-ui,Segoe UI,Arial,sans-serif'
      ].join(';');

      const fill = document.createElement('button');
      fill.type = 'button';
      fill.textContent = 'Fill note';
      fill.style.cssText = [
        'background:#0a66c2', 'color:#fff', 'border:0', 'border-radius:6px',
        'padding:6px 10px', 'font-weight:600', 'cursor:pointer'
      ].join(';');
      fill.onclick = (event) => {
        event.preventDefault();
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype, 'value'
        ).set;
        setter.call(textarea, NOTE);
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
        textarea.dispatchEvent(new Event('change', { bubbles: true }));
        textarea.focus();
        fill.textContent = 'Filled';
        setTimeout(() => { fill.textContent = 'Fill note'; }, 1500);
      };

      const hint = document.createElement('span');
      hint.textContent = 'Local helper - review before sending';
      hint.style.cssText = 'color:#6b7280';

      wrap.appendChild(fill);
      wrap.appendChild(hint);
      textarea.parentElement.insertBefore(wrap, textarea);
    });
  };

  const observer = new MutationObserver(injectFillButton);
  observer.observe(document.body, { childList: true, subtree: true });
  injectFillButton();
}
"""


def normalize_profile_url(value: str) -> str:
    url = (value or "").strip().split("?")[0].rstrip("/")
    if not url:
        return ""
    if not url.startswith("http"):
        if url.startswith("linkedin.com") or url.startswith("www.linkedin.com"):
            url = "https://" + url
        else:
            url = "https://www.linkedin.com/" + url.lstrip("/")
    if "/in/" not in url:
        return ""
    return url


def import_contacts(con: sqlite3.Connection, csv_path: str) -> tuple[int, int]:
    imported = 0
    skipped = 0
    timestamp = now_iso()

    with open(csv_path, "r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            row = {
                str(key or "").strip().lower(): str(value or "").strip()
                for key, value in raw.items()
            }
            url = normalize_profile_url(row.get("profile_url", ""))
            if not url:
                skipped += 1
                continue

            name = row.get("name", "")
            first_name = row.get("first_name", "") or (name.split()[0] if name else "")
            cursor = con.execute(
                """
                INSERT OR IGNORE INTO contacts
                    (profile_url, name, first_name, company, role, note, status,
                     last_error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'queued', '', ?, ?)
                """,
                (
                    url,
                    name,
                    first_name,
                    row.get("company", ""),
                    row.get("role", ""),
                    row.get("note", ""),
                    timestamp,
                    timestamp,
                ),
            )
            if cursor.rowcount:
                imported += 1
            else:
                skipped += 1

    con.commit()
    return imported, skipped


def _first_text(scope, selectors) -> str:
    for selector in selectors:
        try:
            locator = scope.locator(selector)
            if locator.count():
                text = " ".join(locator.first.inner_text(timeout=2000).split())
                if text:
                    return text
        except Exception:
            continue
    return ""


def _split_headline(headline: str) -> tuple[str, str]:
    text = re.sub(r"\s*[•·]\s*(1st|2nd|3rd).*$", "", headline or "", flags=re.I).strip()
    match = re.match(r"^(.*)\s+at\s+(.+)$", text, flags=re.I)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text, ""


LOCATION_GEO = {
    "japan": "101355337",
    "india": "102713980",
    "united states": "103644278",
    "usa": "103644278",
    "united kingdom": "101165590",
    "uk": "101165590",
    "singapore": "102454443",
    "australia": "101452733",
    "canada": "101174742",
    "germany": "101282230",
}


def build_people_search_url(query: str, location: str = "", geo: str = "") -> str:
    query = (query or "").strip()
    if not query:
        raise ValueError("Provide --query with search keywords, or pass a full --url.")

    params = {"keywords": query, "origin": "GLOBAL_SEARCH_HEADER"}
    geo_id = (geo or "").strip()
    if not geo_id and location:
        key = location.strip().lower()
        if key not in LOCATION_GEO:
            raise ValueError(
                f"Unknown location '{location}'. Use --geo <LinkedIn geo ID> or --url."
            )
        geo_id = LOCATION_GEO[key]
    if geo_id:
        params["geoUrn"] = json.dumps([geo_id])

    return "https://www.linkedin.com/search/results/people/?" + urlencode(params)


def extract_contact_cards(page, found: dict, limit: int) -> None:
    cards = page.locator("main div[role='listitem']")
    if cards.count() == 0:
        cards = page.locator("div[role='listitem']")
    if cards.count() == 0:
        cards = page.locator("li.reusable-search__result-container")
    if cards.count() == 0:
        cards = page.locator("div.entity-result")

    count = cards.count()
    for index in range(min(count, max(limit * 3, 30))):
        try:
            card = cards.nth(index)

            # New LinkedIn markup only offers Connect on people we can invite.
            if card.get_by_text("Connect", exact=True).count() == 0:
                continue

            link = card.locator("p a[href*='/in/']").first
            if not link.count():
                link = card.locator("a[href*='/in/']").first
            if not link.count():
                continue

            url = normalize_profile_url(link.get_attribute("href") or "")
            if not url or url in found:
                continue

            name = " ".join(link.inner_text(timeout=2000).split())
            name = re.sub(r"^View\s+", "", name)
            name = re.sub(r"'s profile.*$", "", name, flags=re.I)
            name = re.sub(r"\s*[•·]\s*(1st|2nd|3rd).*$", "", name, flags=re.I).strip()

            headline = ""
            try:
                text_block = link.locator("xpath=..").locator("xpath=..")
                paragraphs = text_block.locator(":scope > div > p")
                if paragraphs.count() > 0:
                    headline = " ".join(paragraphs.nth(0).inner_text(timeout=2000).split())
            except Exception:
                headline = ""

            if not headline:
                headline = _first_text(
                    card, (".entity-result__primary-subtitle", ".entity-result__summary")
                )

            role, company = _split_headline(headline)

            current = re.search(
                r"Current:\s*([^\n]+?)\s+at\s+([^\n]+)", card.inner_text(timeout=2000)
            )
            if current:
                if not role:
                    role = current.group(1).strip()
                if not company:
                    company = current.group(2).strip()

            found[url] = {
                "profile_url": url,
                "name": name,
                "first_name": name.split()[0] if name else "",
                "company": company,
                "role": role or headline,
            }
            if len(found) >= limit:
                break
        except Exception:
            continue


def discover_contacts(
    con: sqlite3.Connection,
    cfg: dict,
    page,
    url: str,
    limit: int,
) -> tuple[int, int]:
    open_url(page, url, 3.0, 5.0)
    found: dict[str, dict] = {}
    rounds = max(3, min(10, limit // 5 + 3))

    for _ in range(rounds):
        extract_contact_cards(page, found, limit)
        print(f"  [discover] {len(found)} profiles seen")
        if len(found) >= limit:
            break
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(int(random.uniform(2000, 4000)))

    if not found:
        print(f"No profiles found. Screenshot: {save_screenshot(page, cfg, 'discover_empty')}")
        return 0, 0

    timestamp = now_iso()
    added = 0
    for item in list(found.values())[:limit]:
        cursor = con.execute(
            """
            INSERT OR IGNORE INTO contacts
                (profile_url, name, first_name, company, role, note, status,
                 last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, '', 'queued', '', ?, ?)
            """,
            (
                item["profile_url"],
                item["name"],
                item["first_name"],
                item["company"],
                item["role"],
                timestamp,
                timestamp,
            ),
        )
        added += cursor.rowcount
    con.commit()
    return added, len(found)


def _fallback_note(cfg: dict, contact) -> str:
    values = {
        "first_name": contact["first_name"] or "there",
        "name": contact["name"] or "",
        "company": contact["company"] or "",
        "role": contact["role"] or "",
    }
    if contact["role"] and contact["company"]:
        template = cfg["templates"]["connection_note"]
    elif contact["company"]:
        template = "Hi {first_name}, I'd value connecting and learning about opportunities at {company}. Thanks!"
    else:
        template = "Hi {first_name}, I'd value connecting and learning from your experience. Thanks!"
    return safe_format(template, values)


def resolve_note(cfg: dict, contact, follow_up: bool = False) -> str:
    if contact["note"]:
        note = contact["note"]
    elif follow_up:
        note = safe_format(
            cfg["templates"]["follow_up"],
            {
                "first_name": contact["first_name"] or "there",
                "company": contact["company"] or "your team",
                "role": contact["role"] or "open",
            },
        )
    else:
        note = _fallback_note(cfg, contact)

    limit = int(cfg["outreach"].get("note_max_chars", 200))
    note = " ".join(note.split())
    if len(note) > limit:
        note = note[:limit].rsplit(" ", 1)[0]
    return note


def _top_card(page):
    for selector in ("div[class*='pv-top-card']", "section.artdeco-card", "main"):
        try:
            locator = page.locator(selector)
            if locator.count():
                return locator.first
        except Exception:
            continue
    return page.locator("body")


def _control_present(page, word: str) -> bool:
    """True when a clickable control (button, link, or role=button) matches the word.

    LinkedIn now renders Connect / Pending / Message as links or divs rather than
    buttons, and Pending carries the real label in aria-label.
    """
    try:
        return bool(
            page.evaluate(
                r"""
                (word) => {
                  const exact = new RegExp('^' + word + '$', 'i');
                  const prefix = new RegExp('^' + word + '[,\\s]', 'i');
                  const nodes = document.querySelectorAll("button, a, [role='button']");
                  for (const el of nodes) {
                    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
                    const aria = (el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
                    if (exact.test(text) || prefix.test(text) || prefix.test(aria)) {
                      return true;
                    }
                  }
                  return false;
                }
                """,
                word,
            )
        )
    except Exception:
        return False


def profile_state(page) -> str:
    top = _top_card(page)
    try:
        text = top.inner_text(timeout=5000)
    except Exception:
        text = ""
    lowered = text.lower()

    if _control_present(page, "Pending"):
        return "pending"
    if _control_present(page, "Connect"):
        return "connect"
    if _control_present(page, "Message"):
        return "message"
    if re.search(r"\bpending\b", lowered):
        return "pending"
    return "unknown"


def _click_connect(page) -> bool:
    top = _top_card(page)
    button = top.get_by_role("button", name=re.compile(r"^\s*Connect\s*$", re.I))
    if not button.count():
        button = top.get_by_role("button", name=re.compile(r"\bConnect\b", re.I))
    if button.count():
        button.first.click()
        page.wait_for_timeout(1200)
        return True

    more = top.get_by_role("button", name=re.compile(r"More actions", re.I))
    if more.count():
        more.first.click()
        page.wait_for_timeout(800)
        item = page.get_by_role("menuitem", name=re.compile(r"\bConnect\b", re.I))
        if item.count():
            item.first.click()
            page.wait_for_timeout(1200)
            return True
    return False


def _send_connect_note(page, cfg: dict, note: str) -> str:
    dialog = page.locator("div[role='dialog']")
    if not dialog.count():
        return "no-dialog"

    panel = dialog.last
    if note and cfg["outreach"].get("send_connection_note", True):
        add_note = panel.get_by_role("button", name=re.compile(r"Add a note", re.I))
        if add_note.count():
            add_note.first.click()
            page.wait_for_timeout(600)

        textarea = panel.locator("textarea")
        if textarea.count():
            textarea.first.fill(note[:300])
            send = panel.get_by_role("button", name=re.compile(r"^\s*Send\s*$", re.I))
            if not send.count():
                send = panel.locator("button[type='submit']")
            if send.count():
                send.first.click()
                page.wait_for_timeout(1600)
                return "sent"
            return "no-send-button"

    send = panel.get_by_role(
        "button", name=re.compile(r"Send without a note|^\s*Send\s*$", re.I)
    )
    if not send.count():
        send = panel.locator("button[type='submit']")
    if send.count():
        send.first.click()
        page.wait_for_timeout(1600)
        return "sent"
    return "no-send-button"


def _page_error(page) -> str:
    try:
        alerts = page.locator(
            "div[role='alert'], .artdeco-toast-item, .artdeco-inline-feedback--error"
        )
        if not alerts.count():
            return ""
        text = " ".join(alerts.all_inner_texts()).lower()
    except Exception:
        return ""
    for phrase in (
        "something went wrong",
        "couldn't send",
        "could not send",
        "try again later",
        "rate limit",
    ):
        if phrase in text:
            return phrase
    return ""


def connect_to(page, cfg: dict, contact) -> tuple[str, str]:
    open_url(page, contact["profile_url"], 2.5, 4.0)
    state = profile_state(page)
    if state == "pending":
        return "pending", "invitation already pending"
    if state == "message":
        return "connected", "already connected"
    if state != "connect":
        return "failed", "Connect/Message button not found"

    note = resolve_note(cfg, contact)
    print(f"  note: {note}")
    if not _click_connect(page):
        return "failed", "could not click Connect"

    dialog_result = _send_connect_note(page, cfg, note)
    if dialog_result == "no-dialog":
        page.wait_for_timeout(1200)
        if profile_state(page) == "pending":
            return "sent", "sent without note dialog"
        return "failed", "connection dialog did not appear"
    if dialog_result != "sent":
        return "failed", dialog_result

    error = _page_error(page)
    if error:
        return "failed", f"LinkedIn error: {error}"
    return "sent", "note sent" if note else "sent"


def send_followup(page, cfg: dict, contact) -> tuple[str, str]:
    open_url(page, contact["profile_url"], 2.5, 4.0)
    state = profile_state(page)
    if state != "message":
        return "skipped", f"profile state is {state}"

    top = _top_card(page)
    button = top.get_by_role("button", name=re.compile(r"\bMessage\b", re.I))
    if not button.count():
        button = page.get_by_role("button", name=re.compile(r"\bMessage\b", re.I))
    if not button.count():
        return "failed", "Message button not found"

    button.first.click()
    page.wait_for_timeout(2200)

    box = page.locator(
        "div[contenteditable='true'][role='textbox'], "
        "div.msg-form__contenteditable, "
        "div[contenteditable='true']"
    ).first
    if not box.count():
        return "failed", "message composer not found"

    note = resolve_note(cfg, contact, follow_up=True)
    box.click()
    page.keyboard.insert_text(note[:1000])
    page.wait_for_timeout(600)

    send = page.locator(
        "button.msg-form__send-button, button[aria-label='Send'], "
        "button[type='submit']:has-text('Send')"
    )
    if not send.count():
        send = page.get_by_role("button", name=re.compile(r"^\s*Send\s*$", re.I))
    if not send.count():
        return "failed", "send button not found"

    send.first.click()
    page.wait_for_timeout(1500)

    error = _page_error(page)
    if error:
        return "failed", f"LinkedIn error: {error}"
    return "sent", "follow-up sent"


def preview_queue(con: sqlite3.Connection, cfg: dict, limit: int) -> None:
    rows = con.execute(
        "SELECT * FROM contacts WHERE status = 'queued' ORDER BY id LIMIT ?", (limit,)
    ).fetchall()
    if not rows:
        print("No queued contacts. Import a CSV with 'contacts import'.")
        return

    display = []
    for row in rows:
        display.append(
            {
                "id": row["id"],
                "name": row["name"] or "-",
                "company": row["company"] or "-",
                "role": row["role"] or "-",
                "note": resolve_note(cfg, row),
            }
        )
    print_table(display, ["id", "name", "company", "role", "note"], max_width=48)


def inspect_queue(
    con: sqlite3.Connection,
    cfg: dict,
    page,
    limit: int,
    apply: bool = False,
) -> None:
    rows = con.execute(
        "SELECT * FROM contacts WHERE status IN ('queued', 'failed') ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        print("No queued contacts to inspect.")
        return

    for row in rows:
        print(f"[{row['id']}] {row['name'] or row['profile_url']}")
        try:
            open_url(page, row["profile_url"], 2.5, 4.0)
            state = profile_state(page)
            print(f"  state: {state}")
            print(f"  note:  {resolve_note(cfg, row)}")
            if apply:
                if state == "pending":
                    _update_contact(con, row["id"], "sent")
                    log_action(con, "connect", row["profile_url"], "sent", "verified pending")
                    print("  -> marked sent")
                elif state == "message":
                    _update_contact(con, row["id"], "connected")
                    print("  -> marked connected")
        except SafetyStop as exc:
            print(f"  STOP: {exc}")
            break
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  error: {exc}")
        page.wait_for_timeout(int(random.uniform(3000, 6000)))


def _update_contact(con: sqlite3.Connection, contact_id: int, status: str, error: str = "") -> None:
    con.execute(
        "UPDATE contacts SET status = ?, last_error = ?, updated_at = ? WHERE id = ?",
        (status, error, now_iso(), contact_id),
    )
    con.commit()


def send_connections(
    con: sqlite3.Connection,
    cfg: dict,
    page,
    limit: int,
) -> dict:
    rows = con.execute(
        "SELECT * FROM contacts WHERE status = 'queued' ORDER BY id LIMIT ?", (limit,)
    ).fetchall()
    summary = {"sent": 0, "pending": 0, "connected": 0, "failed": 0}
    if not rows:
        print("No queued contacts.")
        return summary

    for index, row in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] {row['name'] or row['profile_url']}")
        try:
            status, detail = connect_to(page, cfg, row)
        except SafetyStop as exc:
            print(f"  STOP: {exc}")
            screenshot = save_screenshot(page, cfg, f"safety_stop_contact_{row['id']}")
            print(f"  screenshot: {screenshot}")
            break
        except Exception as exc:  # noqa: BLE001 - keep the queue moving on selector errors
            status, detail = "failed", str(exc)

        print(f"  -> {status}: {detail}")
        if status == "sent":
            summary["sent"] += 1
            _update_contact(con, row["id"], "sent")
            log_action(con, "connect", row["profile_url"], "sent", detail)
        elif status == "pending":
            summary["pending"] += 1
            _update_contact(con, row["id"], "pending", detail)
            log_action(con, "connect", row["profile_url"], "skipped", detail)
        elif status == "connected":
            summary["connected"] += 1
            _update_contact(con, row["id"], "connected", detail)
            log_action(con, "connect", row["profile_url"], "skipped", detail)
        else:
            summary["failed"] += 1
            _update_contact(con, row["id"], "failed", detail)
            log_action(con, "connect", row["profile_url"], "failed", detail)
            if status == "failed":
                screenshot = save_screenshot(page, cfg, f"contact_{row['id']}_failed")
                print(f"  screenshot: {screenshot}")

        if index < len(rows):
            wait_low = float(cfg["outreach"]["min_delay_seconds"])
            wait_high = float(cfg["outreach"]["max_delay_seconds"])
            seconds = random.uniform(wait_low, wait_high)
            print(f"  waiting {seconds:.0f}s before the next profile")
            page.wait_for_timeout(int(seconds * 1000))

    return summary


def send_followups(
    con: sqlite3.Connection,
    cfg: dict,
    page,
    limit: int,
) -> dict:
    rows = con.execute(
        """
        SELECT * FROM contacts
        WHERE status IN ('connected', 'accepted')
        ORDER BY id LIMIT ?
        """,
        (limit,),
    ).fetchall()
    summary = {"sent": 0, "skipped": 0, "failed": 0}
    if not rows:
        print("No connected contacts to message. Mark one first: outreach mark <id> accepted")
        return summary

    for index, row in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] {row['name'] or row['profile_url']}")
        try:
            status, detail = send_followup(page, cfg, row)
        except SafetyStop as exc:
            print(f"  STOP: {exc}")
            screenshot = save_screenshot(page, cfg, f"safety_stop_message_{row['id']}")
            print(f"  screenshot: {screenshot}")
            break
        except Exception as exc:  # noqa: BLE001
            status, detail = "failed", str(exc)

        print(f"  -> {status}: {detail}")
        if status == "sent":
            summary["sent"] += 1
            _update_contact(con, row["id"], "messaged")
            log_action(con, "message", row["profile_url"], "sent", detail)
        elif status == "skipped":
            summary["skipped"] += 1
            log_action(con, "message", row["profile_url"], "skipped", detail)
        else:
            summary["failed"] += 1
            _update_contact(con, row["id"], "failed", detail)
            log_action(con, "message", row["profile_url"], "failed", detail)
            screenshot = save_screenshot(page, cfg, f"message_{row['id']}_failed")
            print(f"  screenshot: {screenshot}")

        if index < len(rows):
            seconds = random.uniform(
                float(cfg["outreach"]["min_delay_seconds"]),
                float(cfg["outreach"]["max_delay_seconds"]),
            )
            print(f"  waiting {seconds:.0f}s before the next profile")
            page.wait_for_timeout(int(seconds * 1000))

    return summary


def run_batch(
    con: sqlite3.Connection,
    cfg: dict,
    page,
    limit: int,
    keep_open: bool = False,
) -> dict | None:
    rows = con.execute(
        "SELECT * FROM contacts WHERE status = 'queued' ORDER BY id LIMIT ?", (limit,)
    ).fetchall()
    if not rows:
        print("No queued contacts. Import a CSV or run 'contacts discover' first.")
        return None

    daily_left, _, daily_used, _ = remaining_allowance(con, cfg, "connect")
    if len(rows) > daily_left:
        print(
            f"Warning: opening {len(rows)} tabs, but only {daily_left} slots remain "
            f"under the daily cap ({daily_used} already sent). Manual sends still count."
        )

    batch = []
    for index, row in enumerate(rows, start=1):
        note = resolve_note(cfg, row)
        subtitle = " | ".join(part for part in (row["role"], row["company"]) if part)
        print(f"[{index}/{len(rows)}] opening {row['name'] or row['profile_url']}")

        tab = page.context.new_page()
        try:
            open_url(tab, row["profile_url"], 2.5, 4.0)
            tab.evaluate(
                BATCH_OVERLAY_JS,
                {
                    "label": f"{index}. {row['name'] or 'Contact'}",
                    "subtitle": subtitle,
                    "note": note,
                },
            )
        except SafetyStop:
            tab.close()
            raise
        except Exception as exc:  # noqa: BLE001 - skip a broken profile, keep the batch
            print(f"  could not open tab: {exc}")
            tab.close()
            continue

        batch.append({"row": row, "tab": tab, "note": note})
        if index < len(rows):
            page.wait_for_timeout(int(random.uniform(3000, 6000)))

    if not batch:
        print("No tabs opened.")
        return None

    folder = project_path(cfg["storage"]["exports"])
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sheet = folder / f"outreach_batch_{stamp}.md"
    lines = [f"# Outreach batch {stamp}", ""]
    for index, item in enumerate(batch, start=1):
        row = item["row"]
        heading = f"{index}. {row['name'] or 'Contact'}"
        if row["role"]:
            heading += f" - {row['role']}"
        if row["company"]:
            heading += f" @ {row['company']}"
        lines.extend([heading, f"   {row['profile_url']}", f"   Note: {item['note']}", ""])
    sheet.write_text("\n".join(lines), encoding="utf-8")

    print()
    print(f"{len(batch)} tabs are open. Batch sheet: {sheet}")
    print("In each tab: Connect -> Add a note -> Fill note (inside dialog) -> review -> Send.")
    answer = input("Press Enter here when done, or type q to skip review: ").strip().lower()
    if answer == "q":
        print("Skipped review. Tabs left open, statuses unchanged.")
        return None

    summary = {"sent": 0, "connected": 0, "not_sent": 0, "unknown": 0}
    for index, item in enumerate(batch, start=1):
        row = item["row"]
        tab = item["tab"]
        label = row["name"] or row["profile_url"]

        if tab.is_closed():
            print(f"[{index}] {label}: tab closed")
            summary["unknown"] += 1
            continue

        try:
            state = profile_state(tab)
        except SafetyStop:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[{index}] {label}: error {exc}")
            summary["unknown"] += 1
            continue

        if state == "pending":
            summary["sent"] += 1
            _update_contact(con, row["id"], "sent")
            log_action(con, "connect", row["profile_url"], "sent", "manual batch")
            print(f"[{index}] {label}: sent")
        elif state == "message":
            summary["connected"] += 1
            _update_contact(con, row["id"], "connected")
            print(f"[{index}] {label}: already connected")
        elif state == "connect":
            summary["not_sent"] += 1
            print(f"[{index}] {label}: still shows Connect (left queued)")
        else:
            summary["unknown"] += 1
            print(f"[{index}] {label}: unknown state (left queued)")

        if not keep_open:
            tab.close()

    return summary


def remaining_allowance(con: sqlite3.Connection, cfg: dict, kind: str) -> tuple[int, int, int, int]:
    daily_cap = int(cfg["outreach"]["daily_cap"])
    weekly_cap = int(cfg["outreach"]["weekly_cap"])
    daily_used = count_actions(con, kind, "sent", today_start_iso())
    weekly_used = count_actions(con, kind, "sent", week_start_iso())
    return (
        max(0, daily_cap - daily_used),
        max(0, weekly_cap - weekly_used),
        daily_used,
        weekly_used,
    )


def within_working_hours(cfg: dict) -> bool:
    start, end = cfg["outreach"].get("working_hours", [0, 24])
    hour = datetime.now().hour
    if int(start) == int(end):
        return True
    if int(start) < int(end):
        return int(start) <= hour < int(end)
    return hour >= int(start) or hour < int(end)


def mark_contact(con: sqlite3.Connection, contact_id: int, status: str) -> bool:
    if status not in CONTACT_STATUSES:
        print(f"Invalid status. Choose from: {', '.join(sorted(CONTACT_STATUSES))}")
        return False
    row = con.execute("SELECT id FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    if not row:
        print(f"No contact with id {contact_id}.")
        return False
    _update_contact(con, contact_id, status)
    return True
