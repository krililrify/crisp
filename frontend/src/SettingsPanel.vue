<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api, date, type Row } from "./api";
import Editor from "./Editor.vue";
const props = defineProps<{ sites: Row[] }>();
const emit = defineEmits<{ refresh: [] }>();
const tab = ref("sites"),
  rows = ref<Row[]>([]),
  edit = ref<Row>(),
  error = ref(""),
  result = ref(""),
  batch = ref(""),
  barkEnabled = ref(true),
  page = ref(0);
const tabs = [
  ["sites", "网站管理"],
  ["telegram", "Telegram"],
  ["bark", "Bark 推送"],
  ["quick-replies", "快捷回复"],
  ["rules", "自动回复"],
  ["topics", "话题映射"],
  ["deliveries", "投递日志"],
  ["password", "修改密码"],
];
const names = Object.fromEntries(tabs);
const siteOptions = computed(() =>
  props.sites.map((s) => ({ value: s.id, label: s.name })),
);
const fields = computed<Row[]>(
  () =>
    ({
      sites: [
        { key: "name", label: "网站名称", required: true },
        {
          key: "domains",
          label: "允许嵌入的网站 Origin（每行一个）",
          type: "list",
          hint: "例如 https://example.com；www 域名需单独添加，不含尾部斜杠",
        },
        { key: "enabled", label: "启用网站", type: "checkbox" },
        { key: "title", label: "窗口标题" },
        { key: "subtitle", label: "顶部状态文案（留空不显示）" },
        { key: "welcome_heading", label: "欢迎页标题（留空不显示）" },
        { key: "welcome_icon", label: "欢迎页图标或 Emoji（留空不显示）" },
        { key: "business_hours", label: "营业时间说明（展示给客户）", type: "textarea" },
        { key: "problem_prompt", label: "问题描述引导文案", type: "textarea" },
        { key: "color", label: "主题颜色", type: "color" },
        { key: "logo", label: "Logo HTTPS 地址" },
        { key: "welcome", label: "欢迎语", type: "textarea" },
        { key: "offline", label: "等待回复提示", type: "textarea" },
      ],
      telegram: [
        {
          key: "bot_token",
          label: "Bot Token（留空保留原值）",
          type: "password",
        },
        {
          key: "chat_id",
          label: "超级群组 Chat ID，如 -1001234567890",
          required: true,
        },
        {
          key: "admin_ids",
          label: "授权客服 Telegram 用户 ID（每行一个）",
          type: "list",
          numbers: true,
          required: true,
        },
        {
          key: "webhook_secret",
          label: "Webhook Secret（留空保留，首次自动生成）",
          type: "password",
        },
      ],
      bark: [
        { key: "name", label: "设备名称", required: true },
        { key: "url", label: "Bark 地址（编辑时留空保留）", type: "password" },
        { key: "enabled", label: "启用", type: "checkbox" },
      ],
      "quick-replies": [
        { key: "title", label: "标题", required: true },
        { key: "category", label: "分类" },
        {
          key: "body",
          label: "Markdown 正文",
          type: "textarea",
          required: true,
        },
      ],
      rules: [
        {
          key: "site_id",
          label: "所属网站",
          type: "select",
          options: siteOptions.value,
        },
        {
          key: "kind",
          label: "触发类型",
          type: "select",
          options: [
            { value: "welcome", label: "首次咨询" },
            { value: "offline", label: "非工作时间" },
            { value: "keyword", label: "关键词" },
          ],
        },
        { key: "keyword", label: "关键词（不区分大小写）" },
        {
          key: "body",
          label: "Markdown 回复正文",
          type: "textarea",
          required: true,
        },
        { key: "enabled", label: "启用", type: "checkbox" },
        { key: "cooldown", label: "冷却时间（秒，至少 60）", type: "number" },
        { key: "timezone", label: "时区" },
        { key: "start_hour", label: "工作开始时（0-23）", type: "number" },
        {
          key: "end_hour",
          label: "工作结束时（0-23，可跨午夜）",
          type: "number",
        },
        {
          key: "weekdays",
          label: "工作日（0 周一至 6 周日）",
          type: "list",
          numbers: true,
        },
      ],
      topics: [
        { key: "chat_id", label: "群组 Chat ID", required: true },
        {
          key: "thread_id",
          label: "正确的话题 ID",
          type: "number",
          required: true,
        },
      ],
      password: [
        {
          key: "old_password",
          label: "原密码",
          type: "password",
          required: true,
        },
        {
          key: "new_password",
          label: "新密码（至少 12 位）",
          type: "password",
          required: true,
        },
      ],
    })[tab.value] || [],
);
async function load() {
  edit.value = undefined;
  error.value = "";
  result.value = "";
  try {
    if (tab.value === "password") {
      rows.value = [];
      edit.value = { old_password: "", new_password: "" };
      return;
    }
    const r = await api(
      "/admin/" +
        (tab.value === "bark" ? "bark" : tab.value) +
        (tab.value === "deliveries" ? `?offset=${page.value * 100}` : ""),
    );
    if (tab.value === "bark") {
      rows.value = r.devices;
      barkEnabled.value = r.enabled;
    } else if (tab.value === "telegram") {
      rows.value = [];
      edit.value = { ...r, bot_token: "", webhook_secret: "" };
    } else rows.value = r;
  } catch (e: any) {
    error.value = e.message;
  }
}
watch(
  tab,
  () => {
    page.value = 0;
    load();
  },
  { immediate: true },
);
function add() {
  const defaults: Row = {
    sites: {
      name: "",
      domains: [],
      enabled: true,
      title: "在线客服",
      subtitle: "私密对话",
      welcome_heading: "很高兴为您服务",
      welcome_icon: "✦",
      business_hours: "",
      problem_prompt: "请直接说明您的问题，我们会尽快回复您。",
      color: "#2563eb",
      welcome: "您好，请留下邮箱开始咨询。",
      offline: "我们会尽快回复。",
      logo: "",
    },
    bark: { name: "iPhone", url: "", enabled: true },
    "quick-replies": { title: "", category: "常用", body: "" },
    rules: {
      site_id: props.sites[0]?.id,
      kind: "welcome",
      enabled: true,
      keyword: "",
      body: "",
      cooldown: 300,
      timezone: "Asia/Shanghai",
      start_hour: 9,
      end_hour: 18,
      weekdays: [0, 1, 2, 3, 4],
    },
  };
  edit.value = defaults[tab.value];
}
async function save(data: Row) {
  error.value = "";
  try {
    const id = edit.value?.id || edit.value?.customer_id;
    const path = tab.value === "bark" ? "bark/devices" : tab.value;
    const singleton = ["telegram", "password"].includes(tab.value);
    const method =
      tab.value === "password" ? "POST" : singleton || id ? "PUT" : "POST";
    const response = await api(
      "/admin/" + path + (!singleton && id ? "/" + id : ""),
      method,
      data,
    );
    if (tab.value === "password") {
      location.reload();
      return;
    }
    await load();
    result.value = response.warning || (tab.value === "telegram" ? "已保存并自动注册 Webhook，新配置已生效" : "已保存，新配置已生效");
    emit("refresh");
  } catch (e: any) {
    error.value = e.message;
  }
}
async function action(path: string, method = "POST", body?: Row) {
  error.value = "";
  result.value = "";
  try {
    const value = await api("/admin/" + path, method, body);
    await load();
    result.value = JSON.stringify(value, null, 2);
  } catch (e: any) {
    error.value = e.message;
  }
}
async function remove(r: Row) {
  if (confirm("确定删除此配置？"))
    await action(
      (tab.value === "bark" ? "bark/devices" : tab.value) + "/" + r.id,
      "DELETE",
    );
}
function embed(r: Row) {
  result.value =
    `<script src="${location.origin}/widget.js" data-site-id="${r.id}" async><` +
    "/script>\n\n独立页面：" +
    location.origin +
    "/chat/?site=" +
    r.id;
}
</script>
<template>
  <section class="settings">
    <nav class="settings-tabs">
      <button
        v-for="t in tabs"
        :key="t[0]"
        class="secondary"
        :class="{ selected: tab === t[0] }"
        @click="tab = t[0]"
      >
        {{ t[1] }}
      </button>
    </nav>
    <div class="settings-content">
      <div class="section-heading">
        <h1>{{ names[tab] }}</h1>
        <button
          v-if="['sites', 'bark', 'quick-replies', 'rules'].includes(tab)"
          @click="add"
        >
          ＋ 添加</button
        ><button class="secondary" @click="load">刷新</button>
      </div>
      <div v-if="error" class="alert">{{ error }}</div>
      <pre v-if="result" class="result">{{ result }}</pre>
      <div v-if="tab === 'telegram'" class="info">
        Bot 需进入启用 Topics 的超级群组，并拥有管理话题权限。请在 BotFather
        关闭隐私模式，使 Bot 能收到普通客服消息。保存会自动注册 Webhook，无需另点注册。
        <div class="actions">
          <button @click="action('telegram/test')">测试连接</button
          ><button @click="action('telegram/webhook')">注册 Webhook</button>
        </div>
      </div>
      <div v-if="tab === 'bark'" class="info">
        <label
          ><input
            type="checkbox"
            :checked="barkEnabled"
            @change="action('bark?enabled=' + !barkEnabled, 'PUT')"
          />
          全局启用 Bark</label
        >
        <p>
          设备密钥仅保存在后端。测试结果表示 API 是否接受请求，不代表 iPhone
          已收到通知。
        </p>
        <textarea
          v-model="batch"
          placeholder="批量添加：英文逗号或换行分隔完整 Bark 地址"
          rows="3"
        ></textarea>
        <div class="actions">
          <button @click="action('bark/batch', 'POST', { urls: batch })">
            批量添加</button
          ><button @click="action('bark/test')">测试全部启用设备</button>
        </div>
      </div>
      <Editor
        v-if="edit"
        :key="tab + String(edit.id || edit.customer_id || 'new')"
        :fields="fields"
        :value="edit"
        @save="save"
        @cancel="edit = undefined"
      />
      <div v-if="tab === 'deliveries'" class="info">
        sent 表示外部 API 接受请求；failed
        表示重试耗尽。修复配置或话题映射后可重新执行失败任务。
        <div class="actions">
          <button
            :disabled="page === 0"
            @click="
              page--;
              load();
            "
          >
            上一页</button
          ><span>第 {{ page + 1 }} 页</span
          ><button
            :disabled="rows.length < 100"
            @click="
              page++;
              load();
            "
          >
            下一页
          </button>
        </div>
      </div>
      <article
        v-for="r in rows"
        :key="r.id || r.customer_id"
        class="config-row"
      >
        <div>
          <strong>{{ r.name || r.title || r.email || r.kind }}</strong
          ><small v-if="r.id">{{ r.id }}</small>
          <p v-if="tab === 'sites'">
            {{ r.domains.join(" · ") }} · {{ r.enabled ? "启用" : "停用" }}
          </p>
          <p v-if="tab === 'bark'">
            {{ r.url_hint }} · {{ r.enabled ? "启用" : "停用" }}
          </p>
          <p v-if="tab === 'rules'">
            {{ sites.find((s) => s.id === r.site_id)?.name }} · {{ r.kind }} ·
            {{ r.enabled ? "启用" : "停用" }}
          </p>
          <p v-if="tab === 'quick-replies'">
            {{ r.category }} · {{ r.body.slice(0, 160) }}
          </p>
          <p v-if="tab === 'topics'">
            群组 {{ r.chat_id }} / 话题 {{ r.thread_id || "待修复" }}<br />{{
              r.error
            }}
          </p>
          <p v-if="tab === 'deliveries'">
            {{ r.device_name || "" }} · {{ r.status }} · 尝试
            {{ r.attempts }} 次 · HTTP {{ r.http_status || "—" }}<br />创建
            {{ date(r.created_at) }}<br />完成
            {{ r.sent_at ? date(r.sent_at) : "—" }}<br />{{ r.error }}
          </p>
        </div>
        <div class="actions">
          <button
            v-if="tab !== 'deliveries'"
            class="secondary"
            @click="edit = { ...r, url: '' }"
          >
            编辑</button
          ><button v-if="tab === 'sites'" @click="embed(r)">接入代码</button
          ><button
            v-if="tab === 'bark'"
            @click="action('bark/test?device_id=' + r.id)"
          >
            测试</button
          ><button
            v-if="['bark', 'quick-replies', 'rules'].includes(tab)"
            class="danger secondary"
            @click="remove(r)"
          >
            删除</button
          ><button
            v-if="
              tab === 'deliveries' && ['pending', 'failed'].includes(r.status)
            "
            @click="action('deliveries/' + r.id + '/retry')"
          >
            重试
          </button>
        </div>
      </article>
      <div v-if="!rows.length && !edit" class="empty">暂无配置</div>
    </div>
  </section>
</template>
