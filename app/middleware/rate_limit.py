from slowapi import Limiter
from slowapi.util import get_remote_address

# Rate limiter instance — keyed by client IP by default
limiter = Limiter(key_func=get_remote_address)
