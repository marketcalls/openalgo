#!/usr/bin/env python3
"""
TradeFinder JWT auto-refresh via Google-OAuth browser automation.

TradeFinder authenticates through Google SSO (NextAuth.js / api/auth/callback/google),
so there is no password to POST. Instead we keep a dedicated, persistent Chromium
profile that stays signed into Google (one-time manual login via tf_login_setup.py).
Refreshing the token is then just reloading tradefinder.in in that profile and reading
the `lt` token from localStorage — fully unattended, no password or 2FA each time.

Public API
----------
refresh_tf_jwt(headless=True) -> str | None     # force a fresh token via the browser
jwt_expiry_seconds(jwt) -> float                 # seconds left on a token's exp claim
ensure_fresh_jwt(min_seconds=1800) -> str | None # return file token, refresh if expiring

Only refresh runs a browser. The hot polling loop keeps using the plain `requests`
client with the cached file token, so there is no per-poll browser overhead.
"""

import base64
import json
import os
import time

# Reuse the strategy's canonical JWT file path so all components share one token.
_HERE          = os.path.dirname(os.path.abspath(__file__))
TF_JWT_FILE    = os.getenv("TF_JWT_FILE", os.path.join(_HERE, "tf_jwt.txt"))
TF_PROFILE_DIR = os.getenv("TF_PROFILE_DIR", os.path.join(_HERE, ".tf_browser_profile"))
TF_HOME_URL    = "https://tradefinder.in/home"
TF_LOGIN_URL   = "https://tradefinder.in/login"
TF_EMAIL       = os.getenv("TF_EMAIL", "sheladiyaaakash123@gmail.com")
TF_LS_KEY      = "tradefinder_token"   # localStorage key holding the JWT (DevTools → Application → Local Storage). Was "lt" until TradeFinder renamed it 2026-09.


# ──────────────────────────────────────────────────────────────────────────────
# JWT helpers (no browser)
# ──────────────────────────────────────────────────────────────────────────────

def _decode_exp(jwt: str) -> float | None:
    """Return the `exp` unix timestamp from a JWT payload, or None if unparseable."""
    try:
        payload_b64 = jwt.split(".")[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)   # pad base64
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload.get("exp"))
    except Exception:
        return None


def jwt_expiry_seconds(jwt: str) -> float:
    """Seconds remaining before the token expires. <=0 means expired/unknown."""
    if not jwt:
        return 0.0
    exp = _decode_exp(jwt)
    if exp is None:
        return 0.0
    return exp - time.time()


def _read_file_jwt() -> str:
    if TF_JWT_FILE and os.path.exists(TF_JWT_FILE):
        try:
            return open(TF_JWT_FILE).read().strip()
        except Exception:
            return ""
    return ""


def _write_file_jwt(jwt: str) -> None:
    with open(TF_JWT_FILE, "w") as f:
        f.write(jwt.strip() + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# Browser-based refresh
# ──────────────────────────────────────────────────────────────────────────────

def _read_lt_from_page(page) -> str | None:
    try:
        val = page.evaluate(f"() => window.localStorage.getItem('{TF_LS_KEY}')")
        return val.strip() if val else None
    except Exception:
        return None


def _attempt_google_login(page) -> None:
    """
    Best-effort: trigger the Google-OAuth login when the persistent session is logged out.
    With the persistent profile already signed into Google, clicking the account tile
    completes in ~5s without a password.

    Current TF landing-page flow (verified 2026-09-14): the site opens a
    "Welcome!" modal (`.tf-land-modal`) with a "User Login" pill (Google-icon,
    no "google" in its text) that then opens the standard Google account
    chooser **in a separate popup window**, not inline — clicking the email
    tile on `page` itself is a silent no-op since the tile lives on that
    popup. TF has rewritten the nav button's markup/classes at least three
    times now (see git history) while its accessible role and exact text
    ("Login", not "Login Now") have stayed put, so the primary selector
    targets those instead of CSS classes — the old class-based selectors stay
    as a fallback in case a future TF rewrite drops the role/text too.
    """
    # 1) Open the "Welcome!" login modal from the homepage nav button.
    # get_by_role first (survives class/DOM rewrites); wait_for_selector on
    # the fallbacks so a cold load that's still hydrating gets one more beat
    # before click(timeout=...) gives up.
    try:
        page.get_by_role("button", name="Login", exact=True).click(timeout=8000)
    except Exception:
        for sel in ["nav.tf-hp-nav-links button:has-text('Login')", "div.homepagebutton.login", "a.item-menu-mobile:has-text('Login')"]:
            try:
                page.wait_for_selector(sel, timeout=8000, state="visible")
                page.locator(sel).first.click(timeout=8000)
                break
            except Exception:
                continue

    # 2) In the modal, click "User Login" (the Google-OAuth option). This has
    # opened a popup window on every run verified so far, but Google's own
    # OAuth flow is free to redirect the current tab instead (observed live
    # 2026-09-14) -- expect_page times out with no popup ever created in that
    # case, so `target` falls through to `page` itself rather than silently
    # giving up (the bug this replaces: no popup meant no click, ever, and
    # the account chooser just sat there for the rest of the timeout budget).
    popup = None
    try:
        with page.context.expect_page(timeout=5000) as popup_info:
            page.locator("text=User Login").first.click(timeout=5000)
        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass

    # 3) On the Google account chooser -- in the popup if one opened,
    # otherwise `page` itself navigated there inline -- click our email tile.
    target = popup if popup is not None else page
    if target is page:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
    try:
        target.locator(f"text={TF_EMAIL}").first.click(timeout=8000)
    except Exception:
        pass


# A page reload doesn't necessarily make TradeFinder mint a NEW `lt` token —
# their frontend appears to only rotate it once the current one is genuinely
# (near-)expired, not proactively ahead of time. So a token can still satisfy
# "> 60s left" while being the exact same stale token we already had, minutes
# from dying — that's not a real refresh. Require a meaningfully fresh token
# (most of TF's own ~180min lifetime) before accepting it as "refreshed";
# anything less forces the login-modal flow to try to force a real re-mint.
_FRESH_ENOUGH_SECONDS = 2700   # 45 min — well under the observed 180min TTL


def refresh_tf_jwt(headless: bool = True, timeout_s: int = 60) -> str | None:
    """
    Launch the persistent profile, reload TradeFinder, and return a fresh `lt` token.
    Writes the token to TF_JWT_FILE on success. Returns None on any failure.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # playwright not installed
        print(f"[tf_auth] playwright unavailable: {e}")
        return None

    if not os.path.isdir(TF_PROFILE_DIR):
        print(f"[tf_auth] profile dir missing: {TF_PROFILE_DIR}\n"
              f"          run: uv run python strategies/tf_login_setup.py  (one-time Google login)")
        return None

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                TF_PROFILE_DIR, headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(TF_HOME_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass

            # Poll localStorage for the token; the app re-issues `lt` on load
            # — but only once the current one is close to/actually expired,
            # so a merely-alive-but-stale token doesn't count as fresh here.
            jwt = _read_lt_from_page(page)
            if not (jwt and jwt_expiry_seconds(jwt) > _FRESH_ENOUGH_SECONDS):
                # Stale/missing token on first load — run the login-modal flow
                # once (harmless no-op if already fully authenticated, but
                # this is what actually triggers TF's backend to mint a new
                # token when a plain reload alone doesn't), then keep polling.
                _attempt_google_login(page)
                try:
                    page.wait_for_url("**/home", timeout=15000)
                except Exception:
                    pass

            # Budget starts HERE, not before launch. Cold Chromium start +
            # goto (30s) + the login-modal flow (up to ~33s of waits) used to
            # eat the whole timeout, so on a busy boot this loop ran zero
            # times and a perfectly healthy profile returned None.
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                jwt = _read_lt_from_page(page)
                if jwt and jwt_expiry_seconds(jwt) > _FRESH_ENOUGH_SECONDS:
                    break
                page.wait_for_timeout(1500)

            ctx.close()

            if jwt and jwt_expiry_seconds(jwt) > _FRESH_ENOUGH_SECONDS:
                _write_file_jwt(jwt)
                mins = jwt_expiry_seconds(jwt) / 60.0
                print(f"[tf_auth] refreshed JWT (expires in {mins:.0f} min) → {TF_JWT_FILE}")
                return jwt

            # Didn't get a meaningfully fresh token, but if what we have is
            # still technically alive, write it anyway (better than nothing —
            # matches ensure_fresh_jwt's stale-fallback contract) and say so.
            if jwt and jwt_expiry_seconds(jwt) > 60:
                _write_file_jwt(jwt)
                mins = jwt_expiry_seconds(jwt) / 60.0
                print(f"[tf_auth] WARNING: could not obtain a fresh token — reusing stale "
                      f"token (expires in {mins:.0f} min) → {TF_JWT_FILE}")
                return jwt

            print("[tf_auth] could not obtain a fresh token (session may be logged out — "
                  "re-run tf_login_setup.py headed)")
            return None
    except Exception as e:
        print(f"[tf_auth] refresh error: {e}")
        return None


def ensure_fresh_jwt(min_seconds: int = 1800) -> str | None:
    """
    Return a usable JWT. If the cached file token has more than `min_seconds` left,
    return it as-is (no browser). Otherwise refresh via the browser. Falls back to the
    (possibly stale) file token if refresh fails so manual-paste still works.
    """
    cached = _read_file_jwt()
    if cached and jwt_expiry_seconds(cached) > min_seconds:
        return cached
    fresh = refresh_tf_jwt()
    return fresh or (cached or None)


if __name__ == "__main__":
    tok = refresh_tf_jwt(headless=True)
    if tok:
        print(f"OK  exp_in={jwt_expiry_seconds(tok)/60:.0f}min")
    else:
        print("FAILED — run tf_login_setup.py first")
