"""SMS notifications via the Twilio REST API.

Runs in log-only mode until all four env vars are set (Replit Secrets):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, SMS_TO
Optional: DASHBOARD_URL — appended to alerts that need intervention.
"""

import os
import logging
import requests

log = logging.getLogger('bhawk').info

SID = os.getenv('TWILIO_ACCOUNT_SID')
TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
FROM = os.getenv('TWILIO_FROM')
TO = os.getenv('SMS_TO')
DASHBOARD_URL = os.getenv('DASHBOARD_URL', '')

_last_sent = {}  # dedupe key -> last message, so we don't spam repeats


def sms(message, dedupe_key=None, with_link=False):
    """Send an SMS. dedupe_key suppresses repeats of the same message."""
    if with_link and DASHBOARD_URL:
        message = f"{message}\n{DASHBOARD_URL}"
    if dedupe_key is not None:
        if _last_sent.get(dedupe_key) == message:
            return
        _last_sent[dedupe_key] = message

    if not all((SID, TOKEN, FROM, TO)):
        log(f"SMS (not configured, log only): {message}")
        return
    try:
        resp = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json",
            auth=(SID, TOKEN),
            data={'From': FROM, 'To': TO, 'Body': message},
            timeout=15,
        )
        if resp.status_code >= 300:
            log(f"SMS failed ({resp.status_code}): {resp.text[:200]}")
        else:
            log(f"SMS sent: {message.splitlines()[0]}")
    except requests.RequestException as e:
        log(f"SMS error: {e}")
