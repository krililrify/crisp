# 部署与维护

## 1. 环境与首次启动

建议 Linux VPS、1–2 CPU、2GB RAM，预留至少 10GB 可用磁盘。容量主要由图片和聊天记录决定，实际并发能力需在目标 VPS 测量。Compose 配置了约 1.45GB 的运行时内存上限总和；首次构建需要额外内存，可在本地/CI 构建镜像后部署。2GB VPS 建议配置 1GB swap 作为构建时缓冲。

安装 Docker Engine 与 Docker Compose V2。准备专属域名，将 A/AAAA 指向 VPS；只设置真正可用的 IPv6。防火墙允许 80、443；数据库和 API 没有宿主机端口。Telegram 需要能连接公网 HTTPS。

进入项目根目录：

```sh
python3 scripts/generate-env.py
chmod 600 .env
```

编辑 `.env`：

| 变量 | 说明 |
|---|---|
| SUPPORT_DOMAIN | 例如 support.example.com，不含协议和路径 |
| PUBLIC_URL | https://support.example.com，与实际访问 Origin 一致，无尾部斜杠 |
| ACME_EMAIL | 证书通知邮箱 |
| POSTGRES_PASSWORD | 随机数据库密码，生成脚本使用 64 位十六进制 |
| ADMIN_USERNAME | 首位管理员用户名 |
| ADMIN_PASSWORD | 仅首次初始化使用，至少 12 位 |
| ENCRYPTION_KEY | Fernet 密钥，加密 Telegram/Bark 秘密，不可随意更换 |
| COOKIE_SECURE | 生产始终为 true |
| SESSION_DAYS | 固定使用 30 |
| BARK_ALLOWED_HOSTS | 精确允许的 Bark 域名，以英文逗号分隔；默认 api.day.app |
| MAX_UPLOAD_BYTES | 5242880，即 5MiB |

```sh
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 migrate api worker caddy
python3 scripts/smoke.py https://support.example.com
```

启动顺序：PostgreSQL 健康 → Alembic 迁移并初始化管理员 → API/worker → Caddy。`migrate` 成功退出是正常状态。Caddy 自动申请并续期证书。参考 [Compose 启动依赖](https://docs.docker.com/compose/how-tos/startup-order/) 与 [Caddy 请求体限制](https://caddyserver.com/docs/caddyfile/directives/request_body)。

登录 `/admin/`，确认账号可用后清空 `.env` 中的 `ADMIN_PASSWORD`；这不会删除或修改现有账号。请在后台设置自己的密码。管理员登录会话有效期 12 小时，改密码会注销全部已登录会话。

## 2. Telegram 配置

1. 用 BotFather 创建 Bot，保管 Token；关闭 Bot 的群组 Privacy Mode，必要时移除后重新加入群组。
2. 创建超级群组并开启 Topics，将 Bot 加为管理员，授予管理话题和发送消息/图片权限。
3. 获取超级群组 Chat ID（`-100…`）与允许回复的客服用户数字 ID。V1 使用显式用户 ID 白名单，不接受匿名管理员、频道身份或其他 Bot 的回复。
4. 后台「设置 → Telegram」填入 Token、Chat ID 和客服 ID。Webhook Secret 留空自动生成，保存在后端加密配置中。
5. 保存，点击「测试连接」；结果应显示 `is_forum=true`、`can_manage_topics=true`。
6. 点击「注册 Webhook」。URL 固定为 `https://客服域名/api/telegram/webhook`，请求验证 `X-Telegram-Bot-Api-Secret-Token`。更改 Telegram 配置后需重新注册。
7. 从网站发送消息，确认话题 `[网站名称] 邮箱` 出现。用白名单内用户直接在该话题发消息和图片，检查网站接收情况。

命令：`/close` 解决会话并关闭话题；`/reopen` 重新打开；`/quick` 列出模板；`/quick windows` 匹配唯一标题，或者使用模板 ID 精确发送。所有命令只接受白名单用户，并限定在已映射话题内。

话题被删除后不会自动重建，防止误混历史。先在 Telegram 手动创建正确话题，再在「话题映射」填入正确 Chat ID 和 Thread ID，最后到「投递日志」重试失败任务。创建请求超时也采用这一修复方式，因为 Telegram 不提供幂等的话题创建键，无法确认远端是否已经成功。

切换 Bot 或群组前记录现有映射。旧话题不会自动迁移到新群组。修复每个客户的映射后再重试积压任务。

官方接口依据：[Telegram Bot API](https://core.telegram.org/bots/api)。

## 3. Bark 配置

从 Bark App 复制 `https://api.day.app/设备密钥`，在后台批量添加或单独添加；可修改名称、启停、删除。编辑时 URL 留空保留原密钥。列表不回显密钥。

自建 Bark 时将精确域名加入 `BARK_ALLOWED_HOSTS`，重新创建 API/worker 容器。只支持 HTTPS 443，不跟随重定向，避免配置把后端变为任意 URL 请求代理。允许列表内域名应由可信运营者控制，不能解析到内网或云元数据地址。

测试单个或全部设备后刷新投递日志：显示设备名、状态、HTTP 状态码、错误、创建和完成时间。`sent / HTTP 200` 只表示 Bark 服务端接受请求，需要在 iPhone 上自行确认通知权限、静音、专注模式和实际到达。

通知打开 `/admin/?conversation=会话ID`；未登录时先登录，再恢复目标会话。会话 ID 不具有授权能力。官方格式依据：[Bark HTTP API](https://github.com/Finb/Bark/blob/master/docs/en-us/tutorial.md)。

## 4. 备份与恢复

每天运行并将备份**加密后**复制到其他机器或私有对象存储：

```sh
./scripts/backup.sh
```

备份包含 PostgreSQL 自定义格式 dump、图片归档和 `.env`。图片文件不可变，脚本先导出数据库再归档图片，可确保数据库快照引用的图片已被包含；可能多包含少量快照之后新增的图片，不影响恢复。备份目录默认仅所有者可读。

恢复到**同一数据库密码的部署**或全新空部署，先保留当前数据和配置的独立备份，准备与备份兼容的代码/镜像，然后：

```sh
./scripts/restore.sh backups/20261022T120000Z
```

脚本要求输入 `RESTORE`，会停止 API/worker、覆盖数据库、图片和配置，随后执行迁移再启动。新机器上先安装 Docker 并运行 `docker compose build`。已有 PostgreSQL 数据卷不会根据 `.env` 自动修改角色密码；如果与备份密码不一致，应先按 PostgreSQL 运维方式同步密码，再运行恢复。不要通过删除现有数据卷来试错。

每月实际恢复到隔离环境一次，验证登录、历史图片和 Telegram/Bark 解密配置。Fernet 密钥丢失后不能解密旧外部服务配置，但聊天记录仍在数据库。不要在共享日志、聊天消息或公开仓库暴露 `.env` 和备份。

## 5. 升级、健康与排错

升级前备份。先在隔离环境验证新版本与数据库迁移，然后：

```sh
docker compose build
docker compose stop api worker
docker compose run --rm migrate
docker compose up -d --force-recreate api worker
```

迁移失败时保留数据库和备份，修复迁移后继续；不要执行删除数据卷的命令。代码回退若不兼容新 schema，应恢复升级前的数据库、图片和配置备份。

- `/health` 检查数据库；worker 心跳文件健康检查反映执行器存活。
- 投递日志是通知是否发送成功的依据，任务最多自动尝试 8 次，指数退避到最多 1 小时，并尊重 Telegram `retry_after`。
- 单个外部请求超时 15–20 秒，不会回滚已保存的客户消息。队列为单 worker 顺序执行，某设备网络缓慢会增加后续任务等待，但失败不阻止其他任务继续。
- 失败任务修复后手动重试。`working` 任务采用 10 分钟租约，worker 崩溃后会恢复处理。
- `docker compose logs --tail=200 worker` 查看错误类型；应用不打印密钥和原始请求 URL。
- 后台图像上传失败先检查 5MiB 限制、格式和文件系统空间。上传会重编码 JPEG 并去除 EXIF，不支持 SVG/GIF/任意附件。
- 不自动删除聊天记录；定期检查 PostgreSQL 和上传卷空间，安排备份保留策略。
- 仅部署一个 API 和一个 worker。需扩容前先压测并修改事件推送/任务公平调度方案。

Caddy 外若还有 CDN/代理，要额外检查真实 IP 信任链和 WebSocket 支持。当前登录限流依赖 Caddy → Uvicorn 的来源 IP；额外代理可能让多用户共享限流。避免将 API 端口直接开放公网。
