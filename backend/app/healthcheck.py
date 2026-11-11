"""Container health probe for the worker: healthy if it wrote a heartbeat in the last 3 intervals."""
import sys
from datetime import timedelta

from .config import get_settings
from .db import SessionLocal
from .models import WorkerHeartbeat
from .security import utcnow


def main() -> int:
    db = SessionLocal()
    try:
        hb = db.get(WorkerHeartbeat, "worker")
        limit = timedelta(seconds=get_settings().worker_interval_seconds * 3 + 30)
        return 0 if hb and utcnow() - hb.ts < limit else 1
    except Exception:  # noqa: BLE001
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
