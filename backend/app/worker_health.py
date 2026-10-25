from pathlib import Path
import time

if (
    not Path("/tmp/support-worker-heartbeat").exists()
    or time.time() - Path("/tmp/support-worker-heartbeat").stat().st_mtime > 660
):
    raise SystemExit(1)
