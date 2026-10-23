<script setup lang="ts">
import { watch, nextTick, ref, onBeforeUnmount } from "vue";
import { date, type Row } from "./api";
const props = defineProps<{
  messages: Row[];
  token?: string;
  siteId?: string;
}>();
const list = ref<HTMLElement>(),
  urls = new Map<string, string>(),
  pictures = ref<Record<string, string>>({});
function zoom(e: MouseEvent) {
  const img = e.target;
  if (
    img instanceof HTMLImageElement &&
    img.parentElement?.tagName !== "A" &&
    /^(https:|blob:)/.test(img.src)
  )
    window.open(img.src, "_blank", "noopener,noreferrer");
}
let alive = true;
watch(
  () => props.messages,
  async () => {
    const nearBottom =
      !list.value ||
      list.value.scrollHeight - list.value.scrollTop - list.value.clientHeight <
        160;
    for (const m of props.messages) {
      if (m.attachment_id && !urls.has(m.attachment_id)) {
        const id = m.attachment_id;
        const r = await fetch(
          `/api/attachments/${encodeURIComponent(id)}?site_id=${encodeURIComponent(props.siteId || "")}`,
          {
            headers: props.token
              ? { Authorization: "Bearer " + props.token }
              : {},
            credentials: "same-origin",
          },
        );
        if (r.ok && alive) {
          const u = URL.createObjectURL(await r.blob());
          urls.set(id, u);
          pictures.value[id] = u;
        }
      }
    }
    await nextTick();
    if (nearBottom)
      list.value?.scrollTo({
        top: list.value.scrollHeight,
        behavior: "smooth",
      });
  },
  { deep: true, immediate: true },
);
onBeforeUnmount(() => {
  alive = false;
  urls.forEach((u) => URL.revokeObjectURL(u));
});
</script>
<template>
  <div ref="list" class="messages" aria-live="polite" @click="zoom">
    <div v-if="!messages.length" class="empty">对话将从这里开始</div>
    <article
      v-for="m in messages"
      :key="m.id"
      class="message"
      :class="m.source === 'visitor' ? 'visitor' : 'agent'"
    >
      <div class="message-label">
        {{
          (
            {
              visitor: "客户",
              admin: "客服",
              telegram: "客服 · Telegram",
              auto: "自动回复",
              ai: "AI",
            } as Row
          )[m.source] || m.source
        }}
        · {{ date(m.created_at) }}
      </div>
      <div class="bubble">
        <div class="markdown" v-html="m.html"></div>
        <a
          v-if="pictures[m.attachment_id]"
          :href="pictures[m.attachment_id]"
          target="_blank"
          rel="noopener"
          ><img
            :src="pictures[m.attachment_id]"
            alt="聊天图片，点击查看大图"
            @load="list?.scrollTo({ top: list.scrollHeight })"
        /></a>
      </div>
      <small>{{
        m.status === "stored"
          ? "已保存"
          : m.status === "forwarded"
            ? "已同步 Telegram"
            : m.status
      }}</small>
    </article>
  </div>
</template>
