<script setup lang="ts">
import Admin from "./Admin.vue";
import Chat from "./Chat.vue";
const isChat = location.pathname.startsWith("/chat");
</script>
<template><Chat v-if="isChat" /><Admin v-else /></template>
