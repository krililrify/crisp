export type Row = Record<string, any>;
export let csrf = "";
export const setCsrf = (v: string) => {
  csrf = v;
};
export async function api(
  path: string,
  method = "GET",
  data?: unknown,
  token?: string,
): Promise<any> {
  const headers: Record<string, string> = {};
  if (data && !(data instanceof FormData))
    headers["Content-Type"] = "application/json";
  if (csrf) headers["X-CSRF-Token"] = csrf;
  if (token) headers.Authorization = "Bearer " + token;
  const r = await fetch("/api" + path, {
    method,
    headers,
    credentials: "same-origin",
    body: data
      ? data instanceof FormData
        ? data
        : JSON.stringify(data)
      : undefined,
  });
  if (!r.ok) {
    let detail: any;
    try {
      detail = (await r.json()).detail;
    } catch {
      detail = r.statusText;
    }
    const message =
      typeof detail === "string" ? detail : JSON.stringify(detail);
    throw Object.assign(new Error(message || "请求失败"), { status: r.status });
  }
  return r.json();
}
export function connect(
  auth: Row,
  onChange: () => void,
  onState: (state: string) => void,
) {
  let socket: WebSocket | undefined,
    timer: number | undefined,
    stopped = false,
    attempt = 0;
  function open() {
    if (stopped) return;
    socket = new WebSocket(
      `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/ws`,
    );
    socket.onopen = () => {
      socket?.send(JSON.stringify(auth));
      attempt = 0;
      onState("已连接");
    };
    socket.onmessage = () => onChange();
    socket.onclose = (event) => {
      if (stopped) return;
      if (event.code === 4401 || event.code === 4403) {
        onState("访问凭证已失效");
        return;
      }
      onState("连接中断，正在重连…");
      timer = window.setTimeout(
        open,
        Math.min(30000, 1000 * 2 ** attempt++) + Math.random() * 500,
      );
    };
    socket.onerror = () => socket?.close();
  }
  open();
  return () => {
    stopped = true;
    clearTimeout(timer);
    socket?.close();
  };
}
export const date = (v: number) => new Date(v * 1000).toLocaleString();
