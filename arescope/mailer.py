"""Outbound transactional email — provider-agnostic, degrades gracefully.

One small surface (`send_email`) with two backends chosen at call time:
  * **Resend** (https://resend.com) when ARESCOPE_RESEND_API_KEY is set — a single
    REST call via httpx, so no extra dependency and no SDK shapes to guess.
  * **Console** otherwise — logs the message (and any link) to the app log, so local
    dev and tests need no key and an email never fails a flow.

A send failure is logged and returns False; callers decide whether that's fatal
(magic-link login → tell the user) or fire-and-forget (signup verify → don't block).
The HTML is a single clean, dark, table-based template that renders everywhere.
"""

from __future__ import annotations

import logging

import httpx

from arescope.config import get_settings

logger = logging.getLogger("arescope.mailer")

_RESEND_ENDPOINT = "https://api.resend.com/emails"


def send_email(to: str, subject: str, html: str, text: str) -> bool:
    """Send one email. Returns True on success, False on any failure (logged)."""
    cfg = get_settings()
    if not cfg.resend_api_key:
        logger.info("[email:console] to=%s subject=%s\n%s", to, subject, text)
        return True
    try:
        resp = httpx.post(
            _RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {cfg.resend_api_key}"},
            json={"from": cfg.email_from, "to": [to], "subject": subject,
                  "html": html, "text": text},
            timeout=15,
        )
    except httpx.HTTPError as e:
        logger.warning("email send to %s failed (transport): %s", to, e)
        return False
    if resp.status_code >= 300:
        logger.warning("email send to %s failed: %s %s", to, resp.status_code, resp.text)
        return False
    return True


# --- the magic-link template ------------------------------------------------


def _layout(heading: str, body_html: str, link: str, cta: str) -> str:
    """Dark, single-column, inline-styled email that renders across clients."""
    return f"""\
<!doctype html>
<html lang="en"><body style="margin:0;background:#0a0a0a;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#ededed;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:40px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:440px;background:#121212;border:1px solid #242424;border-radius:14px;overflow:hidden;">
        <tr><td style="padding:32px 36px 8px;">
          <div style="font-weight:700;letter-spacing:.14em;font-size:13px;color:#7CFF9B;">ARESCOPE</div>
        </td></tr>
        <tr><td style="padding:8px 36px 4px;">
          <h1 style="margin:0;font-size:21px;font-weight:600;color:#fafafa;">{heading}</h1>
        </td></tr>
        <tr><td style="padding:8px 36px 0;font-size:15px;line-height:1.55;color:#bdbdbd;">
          {body_html}
        </td></tr>
        <tr><td style="padding:26px 36px 8px;">
          <a href="{link}" style="display:inline-block;background:#7CFF9B;color:#06210f;text-decoration:none;font-weight:600;font-size:15px;padding:13px 26px;border-radius:9px;">{cta}</a>
        </td></tr>
        <tr><td style="padding:18px 36px 30px;font-size:12px;line-height:1.5;color:#6b6b6b;">
          This link expires soon and can be used once. If you didn't request it, you can ignore this email.
          <br><br>Or paste this URL into your browser:<br>
          <span style="color:#8a8a8a;word-break:break-all;">{link}</span>
        </td></tr>
      </table>
      <div style="max-width:440px;margin-top:18px;font-size:11px;color:#5a5a5a;">Arescope · self-audit, by design.</div>
    </td></tr>
  </table>
</body></html>"""


def send_login_link(to: str, link: str) -> bool:
    html = _layout(
        "Sign in to Arescope",
        "<p style='margin:0;'>Use the button below to sign in. No password needed.</p>",
        link,
        "Sign in",
    )
    text = f"Sign in to Arescope:\n\n{link}\n\nThis link expires soon and can be used once."
    return send_email(to, "Your Arescope sign-in link", html, text)


def send_verify_link(to: str, link: str) -> bool:
    html = _layout(
        "Confirm your email",
        "<p style='margin:0;'>Confirm this address to finish setting up your Arescope account.</p>",
        link,
        "Confirm email",
    )
    text = f"Confirm your Arescope email:\n\n{link}\n\nThis link expires soon and can be used once."
    return send_email(to, "Confirm your Arescope email", html, text)
