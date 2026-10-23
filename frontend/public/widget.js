(() => {
  "use strict";
  const script = document.currentScript;
  if (!script) return;
  const siteId = script.dataset.siteId;
  if (!siteId) return;
  const service = new URL(script.src).origin,
    origin = location.origin,
    key = "support:" + service + ":" + siteId;
  if (
    document.querySelector('[data-support-site="' + CSS.escape(siteId) + '"]')
  )
    return;
  const host = document.createElement("div");
  host.dataset.supportSite = siteId;
  const shadow = host.attachShadow({ mode: "open" }),
    style = document.createElement("style");
  style.textContent = `:host{all:initial!important;position:fixed!important;right:18px!important;bottom:max(18px,env(safe-area-inset-bottom))!important;z-index:2147483000!important;font-family:system-ui!important}.launcher{width:58px;height:58px;border:0;border-radius:21px;background:#2563eb;color:white;font-size:25px;box-shadow:0 8px 30px #1e4d7350;cursor:pointer;position:relative}.badge{position:absolute;right:-2px;top:-3px;background:#e43d54;border:3px solid white;width:16px;height:16px;border-radius:100%}.panel{position:absolute;bottom:76px;right:0;width:380px;height:min(650px,calc(100dvh - 120px));border:0;border-radius:18px;background:white;box-shadow:0 12px 70px #162d4a38;display:none}.panel.open{display:block}@media(max-width:480px){:host{right:12px!important;bottom:12px!important}.panel{position:fixed;inset:0;width:100%;height:calc(100dvh - 82px);border-radius:0}.launcher{width:54px;height:54px}}`;
  const button = document.createElement("button");
  button.className = "launcher";
  button.type = "button";
  button.textContent = "☏";
  button.setAttribute("aria-label", "打开在线客服");
  button.setAttribute("aria-expanded", "false");
  const frame = document.createElement("iframe");
  frame.className = "panel";
  frame.title = "在线客服";
  frame.referrerPolicy = "no-referrer";
  frame.src =
    service +
    "/chat/?site=" +
    encodeURIComponent(siteId) +
    "&parent=" +
    encodeURIComponent(origin);
  frame.setAttribute(
    "sandbox",
    "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-forms",
  );
  let open = false,
    credential;
  try {
    credential = JSON.parse(localStorage.getItem(key) || "null");
    if (credential?.expires_at * 1000 <= Date.now()) {
      localStorage.removeItem(key);
      credential = null;
    }
  } catch {}
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.hidden = true;
  button.appendChild(badge);
  function post(data) {
    frame.contentWindow?.postMessage({ ...data, siteId }, service);
  }
  button.onclick = () => {
    open = !open;
    frame.classList.toggle("open", open);
    button.setAttribute("aria-expanded", String(open));
    button.setAttribute("aria-label", open ? "最小化在线客服" : "打开在线客服");
    button.firstChild.textContent = open ? "×" : "☏";
    if (open) badge.hidden = true;
    post({ type: "support-open", open });
  };
  window.addEventListener("message", (e) => {
    if (
      e.source !== frame.contentWindow ||
      e.origin !== service ||
      e.data?.siteId !== siteId
    )
      return;
    if (e.data.type === "support-ready") {
      if (/^#[0-9a-f]{6}$/i.test(e.data.color))
        button.style.background = e.data.color;
      post({ type: "support-init", credential });
      post({ type: "support-open", open });
    }
    if (e.data.type === "support-credential") {
      credential = e.data.credential;
      try {
        if (credential) localStorage.setItem(key, JSON.stringify(credential));
        else localStorage.removeItem(key);
      } catch {
        post({ type: "support-storage-error" });
      }
    }
    if (e.data.type === "support-unread" && !open) badge.hidden = false;
  });
  shadow.append(style, frame, button);
  (document.body || document.documentElement).appendChild(host);
})();
