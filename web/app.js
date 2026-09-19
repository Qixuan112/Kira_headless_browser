// ─────────────────────────────────────────────────────────────
//  全能浏览器 · 侧边栏 WebUI
//  ⚠️ 插件 id 必须与 manifest.json 的 plugin_id 一致 ——
//     框架把插件 API 挂在 /api/plugin/{plugin_id}/... 下，对不上就是 404。
// ─────────────────────────────────────────────────────────────
const API = "/api/plugin/headless_browser";

/* ── Lucide 图标（内联 SVG，界面全程不用表情符号）────────────
   取 Lucide 的官方路径子集；stroke 用 currentColor，尺寸交给 CSS。  */
const P = {
  eye:'<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
  'eye-off':'<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
  monitor:'<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>',
  plug:'<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
  sliders:'<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
  image:'<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
  shield:'<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  clock:'<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  folder:'<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  activity:'<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
  refresh:'<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  copy:'<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  key:'<path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4"/><path d="m21 2-9.6 9.6"/><circle cx="7.5" cy="15.5" r="5.5"/>',
  alert:'<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  check:'<path d="M20 6 9 17l-5-5"/>',
  save:'<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/><path d="M7 3v4a1 1 0 0 0 1 1h7"/>',
  sparkle:'<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
  link:'<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
};
const icon = (n, cls) =>
  `<svg class="${cls || ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
  `stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${P[n] || ''}</svg>`;

const $ = (id) => document.getElementById(id);

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2000);
}

/** 打**框架自己**的接口（不带插件前缀）。
 *
 *  `api()` 会把路径拼到 `/api/plugin/<id>` 下面 —— 想读框架的
 *  provider / model 列表得绕出去，所以单独留一个。
 *  同样带 kira_token cookie，否则会被拒。
 */

async function api(path, opts) {
  const o = Object.assign({
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",          // 带上 kira_token cookie
  }, opts || {});
  // ⚠️⚠️ **非 GET 必须带 body，哪怕是空的 `{}`** ——
  //    框架官方的 Bridge SDK（webui/frontend/public/plugin-bridge.js）就是
  //    `body: JSON.stringify(body || {})`，永远给一个。
  //    我们这边原来 POST 一个字节都不发 ✗：带着
  //    `Content-Type: application/json` 却没有 body，FastAPI 解析 JSON 失败
  //    → **422** → 界面就显示"读取失败" / "保存失败"。
  //    （旧版面板也不带 body，但在**旧框架**上没这么严；KiraAI 现在 2.34.x
  //     收紧了这一条 —— 这就是"旧版行、重写后不行"的真正原因 ✗）
  const m = String(o.method || "GET").toUpperCase();
  if (m !== "GET" && m !== "HEAD" && o.body == null) o.body = "{}";
  const res = await fetch(API + path, o);
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// ── 状态轮询 ──────────────────────────────────────────────────
// ⚠️ 一次 /status 可能比轮询间隔还慢（桥接卡一下就会）。fetch 不保证先发先回，
//    旧请求后到会把新状态覆盖回去 —— 只认"最后一次发出"的响应。
let _refreshSeq = 0;

async function refresh() {
  const seq = ++_refreshSeq;
  let s;
  // ⚠️ **取数和渲染分开**：原来整个塞在一个 try 里，渲染里任何一个小错
  //    （比如某个 DOM 节点没找到）都会被 catch 当成"请求失败"，
  //    界面显示"读取失败" —— 明明是渲染的问题，却指向了网络 ✗
  try {
    s = await api("/status");
  } catch (e) {
    if (seq === _refreshSeq) {
      $("conn").innerHTML = `<span class="dot err"></span>读取失败`;
      $("connHint").style.display = "";
      $("connHint").innerHTML = "状态读取失败：" + String(e.message || e);
    }
    return;
  }
  if (seq !== _refreshSeq) return;                  // 有更新的请求 → 丢弃这次结果
  renderStatus(s);
}

/* ── 连接状态 ────────────────────────────────────────────────── */
function renderStatus(s) {
  const b = s.bridge || {};
  const on = !!b.connected;
  $("conn").innerHTML = on
    ? `<span class="dot on"></span>已连接`
    : `<span class="dot off"></span>未连接`;

  // ⚠️ 未连接时必须给出下一步，而且第一步就是"打开一次这个页面" ——
  //    扩展是靠**页面自己的地址**（host + port）认出 KiraAI 在哪儿的，
  //    用户打开这个面板的那一刻接入信息就推过去了，不用手填、也不用管端口。
  const h = $("connHint");
  if (on) { h.style.display = "none"; }
  else {
    h.style.display = "";
    h.innerHTML = "扩展没连上？<b>打开一次这个页面</b>就行 —— " +
      "扩展会从这个页面的地址认出 KiraAI 在哪个端口（不用手填、也不用管端口是不是常见的）。" +
      "<br>还不行的话：点一下浏览器上的扩展图标，看它自己报什么错。";
  }

  // ⚠️ 字段名要和 /status 的真实结构对上（bridge.info 里是 extension_version /
  //    commands_sent；策略在 router.strategy 下）—— 写错界面就全是"—"。
  const rt = s.router || {};
  $("route").textContent = rt.describe || "—";
  $("strategy").textContent = rt.strategy || "—";
  $("cmds").textContent = (b.commands_sent || 0) + " / " + (b.commands_failed || 0);
  $("extVer").textContent = b.extension_version || "—";
  $("browser").textContent = b.browser || "—";
  if (s.plugin_version) $("ver").textContent = "v" + s.plugin_version;

  const pol = s.policy || {};
  _renderDomains($("domains"), pol.allowed_domains, pol.blocked_domains, pol.local_access);
  renderConfirmLog(s.confirm_log);
}

/* ── 域名与确认记录 ──────────────────────────────────────────────
   ⚠️ 这两块渲染的**不是我们写的字**：域名来自用户配置、确认记录里带着
      模型给的理由和用户的选择。所以一律用 DOM 节点 + textContent 拼 ——
      **绝不 innerHTML**，否则用户把域名写成 `<img onerror=...>` 就是一次注入。
   （受控字段——比如 schema 里的说明文字——才可以走 innerHTML。）        */
function _renderDomains(box, allowedRaw, blockedRaw, localAccess) {
  if (!box) return;
  box.textContent = "";
  const listRow = (label, items, emptyText) => {
    const row = document.createElement("div");
    row.className = "hint";
    const b = document.createElement("b");
    b.textContent = label + "：";
    row.appendChild(b);
    row.appendChild(document.createTextNode(
      items && items.length ? " " + items.join("、") : " " + emptyText));
    return row;
  };
  box.appendChild(listRow("允许", allowedRaw, "未限制（除下列黑名单）"));
  box.appendChild(listRow("禁止", blockedRaw, "无"));
  if (localAccess === false) {
    const w = document.createElement("div");
    w.className = "hint";
    w.textContent = "本机/内网地址：已拒绝";
    box.appendChild(w);
  }
}

function renderConfirmLog(log) {
  const box = $("clog");
  if (!box) return;
  box.textContent = "";
  (log || []).slice(0, 8).forEach((c) => {
    const row = document.createElement("div");
    row.className = "hint";
    row.textContent = `[${c.time || ""}] ${c.action || ""} ${c.answer || ""} `
                    + `${c.reason || ""}`.trim();
    box.appendChild(row);
  });
}

/* 令牌显示：**默认遮住** —— 它是连接凭据，不该一打开就摊在屏幕上
   （旁边有人、或者投屏的时候特别尴尬）。点眼睛才显示。
   ⚠️ 值一直存在 dataset 里，复制按钮用的也是它，所以遮住不影响复制。 */
let _tokShown = false;
function renderToken() {
  const t = $("tokBox").dataset.token || "";
  if (!t) { $("tok").textContent = "（无）"; return; }
  $("tok").textContent = _tokShown ? t : "•".repeat(28);
  const eye = $("eye");
  if (eye) {
    eye.innerHTML = icon(_tokShown ? "eye" : "eye-off");
    eye.title = _tokShown ? "隐藏令牌" : "显示令牌";
  }
}

/* ── 令牌 ────────────────────────────────────────────────────── */
let _tokenSeq = 0;

async function loadToken(force) {
  const seq = ++_tokenSeq;
  try {
    // ⚠️⚠️ `force` 必须走 **query**，不能放 JSON body ——
    //    FastAPI 对简单类型（bool）默认按 query 绑定；塞进 body 的话
    //    根本没绑上 → 端点走它自己的默认值 `force=True` →
    //    **每次打开面板都会重新生成令牌** ✗✗✗
    //    （旧令牌当场作废 → 扩展刚配对好就又连不上了）
    //    所以：只是读取就 `force=false`，只有点「重新生成」才给 true。
    const r = await api(`/token?force=${force ? "true" : "false"}`, {
      method: "POST",
    });
    if (seq !== _tokenSeq) return;
    const t = r.token || "";
    $("tokBox").dataset.token = t;
    renderToken();                       // 默认遮住，点了眼睛才显示
    pairWithExtension(t);
  } catch (e) {
    if (seq === _tokenSeq) $("tok").textContent = "读取失败";
  }
}

async function regen() {
  const btn = $("regen");
  btn.disabled = true;
  try {
    // 重新生成：这才是 force=true（旧令牌当场作废）
    const r = await api("/token?force=true", { method: "POST" });
    if (!r.ok) throw new Error(r.error || "失败");
    $("tokBox").dataset.token = r.token || "";
    renderToken();
    pairWithExtension(r.token || "");
    toast(r.changed ? "已生成新令牌（旧令牌已作废）" : "令牌未变化");
  } catch (e) {
    toast("生成失败：" + (e.message || e));
  } finally {
    btn.disabled = false;
  }
}

function copyToken() {
  const t = $("tokBox").dataset.token || "";
  if (!t) { toast("还没有令牌"); return; }
  navigator.clipboard.writeText(t).then(
    () => toast("已复制到剪贴板"),
    () => toast("复制失败，请手动选中复制"));
}

/* ── 零配置接入：把接入信息推给扩展 ──────────────────────────────
   ⚠️ 这条是"打开面板即配对"的关键，别动：
      pairing-page.js 内容脚本只在本机/私网页面上跑，
      收到这个 postMessage 后转给扩展，扩展据此记住 host/port/token。   */
function pairWithExtension(token) {
  try {
    window.postMessage({
      __kiraPair: true,
      host: location.hostname || "127.0.0.1",
      port: Number(location.port) || 80,
      token: token || "",
      origin: location.origin,
    }, location.origin);
  } catch (_) { /* 推不出去就算了，用户可以手填 */ }
}

/* ─────────────────────────────────────────────────────────────
   配置：界面从 schema.json 长出来 —— 一处真源。
   后端 /config 会把 schema 原样返回，这里只负责分组 + 渲染 +
   改完立刻 POST 回后端（后端热应用，不用重启）。
   ───────────────────────────────────────────────────────────── */
const GROUPS = [
  { id: "conn",  name: "连接",   icon: "plug",     keys: ["backend_strategy","extension_enabled","headless_enabled","allow_remote_pairing","panel_auth_required"] },
  { id: "behav", name: "行为",   icon: "sliders",  keys: ["read_only","require_confirm","return_page_after_write","allow_history","inject_page_state"] },
  { id: "vision",name: "视觉",   icon: "image",    keys: ["vlm_model","auto_describe_screenshot","vlm_compress","vlm_compress_max_size","vlm_compress_quality","vlm_timeout","vlm_describe_prompt"] },
  { id: "safety",name: "安全",   icon: "shield",   keys: ["local_access","allowed_domains","blocked_domains","upload_allow_any_path","upload_allowed_dirs","upload_max_bytes"] },
  { id: "time",  name: "超时",   icon: "clock",    keys: ["op_timeout","action_timeout","download_timeout","default_wait_until","op_timeout_follows_framework","op_timeout_ratio"] },
  { id: "store", name: "存储",   icon: "folder",   keys: ["screenshot_dir","download_dir","cookies_dir","download_auto_clean","download_max_count","max_content_chars"] },
];

let SCHEMA = {}, VALUES = {}, INFO_BLOCKS = [], MODEL_OPTIONS = {};
const LOCALE = (navigator.language || "zh").toLowerCase().startsWith("zh") ? "zh" : "en";

function labelOf(key, meta) {
  const loc = (meta && meta.locales && meta.locales[LOCALE]) || {};
  return loc.name || (meta && meta.name) || key;
}
function hintOf(key, meta) {
  const loc = (meta && meta.locales && meta.locales[LOCALE]) || {};
  return loc.hint || (meta && meta.hint) || "";
}
/** 把 markdown 的 **粗体** 转成 <b>（描述里常用），其余转义。 */
function fmt(s) {
  return String(s || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}

function fieldHTML(key) {
  const meta = SCHEMA[key] || {};
  const type = meta.type || "string";
  const v = VALUES[key];
  const lab = `<div class="lab">${fmt(labelOf(key, meta))}</div>`;
  const sub = hintOf(key, meta) ? `<div class="sub">${fmt(hintOf(key, meta))}</div>` : "";
  if (type === "switch") {
    const on = v !== false && v !== "false";
    return `<div class="field" data-k="${key}">${lab}${sub}
      <label class="sw"><input type="checkbox" data-k="${key}" ${on ? "checked" : ""}>
      <span class="track"></span><span class="knob"></span></label></div>`;
  }
  if (Array.isArray(v)) {
    return `<div class="field full" data-k="${key}">${lab}
      <textarea data-k="${key}" spellcheck="false">${(v || []).join("\n")}</textarea>${sub}</div>`;
  }
  if (type === "integer" || type === "number") {
    return `<div class="field" data-k="${key}">${lab}
      <input type="number" data-k="${key}" value="${v ?? ""}">${sub}</div>`;
  }
  // ⚠️ `model_select` 要渲染成**下拉**，不是文本框 —— 框架那边就是这么给的
  //    （它的设置页里这类字段是下拉框）。模型列表是从框架的
  //    /api/providers/<id>/models 拉来的：拉得到就出真正的 <select>，
  //    拉不到（比如接口没权限）就**优雅退回文本框**，并说明格式 ——
  //    总比给一个空下拉、用户没法选要好。
  if (type === "model_select" || type === "persona_select" || type === "session_select") {
    const opts = (MODEL_OPTIONS[key] || []);
    if (!opts.length) {
      return `<div class="field" data-k="${key}">${lab}
        <input data-k="${key}" value="${v ?? ""}" placeholder="（没能取到模型列表，可直接填模型名）">
        <div class="sub">${fmt(hintOf(key, meta))} 取不到列表时可以直接填模型名。</div></div>`;
    }
    const cur = String(v ?? "");
    const has = opts.some((o) => o.value === cur);
    return `<div class="field" data-k="${key}">${lab}
      <select data-k="${key}">
        <option value=""${cur ? "" : " selected"}>（用默认）</option>
        ${opts.map((o) => `<option value="${fmt(o.value)}"${o.value === cur ? " selected" : ""}>`
                          + `${fmt(o.label)}</option>`).join("")}
        ${cur && !has ? `<option value="${fmt(cur)}" selected>${fmt(cur)}（当前，已不在列表里）</option>` : ""}
      </select>${sub}</div>`;
  }
  // 长文本用 textarea
  const long = key.endsWith("_prompt") || String(v || "").length > 60;
  if (long) {
    return `<div class="field full" data-k="${key}">${lab}
      <textarea data-k="${key}" spellcheck="false">${v ?? ""}</textarea>${sub}</div>`;
  }
  return `<div class="field" data-k="${key}">${lab}
    <input type="text" data-k="${key}" value="${v ?? ""}">${sub}</div>`;
}

function renderConfig() {
  const used = new Set();
  const out = [];
  for (const g of GROUPS) {
    const keys = g.keys.filter((k) => k in SCHEMA);
    if (!keys.length) continue;
    keys.forEach((k) => used.add(k));
    out.push(`<section class="sec" id="sec-${g.id}">
      <h3>${icon(g.icon)}${g.name}</h3>
      <div class="card"><div class="pad">${keys.map(fieldHTML).join("")}</div></div>
    </section>`);
  }
  // 说明块：放在配置区**最上面**（和框架设置页里那个 info 是同一段话）
  if (INFO_BLOCKS.length) {
    out.unshift(INFO_BLOCKS.map((f) => {
      const zh = (f.locales || {}).zh || {};
      const title = zh.name || f.name || "说明";
      // 走现成的 fmt()：它做 HTML 转义，再把 **粗体** / `代码` / 换行转好
      return `<section class="sec" id="sec-note"><div class="note info">`
        + `<b>${fmt(title)}</b><p>${fmt(zh.hint || f.hint || "")}</p></div></section>`;
    }).join(""));
  }

  const rest = Object.keys(SCHEMA).filter((k) => !used.has(k));
  if (rest.length) {
    out.push(`<section class="sec" id="sec-more">
      <h3>${icon("sparkle")}其他</h3>
      <div class="card"><div class="pad">${rest.map(fieldHTML).join("")}</div></div>
    </section>`);
  }
  $("config").innerHTML = out.join("");
  $("config").querySelectorAll("input,textarea").forEach((el) => {
    el.addEventListener("change", () => markChanged(el));
  });
}

function markChanged(el) {
  const f = el.closest(".field");
  if (f) f.classList.add("changed");
  $("saveBar").style.display = "flex";
}

function collect() {
  const out = {};
  $("config").querySelectorAll("[data-k]").forEach((el) => {
    if (!el.matches("input,textarea")) return;
    const k = el.dataset.k;
    const meta = SCHEMA[k] || {};
    const t = meta.type;
    if (t === "switch") out[k] = !!el.checked;
    else if (t === "integer" || t === "number") out[k] = el.value === "" ? null : Number(el.value);
    else if (Array.isArray(VALUES[k]))
      out[k] = el.value.split("\n").map((x) => x.trim()).filter(Boolean);
    else out[k] = el.value;
  });
  return out;
}

async function saveConfig() {
  const btn = $("save");
  btn.disabled = true;
  try {
    const r = await api("/config", { method: "POST", body: JSON.stringify({ values: collect() }) });
    if (!r.ok) throw new Error(r.error || "保存失败");
    VALUES = r.values || VALUES;
    renderConfig();
    $("saveBar").style.display = "none";
    $("config").classList.add("pulse");
    setTimeout(() => $("config").classList.remove("pulse"), 800);
    toast("已保存并立刻生效（不用重启）");
  } catch (e) {
    toast("保存失败：" + (e.message || e));
  } finally {
    btn.disabled = false;
    $("saveBar").style.display = "flex";
  }
}

/** 拉框架里的模型清单，供 model_select 渲染成下拉。
 *
 *  ⚠️ 失败**不能影响别的** —— 拉不到就退回文本框（见 fieldHTML），
 *     所以这里全程吞异常，只把"没拿到"记下来。
 */
async function loadModelOptions() {
  const want = Object.keys(SCHEMA).filter(
    (k) => (SCHEMA[k] || {}).type === "model_select");
  if (!want.length) return;
  try {
    // ⚠️ 调**插件自己的** `/models`，不是框架的 /api/providers ——
    //    照 Z 插件的做法：后端替我们读框架配置，返回 [{id, name}]，
    //    其中 id 是 `provider_id:model_id`（配置里就是这个格式），
    //    name 是「模型名 (提供商名)」—— 下拉里显示的是**提供商的名字**，
    //    不是那串 id ✓
    //    （原来直连 /api/providers 既绕、又容易把 id 当成名字显示出来 ✗）
    const d = await api("/models");
    const list = (d && d.models) || [];
    const opts = list.map((m) => ({
      value: String(m.id),
      label: String(m.name || m.id),
    }));
    want.forEach((k) => { MODEL_OPTIONS[k] = opts; });
  } catch (e) {
    want.forEach((k) => { MODEL_OPTIONS[k] = []; });   // 退回文本框
  }
}

async function loadConfig() {
  try {
    const r = await api("/config");
    // ⚠️ `info` / `section` 是**版面元素**（说明块、分组），不是配置项 ——
    //    滤掉它们，否则会被当成输入框渲染（info 连 default 都没有）。
    //    info 的文字单独取出来，渲染成配置区最上面那块说明。
    const rawFields = r.fields || {};
    INFO_BLOCKS = Object.keys(rawFields)
      .filter((k) => (rawFields[k] || {}).type === "info")
      .map((k) => rawFields[k]);
    SCHEMA = {};
    for (const k of Object.keys(rawFields)) {
      const t = (rawFields[k] || {}).type;
      if (t !== "info" && t !== "section") SCHEMA[k] = rawFields[k];
    }
    VALUES = r.values || {};
    // 启动动画开关：记到 localStorage，**下次打开就能在渲染前判断** ——
    // 这样"关掉"是真的一个闪都不闪，而不是"播完再藏"。
    try {
      localStorage.setItem("kira-browser-boot", JSON.stringify({
        enabled: VALUES.boot_animation !== false,
      }));
      if (VALUES.boot_replay_seconds != null) {
        localStorage.setItem("kb_boot_cool", String(Number(VALUES.boot_replay_seconds) || 0));
      }
      if (VALUES.boot_animation === false) endBoot();
    } catch (e) { /* 隐私模式下 localStorage 可能不可用，忽略 */ }
    renderConfig();
    $("cfgCount").textContent = Object.keys(SCHEMA).length;
  } catch (e) {
    $("config").innerHTML = `<div class="note warn">${icon("alert")}
      <div>配置读取失败：${fmt(e.message || String(e))}</div></div>`;
  }
}

/* ── 左侧栏：滚动高亮 ─────────────────────────────────────────── */
function spy() {
  const secs = [...document.querySelectorAll(".sec[id]")];
  const links = [...document.querySelectorAll(".nav a")];
  const on = () => {
    let cur = secs[0];
    for (const s of secs) if (s.getBoundingClientRect().top <= 120) cur = s;
    links.forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + (cur && cur.id)));
  };
  window.addEventListener("scroll", on, { passive: true });
  on();
}

/* ── 启动 ─────────────────────────────────────────────────────── */
document.addEventListener("click", (e) => {
  const a = e.target.closest('a[href^="#"]');
  if (!a) return;
  const t = document.querySelector(a.getAttribute("href"));
  if (t) { e.preventDefault(); t.scrollIntoView({ behavior: "smooth", block: "start" }); }
});

const _regen = $("regen"); if (_regen) _regen.addEventListener("click", regen);
const _copy = $("copy");   if (_copy)  _copy.addEventListener("click", copyToken);
const _save = $("save");   if (_save)  _save.addEventListener("click", saveConfig);
const _reload = $("reload"); if (_reload) _reload.addEventListener("click", () => {
  loadConfig(); refresh(); toast("已重新读取");
});

/** 载入动画的收尾 —— 结构照 Z 插件那套（它已经跑通了）。
 *
 *  ⚠️ **收尾的主力是 CSS**（`.boot` 上写了 `animation: boot-out ... 3.1s forwards`），
 *     不靠 JS 掐时间 —— 接口快慢都不会影响它，JS 只负责"点击跳过"和兜底。
 */
let bootPlaying = true;
let bootTimer = null;

function endBoot() {
  const b = $("boot");
  if (!b || !bootPlaying) return;
  b.classList.add("skip");                  // 立刻走一段短动画抹掉
  clearTimeout(bootTimer);
  bootTimer = setTimeout(() => {
    b.hidden = true;                        // [hidden] → display:none
    b.classList.remove("skip");
    bootPlaying = false;
  }, 320);
}

(async function boot() {
  // 重播冷却：同一标签页里短时间内（默认 90 秒）不重复播 ——
  // 不然在页面间来回切会一遍遍放，很烦。照 Z 插件的做法。
  try {
    const last = Number(sessionStorage.getItem("kb_boot_at") || 0);
    const cool = Number(localStorage.getItem("kb_boot_cool") || 90) * 1000;
    if (last && Date.now() - last < cool) {
      const b = $("boot");
      if (b) b.hidden = true;
      bootPlaying = false;
    } else {
      sessionStorage.setItem("kb_boot_at", String(Date.now()));
    }
  } catch (e) { /* 隐私模式下 sessionStorage 可能不可用 */ }
  // 点击任意处跳过
  document.addEventListener("click", () => endBoot(), true);
  _regen.innerHTML = icon("refresh") + "重新生成";
  _copy.innerHTML = icon("copy") + "复制令牌";
  _save.innerHTML = icon("save") + "保存并立刻生效";
  _reload.innerHTML = icon("activity") + "重新读取";
  $("ver").textContent = "v—";  // 真正的版本号由 /status 回填

  await loadConfig();
  loadModelOptions().then(() => renderConfig());   // 拿到模型列表后重渲染一次，换成下拉
  spy();
  await loadToken();
  await refresh();
  setInterval(refresh, 3000);
})();
