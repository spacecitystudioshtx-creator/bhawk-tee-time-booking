"""BookingProvider interface.

Each golf course / booking system implements this. The scheduler and dashboard
never know which provider they're talking to.

All methods run on the browser-executor thread and receive the BrowserManager.
"""


class InterventionNeeded(Exception):
    """Raise when a human must take over (CAPTCHA, unexpected page, login wall).
    The worker pauses, sends an SMS with the dashboard link, and leaves the
    browser exactly where it is so the user can fix it via Take Control."""


class BookingProvider:
    name = 'base'

    def check_session(self, manager) -> bool:
        """Cheap health check: is our session still logged in?"""
        raise NotImplementedError

    def ensure_logged_in(self, manager):
        """Log in if needed. Raise InterventionNeeded on CAPTCHA/unexpected page."""
        raise NotImplementedError

    def attempt(self, manager, target_date, t_start, t_end, dry_run=False) -> str:
        """One full search-and-book attempt.
        Returns 'success' | 'no_times' | 'error'. May raise InterventionNeeded."""
        raise NotImplementedError
