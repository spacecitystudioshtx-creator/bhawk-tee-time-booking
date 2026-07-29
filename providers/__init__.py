from providers.blackhawk import BlackHawkProvider
from providers.memorial import MemorialParkProvider

PROVIDERS = {
    'blackhawk': BlackHawkProvider(),
    'memorial': MemorialParkProvider(),
}


def get_provider(name):
    if name not in PROVIDERS:
        raise KeyError(f"Unknown provider '{name}'. Available: {list(PROVIDERS)}")
    return PROVIDERS[name]
