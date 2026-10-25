# 交付测试记录

验证时间：2026-10-22 至 2026-10-23（Asia/Shanghai）。这是本地开发交付记录，不是生产上线证明。

## 已执行

| 检查 | 结果 | 范围 |
|---|---|---|
| pytest | 32 passed / 1 skipped | 临时 SQLite，API、权限、消息与模拟外部服务 |
| Vue TypeScript 检查 | 通过 | vue-tsc --noEmit |
| 生产构建 | 通过 | Vite；JS 约 97KB、gzip 约 37KB，CSS 约 9KB |
| 冻结依赖安装 | 通过 | pnpm 11.25.0、pnpm-lock.yaml |
| Compose 配置 | 通过 | Docker 官方 Compose 5.6.1，经官方 SHA-256 文件校验；使用 .env.example，跳过运行时 env_file 加载 |
| Alembic 初始迁移 | 通过 | 独立 SQLite 空库；迁移后 schema 与 ORM 元数据一致 |
| Python 语法与 shell 脚本 | 通过 | compileall、sh -n |
| pip-audit | 未发现已知漏洞 | requirements.lock；2026-10-22 查询 |
| pnpm audit --prod | 0 项公告 | Vue 生产依赖；2026-10-22 查询 |
| 浏览器后台 | 通过 | 登录、会话列表、历史 Markdown、新消息实时出现、后台回复 |
| 浏览器独立聊天 | 通过 | 邮箱建会话、发送、实时接收、刷新恢复 |
| 浏览器跨 Origin 嵌入 | 通过 | localhost 宿主与 127.0.0.1 客服不同 Origin；展开、发消息、刷新恢复 |
| 响应式结构 | 检查通过 | 后台桌面 1440px 与窄屏布局；未使用真实 iPhone |

浏览器测试使用独立本地预览数据库与虚构邮箱，不包含客户真实数据。未运行通知 worker，因此没有向任何真实 Telegram 或 Bark 设备发送通知。

## 自动测试覆盖

- 同网站标准化邮箱复用长期客户，但新访客凭证不能读取旧会话。
- 过期凭证拒绝历史、发送和 WebSocket；跨网站与伪造 token 无权访问。
- 访客发送幂等与同事务 outbox；离线后台回复也支持幂等重试。
- 管理员 Origin/CSRF、修改密码撤销会话、登录限流、Cookie 属性。
- Markdown 标题、粗斜体、列表、代码和 HTTPS 图片的安全渲染；HTML/危险链接过滤。
- 真实图片解码与伪造文件拒绝、超限拒绝、附件跨访客范围拒绝。
- 自动欢迎/关键词冷却、无循环、时区校验、跨午夜工作日。
- Bark 批量去重、密钥加密与不回显、域名限制、设备失败隔离、测试 HTTP 结果记录。
- 持久化任务失败退避、重试后成功、客户原消息保留。
- Telegram 话题一次创建、创建未知结果停止盲目创建、删除错误可见与映射修复。
- Webhook secret、update_id 去重、群组/客服白名单/防 Bot 循环。
- Telegram 正文格式转换、UTF-16 Emoji 偏移、常见快捷命令和当前会话路由。
- 站点停用、话题唯一映射、消息内容搜索。
- WebSocket 空闲断开立即清理服务端任务、畸形认证消息安全拒绝。
- 冻结数据库迁移执行和 schema 比较。

## 未执行的必要项目

1. **PostgreSQL 并发测试**：本机没有 PostgreSQL 服务，相关测试明确 skip；CI 已设置独立 PostgreSQL 16 服务执行，尚未在 GitHub 运行。
2. **Docker 镜像构建和容器启动**：本机没有 Docker 引擎，只执行了官方 Compose 配置校验；CI 包含镜像构建任务。
3. **VPS / TLS / 备份恢复**：没有目标 VPS、域名配置或运行中的生产服务，须按部署和验收文档执行。
4. **真实 Telegram / Bark**：没有 Bot Token、论坛群组、客服 ID、Bark 地址或真实设备。现有外部服务测试使用 mock，不能代表网络权限、Webhook 可达性或通知实际到达。
5. **真实移动浏览器**：未测 iOS Safari、Android、WordPress 实际站点，以及系统软键盘和第三方存储策略。不同 Origin 的桌面浏览器测试不能替代这些测试。
6. **压力、资源和长时运行**：尚未对目标 1C2G / 2C2G VPS 做吞吐、内存、磁盘和队列延迟测试。

测试运行有一条 Starlette TestClient 关于未来 httpx2 迁移的弃用警告，不影响当前 32 项断言。版本已固定，后续升级测试客户端时可处理该警告。

完整人工验收步骤见 [ACCEPTANCE.md](ACCEPTANCE.md)。
