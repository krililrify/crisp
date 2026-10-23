#!/usr/bin/env python3
"""部署后匿名检查，无真实凭证，无写操作。"""

import sys, json, urllib.request, urllib.error

base = sys.argv[1].rstrip("/")
for path, expected in [
    ("/health", 200),
    ("/admin/", 200),
    ("/widget.js", 200),
    ("/api/admin/me", 401),
    ("/api/admin/conversations", 401),
]:
    try:
        with urllib.request.urlopen(base + path, timeout=15) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    print(f"{path}: HTTP {status}")
    if status != expected:
        raise SystemExit(f"失败：预期 {expected}")
print("基础检查通过；真实消息链路请继续执行 docs/ACCEPTANCE.md。")
