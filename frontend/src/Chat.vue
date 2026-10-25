<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { api, connect, type Row } from "./api";
import Messages from "./Messages.vue";
const params = new URLSearchParams(location.search),
  siteId = params.get("site") || "",
  parentOrigin = params.get("parent") || "";
const embedded = window.parent !== window;
const site = ref<Row>(),
  email = ref(""),
  problem = ref(""),
  body = ref(""),
  messages = ref<Row[]>([]),
  error = ref(""),
  state = ref("正在连接"),
  busy = ref(false),
  credential = ref<Row>(),
  attachment = ref(""),
  uploading = ref(false);
const pending = ref<Row>();
const problemLength = computed(() => [...problem.value.trim()].length);
function composerKey(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); void send(); }
}
let stop: (() => void) | undefined,
  open = true;
function save(c: Row | undefined) {
  credential.value = c;
  if (embedded) {
    window.parent.postMessage(
      { type: "support-credential", siteId, credential: c || null },
      parentOrigin,
    );
  } else {
    try {
      if (c) localStorage.setItem("support:" + siteId, JSON.stringify(c));
      else localStorage.removeItem("support:" + siteId);
    } catch {
      error.value = "浏览器无法保存凭证，关闭页面后将无法继续此会话。";
    }
  }
}
async function refresh() {
  if (!credential.value) return;
  try {
    const previous = messages.value.length;
    const batch = await api(
      `/sites/${siteId}/messages`,
      "GET",
      undefined,
      credential.value.token,
    );
    const map = new Map(messages.value.map((m) => [m.id, m]));
    for (const m of batch) map.set(m.id, m);
    messages.value = [...map.values()].sort(
      (a, b) => a.created_at - b.created_at,
    );
    if (
      embedded &&
      !open &&
      messages.value.length > previous &&
      batch.some((m: Row) => m.source !== "visitor")
    )
      window.parent.postMessage(
        { type: "support-unread", siteId },
        parentOrigin,
      );
  } catch (e: any) {
    if (e.status === 401) {
      stop?.();
      save(undefined);
      messages.value = [];
    }
    error.value = e.message;
  }
}
async function resume(c: Row) {
  if (!c.token || c.expires_at * 1000 <= Date.now()) {
    save(undefined);
    return;
  }
  stop?.();
  credential.value = c;
  try {
    const profile = await api(`/sites/${siteId}/me`, "GET", undefined, c.token);
    save({ ...c, email: profile.email });
  } catch (e: any) { error.value = e.message; }
  await refresh();
  if (credential.value)
    stop = connect(
      { role: "visitor", site_id: siteId, token: c.token },
      refresh,
      (s) => {
        state.value = s;
        if (s === "访问凭证已失效") {
          save(undefined);
          messages.value = [];
        }
      },
    );
}
async function start() {
  if (problemLength.value <= 5) { error.value = "请完善问题"; return; }
  busy.value = true;
  error.value = "";
  try {
    const c = await api(`/sites/${siteId}/sessions`, "POST", {
      email: email.value,
      problem: problem.value.trim(),
    });
    save(c);
    await resume(c);
  } catch (e: any) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function send() {
  if (!credential.value || busy.value || uploading.value) return;
  if (!body.value.trim() && !attachment.value) return;
  busy.value = true;
  error.value = "";
  pending.value = pending.value || {
    body: body.value,
    attachment_id: attachment.value || null,
    client_id: crypto.randomUUID(),
  };
  try {
    await api(
      `/sites/${siteId}/messages`,
      "POST",
      pending.value,
      credential.value.token,
    );
    body.value = "";
    attachment.value = "";
    pending.value = undefined;
    await refresh();
  } catch (e: any) {
    error.value = e.message + "；再次发送会使用相同消息编号重试。";
  } finally {
    busy.value = false;
  }
}
async function upload(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file || !credential.value) return;
  if (file.size > 5 * 1024 * 1024) {
    error.value = "图片不能超过 5MB";
    return;
  }
  uploading.value = true;
  try {
    const f = new FormData();
    f.append("file", file);
    attachment.value = (
      await api(`/sites/${siteId}/uploads`, "POST", f, credential.value.token)
    ).id;
  } catch (e: any) {
    error.value = e.message;
  } finally {
    uploading.value = false;
  }
}
async function older() {
  if (!credential.value || !messages.value.length) return;
  const rows = await api(
    `/sites/${siteId}/messages?before=${messages.value[0].created_at}`,
    "GET",
    undefined,
    credential.value.token,
  );
  messages.value = [...rows, ...messages.value];
}
function bridge(e: MessageEvent) {
  if (
    e.source !== window.parent ||
    e.origin !== parentOrigin ||
    e.data?.siteId !== siteId
  )
    return;
  if (e.data.type === "support-init" && e.data.credential)
    resume(e.data.credential);
  if (e.data.type === "support-open") open = e.data.open;
  if (e.data.type === "support-storage-error")
    error.value = "当前浏览器禁止保存访问凭证，关闭页面后将无法恢复此会话。";
}
onMounted(async () => {
  try {
    site.value = await api(`/sites/${siteId}/public`);
    if (embedded) {
      if (!site.value?.domains.includes(parentOrigin)) {
        error.value = "此网站未被授权嵌入聊天窗口";
        site.value = undefined;
        return;
      }
      window.addEventListener("message", bridge);
      window.parent.postMessage(
        { type: "support-ready", siteId, color: site.value?.color },
        parentOrigin,
      );
    } else {
      try {
        const c = JSON.parse(
          localStorage.getItem("support:" + siteId) || "null",
        );
        if (c) await resume(c);
      } catch {}
    }
  } catch (e: any) {
    error.value = e.message;
  }
});
onBeforeUnmount(() => {
  stop?.();
  window.removeEventListener("message", bridge);
});
</script>
<template>
  <div class="chat-shell" :style="{ '--accent': site?.color || '#2563eb' }">
    <header class="chat-header">
      <img v-if="site?.logo" :src="site.logo" alt="网站 Logo" />
      <div>
        <strong>{{ site?.title || "在线客服" }}</strong
        ><small>{{ site?.name }}<span v-if="site?.subtitle"> · {{ site.subtitle }}</span><span v-if="credential"> · {{ state }}</span></small>
      </div>
    </header>
    <p v-if="credential && site?.business_hours" class="chat-hours">{{ site.business_hours }}</p>
    <div v-if="error" class="alert" role="alert">{{ error }}</div>
    <form v-if="site && !credential" class="welcome" @submit.prevent="start">
      <span v-if="site.welcome_icon" class="welcome-icon">{{ site.welcome_icon }}</span>
      <h1 v-if="site.welcome_heading">{{ site.welcome_heading }}</h1>
      <p v-if="site.welcome">{{ site.welcome }}</p>
      <p v-if="site.business_hours" class="business-hours">{{ site.business_hours }}</p>
      <label
        >您的邮箱<input
          v-model="email"
          type="email"
          autocomplete="email"
          required
          placeholder="you@example.com" /></label
      ><label>{{ site.problem_prompt || "请直接说明您的问题，我们会尽快回复您。" }}<textarea v-model="problem" maxlength="12000" rows="3" placeholder="请描述您遇到的问题"></textarea></label><button :disabled="busy">{{ busy ? "正在开始…" : "开始聊天 →" }}</button
      ><small
        >此浏览器访问凭证保留 30 天。清除浏览器数据后，旧消息将无法恢复。</small
      >
    </form>
    <template v-if="credential"
      ><button class="older" @click="older().catch((e) => (error = e.message))">
        查看更早消息</button
      ><Messages
        :messages="messages"
        :token="credential.token"
        :site-id="siteId"
        :visitor-email="credential.email"
        :site-name="site?.name"
        perspective="visitor"
      />
      <form class="composer" @submit.prevent="send">
        <div v-if="attachment" class="attachment-ready">
          图片已准备好
          <button type="button" :disabled="!!pending" @click="attachment = ''">
            移除
          </button>
        </div>
        <textarea
          v-model="body"
          @keydown="composerKey"
          :disabled="!!pending"
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          rows="3"
          maxlength="12000"
          aria-label="消息正文"
        ></textarea>
        <div class="composer-actions">
          <label class="upload"
            >＋ 图片<input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              @change="upload"
              :disabled="busy || uploading || !!pending" /></label
          ><small>{{ uploading ? "上传中…" : site?.offline }}</small
          ><button :disabled="busy || uploading">
            {{ busy ? "发送中…" : pending ? "重试发送" : "发送 ↑" }}
          </button>
        </div>
      </form></template
    >
  </div>
</template>
