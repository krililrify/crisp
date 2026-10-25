#!/usr/bin/env python3
"""仅在 .env 不存在时生成随机初始密钥；不在终端输出凭证。仅依赖 Python 标准库。"""

import base64, secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
text = (root / ".env.example").read_text()
text = text.replace("REPLACE_WITH_64_HEX_CHARACTERS", secrets.token_hex(32))
text = text.replace(
    "REPLACE_WITH_STRONG_PASSWORD_AT_LEAST_12_CHARACTERS", secrets.token_urlsafe(24)
)
text = text.replace(
    "REPLACE_WITH_GENERATED_FERNET_KEY",
    base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
)
with (root / ".env").open("x") as f:
    f.write(text)
(root / ".env").chmod(0o600)
print("已创建 .env。请修改域名和 ACME 邮箱；管理员初始密码保存在 .env。")
