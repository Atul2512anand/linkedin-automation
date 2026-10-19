from __future__ import annotations

import json
import re
from pathlib import Path

from .browser import open_url
from .config import CONFIG_PATH, load_config, project_path
from .util import now_iso

PROFILE_SECTIONS = (
    "About",
    "Experience",
    "Education",
    "Licenses & certifications",
    "Skills",
    "Languages",
    "Test scores",
    "Organizations",
    "Projects",
)


def _data_dir(cfg: dict) -> Path:
    return project_path(cfg["storage"]["database"]).parent / "profile"


def _scroll_workspace(page, steps: int = 10, delta: int = 1400) -> None:
    for _ in range(steps):
        page.evaluate(
            """
            (delta) => {
              const el = document.querySelector('main#workspace') || document.querySelector('main');
              if (el) el.scrollTop = el.scrollTop + delta;
            }
            """,
            delta,
        )
        page.wait_for_timeout(700)


def _section_text(page, heading: str) -> str:
    return page.evaluate(
        """
        (heading) => {
          const sec = Array.from(document.querySelectorAll('section'))
            .find(el => (el.innerText || '').trim().toLowerCase().startsWith(heading.toLowerCase()));
          return sec ? (sec.innerText || '').trim() : '';
        }
        """,
        heading,
    )


def _strip_heading(text: str, heading: str) -> str:
    lines = (text or "").splitlines()
    if lines and lines[0].strip().lower().startswith(heading.lower()):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _top_card(page) -> dict:
    data = page.evaluate(
        """
        () => {
          const h1 = document.querySelector('main h1') || document.querySelector('h1');
          if (h1) {
            const card = h1.closest('section') || h1.parentElement || h1;
            return {name: (h1.innerText || '').trim(), text: (card.innerText || '')};
          }
          const sections = Array.from(document.querySelectorAll('section'));
          const sec = sections.find(el => {
            const text = (el.innerText || '').trim();
            if (!text || text.startsWith('0 notifications')) return false;
            return text.split('\\n').map(s => s.trim()).filter(Boolean).length >= 3;
          });
          if (!sec) return null;
          const lines = (sec.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
          return {name: lines[0] || '', text: sec.innerText || ''};
        }
        """
    )
    if not data:
        return {"name": "", "headline": "", "location": ""}

    name = data["name"]
    lines = [line.strip() for line in data["text"].splitlines() if line.strip()]
    rest = [
        line
        for line in lines
        if line != name
        and not line.startswith("·")
        and line.lower() not in {"contact info", "open to", "add section", "enhance profile"}
    ]
    location = ""
    for line in rest[1:5]:
        if "," in line and not line.lower().startswith(("open to", "show ", "past ")):
            location = line
            break
    headline = next(
        (line for line in rest if line != location), rest[0] if rest else ""
    )
    return {"name": name, "headline": headline, "location": location}


def _about(page) -> str:
    page.evaluate(
        """
        () => {
          const sec = Array.from(document.querySelectorAll('section'))
            .find(el => (el.innerText || '').trim().toLowerCase().startsWith('about'));
          if (!sec) return;
          const more = Array.from(sec.querySelectorAll('button, a'))
            .find(el => /more/i.test((el.innerText || '').trim()));
          if (more) more.click();
        }
        """
    )
    page.wait_for_timeout(1000)
    return _strip_heading(_section_text(page, "About"), "About")


def _contact(page, base_url: str) -> dict:
    open_url(page, base_url.rstrip("/") + "/overlay/contact-info/", 2.0, 3.0)
    body = page.locator("body").inner_text(timeout=10000)
    match = re.search(
        r"Contact info\s*(.*?)(?:Refine your profile|Edit contact info|0 notifications)",
        body,
        flags=re.S | re.I,
    )
    text = (match.group(0) if match else body[:1500]).strip()
    email = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
    website = re.search(r"Website\s*\n+\s*(.+)", text)
    return {
        "raw": text,
        "email": email.group(0) if email else "",
        "website": website.group(1).strip() if website else "",
    }


SKILL_TAIL = re.compile(
    r"^(someone at|founder in|why am i|manage your|hide or|tell us|your feedback|"
    r"it[’']s annoying|i[’']ve seen|if you think|private to you|view$)",
    re.I,
)


def _skills_page(page, base_url: str) -> dict:
    open_url(page, base_url.rstrip("/") + "/details/skills/", 2.5, 4.0)
    for _ in range(10):
        page.evaluate(
            """
            () => {
              const el = document.querySelector('main#workspace') || document.querySelector('main');
              if (el) el.scrollTop = el.scrollHeight;
            }
            """
        )
        page.wait_for_timeout(600)
    page.wait_for_timeout(800)

    raw = page.locator("main").inner_text(timeout=15000).strip()
    names = page.evaluate(
        """
        () => {
          const out = [];
          for (const p of document.querySelectorAll('main p')) {
            const span = p.querySelector(':scope > span');
            if (!span) continue;
            if (p.closest("[role='list']")) continue;
            const text = (span.innerText || '').trim();
            if (text) out.push(text);
          }
          return out;
        }
        """
    )

    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        if SKILL_TAIL.match(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return {"skills": unique, "raw": raw}


def _detail_page(page, base_url: str, slug: str) -> str:
    open_url(page, base_url.rstrip("/") + f"/details/{slug}/", 2.5, 4.0)
    _scroll_workspace(page, steps=6)
    page.wait_for_timeout(600)
    return page.locator("main").inner_text(timeout=15000).strip()


def scan_profile(page, cfg: dict, url: str = "") -> dict:
    profile_cfg = cfg.get("profile", {}) or {}
    base_url = (url or profile_cfg.get("linkedin") or "https://www.linkedin.com/in/me/").split("?")[0].rstrip("/") + "/"

    open_url(page, base_url, 3.0, 5.0)
    resolved = page.url.split("?")[0].rstrip("/")
    if resolved and "/in/" in resolved:
        base_url = resolved + "/"
    _scroll_workspace(page, steps=10)
    page.wait_for_timeout(1000)

    top = _top_card(page)
    about = _about(page)
    sections = {
        heading: _strip_heading(_section_text(page, heading), heading)
        for heading in PROFILE_SECTIONS
    }
    raw_profile = page.locator("main").inner_text(timeout=15000).strip()

    contact = _contact(page, base_url)
    skills = _skills_page(page, base_url)
    certifications = _detail_page(page, base_url, "certifications")
    education = _detail_page(page, base_url, "education")

    data = {
        "scanned_at": now_iso(),
        "source_url": base_url,
        "name": top["name"],
        "headline": top["headline"],
        "location": top["location"],
        "about": about,
        "contact": contact,
        "sections": sections,
        "skills": skills["skills"],
        "skills_raw": skills["raw"],
        "certifications": certifications,
        "education_detail": education,
        "raw_profile_text": raw_profile,
    }
    return data


def _set_profile_config(profile: dict) -> Path:
    lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines()
    try:
        start = next(
            i for i, line in enumerate(lines)
            if re.match(r"^profile:\s*(#.*)?$", line)
        )
    except StopIteration:
        lines.extend(["", "profile:"])
        start = len(lines) - 1

    end = start + 1
    while end < len(lines) and (lines[end].startswith("  ") or not lines[end].strip()):
        end += 1

    values = {
        "full_name": profile.get("name", ""),
        "headline": profile.get("headline", ""),
        "location": profile.get("location", ""),
        "linkedin": profile.get("source_url", "").rstrip("/"),
        "email": profile.get("contact", {}).get("email", ""),
        "portfolio": profile.get("contact", {}).get("website", ""),
    }
    about = (profile.get("about") or "").strip()
    if about:
        first = re.split(r"\n\s*\n", about)[0].strip()
        values["summary"] = first[:600]

    for key, value in values.items():
        if not value:
            continue
        new_line = f"  {key}: {json.dumps(value, ensure_ascii=False)}"
        pattern = re.compile(rf"^  {re.escape(key)}:\s*")
        for index in range(start + 1, end):
            if pattern.match(lines[index]):
                lines[index] = new_line
                break

    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return CONFIG_PATH


FOOTER_MARKERS = ("\nAbout\n\nAccessibility", "\nProfile language\n", "\nSelect language\n", "\nQuestions?\n")


def _trim_footer(text: str) -> str:
    text = text or ""
    for marker in FOOTER_MARKERS:
        index = text.find(marker)
        if index != -1:
            text = text[:index]
    return text.strip()


def render_markdown(profile: dict) -> str:
    lines = [
        f"# {profile.get('name') or 'LinkedIn profile'}",
        "",
        f"- Headline: {profile.get('headline') or '-'}",
        f"- Location: {profile.get('location') or '-'}",
        f"- LinkedIn: {profile.get('source_url') or '-'}",
        f"- Scanned: {profile.get('scanned_at') or '-'}",
        "",
    ]

    contact = profile.get("contact", {}) or {}
    lines += ["## Contact", ""]
    if contact.get("email"):
        lines.append(f"- Email: {contact['email']}")
    if contact.get("website"):
        lines.append(f"- Website: {contact['website']}")
    if contact.get("raw"):
        lines += ["", "```text", _trim_footer(contact["raw"]), "```"]
    lines += [""]

    lines += ["## About", "", profile.get("about") or "-", ""]

    for heading in ("Experience", "Education", "Projects", "Languages", "Test scores", "Organizations"):
        text = (profile.get("sections", {}) or {}).get(heading)
        if text:
            lines += [f"## {heading}", "", _trim_footer(text), ""]

    skills = profile.get("skills") or []
    lines += ["## Skills", ""]
    lines += [f"- {skill}" for skill in skills] if skills else ["- (not parsed; see skills_raw in profile.json)"]
    lines += [""]

    certs = profile.get("certifications")
    if certs:
        lines += ["## Licenses & certifications", "", _trim_footer(certs), ""]

    education = profile.get("education_detail")
    if education:
        lines += ["## Education detail", "", _trim_footer(education), ""]

    return "\n".join(lines).strip() + "\n"


def save_profile(profile: dict, cfg: dict) -> tuple[Path, Path]:
    folder = _data_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / "profile.json"
    md_path = folder / "profile.md"
    json_path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    md_path.write_text(render_markdown(profile), encoding="utf-8")
    return json_path, md_path


def load_profile(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    path = _data_dir(cfg) / "profile.json"
    if not path.exists():
        return {}
    profile = json.loads(path.read_text(encoding="utf-8"))
    resume = load_resume(cfg)
    if resume:
        profile["resume"] = resume
    return profile


def load_resume(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    path = _data_dir(cfg) / "resume.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def update_config_from_profile(profile: dict) -> Path:
    return _set_profile_config(profile)
