<script setup lang="ts">
import { reactive } from "vue";
import type { Row } from "./api";
const props = defineProps<{ fields: Row[]; value: Row }>();
const emit = defineEmits<{ save: [Row]; cancel: [] }>();
const draft = reactive<Row>({ ...props.value });
for (const f of props.fields) {
  if (f.type === "list") draft[f.key] = (draft[f.key] || []).join("\n");
}
function submit() {
  const out = { ...draft };
  for (const f of props.fields) {
    if (f.type === "list")
      out[f.key] = String(out[f.key] || "")
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean)
        .map((s) => (f.numbers ? Number(s) : s));
  }
  emit("save", out);
}
</script>
<template>
  <form class="editor" @submit.prevent="submit">
    <label v-for="f in fields" :key="f.key"
      >{{ f.label
      }}<textarea
        v-if="f.type === 'textarea' || f.type === 'list'"
        v-model="draft[f.key]"
        :required="f.required"
        rows="4"
      ></textarea
      ><select v-else-if="f.type === 'select'" v-model="draft[f.key]">
        <option
          v-for="o in f.options"
          :key="o.value || o"
          :value="o.value || o"
        >
          {{ o.label || o }}
        </option></select
      ><input
        v-else-if="f.type === 'checkbox'"
        type="checkbox"
        v-model="draft[f.key]"
      /><input
        v-else-if="f.type === 'number'"
        type="number"
        v-model.number="draft[f.key]"
        :required="f.required"
      /><input
        v-else
        :type="f.type || 'text'"
        v-model="draft[f.key]"
        :required="f.required"
        :autocomplete="f.type === 'password' ? 'new-password' : 'off'"
      /><small v-if="f.hint">{{ f.hint }}</small></label
    >
    <div class="actions">
      <button>保存</button
      ><button class="secondary" type="button" @click="emit('cancel')">
        取消
      </button>
    </div>
  </form>
</template>
