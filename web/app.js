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
  if (!el) return;
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  // ⚠️ 一定要**自己收掉**：这个提示条是 fixed 定位的，赖着不走会挡住
  //    右下角那排按钮（用户报过"保存的弹窗不消失"）。
  el._t = setTimeout(() => el.classList.remove("show"), 2200);
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
      // 自检行也记一笔：用户截图就能看出是"状态接口"挂了而不是别的
      _lastErr = "读取状态：" + String(e.message || e);
      renderDiag();
    }
    return;
  }
  if (seq !== _refreshSeq) return;                  // 有更新的请求 → 丢弃这次结果
  renderStatus(s);
}

/* ── 扩展版本提示 ────────────────────────────────────────────────
   ⚠️ 判断全在**后端**（setup_guide.extension_update_state → /status.extension）：
      前端只按 state 取文案、把版本号显示出来。
      **这里不许出现任何版本号字面量** —— 否则以后插件升级扩展版本，
      提示就不会自己出现（用户装的是旧扩展却没人告诉他）。
   以后要加状态：后端加一个 state + 这里加一条文案即可。 */
const EXT_TEXT = {
  zh: {
    update_available: (e) =>
      `扩展可以更新了：你现在用的是 v${e.connected_version}，插件自带的已经是 v${e.bundled_version}。` +
      `旧版扩展可能缺一些修复与新能力（例如连接空闲时的自愈），更新后功能才完整。`,
    outdated_protocol: () =>
      "扩展与插件的协议版本对不上（有些能力可能调用失败）。建议更新扩展 —— " +
      "扩展是随插件打包的，用插件目录里的那份重新加载即可。",
    unknown: () =>
      "扩展没有上报版本号，可能是很久以前的版本。建议重新加载一次扩展；" +
      "如果仍是这样，按下面的步骤用插件自带的那份覆盖安装。",
  },
  en: {
    update_available: (e) =>
      `The extension can be updated: you are running v${e.connected_version}, ` +
      `while the plugin bundles v${e.bundled_version}. Older builds miss recent ` +
      `fixes (for example the idle-link self-healing), so updating keeps everything working.`,
    outdated_protocol: () =>
      "The extension and the plugin disagree on the protocol version, so some " +
      "capabilities may fail. Please update the extension - it ships inside the " +
      "plugin folder, so just reload that copy.",
    unknown: () =>
      "The extension did not report a version, which usually means a very old " +
      "build. Reload the extension; if it stays like this, reinstall the copy " +
      "bundled with the plugin using the steps below.",
  },
};

// 「扩展建议更新」提示 + 更新步骤块的状态。
//   三个变量缺一不可：
//     _extStepsOpen   —— 用户有没有把步骤块展开（收放开关的样子）
//     _extStepsLoaded —— 步骤内容是否已经拉过一次（拉过就不再重拉）
//     _extNoticeSig   —— 上次渲染提示块的签名（内容没变就不重绘）
//
// ⚠️ 为什么必须有这三个（用户报的"点查看更新步骤，那块一闪一闪"）：
//    面板每 3 秒 refresh 一次 → renderStatus → renderExtNotice。
//    以前这个函数**每次调用都重建整个提示块**，又因为 _extStepsShown 为真
//    **每次都重新拉一次 /extension** —— 于是用户点开的步骤块每 3 秒被
//    清成"正在读取安装步骤…"再填满一次 = 一闪一闪；
//    按钮也只会重拉、根本没有"收"这个动作。
let _extStepsOpen = false;
let _extStepsLoaded = false;
let _extNoticeSig = "";

function extStepsInner() { return $("extStepsInner") || $("extSteps"); }

/** 展开/收起步骤块：只切 class 与按钮状态，动画交给 CSS（见 .fold）。 */
function setExtSteps(open) {
  _extStepsOpen = !!open;
  const box = $("extSteps");
  if (box) box.classList.toggle("open", _extStepsOpen);
  const btn = $("extStepsBtn");
  if (btn) {
    btn.setAttribute("aria-expanded", _extStepsOpen ? "true" : "false");
    btn.textContent = _extStepsOpen ? "收起更新步骤" : "查看更新步骤";
  }
}

function renderExtNotice(ext) {
  const box = $("extNotice");
  if (!box) return;
  ext = ext || {};
  if (!ext.needs_update) {
    // 只在**真的显示过**的时候才动 DOM：平时每 3 秒的轮询什么都不该碰
    if (_extNoticeSig || box.firstChild) {
      box.style.display = "none";
      box.textContent = "";
      _extNoticeSig = "";
      // 更新好了就把步骤收起来并清掉缓存（下次需要时重新拉最新的步骤）
      setExtSteps(false);
      _extStepsLoaded = false;
      const inner = extStepsInner();
      if (inner) inner.textContent = "";
    }
    return;
  }
  // ★ 内容没变就别重绘：重绘会重建按钮，也会把用户展开的步骤块打回初始态
  //   （这正是"一闪一闪"的来源）。状态/版本任何一个变了才重画。
  const sig = [ext.state, ext.connected_version, ext.bundled_version].join("|");
  if (sig === _extNoticeSig && box.firstChild) return;
  _extNoticeSig = sig;
  const t = (EXT_TEXT[LOCALE] || EXT_TEXT.zh)[ext.state];
  const msg = t ? t(ext) : "扩展与插件版本不一致，建议更新扩展。";
  box.style.display = "flex";
  box.innerHTML = icon("alert")
    + `<div><b>扩展建议更新</b><br>${fmt(msg)}`
    + ` <button class="btn ghost" id="extStepsBtn" type="button" `
    + `aria-expanded="${_extStepsOpen ? "true" : "false"}" style="margin-top:8px">`
    + `${_extStepsOpen ? "收起更新步骤" : "查看更新步骤"}</button></div>`;
  const btn = $("extStepsBtn");
  if (btn) btn.addEventListener("click", loadExtSteps);
}

/** 「查看更新步骤」：拉 /extension（安装步骤 + 扩展在插件目录里的绝对路径）。
 *  复用现成接口，不另造一份文案 —— 步骤改了这里自动跟上。
 *
 *  行为：**没拉过** → 拉一次并展开；**已经拉过** → 只做展开/收起，不再请求。
 *  （以前每点一次、每次轮询都重拉一次 —— 那正是"一闪一闪"的根源。） */
async function loadExtSteps() {
  const inner = extStepsInner();
  if (!inner) return;
  if (_extStepsLoaded) { setExtSteps(!_extStepsOpen); return; }
  setExtSteps(true);
  inner.innerHTML = `<div class="hint">正在读取安装步骤…</div>`;
  try {
    const d = await api("/extension");
    const steps = (d && d.steps) || [];
    const path = (d && d.path) || "";
    const url = (d && d.extensions_url) || "";
    inner.innerHTML = `<div class="note"><div>`
      + `<b>扩展所在位置</b><br><span class="mono">${fmt(path)}</span>`
      + `<br><span class="hint">在浏览器地址栏打开 <span class="mono">${fmt(url)}</span>，`
      + `删掉旧的「Kira Browser Bridge」，再用下面的方式加载上面这个目录。</span>`
      + `<ol style="margin:8px 0 0 18px;padding:0">`
      + steps.map((s) => `<li>${fmt(s)}</li>`).join("")
      + `</ol></div></div>`;
    _extStepsLoaded = true;
  } catch (e) {
    inner.innerHTML = `<div class="hint">读取安装步骤失败：${fmt(e.message || String(e))}</div>`;
    _extStepsLoaded = false;   // 失败不算"已加载"，下次点还能再试
  }
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
  const _ext = s.extension || {};
  $("extVer").textContent = _ext.connected_version
    ? `v${_ext.connected_version}` + (_ext.bundled_version
        && _ext.connected_version !== _ext.bundled_version
        ? `（插件自带 v${_ext.bundled_version}）` : " ✓")
    : "—";
  $("browser").textContent = b.browser || "—";
  if (s.plugin_version) $("ver").textContent = "v" + s.plugin_version;

  // 扩展版本提示（旧版/协议不匹配/没上报版本 → 提示可以更新）
  renderExtNotice(s.extension);

  const pol = s.policy || {};
  _renderDomains($("domains"), pol.allowed_domains, pol.blocked_domains, pol.local_access);
  renderConfirmLog(s.confirm_log);

  // 桥接的"空闲探活 / 判死"计数：扩展一断一合到底正不正常，看这两个数最清楚
  _bridgeIdle = {
    probes: b.idle_probes || 0,
    disconnects: b.idle_disconnects || 0,
    ago: b.last_inbound_ago,
  };
  renderDiag();
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

/* 令牌值的**存取口**：既要能显示，也要能暂存真值（复制按钮用它）。
   ⚠️ 这里原来是裸的 `$("tokBox").dataset.token` —— 而 HTML 里**没有这个 id** ✗
      → `null.dataset` 抛 TypeError → 被 loadToken 的 catch 吞掉 →
      面板永远显示"读取失败"（用户报的问题 ②，真根因就在这）。
   现在：拿不到那个容器也**绝不能**变成"读取失败"，退回到 #tok 本身。 */
function tokStore() {
  return $("tokBox") || $("tok") || null;
}
function tokValue() {
  const el = tokStore();
  return (el && el.dataset && el.dataset.token) || "";
}
function setTokValue(t) {
  const el = tokStore();
  if (el && el.dataset) el.dataset.token = t || "";
}

/* 令牌显示：**默认遮住** —— 它是连接凭据，不该一打开就摊在屏幕上
   （旁边有人、或者投屏的时候特别尴尬）。点眼睛才显示。
   ⚠️ 值一直存在 dataset 里，复制按钮用的也是它，所以遮住不影响复制。 */
let _tokShown = false;
function renderToken() {
  const t = tokValue();
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
let _lastErr = "";          // 最近一次接口错误（面板自检那一行会显示）

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
    // 后端把失败包在 200 里返回（{ok:false, error}）—— 也要当失败，
    // 但要把**它给的原因**显示出来，而不是笼统一句"读取失败"。
    if (!r || r.ok === false) throw new Error((r && r.error) || "接口没有返回令牌");
    const t = r.token || "";
    if (!t) throw new Error("接口返回了空令牌");
    setTokValue(t);
    _lastErr = "";
    renderToken();                       // 默认遮住，点了眼睛才显示
    pairWithExtension(t, r);             // r 里带 instance/data_dir（/token 响应）
  } catch (e) {
    if (seq !== _tokenSeq) return;
    const why = String((e && e.message) || e);
    _lastErr = "读取令牌：" + why;
    // ⚠️ 别只说"读取失败"：用户没法据此判断到底是没登录、404 还是后端报错，
    //    上一轮就是被这句笼统的话带偏的。
    $("tok").textContent = "读取失败（" + why + "）";
    $("tok").title = why;
  } finally {
    if (seq === _tokenSeq) renderDiag();
  }
}

async function regen() {
  const btn = $("regen");
  btn.disabled = true;
  try {
    // 重新生成：这才是 force=true（旧令牌当场作废）
    const r = await api("/token?force=true", { method: "POST" });
    if (!r || r.ok === false) throw new Error((r && r.error) || "失败");
    setTokValue(r.token || "");
    renderToken();
    pairWithExtension(r.token || "", r);  // r 里带 instance/data_dir
    toast(r.changed ? "已生成新令牌（旧令牌已作废）" : "令牌未变化");
  } catch (e) {
    toast("生成失败：" + (e.message || e));
  } finally {
    btn.disabled = false;
  }
}

function copyToken() {
  const t = tokValue();
  if (!t) { toast("还没有令牌"); return; }
  navigator.clipboard.writeText(t).then(
    () => toast("已复制到剪贴板"),
    () => toast("复制失败，请手动选中复制"));
}

/* ── 零配置接入：把接入信息推给扩展 ──────────────────────────────
   ⚠️ 这条是"打开面板即配对"的关键，别动：
      pairing-page.js 内容脚本只在本机/私网页面上跑，
      收到这个 postMessage 后转给扩展，扩展据此记住 host/port/token。   */
function pairWithExtension(token, meta) {
  try {
    window.postMessage({
      __kiraPair: true,
      host: location.hostname || "127.0.0.1",
      port: Number(location.port) || 80,
      token: token || "",
      // ⚠️ 实例标识必须一起推过去：扩展靠 data_dir 做**身份级去重** ——
      //    没有它，localhost 与 127.0.0.1 两种写法会存成两条实例、
      //    两条连接互踢（重连风暴的导火索）。
      instance: (meta && meta.instance) || "",
      data_dir: (meta && meta.data_dir) || "",
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

/** 放进 HTML 属性里的转义（placeholder / value 用，不能带标签）。 */
function attr(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** 默认值的**人话**写法（给占位符和提示用）。 */
function defaultText(meta) {
  const d = meta && meta.default;
  if (d === undefined || d === null) return "";
  if (typeof d === "boolean") return d ? "开" : "关";
  if (Array.isArray(d)) return d.length ? d.join("、") : "空";
  if (d === "") return "";
  return String(d);
}

/** 输入框空了但确实有默认值时，用占位符把默认值显示出来。 */
function defaultPlaceholder(meta, v) {
  const t = defaultText(meta);
  if (!t) return "";
  if (v === "" || v === null || v === undefined) return ` placeholder="默认：${attr(t)}"`;
  return "";
}

/* ⚠️ 类型判断要和**框架认的那套**对齐（见框架的 configFieldTypes.ts）：
   数值 = integer / float / number，开关 = switch / boolean / bool，
   列表 = list，多选 = multi_select。
   以前面板只认 integer/number ✗ —— schema 里的 `float`（命令超时、
   跟随框架的比例）就被当成**文本框**渲染，值也可能以字符串提交。
   框架自己的设置页是认全的，两边不能不一样。 */
const NUM_TYPES = ["integer", "float", "number"];
const BOOL_TYPES = ["switch", "boolean", "bool"];
const LIST_TYPES = ["list", "array"];

function fieldHTML(key) {
  const meta = SCHEMA[key] || {};
  const type = meta.type || "string";
  const v = VALUES[key];
  const lab = `<div class="lab">${fmt(labelOf(key, meta))}</div>`;
  const sub = hintOf(key, meta) ? `<div class="sub">${fmt(hintOf(key, meta))}</div>` : "";
  if (BOOL_TYPES.includes(type)) {
    const on = v !== false && v !== "false";
    return `<div class="field" data-k="${key}">${lab}${sub}
      <label class="sw"><input type="checkbox" data-k="${key}" ${on ? "checked" : ""}>
      <span class="track"></span><span class="knob"></span></label></div>`;
  }
  // ⚠️ **带 `options` 的枚举字段必须渲染成下拉**（后端策略、浏览器来源、
  //    profile 模式、等待策略…）。
  //    以前只认 `model_select`，于是这些字段在面板里是**自由文本框** ✗ ——
  //    用户手打 `Auto` / `chrome ` 这种拼错的值会被原样存下去，谁也不知道
  //    哪个才对；而框架自己的设置页里它们本来就是下拉（`hasOptions(field)`
  //    → CustomSelect）。两边行为要一致。
  const opts = Array.isArray(meta.options) ? meta.options
    : (Array.isArray(meta.enum) ? meta.enum : []);
  if (opts.length) {
    // 当前值拿不到时用 schema 默认值兜底 —— 下拉必须**始终反映真实取值**，
    // 否则第一项会被浏览器默认选中，用户看到的就不是实际生效的值 ✗
    const cur = String(v ?? (meta.default ?? ""));
    const def = meta.default;
    const label = (o) => (String(o) === String(def) ? `${o}（默认）` : String(o));
    const has = opts.some((o) => String(o) === cur);
    return `<div class="field" data-k="${key}">${lab}
      <select data-k="${key}">
        ${opts.map((o) => `<option value="${attr(o)}"${String(o) === cur ? " selected" : ""}>`
                          + `${fmt(label(o))}</option>`).join("")}
        ${cur && !has ? `<option value="${attr(cur)}" selected>${fmt(cur)}（当前值，已不在可选列表里）</option>` : ""}
      </select>${sub}</div>`;
  }
  if (LIST_TYPES.includes(type) || Array.isArray(v)) {
    return `<div class="field full" data-k="${key}">${lab}
      <textarea data-k="${key}" spellcheck="false">${(v || []).join("\n")}</textarea>${sub}</div>`;
  }
  if (NUM_TYPES.includes(type)) {
    return `<div class="field" data-k="${key}">${lab}
      <input type="number" data-k="${key}" value="${attr(v ?? "")}"${defaultPlaceholder(meta, v)}>${sub}</div>`;
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
  // ⚠️ 判断条件别只看长度：目录/路径字段现在**回显的是绝对路径**
  //    （快照会填真实值），几十个字符很正常 —— 用长度一刀切会让
  //    「截图目录」这种字段变成大文本框 ✗。
  //    只有**真有多行**、或者明显是长文（提示词/正文）才用 textarea。
  const long = type === "textarea" || key.endsWith("_prompt")
    || String(v || "").includes("\n") || String(v || "").length > 120;
  if (long) {
    return `<div class="field full" data-k="${key}">${lab}
      <textarea data-k="${key}" spellcheck="false">${v ?? ""}</textarea>${sub}</div>`;
  }
  return `<div class="field" data-k="${key}">${lab}
    <input type="text" data-k="${key}" value="${attr(v ?? "")}"${defaultPlaceholder(meta, v)}>${sub}</div>`;
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
  // ⚠️ 事件用**委托**绑在容器上（只绑一次，见文件末尾），
  //    别在这里逐个绑 —— 那样每处都要记得把 select 列进去，
  //    而"漏了 select"正是"改了模型下拉却没反应"的原因 ✗
}

/* ── 改动标记 / 保存条 ──────────────────────────────────────── */
function countChanged() {
  const box = $("config");
  return box ? box.querySelectorAll(".field.changed").length : 0;
}
function showSaveBar() {
  const n = countChanged();
  const lab = $("saveBarLabel");
  if (lab) lab.textContent = n ? `有 ${n} 项未保存的改动` : "有未保存的改动";
  const bar = $("saveBar");
  if (bar) bar.style.display = "flex";
}
function hideSaveBar() {
  const bar = $("saveBar");
  if (bar) bar.style.display = "none";
}

function markChanged(el) {
  const f = el.closest(".field");
  if (f) f.classList.add("changed");
  // 让用户**看得见**"改了哪几项、一共几项" —— 下拉框改完也是同一条路
  // （用户报的问题 ④：选了别的模型却没有任何反馈，无从判断会不会生效）
  showSaveBar();
}

function collect() {
  const out = {};
  $("config").querySelectorAll("[data-k]").forEach((el) => {
    // ⚠️ 只收**控件本身**：`data-k` 在外层 .field 上也有一份，
    //    用 matches 把它过滤掉。
    // ⚠️ `select` 必须在内 —— 以前只写 input/textarea，
    //    结果模型下拉选完**根本不提交**（保存了也没生效）✗
    if (!el.matches("input,textarea,select")) return;
    // ⚠️ 只提交**用户改过**的那些字段。
    //    原因：后端快照现在会把没设置过的键**回退成 schema 默认值**
    //    （否则面板上是空框），如果连这些一起存下去，就等于把"当前的默认值"
    //    钉成覆盖值 —— 以后插件升级改了默认值，这些用户再也跟不上 ✗
    //    没动过的字段不提交 = 保持"跟随默认"的语义。
    const box = el.closest(".field");
    if (!box || !box.classList.contains("changed")) return;
    const k = el.dataset.k;
    const meta = SCHEMA[k] || {};
    const t = meta.type;
    if (BOOL_TYPES.includes(t)) out[k] = !!el.checked;
    else if (NUM_TYPES.includes(t)) out[k] = el.value === "" ? null : Number(el.value);
    else if (LIST_TYPES.includes(t) || Array.isArray(VALUES[k]))
      out[k] = el.value.split("\n").map((x) => x.trim()).filter(Boolean);
    else out[k] = el.value;
  });
  return out;
}

async function saveConfig() {
  const btn = $("save");
  if (btn) btn.disabled = true;
  try {
    const r = await api("/config", { method: "POST", body: JSON.stringify({ values: collect() }) });
    if (!r || r.ok === false) throw new Error((r && r.error) || "保存失败");
    VALUES = r.values || VALUES;
    renderConfig();          // 重渲染 = 所有"已改动"标记一起清掉
    hideSaveBar();
    _lastErr = "";
    renderDiag();
    $("config").classList.add("pulse");
    setTimeout(() => $("config").classList.remove("pulse"), 800);
    const n = Object.keys((r.applied || [])).length || (r.applied || []).length;
    toast(n ? `已保存 ${n} 项，立刻生效（不用重启）` : "已保存并立刻生效（不用重启）");
  } catch (e) {
    _lastErr = "保存配置：" + String((e && e.message) || e);
    renderDiag();
    toast("保存失败：" + (e.message || e));
    showSaveBar();           // 失败才留着，方便改完再存
  } finally {
    if (btn) btn.disabled = false;
    // ⚠️⚠️ 这里**不能**再 `saveBar.style.display="flex"` ✗
    //    原来的 finally 无条件把保存条又打开了一遍，于是"点了保存、
    //    弹窗还挂在那儿、还写着有未保存的改动"（用户报的问题 ③）。
    //    成功已经在 try 里收起，失败在 catch 里保留 —— finally 只管按钮。
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
      if (VALUES.boot_animation === false) endBoot("配置里已关闭");
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
// ⚠️ 眼睛按钮以前**根本没绑事件** ✗ —— 图标画出来了、点了没反应
//    （用户报的"点眼睛并不显示"）。这里补上：点一下显示明文，再点遮回去。
const _eye = $("eye");     if (_eye)  _eye.addEventListener("click", () => {
  _tokShown = !_tokShown;
  renderToken();
});
const _save = $("save");   if (_save)  _save.addEventListener("click", saveConfig);
const _reload = $("reload"); if (_reload) _reload.addEventListener("click", () => {
  // 模型列表也一起重取 —— 用户刚在框架设置里加/删了模型，这里点一下就该跟上
  loadModelOptions().then(() => renderConfig());
  loadConfig(); refresh(); toast("已重新读取");
});

/* 配置区的事件**委托**：一份监听管住所有控件（含后面重渲染出来的）。
   ⚠️ 三个都收：input / textarea / **select** ——
      漏掉 select 就是"模型下拉改了没有任何反馈"的那个 bug（用户报的问题 ④）。
   同时听 `input` 和 `change`：文本框 typing 时也能立刻亮起保存条。 */
(function bindConfigEvents() {
  const box = $("config");
  if (!box) return;
  const onEdit = (e) => {
    const el = e.target && e.target.closest && e.target.closest("[data-k]");
    if (el && el.matches("input,textarea,select")) markChanged(el);
  };
  box.addEventListener("input", onEdit);
  box.addEventListener("change", onEdit);
})();

/** 面板自检：出问题时用户截一张图就够了（载入动画有没有播、
 *  系统是不是开了"减少动效"、最近一次接口报错）。 */
let _bridgeIdle = null;      // 桥接的空闲探活统计（/status 回填）

function renderDiag() {
  const el = $("diag");
  if (!el) return;
  const rm = !!(window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const b = $("boot");
  const state = !b ? "元素不存在"
    : (b.hidden ? "已结束" : (bootPlaying ? "播放中" : "正在收起"));
  const idle = _bridgeIdle
    ? ` · 桥接空闲探活 ${_bridgeIdle.probes} 次 / 判死 ${_bridgeIdle.disconnects} 次`
    : "";
  el.textContent = `面板自检：载入动画 ${state}`
    + (bootWhy ? `（${bootWhy}）` : "")
    + ` · 减少动效偏好：${rm ? "开" : "关"}`
    + idle
    + (_lastErr ? ` · 最近错误：${_lastErr}` : " · 无接口错误");
}

/** 载入动画的收尾 —— 结构照 Z 插件那套（它已经跑通了，别再自创）。
 *
 *  ⚠️ 三条保险，缺一条就会出"不消失"或"不出现"：
 *    ① CSS 自己收（`.boot` 上 `animation: boot-out … forwards`）——
 *       不依赖 JS 的时机，接口慢也照收；
 *    ② `animationend` 再确认一次 —— CSS 真收完了就把节点 hidden；
 *    ③ **JS 硬兜底超时** —— 万一动画根本没跑（样式没加载 /
 *       被别的规则覆盖 / 浏览器把动效关了），也必须收掉。
 *       没有这一条，那一层会**永远盖住整个面板**。
 *  ⚠️ 也**不要**再按 sessionStorage 里的时间戳"跳过播放" ——
 *     用户在 90 秒内重开面板就再也看不到开屏动画了（"根本不出现"的
 *     另一个原因）。重播冷却只用在"页面被切回来重新显示"这一种情形。
 */
let bootPlaying = true;
let bootTimer = null;
let bootHiddenAt = 0;
let bootWhy = "";
const BOOT_MAX_MS = 5000;        // 硬兜底：超过这个时间一定收掉

function endBoot(why) {
  const b = $("boot");
  if (!b || !bootPlaying) return;
  bootPlaying = false;
  bootHiddenAt = Date.now();
  bootWhy = why || "手动跳过";
  b.classList.add("skip");                  // 立刻走一段短动画抹掉
  clearTimeout(bootTimer);
  bootTimer = setTimeout(() => {
    b.hidden = true;                        // [hidden] → display:none
    b.classList.remove("skip");
    renderDiag();
  }, 320);
  renderDiag();
}

function armBoot() {
  const b = $("boot");
  clearTimeout(bootTimer);
  // ② CSS 的收尾动画播完 → 立刻确认收掉（正常路径，不用等兜底）
  if (b) {
    // ⚠️ 这里**不能**用 `{once:true}` ✗ —— 里面那些装饰动画
    //    （bootInk / bootRing / bootStar）的 animationend 也会**冒泡**到 .boot 上，
    //    第一个冒上来的就把监听器吃掉了，真正的 boot-out 事件再也收不到
    //    （实测：只能靠 5 秒兜底才收掉，中间那段时间还会挡住点击）。
    const onEnd = (e) => {
      if (e.animationName !== "boot-out") return;
      b.removeEventListener("animationend", onEnd);
      endBoot("CSS 收尾动画结束");
    };
    b.addEventListener("animationend", onEnd);
  }
  // ③ 硬兜底（见上）
  bootTimer = setTimeout(() => endBoot("兜底超时"), BOOT_MAX_MS);
}

/** 页面被切回来时**重播**（可选）。冷却时间来自配置
 *  `boot_replay_seconds`（默认 90 秒）。没有冷却的话，来来回回切页面
 *  会一遍遍放，很烦 —— 但**首次打开一定是播的**。 */
function replayBootIfDue() {
  const b = $("boot");
  if (!b || bootPlaying || !bootHiddenAt) return;
  const gap = (Date.now() - bootHiddenAt) / 1000;
  const cool = Number(localStorage.getItem("kb_boot_cool") || 90) || 0;
  if (!(cool > 0 && gap >= cool)) return;
  try {
    // 换一个新节点 = 所有 CSS 动画从头再跑一遍（照 Z 插件的做法）
    const fresh = b.cloneNode(true);
    b.replaceWith(fresh);
  } catch (e) { return; }
  bootHiddenAt = 0;
  bootPlaying = true;
  bootWhy = "";
  const cur = $("boot");
  if (cur) { cur.hidden = false; cur.classList.remove("skip"); }
  armBoot();
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") replayBootIfDue();
  else if (!bootHiddenAt) bootHiddenAt = Date.now();
});

(async function boot() {
  // 点击任意处 / Esc 跳过
  document.addEventListener("click", () => endBoot("点击跳过"), true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") endBoot("Esc 跳过");
  });
  armBoot();                       // 静态标记一进来就在动，这里只负责收尾
  _regen.innerHTML = icon("refresh") + "重新生成";
  _copy.innerHTML = icon("copy") + "复制令牌";
  _save.innerHTML = icon("save") + "保存并立刻生效";
  _reload.innerHTML = icon("activity") + "重新读取";
  $("ver").textContent = "v—";  // 真正的版本号由 /status 回填
  renderDiag();

  await loadConfig();
  loadModelOptions().then(() => renderConfig());   // 拿到模型列表后重渲染一次，换成下拉
  spy();
  await loadToken();
  await refresh();
  renderDiag();
  setInterval(refresh, 3000);
})();
