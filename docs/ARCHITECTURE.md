# 架构、安全边界与可靠性

## 身份与历史访问

V1 将四个实体分开：

| 实体 | 生命周期 / 用途 |
|---|---|
| Customer | 站点 + 标准化邮箱唯一，永久客服身份 |
| Conversation | 每个客户一条长期客服会话，后台聚合全部历史 |
| VisitorSession | 一次随机授权范围，固定 30 天有效 |
| TelegramTopic | 每个客户唯一，永久映射到 Chat ID + Thread ID |

邮箱先经过语法校验，再去除首尾空格、casefold；不合并 Gmail 的点号、别名或 `+tag`。邮箱无需验证，仅用于标识，因此不能作为账户所有权证明。任何人知道邮箱都不能读取此前的访客历史。

客户端消息只返回 `visitor_session_id` 与当前有效凭证完全匹配的记录。管理员和 Telegram 回复绑定发送时最新创建且未过期的 VisitorSession；没有有效客户端会话时，消息仍保存至长期会话和后台，不会发给以后创建的新会话。同一邮箱存在多台设备时，客服新回复只发给最新有效客户端会话；其他会话仍能查看各自范围内已有的消息。这是 V1「当前客户端会话」的明确规则。

访客凭证是 256 位随机 Bearer Token，数据库仅存 SHA-256；授权时同时检查站点、有效期和站点启用状态。会话 ID、客户 ID、邮箱均不是凭证。密码使用 Argon2id，管理员 Cookie 采用 HttpOnly、Secure、SameSite=Strict，修改操作要求正确 Origin 和 CSRF Token。改密码撤销全部管理员会话；WebSocket 也检查会话撤销和过期。

跨域 iframe 不依赖第三方 Cookie：加载器在宿主站点 localStorage 按客服服务 Origin + site_id 保存凭证，通过校验 `event.origin`、`event.source` 和 site_id 的 postMessage 传给客服 iframe。iframe 再核对站点允许的宿主 Origin。独立聊天页使用客服域名下按站点分隔的 localStorage。凭证放在 Authorization 头及 WSS 首条消息中，不进入 URL。数据库强制过期，即使修改客户端时间也不能续期。

**边界：localStorage 无法获得 HttpOnly 的防脚本读取属性。宿主网站或客服页面发生 XSS、使用恶意第三方脚本或浏览器扩展时，当前访客凭证可能被读取。** 请控制嵌入站点脚本、启用 CSP 并及时修补宿主站点。该机制用于兼容受限第三方 Cookie，不能防御已经控制宿主网站的攻击者。浏览器完全禁用持久存储时，当前页面仍可聊天，关闭后不能保证恢复；不会退回邮箱恢复历史。

独立聊天链接是公开入口，Origin 域名列表用于控制组件嵌入，不是防机器人或付费访问控制。系统限制会话创建和访客发消息频率，公网大规模滥用还需在 Caddy 前增加适合业务的限流/挑战。

## 数据隔离与并发

- Customer `(site_id,email)` 唯一；Conversation `customer_id` 唯一；TelegramTopic `customer_id` 主键且 `(chat_id,thread_id)` 唯一。
- 首次咨询锁定站点行，防止并发创建相同客户；消息/规则触发锁定客户的 Conversation 行。
- VisitorSession 与消息严格关联。图片携带 customer_id 和 visitor_session_id；访客只能下载当前范围的图片，管理员可查看全部。
- Message `(visitor_session_id,client_id)` 唯一，并额外用 request_key 按来源/访客会话或后台长期会话去重，未在线的后台回复也可幂等重试；网络重试复用随机 client_id；Telegram webhook 以 update_id 持久化去重。
- 客户消息与 Telegram/Bark 待投递任务在同一个数据库事务提交。没有把请求内存队列当作消息权威来源。

V1 不允许管理员删除客户/消息/站点，网站可停用；历史默认长期保留。快捷回复、自动回复规则和 Bark 设备可以删除。图片上传后暂时不发送会产生未引用图片，当前无自动垃圾回收，以免误删长期记录；维护者可在完整备份后按数据库引用关系审计孤立文件。

## 实时通信

WebSocket 建连后 10 秒内必须认证，服务端不接受任意 conversation_id 订阅。访客授权范围由 token 在数据库中解析，管理员使用登录 Cookie + Origin。每秒检查授权范围的数据版本；变化后让客户端通过鉴权 REST API 获取数据。无效凭证关闭连接，不把凭证放到查询参数或访问日志。前端指数退避重连，恢复后重新读取持久化消息。

聊天和后台历史每次获取最多 100 条，支持向前翻页。会话列表每页 100 条，不是网站/设备/数据量的人为总上限。时间筛选匹配范围内存在消息的长期会话，列表显示该会话最近活动；对话内仍显示完整历史。

## Telegram 双向桥接

只使用官方 Bot API。群组必须是开启 Topics 的超级群组；关闭 Privacy Mode 并授予管理话题权限。Webhook 校验随机 secret 头，先持久化任务再返回成功。只处理白名单用户、配置的群组和已映射话题；拒绝 Bot、自发消息、匿名管理员/频道 sender_chat 和未授权用户，避免循环与冒充。

网站/自动/后台消息写入 DB 后转发 Telegram；Telegram 客服消息写入 DB 后推给当前访客，不回转 Telegram。快捷回复命令选择模板后按客服消息保存，再同步到话题。常见 Telegram 实体按 UTF-16 偏移安全转换到 Markdown（粗体、斜体、代码、链接、引用；不支持的样式保留文字），最终仍经过 HTML 禁用和清洗。

创建话题前先提交创建意图。正常成功后保存 thread_id，后续只复用映射。创建失败、超时或进程中断后无法判断远端结果时，不盲目创建第二个话题，等待管理员人工核对与修复。已有映射的消息发送失败也不会自动创建新话题。

向 Telegram 发送支持的 HTML 格式，超过保守长度阈值的长消息降级为可读纯文本并分块；Markdown 图片在 Telegram 变为可点击图片链接，网站聊天页内联展示。上传图片使用 sendPhoto；Telegram 接收照片先受限流式下载、重新校验并重编码，再存成本地受保护图片。文字与图片说明一起保存。暂不支持 Telegram 文档附件、语音、视频和已发送消息编辑/删除同步。

## 外部通知可靠性与限制

独立 worker 从 PostgreSQL 领取任务，采用 10 分钟租约、失败指数退避、最多 8 次尝试；Telegram 429 遵守 retry_after。每个 Bark 设备有独立任务，失败互不回滚，禁用设备和全局关闭会跳过尚未发送的普通 Bark 消息。任务已进入队列不代表已经同步或送达。

**外部投递为至少一次，不承诺严格恰好一次。** Telegram 和 Bark 普通发送接口没有应用可控的幂等键；如果远端已经接受、但响应丢失或进程在保存成功标记前崩溃，重试可能出现重复通知/副本。数据库内部的消息和 Webhook 更新可以去重，Telegram 分块也记录每块进度来缩小重复范围。创建话题的未知结果采用人工修复来避免重复话题。失败重试期间，远端收到消息的顺序可能与 DB 时间顺序不同；DB 保持原始记录。

单 worker 顺序执行避免额外线程/服务，适合轻量 V1；单个慢设备会暂时延后其他任务，但超时后继续处理其他任务。高峰下需监控队列延迟，在扩容前增加分渠道并发、公平调度与 LISTEN/NOTIFY，当前不声称已完成压力测试。

Telegram/Bark 配置使用环境 Fernet 密钥加密存库，管理列表不回显秘密，访客端无法读取。Bark URL 严格限制为管理员在服务器环境声明的 HTTPS 域名，不跟随重定向；允许域名应可信且不指向内网。不要在日志中记录包含 Token 的 URL。

## Markdown 与图片

服务端 Markdown 解析禁用原始 HTML，Bleach 白名单清洗链接与标签，只允许 HTTP/HTTPS 超链接；外部图片限 HTTPS，链接加 noopener、noreferrer、nofollow。安全渲染结果经前端 v-html 展示，前端不接受未经后端清洗的 HTML。

图片原始大小最多 5MiB，格式按实际解码而不是 MIME/扩展名判断，仅 JPEG/PNG/WebP。Pillow 验证并重编码 JPEG、去除 EXIF，限制最多 2000 万像素。文件不提供公开静态 URL；下载要求管理员或当前访客范围鉴权，浏览器以 Blob URL 显示。外部 Markdown 图片由浏览器请求公开链接，不在后端代抓，不能承载私有图片访问凭证。

## 扩展点

- `extensions/ai.py`：AIProvider、ReplyDecision、ContextReader 与 SQLContextReader；human_takeover 状态和 `ai` 消息来源预留。V1 无 AI Provider 实现、模型调用或框架依赖。
- `extensions/storage.py`：ImageStorage 协议与 LocalImageStorage；未来增加 S3 实现及签名访问适配。V1 读附件仍使用本地 FileResponse，接入 S3 时需同时改下载适配层。
- AdminUser.role 预留 owner 等角色，现有权限均为单管理员 owner；V1 未开放多管理员管理界面或角色细分授权。
