#!/usr/bin/env python3
"""Compose healthcheck for non-HTTP loop services (worker, scheduler).

Checks the heartbeat file freshness under LOG_DIR (both native and containers
write to the same ./logs mount). Exit 0 = healthy.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.heartbeat import is_healthy

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "worker"
    if is_healthy(name, max_age_s=90.0):
        print(f"heartbeat ok: {name}")
        sys.exit(0)
    print(f"heartbeat stale/missing: {name}")
    sys.exit(1)
