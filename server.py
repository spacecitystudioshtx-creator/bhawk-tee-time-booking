#!/usr/bin/env python3
"""
Golf tee time booking service — entrypoint.

Threads:
  - browser-executor: owns the one persistent Playwright Chromium
  - worker:           scheduler (snipes, cancellation polling, health checks)
  - main:             FastAPI dashboard (uvicorn)

Required secrets: BHCC_USERNAME, BHCC_PASSWORD, DASHBOARD_PASSWORD
Optional: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, SMS_TO,
          DASHBOARD_URL, DRY_RUN, HEADLESS, DAYS_AHEAD, BOOKING_TZ
"""

import os
import sys
import logging
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()  # local .env; on Replit, Secrets are already in the environment

from status import Status, LOG_DIR, TZ  # noqa: E402


def setup_logging():
    logger = logging.getLogger('bhawk')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter('[%(asctime)s] %(message)s',
                                datefmt='%Y-%m-%d %H:%M:%S')
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        logger.addHandler(console)
        fh = logging.FileHandler(
            os.path.join(LOG_DIR, f'booking_{datetime.now(TZ):%Y-%m-%d}.log'))
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def main():
    log = setup_logging().info
    if not os.getenv('BHCC_USERNAME') or not os.getenv('BHCC_PASSWORD'):
        log("FATAL: set BHCC_USERNAME and BHCC_PASSWORD secrets.")
        sys.exit(1)
    if not os.getenv('DASHBOARD_PASSWORD'):
        log("WARNING: DASHBOARD_PASSWORD not set — the dashboard will refuse "
            "all requests until you add it.")

    from browser import BrowserExecutor
    from worker import Worker
    from web import create_app
    import uvicorn

    status = Status()
    executor = BrowserExecutor()
    executor.start()
    Worker(executor, status).start()

    port = int(os.getenv('PORT', '8080'))
    log(f"Dashboard on port {port}")
    uvicorn.run(create_app(executor, status), host='0.0.0.0', port=port,
                log_level='warning')


if __name__ == '__main__':
    main()
