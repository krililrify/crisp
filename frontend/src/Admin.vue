<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from "vue";
import { api, setCsrf, connect, date, type Row } from "./api";
import Messages from "./Messages.vue";
import SettingsPanel from "./SettingsPanel.vue";
const logged = ref(false),
  username = ref("admin"),
  password = ref(""),
  error = ref(""),
  sites = ref<Row[]>([]),
  conversations = ref<Row[]>([]),
  selected = ref<Row>(),
  messages = ref<Row[]>([]),
  quick = ref<Row[]>([]);
const tab = ref("inbox"),
  siteId = ref(""),
  query = ref(""),
  status = ref(""),
  since = ref(""),
  until = ref(""),
  offset = ref(0),
  body = ref(""),
  attachment = ref(""),
  busy = ref(false),
  connection = ref(""),
  showDetails = ref(false),
  sendingId = ref("");
let stop: (() => void) | undefined, searchTimer: number | undefined;
async function attempt(fn: () => Promise<void>) {
  try {
    error.value = "";
    await fn();
  } catch (e: any) {
    error.value = e.message;
    if (e.status === 401) {
      logged.value = false;
      stop?.();
    }
  }
}
async function loadSites() {
  sites.value = await api("/admin/sites");
  quick.value = await api("/admin/quick-replies");
}
async function list() {
  const p = new URLSearchParams({
    site_id: siteId.value,
    q: query.value,
    status: status.value,
    offset: String(offset.value),
  });
  if (since.value)
    p.set("since", String(new Date(since.value).getTime() / 1000));
  if (until.value)
    p.set("until", String(new Date(until.value).getTime() / 1000 + 86400));
  conversations.value = await api("/admin/conversations?" + p);
}
async function refresh() {
  await list();
  if (selected.value) await loadMessages();
}
async function loadMessages() {
  if (!selected.value) return;
  const id = selected.value.id;
  const batch = await api(`/admin/conversations/${id}/messages`);
  if (selected.value?.id !== id) return;
  const map = new Map(messages.value.map((m) => [m.id, m]));
  for (const m of batch) map.set(m.id, m);
  messages.value = [...map.values()].sort(
    (a, b) => a.created_at - b.created_at,
  );
}
async function select(c: Row) {
  selected.value = await api("/admin/conversations/" + c.id);
  messages.value = [];
  body.value = "";
  attachment.value = "";
  sendingId.value = "";
  await loadMessages();
  await api(`/admin/conversations/${c.id}/read`, "POST");
  await list();
  history.replaceState(null, "", "?conversation=" + encodeURIComponent(c.id));
}
function search() {
  clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    offset.value = 0;
    attempt(list);
  }, 300);
}
async function init() {
  const me = await api("/admin/me");
  setCsrf(me.csrf);
  logged.value = true;
  await loadSites();
  await list();
  const id = new URLSearchParams(location.search).get("conversation");
  if (id) await select({ id });
  stop?.();
  stop = connect(
    { role: "admin" },
    () => attempt(refresh),
    (s) => {
      connection.value = s;
      if (s === "访问凭证已失效") logged.value = false;
    },
  );
}
async function login() {
  busy.value = true;
  await attempt(async () => {
    const r = await api("/admin/login", "POST", {
      username: username.value,
      password: password.value,
    });
    setCsrf(r.csrf);
    password.value = "";
    await init();
  });
  busy.value = false;
}
async function logout() {
  await attempt(async () => {
    await api("/admin/logout", "POST");
    logged.value = false;
    stop?.();
  });
}
async function send() {
  if (
    !selected.value ||
    busy.value ||
    (!body.value.trim() && !attachment.value)
  )
    return;
  busy.value = true;
  if (!sendingId.value) sendingId.value = crypto.randomUUID();
  await attempt(async () => {
    await api(`/admin/conversations/${selected.value!.id}/messages`, "POST", {
      body: body.value,
      attachment_id: attachment.value || null,
      client_id: sendingId.value,
    });
    body.value = "";
    attachment.value = "";
    sendingId.value = "";
    await refresh();
  });
  busy.value = false;
}
async function upload(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file || !selected.value) return;
  if (file.size > 5 * 1024 * 1024) {
    error.value = "图片不能超过 5MB";
    return;
  }
  busy.value = true;
  await attempt(async () => {
    const f = new FormData();
    f.append("file", file);
    attachment.value = (
      await api(`/admin/conversations/${selected.value!.id}/uploads`, "POST", f)
    ).id;
  });
  busy.value = false;
}
async function older() {
  if (selected.value && messages.value.length) {
    const r = await api(
      `/admin/conversations/${selected.value.id}/messages?before=${messages.value[0].created_at}`,
    );
    messages.value = [...r, ...messages.value];
  }
}
async function saveDetails() {
  if (!selected.value) return;
  await api("/admin/conversations/" + selected.value.id, "PATCH", {
    status: selected.value.status,
    notes: selected.value.notes,
    human_takeover: selected.value.human_takeover,
  });
  await list();
}
onMounted(() => {
  init().catch((e: any) => {
    if (e.status !== 401) error.value = e.message;
  });
});
onBeforeUnmount(() => {
  stop?.();
  clearTimeout(searchTimer);
});
</script>
<template>
  <div v-if="!logged" class="login-page">
    <form class="login-card" @submit.prevent="login">
      <div class="brand">◈ Support</div>
      <h1>欢迎回来</h1>
      <p>管理所有网站的客户对话</p>
      <div v-if="error" class="alert">{{ error }}</div>
      <label
        >账号<input
          v-model="username"
          autocomplete="username"
          required /></label
      ><label
        >密码<input
          v-model="password"
          type="password"
          autocomplete="current-password"
          required /></label
      ><button :disabled="busy">{{ busy ? "登录中…" : "登录工作台 →" }}</button>
    </form>
  </div>
  <div v-else class="admin-shell">
    <header class="topbar">
      <strong class="brand">◈ Support</strong>
      <nav>
        <button
          class="secondary"
          :class="{ selected: tab === 'inbox' }"
          @click="tab = 'inbox'"
        >
          收件箱</button
        ><button
          class="secondary"
          :class="{ selected: tab === 'settings' }"
          @click="tab = 'settings'"
        >
          设置
        </button>
      </nav>
      <span class="connection">{{ connection }}</span
      ><button class="secondary" @click="logout">退出</button>
    </header>
    <div v-if="error" class="alert global-alert">{{ error }}</div>
    <SettingsPanel
      v-if="tab === 'settings'"
      :sites="sites"
      @refresh="attempt(loadSites)"
    />
    <main v-else class="inbox" :class="{ 'has-selection': !!selected }">
      <aside class="conversation-list">
        <div class="list-controls">
          <select v-model="siteId" @change="search">
            <option value="">全部网站</option>
            <option v-for="s in sites" :key="s.id" :value="s.id">
              {{ s.name }}
            </option></select
          ><input
            v-model="query"
            type="search"
            placeholder="搜索邮箱或消息…"
            @input="search"
          /><select v-model="status" @change="search">
            <option value="">全部状态</option>
            <option value="pending">待处理</option>
            <option value="active">处理中</option>
            <option value="resolved">已解决</option>
          </select>
          <div class="date-filter">
            <label
              >从<input v-model="since" type="date" @change="search" /></label
            ><label
              >至<input v-model="until" type="date" @change="search"
            /></label>
          </div>
        </div>
        <div class="list-scroll">
          <button
            v-for="c in conversations"
            :key="c.id"
            class="conversation"
            :class="{ current: c.id === selected?.id }"
            @click="attempt(() => select(c))"
          >
            <span class="avatar">{{ c.email[0].toUpperCase() }}</span>
            <div>
              <strong>{{ c.email }}</strong
              ><small
                >{{ c.site_name }} ·
                {{
                  (
                    {
                      pending: "待处理",
                      active: "处理中",
                      resolved: "已解决",
                    } as Row
                  )[c.status]
                }}</small
              ><small>{{ date(c.updated_at) }}</small>
            </div>
            <span v-if="c.unread" class="badge">{{ c.unread }}</span>
          </button>
          <div v-if="!conversations.length" class="empty">没有匹配的会话</div>
        </div>
        <div class="actions pagination">
          <button
            class="secondary"
            :disabled="offset === 0"
            @click="
              offset = Math.max(0, offset - 100);
              attempt(list);
            "
          >
            上一页</button
          ><button
            class="secondary"
            :disabled="conversations.length < 100"
            @click="
              offset += 100;
              attempt(list);
            "
          >
            下一页
          </button>
        </div>
      </aside>
      <section v-if="selected" class="thread">
        <header class="thread-header">
          <button class="secondary mobile-back" @click="selected = undefined">
            ←
          </button>
          <div>
            <strong>{{ selected.email }}</strong
            ><small>{{ selected.site_name }}</small>
          </div>
          <button class="secondary" @click="showDetails = !showDetails">
            客户资料
          </button>
        </header>
        <button class="older" @click="attempt(older)">查看更早消息</button
        ><Messages :key="selected.id" :messages="messages" />
        <form class="composer" @submit.prevent="send">
          <select
            aria-label="快捷回复"
            @change="
              body =
                quick.find(
                  (q) => q.id === ($event.target as HTMLSelectElement).value,
                )?.body || body;
              ($event.target as HTMLSelectElement).value = '';
            "
            :disabled="!!sendingId"
          >
            <option value="">插入快捷回复…</option>
            <option v-for="q in quick" :key="q.id" :value="q.id">
              {{ q.category }} / {{ q.title }}
            </option>
          </select>
          <div v-if="attachment" class="attachment-ready">
            图片已准备好
            <button
              type="button"
              :disabled="!!sendingId"
              @click="attachment = ''"
            >
              移除
            </button>
          </div>
          <textarea
            v-model="body"
            :disabled="!!sendingId"
            maxlength="12000"
            rows="3"
            placeholder="输入回复，支持 Markdown…"
            aria-label="回复正文"
          ></textarea>
          <div class="composer-actions">
            <label class="upload"
              >＋ 图片<input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                :disabled="busy || !!sendingId"
                @change="upload" /></label
            ><small>所有回复将永久保存</small
            ><button :disabled="busy">
              {{ busy ? "发送中…" : sendingId ? "重试发送" : "发送 ↑" }}
            </button>
          </div>
        </form>
      </section>
      <section v-else class="empty-thread">
        <div>
          <span>✦</span>
          <h1>每一段对话，都值得认真对待</h1>
          <p>选择会话开始回复，或在 Telegram 话题中直接处理。</p>
        </div>
      </section>
      <aside v-if="selected && showDetails" class="customer-details">
        <button class="secondary" @click="showDetails = false">关闭资料</button>
        <h2>客户资料</h2>
        <p>{{ selected.email }}</p>
        <dl>
          <dt>来源网站</dt>
          <dd>{{ selected.site_name }}</dd>
          <dt>首次咨询</dt>
          <dd>{{ date(selected.first_seen) }}</dd>
          <dt>最近咨询</dt>
          <dd>{{ date(selected.last_seen) }}</dd>
        </dl>
        <label
          >会话状态<select v-model="selected.status">
            <option value="pending">待处理</option>
            <option value="active">处理中</option>
            <option value="resolved">已解决</option>
          </select></label
        ><label
          >内部备注<textarea
            v-model="selected.notes"
            rows="7"
          ></textarea></label
        ><button @click="attempt(saveDetails)">保存资料</button>
      </aside>
    </main>
  </div>
</template>
