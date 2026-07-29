"""Memorial Park (Houston) booking provider — SCAFFOLD, not yet implemented.

To fill this in, someone needs to walk the real Memorial Park booking flow
(golf course website -> tee time search -> reserve) with browser devtools open
and record:
  1. The login URL and the login form field selectors.
  2. How to reach the tee sheet for a given date.
  3. The selectors for time slots, player count, and the reserve/confirm buttons.
  4. What the "already logged in" state looks like (for check_session).

Then implement the three methods below exactly like providers/blackhawk.py.
The scheduler, dashboard, SMS, and browser management all work unchanged —
entries in booking_config.json just need "provider": "memorial".
"""

import logging

from providers.base import BookingProvider

log = logging.getLogger('bhawk').info


class MemorialParkProvider(BookingProvider):
    name = 'memorial'

    def check_session(self, manager):
        log("Memorial Park provider not implemented yet.")
        return False

    def ensure_logged_in(self, manager):
        raise NotImplementedError(
            "Memorial Park provider is a scaffold — record the booking flow "
            "and implement selectors (see module docstring).")

    def attempt(self, manager, target_date, t_start, t_end, dry_run=False):
        raise NotImplementedError(
            "Memorial Park provider is a scaffold — record the booking flow "
            "and implement selectors (see module docstring).")
