from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# In-memory storage is fine for a single-process dev/eval deployment. For a
# real multi-worker deployment, point storage_uri at Redis
# (e.g. "redis://localhost:6379") so limits are shared across workers.
limiter = Limiter(key_func=get_remote_address, default_limits=[])
