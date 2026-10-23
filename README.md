# Self-hosted Support · 自托管在线客服 V1.0

面向日常使用 Telegram 和 iPhone 处理客服的多网站客服系统。源码、图片和聊天数据由你自己持有。

**当前交付：可部署源码与自动化测试，尚未经过真实 VPS、Telegram 群组和 iPhone Bark 联调。** 生产上线前请完成 [验收清单](docs/ACCEPTANCE.md)。本机验证详情见 [测试记录](docs/TEST-REPORT.md)。

## 技术与目录

- Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL 16。
- Vue 3 + TypeScript 管理后台和 iframe 聊天页；原生 JavaScript 嵌入加载器。
- PostgreSQL 持久化通知队列，单独运行一个 worker，不引入 Redis、Celery 或 AI 服务。
- Caddy 自动 HTTPS；Docker Compose 管理数据库、迁移、API、worker 和代理。
- 单 API 进程；WebSocket 每秒查询一次授权范围的数据版本，适合小型 VPS 的初始规模。需扩容时再引入 PostgreSQL LISTEN/NOTIFY 等事件分发，避免现在增加运维依赖。

```text
backend/app/        API、安全、消息、任务、Telegram/Bark、扩展协议
backend/migrations/冻结的 Alembic 数据库迁移
backend/tests/      权限隔离、去重、重试、消息桥接等测试
frontend/src/       Vue 3 / TypeScript 聊天页与客服后台
frontend/public/    原生 widget.js 加载器
scripts/            配置生成、备份、恢复
scripts/smoke.py    已部署服务健康与匿名访问检查
deploy/Caddyfile    HTTPS 与反向代理
compose.yaml        生产部署
.github/workflows/  后端 PostgreSQL 测试、前端编译、镜像构建
```

## 快速部署

VPS 安装 Docker Engine 和 Compose V2，域名解析至 VPS，开放 TCP 80/443 和可选 UDP 443。在项目根目录运行：

```sh
python3 scripts/generate-env.py
# 编辑 .env：SUPPORT_DOMAIN、PUBLIC_URL、ACME_EMAIL
# 随机初始密码和 Fernet 密钥已由脚本写入 .env

docker compose config --quiet
docker compose up -d --build
docker compose ps
```

打开 `https://客服域名/admin/`，使用 `.env` 中的账号和初始密码登录。首次初始化后可以清空 `.env` 的 `ADMIN_PASSWORD`，密码以后在后台修改。**请保留 `ENCRYPTION_KEY`，并随数据库加密备份。**

完整步骤、Telegram 配置、备份恢复和升级方式见 [部署文档](docs/DEPLOYMENT.md)。

## 网站接入

后台「设置 → 网站管理」创建网站，添加允许的完整网站 Origin，例如 `https://example.com` 和 `https://www.example.com`，然后复制接入代码：

```html
<script src="https://support.example.com/widget.js" data-site-id="后台生成的站点ID" async></script>
```

HTML 网站放在 `</body>` 前；WordPress 可用主题页脚或自定义代码插件加入。站点启用 CSP 时允许客服域名的 `script-src`、`frame-src`。加载器使用 Shadow DOM，聊天页使用 iframe。独立聊天链接：`https://support.example.com/chat/?site=站点ID`。

浏览器不需要允许第三方 Cookie。每个站点的 256 位随机凭证由宿主站点的 localStorage 保存，经严格校验来源的 postMessage 发送到客服 iframe，仅在 API Authorization 头和 WebSocket 首条认证消息使用。服务器仅存凭证哈希，固定 30 天后过期，不延长。邮箱不能恢复历史，聊天 ID 也不能授权访问。具体安全边界见 [架构与安全说明](docs/ARCHITECTURE.md)。

## 主要操作

- 后台收件箱支持全站/单站、状态、邮箱/消息内容和时间查询；完整历史按页加载。
- 回复支持 Markdown、安全外链、JPEG/PNG/WebP 图片和快捷回复。
- 客户资料中修改状态和内部备注；已解决后收到新消息自动转为待处理。
- Telegram：同站点同一标准化邮箱永久映射到一个话题。授权用户直接在话题回复；支持 `/close`、`/reopen`、`/quick`、`/quick 标题或模板ID`。
- Bark：批量添加或单设备管理、总开关和异步测试；结果在投递日志显示。`sent` 仅表示 API 接受，不表示设备实际收到。
- Telegram 配置错误、话题删除和外部请求失败均保留任务；修复配置/映射后在投递日志重试。
- 每站点可设置首次咨询、非工作时间、关键词自动回复；冷却时间避免重复触发。

## 本地开发和测试

```sh
cd backend
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
# 测试默认使用临时 SQLite，不触碰生产库
pytest -q

# PostgreSQL 并发测试（必须是可销毁的独立测试数据库）
TEST_DATABASE_URL=postgresql+psycopg://support:password@localhost/support_test pytest -q
```

`TEST_DATABASE_URL` 指向的数据库在每个测试前重建表，**切勿设置为生产库**。CI 使用独立 PostgreSQL 服务执行这项测试。

```sh
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm build
```

后端开发需要设置 `DATABASE_URL`、`ENCRYPTION_KEY`、`ADMIN_PASSWORD`、`UPLOAD_DIR`、`PUBLIC_URL`。执行 `alembic upgrade head`、`python -m app.bootstrap` 后运行 `uvicorn app.main:app --reload`；另开终端运行 `python -m app.worker`。Vue 开发服务器使用 `http://localhost:5173`，此时设置 `PUBLIC_URL=http://localhost:5173` 和 `COOKIE_SECURE=false`。HTTP 仅用于本机开发。

## GitHub 交付

项目尚未创建或连接 GitHub 仓库，也未推送任何源码。确认验收后，在 GitHub 建立空仓库，再从此目录执行：

```sh
git init -b main
git add .
git commit -m "Initial self-hosted support V1.0"
git remote add origin git@github.com:YOUR_ACCOUNT/self-hosted-support.git
git push -u origin main
```

`.env`、上传数据、数据库、构建缓存和备份已加入忽略规则。项目没有附带任何真实 Bot Token、Bark 地址或客户数据。暂未选择开源许可证，可在发布前按你的授权方式添加。
