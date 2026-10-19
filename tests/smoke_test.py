"""Small offline smoke tests. Run: .venv\\Scripts\\python tests\\smoke_test.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from la.config import load_config  # noqa: E402
from la.jobs import extract_cards  # noqa: E402
from la.outreach import (  # noqa: E402
    BATCH_OVERLAY_JS,
    build_people_search_url,
    extract_contact_cards,
    normalize_profile_url,
    resolve_note,
    within_working_hours,
)
from la.util import safe_format  # noqa: E402

FIXTURE = """
<ul>
  <li data-occludable-job-id="111">
    <a class="job-card-container__link" href="/jobs/view/111/?refId=abc">
      <strong>Data Scientist</strong>
    </a>
    <div class="artdeco-entity-lockup__subtitle">Acme</div>
    <div class="job-card-container__metadata-item">Bengaluru, Karnataka, India</div>
    <time>2 days ago</time>
  </li>
  <li data-occludable-job-id="222">
    <a class="job-card-list__title--link" href="/jobs/view/222/">
      Machine Learning Engineer
    </a>
    <div class="job-card-container__primary-description">Globex</div>
    <div class="artdeco-entity-lockup__caption">Remote</div>
  </li>
</ul>
"""


def test_url_normalization() -> None:
    assert normalize_profile_url("https://www.linkedin.com/in/foo/") == "https://www.linkedin.com/in/foo"
    assert normalize_profile_url("/in/foo?trk=x") == "https://www.linkedin.com/in/foo"
    assert normalize_profile_url("linkedin.com/in/foo") == "https://linkedin.com/in/foo"
    assert normalize_profile_url("https://www.linkedin.com/company/acme") == ""


def test_note_template() -> None:
    cfg = {
        "templates": {
            "connection_note": "Hi {first_name}, I'm exploring roles at {company}. Thanks!",
            "follow_up": "Hi {first_name}, following up about {role} at {company}.",
        },
        "outreach": {"note_max_chars": 200},
    }
    contact = {
        "note": "",
        "name": "Jane Doe",
        "first_name": "Jane",
        "company": "Acme",
        "role": "Data Scientist",
    }
    note = resolve_note(cfg, contact)
    assert "Jane" in note and "Acme" in note
    assert len(note) <= int(cfg["outreach"]["note_max_chars"])
    assert safe_format("Hi {first_name} {missing}", {"first_name": "Jane"}) == "Hi Jane"


def test_working_hours_always_on() -> None:
    cfg = load_config()
    cfg["outreach"]["working_hours"] = [0, 24]
    assert within_working_hours(cfg) is True


PEOPLE_FIXTURE = """
<main>
  <div role="listitem">
    <div>
      <div>
        <p><a href="/in/jane-doe/?trk=abc">Jane Doe</a><span> • 2nd</span></p>
        <div><p>Talent Acquisition / Recruiting</p></div>
        <div><p>Tokyo, Japan</p></div>
      </div>
      <div><div>Connect</div></div>
      <div><div><p><span>Current: Technical Recruiter at Acme</span></p></div></div>
    </div>
  </div>
  <div role="listitem">
    <div>
      <div>
        <p><a href="/in/john-smith/">John Smith</a><span> • 3rd</span></p>
        <div><p>Machine Learning Engineer at Globex</p></div>
        <div><p>Osaka, Japan</p></div>
      </div>
      <div><div>Connect</div></div>
    </div>
  </div>
  <div role="listitem">
    <div>
      <div>
        <p><a href="/in/follow-only/">Follow Only</a></p>
        <div><p>Data Scientist</p></div>
      </div>
      <div><div>Follow</div></div>
    </div>
  </div>
</main>
"""

LEGACY_FIXTURE = """
<ul>
  <li class="reusable-search__result-container">
    <div class="entity-result">
      <span class="entity-result__title-text"><a href="/in/legacy-jane/">Legacy Jane</a></span>
      <div class="entity-result__primary-subtitle">Recruiter at LegacyCo</div>
      <button>Connect</button>
    </div>
  </li>
</ul>
"""


def test_contact_extraction() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(PEOPLE_FIXTURE)
        found: dict = {}
        extract_contact_cards(page, found, 10)
        legacy: dict = {}
        page.set_content(LEGACY_FIXTURE)
        extract_contact_cards(page, legacy, 10)
        browser.close()

    assert len(found) == 2, found
    jane = found["https://www.linkedin.com/in/jane-doe"]
    assert jane["name"] == "Jane Doe"
    assert jane["role"] == "Talent Acquisition / Recruiting"
    assert jane["company"] == "Acme"
    john = found["https://www.linkedin.com/in/john-smith"]
    assert john["role"] == "Machine Learning Engineer"
    assert john["company"] == "Globex"

    assert len(legacy) == 1, legacy
    legacy_jane = legacy["https://www.linkedin.com/in/legacy-jane"]
    assert legacy_jane["name"] == "Legacy Jane"
    assert legacy_jane["role"] == "Recruiter"
    assert legacy_jane["company"] == "LegacyCo"


def test_people_search_url() -> None:
    url = build_people_search_url("technical recruiter", "japan", "")
    assert "keywords=technical+recruiter" in url
    assert "geoUrn=%5B%22101355337%22%5D" in url

    try:
        build_people_search_url("x", "atlantis", "")
        raise AssertionError("expected ValueError for unknown location")
    except ValueError:
        pass


def test_profile_state() -> None:
    from playwright.sync_api import sync_playwright

    from la.outreach import profile_state

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        page.set_content(
            "<main><a aria-label=\"Pending, click to withdraw invitation sent to Jane\">"
            "Pending</a><a>Message</a></main>"
        )
        assert profile_state(page) == "pending"

        page.set_content("<main><a>Connect</a><a>Message</a></main>")
        assert profile_state(page) == "connect"

        page.set_content("<main><a>Message</a></main>")
        assert profile_state(page) == "message"

        page.set_content("<main><a>Follow</a></main>")
        assert profile_state(page) == "unknown"
        browser.close()


def test_batch_overlay() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(
            "<html><body><h1>Profile</h1>"
            "<div role='dialog'><textarea></textarea></div></body></html>"
        )
        page.evaluate(
            BATCH_OVERLAY_JS,
            {"label": "1. Jane Doe", "subtitle": "Recruiter | Acme", "note": "Hi Jane"},
        )
        panel = page.locator("#la-outreach-panel")
        assert panel.count() == 1
        text = panel.inner_text()
        assert "Hi Jane" in text and "1. Jane Doe" in text

        fill = page.get_by_role("button", name="Fill note")
        assert fill.count() == 1
        fill.click()
        assert page.locator("textarea").input_value() == "Hi Jane"
        browser.close()


def test_job_extraction() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(FIXTURE)
        found: dict = {}
        extract_cards(page, found)
        browser.close()

    assert set(found) == {"111", "222"}, found
    assert found["111"]["title"] == "Data Scientist"
    assert found["111"]["company"] == "Acme"
    assert found["111"]["url"] == "https://www.linkedin.com/jobs/view/111/"
    assert found["222"]["title"] == "Machine Learning Engineer"


if __name__ == "__main__":
    test_url_normalization()
    test_note_template()
    test_working_hours_always_on()
    test_contact_extraction()
    test_people_search_url()
    test_profile_state()
    test_batch_overlay()
    test_job_extraction()
    print("All smoke tests passed.")
