from __future__ import annotations

import random
from contextlib import contextmanager
from datetime import datetime

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .config import load_config, project_path

SAFETY_URL_MARKERS = (
    "/checkpoint",
    "/authwall",
    "/login",
    "/uas/login",
    "/signup",
)

SAFETY_PHRASES = (
    "quick security check",
    "security verification",
    "unusual activity",
    "verify your identity",
    "verify it's you",
    "let's do a quick security check",
)


class SafetyStop(RuntimeError):
    """Raised when LinkedIn shows a login wall or security challenge."""


@contextmanager
def browser_session(cfg: dict | None = None, headless: bool | None = None):
    cfg = cfg or load_config()
    bcfg = cfg.get("browser", {})
    profile_dir = project_path(
        bcfg.get("profile_dir", "${LOCALAPPDATA}/linkedin-automation/browser-profile")
    )
    profile_dir.mkdir(parents=True, exist_ok=True)

    desired_headless = bcfg.get("headless", False) if headless is None else headless
    kwargs = {
        "user_data_dir": str(profile_dir),
        "headless": bool(desired_headless),
        "slow_mo": int(bcfg.get("slow_mo_ms", 60)),
        "locale": bcfg.get("locale", "en-US"),
        "viewport": {"width": 1440, "height": 900},
    }
    channel = (bcfg.get("channel") or "").strip()

    with sync_playwright() as playwright:
        if channel:
            kwargs["channel"] = channel
        try:
            context = playwright.chromium.launch_persistent_context(**kwargs)
        except PlaywrightError as first_error:
            if channel:
                print(f"[browser] Could not launch '{channel}': {first_error}")
                print("[browser] Retrying with bundled Chromium...")
                kwargs.pop("channel", None)
                try:
                    context = playwright.chromium.launch_persistent_context(**kwargs)
                except PlaywrightError as second_error:
                    raise SystemExit(
                        "Could not start a browser. Run:\n"
                        "  .venv\\Scripts\\python -m playwright install chromium"
                    ) from second_error
            else:
                raise SystemExit(
                    "Could not start bundled Chromium. Run:\n"
                    "  .venv\\Scripts\\python -m playwright install chromium"
                ) from first_error

        context.set_default_timeout(45000)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            yield page, context
        finally:
            context.close()


def is_logged_in(context) -> bool:
    try:
        cookies = context.cookies("https://www.linkedin.com")
    except PlaywrightError:
        return False
    return any(cookie.get("name") == "li_at" and cookie.get("value") for cookie in cookies)


def dismiss_cookies(page) -> None:
    for label in ("Accept all", "Accept", "Agree"):
        button = page.get_by_role("button", name=label, exact=True)
        try:
            if button.count() and button.first.is_visible():
                button.first.click(timeout=2000)
                page.wait_for_timeout(300)
                return
        except PlaywrightError:
            continue


def assert_safe_page(page, allow_login: bool = False) -> None:
    url = (page.url or "").lower()
    title = ""
    try:
        title = page.title().lower()
    except PlaywrightError:
        pass

    if not allow_login:
        for marker in SAFETY_URL_MARKERS:
            if marker in url:
                raise SafetyStop(
                    f"LinkedIn requires login or verification ({page.url})."
                )
        if "sign up" in title and "/in/" in url:
            raise SafetyStop(
                "LinkedIn served the logged-out auth wall. Run 'run.cmd login' first."
            )

    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=5000).lower()
    except PlaywrightError:
        pass

    for phrase in SAFETY_PHRASES:
        if phrase in body_text:
            raise SafetyStop(
                f"LinkedIn security check detected ('{phrase}'). Stopping automation."
            )


def open_url(page, url: str, min_wait: float = 2.0, max_wait: float = 3.5) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except PlaywrightError as exc:
        print(f"  [browser] navigation warning: {exc}")

    page.wait_for_timeout(int(random.uniform(min_wait, max_wait) * 1000))
    dismiss_cookies(page)
    assert_safe_page(page)


def save_screenshot(page, cfg: dict, name: str) -> str:
    folder = project_path(cfg["storage"]["screenshots"])
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    path = folder / f"{safe_name}_{datetime.now():%Y%m%d_%H%M%S}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        return str(path)
    except PlaywrightError as exc:
        return f"(screenshot failed: {exc})"
