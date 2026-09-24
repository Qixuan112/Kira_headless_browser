/**
 * background.js / capabilities.js / commands.js 三者共享的运行时状态与工具函数。
 *
 * 为什么需要这个文件：ES 模块之间**不共享顶层作用域**。capabilities.js 和
 * commands.js 里调用的 resolveTab / callContent / sendRaw / MSG 等，
 * 如果只在 background.js 里定义，运行时就是 ReferenceError。
 * 这些命令（执行JS/上传/下载 + 补齐的 13 个）会整个不可用。
 */

import { MSG, ERR_TIMEOUT } from "./protocol.js";

/** 共享的可变状态。
 *
 *  ⚠️ 这里**不再有 `socket`** —— 扩展现在可以同时连**多个** KiraAI 实例
 *     （一台机器上跑好几个 KiraAI 是常见情况，它们都装了本插件、
 *      都应该能操作这一个浏览器）。
 *   每条连接在 `links` 里各有一个对象，连接状态也各自持有。
 */
export const state = {
  userDisconnected: false,
  /** popup 做链路验证时挂的一次性回调（收到服务端 ping 时触发） */
  probe: null,
};

/** 所有已登记的连接：`"host:port"` → Link（由 background.js 创建与维护）。
 *
 *  放在这里而不是 background.js，是为了让 `sendEvent` 能广播给全部连接，
 *  同时**不产生循环依赖**（background → shared 是单向的）。
 */
export const links = new Map();

/** 谁最近**写过**页面（跨实例）。
 *
 *  这个插件允许一个浏览器被多个 KiraAI 实例同时操作（用户有两个 bot，
 *  都该看得到同一个页面）。不做仲裁，但要让 bot **自己知道**
 *  页面可能已经不是我记忆里的样子了。 */
export const activity = { lastWriter: "", lastWriteTs: 0 };

/** 多久没收到服务端任何一帧，就认为这条链路"看着 OPEN、其实不通"（毫秒）。
 *
 *  为什么需要：MV3 的 Service Worker 被回收再唤醒之后，WebSocket 可能变成
 *  **半开连接** —— `readyState` 还是 `OPEN`，但对面的数据永远到不了。
 *  只看 readyState 的话，扩展会一直以为"已连接"，而每个命令都卡到超时。
 *
 *  服务端每 25 秒发一次心跳 ping，所以正常情况下永远不该静默这么久；
 *  60 秒没动静 = 链路确实不通了 —— 主动换一条新连接**比**等服务端
 *  把这条判死要好：重连是扩展自己的事，日志里也不会出现
 *  "服务端判定连接已失效"那种惊悚告警。
 */
export const WS_STALE_MS = 60000;

/** 这条连接是不是已经"静默过久"了？（纯函数，方便测试）
 *
 *  `lastInboundAt` 为 0/空 表示"还没收到过任何一帧"（刚建连）→ 不算陈旧。
 */
export function isLinkStale(lastInboundAt, now = Date.now(), limit = WS_STALE_MS) {
  if (!lastInboundAt) return false;
  return (now - lastInboundAt) > limit;
}

/** "换一条新连接"这条日志的**降噪窗口**（毫秒）。
 *
 *  为什么也要降噪：链路真半开时，这个动作每分钟都会发生一次（阈值 60 秒），
 *  一条条打出来就是新的刷屏 —— 而它本来是为了让日志变干净的。
 *  同一个窗口内只喊一次，其余只累加计数（数字可以去弹窗里看）。
 */
export const STALE_LOG_WINDOW_MS = 5 * 60 * 1000;

/** 这次"换连接"要不要**打日志**？（纯函数，方便测试）
 *
 *  `box` 是一个可变状态对象：`{count, logAt, suppressed}`。
 *  返回值：true = 这次该喊（其余情况只累加计数）。
 */
export function staleLogDecision(box, now = Date.now(),
                                windowMs = STALE_LOG_WINDOW_MS) {
  box.count = (box.count || 0) + 1;              // 计数**always**要加
  if (box.logAt && (now - box.logAt) < windowMs) {
    box.suppressed = (box.suppressed || 0) + 1;
    return false;
  }
  box.logAt = now;
  box.suppressed = 0;
  return true;
}

/** 这次要给这条连接带回"页面被别的实例动过"的提示吗？
 *
 *  条件：另一个实例写过，**且**写的时间晚于这条连接上次收到结果的时间。
 *  → 同一个事实只提醒一次；没发生就返回空串，**一个 token 都不花**。
 */
export function otherWriterFor(link) {
  if (!link) return "";
  if (!activity.lastWriter || activity.lastWriter === link.label) return "";
  return activity.lastWriteTs > (link.lastResultTs || 0) ? activity.lastWriter : "";
}

// ─── 发送 ──────────────────────────────────────────────────────────────
//
//  ⚠️ 每个 send* 都必须**显式带上目标连接**（`link`）。
//
//     不要图省事搞一个"当前连接"全局变量：命令是 async 的 ——
//     A（实例1）在 await 期间，B（实例2）的命令进来会把它改掉，
//     A 恢复后再调 sendResult 就把**自己的响应发给了 B**。
//     现象是"跟 A 说话 A 没反应，B 却收到一堆不属于它的结果"，
//     而且只在两个实例同时忙的时候才出现，最难查。

/** 往**指定连接**发一条消息。没有可用连接时返回 false。 */
export function sendRaw(obj, link) {
  if (!link || !link.open) return false;
  try {
    link.ws.send(JSON.stringify(obj));
    return true;
  } catch (e) {
    console.error("[KiraBridge] 发送失败", e);
    return false;
  }
}

export function sendResult(id, ok, data, error, errorCode, link) {
  return sendRaw({ type: MSG.RESULT, id, ok, data: data ?? null,
                   error: error ?? null, error_code: errorCode ?? null }, link);
}

/** 浏览器事件。
 *
 *  ⚠️ 默认**广播给所有已连接实例** —— 标签页切换、页面加载这些是
 *     **浏览器级**的事实，每个实例都该知道（否则另一个实例的"当前页"
 *     会和真实情况脱节）。指定 `link` 时只发那一条。
 */
export function sendEvent(name, data, link) {
  const msg = { type: MSG.EVENT, name, data: data || {} };
  if (link) return sendRaw(msg, link);
  let sent = false;
  for (const l of links.values()) {
    if (sendRaw(msg, l)) sent = true;
  }
  return sent;
}

/** 下载分块回传（扩展 → 插件）。
 *
 * ⚠️ 必须把 sendRaw 的结果**回传出去**：socket 已经关了的时候
 *    sendRaw 返回 false，而这里原来把它丢掉 —— 调用方（下载）
 *    因此以为分块发出去了，最后还会 return {ok:true}，
 *    等于"下载成功了但文件其实缺了一大段"。
 */
export function sendChunk(cmdId, uint8, link) {
  let bin = "";
  const step = 0x8000;
  for (let i = 0; i < uint8.length; i += step) {
    bin += String.fromCharCode.apply(null, uint8.subarray(i, i + step));
  }
  return sendRaw({ type: MSG.CHUNK, id: cmdId, data: btoa(bin) }, link);
}

// ─── 标签页解析 ────────────────────────────────────────────────────────

/** 取得目标标签页：显式 tab_id > 当前窗口激活页 > 任意窗口的激活页 */
export async function resolveTab(tabId) {
  if (tabId !== undefined && tabId !== null && tabId !== "") {
    const tab = await chrome.tabs.get(Number(tabId));
    if (!tab) throw new Error(`找不到标签页 ${tabId}`);
    return tab;
  }
  // query 返回空数组时也是"真值"，所以必须显式判长度
  let tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tabs || !tabs.length) {
    tabs = await chrome.tabs.query({ active: true });
  }
  const tab = tabs && tabs[0];
  if (!tab) throw new Error("找不到活动标签页");
  return tab;
}

const INJECTABLE = /^https?:/i;

/** 本地文件页（`file://`）。
 *
 *  ⚠️ 它和 `chrome://` 那类**不是一回事**：
 *    · `chrome://` / `edge://` / `devtools://` 是浏览器**硬边界** ——
 *      `<all_urls>` 也不包含，任何扩展都注入不了，无法可解；
 *    · `file://` 只受用户的一个开关约束（扩展详情页的
 *      「允许访问文件网址」）。开关**打开之后**扩展就能注入、能读、能点，
 *      和普通网页一样。所以这里要给出"去打开它"这种**能照做**的路径，
 *      而不是甩一句"没有权限"。
 */
const FILE_URL = /^file:/i;

/**
 * 本扩展当前能不能访问本地文件。
 *
 * ⚠️ 为什么必须真去问：这是**用户级**开关，只能由用户在
 *    `chrome://extensions` 里打开，扩展自己改不了、也探测不到别的信号。
 *    （该 API 文档：`chrome.extension.isAllowedFileSchemeAccess()`，
 *      Chrome 99+ 返回 Promise。）
 *
 * 结果会被缓存（用户中途去打开开关的情况下，最多晚几秒生效 ——
 * 但**失败不缓存**，见下）。
 */
let _fileAccessCache = null;

export async function isFileAccessAllowed() {
  if (_fileAccessCache !== null) return _fileAccessCache;
  try {
    const api = chrome.extension;
    if (!api || typeof api.isAllowedFileSchemeAccess !== "function") {
      // 拿不到结论时**按允许处理**：让文件页照常打开，
      // 真没权限的话注入那一步会报出真实原因（比在这里瞎拦好）。
      return true;
    }
    const v = !!(await api.isAllowedFileSchemeAccess());
    _fileAccessCache = v;
    return v;
  } catch (_) {
    // ⚠️ 探测本身出错时**不写缓存** —— 否则一次偶发异常会把"没权限"
    //    永久钉住，用户去打开开关也没用（只能重载扩展）。
    return true;
  }
}

/** 用户去打开那个开关的页面（扩展详情页要用户自己找到本扩展，这里给列表页）。 */
export const EXTENSIONS_URL = "chrome://extensions/";

/** 让缓存作废（用户刚在扩展详情页关掉开关时，下次调用要重新问）。 */
export function invalidateFileAccessCache() {
  _fileAccessCache = null;
}

/** 给模型看的、**能照做**的文件访问引导。 */
export function fileAccessHelp(url) {
  return (
    `当前页面是本机文件（${url}），而这个扩展**还没被允许访问本地文件**。\n`
    + `这是浏览器的一个安全开关，扩展自己打不开，需要用户操作一次：\n`
    + `  1. 浏览器地址栏输入 ${EXTENSIONS_URL}\n`
    + `  2. 找到「Kira Browser Bridge」→ 点「详情」\n`
    + `  3. 打开「允许访问文件网址 / Allow access to file URLs」\n`
    + `（开一次就长期有效，之后本机图片 / PDF / 文本 / 视频都能直接打开。）\n`
    + `另一个办法：不用你的浏览器，改用插件自带的无头浏览器 —— `
    + `让 AI 调 browser_backend(action="use", use="headless")，`
    + `那条路没有这个开关的限制。`
  );
}

/**
 * 页面能不能被扩展注入脚本。**异步**（要真去问文件访问开关）。
 *
 * ⚠️ 报错是给**模型**看的，必须告诉它"还能怎么办" ——
 *    原来只说"不允许注入脚本，请先切换到普通网页"，
 *    模型只能放弃、然后回用户一句"扩展没权限访问"，看着像缺陷。
 */
export async function assertInjectable(tab) {
  const url = (tab && tab.url) || "";
  if (FILE_URL.test(url)) {
    if (await isFileAccessAllowed()) return;
    throw new Error(fileAccessHelp(url));
  }
  if (!url || !INJECTABLE.test(url)) {
    //    真实情况：`chrome://` / `edge://` 这类**浏览器内部页**是
    //    **硬边界** —— `<all_urls>` 也不包含它们，任何扩展都注入不了，
    //    这不是权限没开、也没法开。
    //
    //    但有两条**能走通**的路，必须写出来：
    //      ① **截图**：`browser_screenshot` 走的是 captureVisibleTab，
    //         截的是可见区域，**不需要注入** → 内部页照常能截，
    //         配合 VLM 就能读到画面上的内容（书签列表、设置项…）。
    //      ② **要数据不要页面**：书签数据走 `chrome.bookmarks`（数据接口，
    //         不碰页面），用 browser_interact 的 action="bookmarks"。
    throw new Error(
      `当前页面（${url || "未知"}）是**浏览器内部页**，`
      + `任何扩展都无法在里面注入脚本（浏览器的硬边界，不是权限没开）。\n`
      + `可以这样做：\n`
      + `  · 想**看这个页面**：用 browser_screenshot —— 它对内部页照常有效`
      + `（截的是可见区域，不需要注入），配合 VLM 就能读到画面内容；\n`
      + `  · 想读**书签数据**：用 browser_interact 的 action="bookmarks"`
      + `（走 chrome.bookmarks，读的是数据不是页面）；\n`
      + `  · 想读普通网页的内容：先 browser_navigate 切过去。`);
  }
}

/**
 * 向 content script 发一条指令。
 * content script 在页面加载时就会注入，但如果扩展刚安装、页面还没刷新，
 * 就可能没有监听者。这里用 ping 探测一次，失败则手动补注入。
 */
export async function callContent(tab, action, payload = {}, timeout = 15000) {
  await assertInjectable(tab);

  const send = (a, p) => chrome.tabs.sendMessage(tab.id, { action: a, ...p });

  try {
    await send("ping", {});
  } catch (_) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["content.js"],
      });
    } catch (e) {
      throw new Error(`无法注入页面脚本：${e.message}`);
    }
  }

  // ⚠️ 超时必须标记成**不确定**（indeterminate）而不是普通失败：
  //    Promise.race 只是在本地"不再等"，**并不能取消**已经发出去的操作 ——
  //    慢点击/慢输入很可能在超时之后才真正完成。
  //    如果报成"失败"，上层会换（无头）后端**重试**，
  //    于是同一个点击/输入被执行两次，而这是不可撤销的。
  //    带上 error_code 让插件侧能识别（不依赖文案）。
  const result = await Promise.race([
    send(action, payload),
    new Promise((_, rej) => {
      const err = new Error("页面操作超时（操作可能仍在进行）");
      err.code = ERR_TIMEOUT;
      setTimeout(() => rej(err), timeout);
    }),
  ]);

  if (result && result.__error) throw new Error(result.__error);
  return result;
}

export function detectBrowser() {
  const ua = navigator.userAgent;
  if (ua.includes("Edg/")) return "Edge";
  if (ua.includes("Chrome/")) return "Chrome";
  if (ua.includes("Firefox/")) return "Firefox";
  return "Unknown";
}

// ─── 二次确认 ──────────────────────────────────────────────────────────

const pendingConfirms = new Map();

/**
 * 二次确认弹窗等多久算用户拒绝。
 * 插件传的是它自己愿意等多久（CONFIRM_WAIT_SECONDS），这里留 5 秒提前量 ——
 * 让扩展先判超时并回一个明确的「拒绝」，比插件单方面超时更好排查。
 */
export function confirmTimeoutMs(params) {
  const waits = Number(params && params.confirm_timeout);
  const base = waits > 0 ? waits * 1000 : 45000;
  return Math.max(5000, base - 5000);
}

export async function askUser(title, message, meta = {}) {
  const id = "kira-confirm-" + Date.now() + "-" + Math.random().toString(36).slice(2, 7);
  const waitMs = Number(meta.timeout_ms) > 0 ? Number(meta.timeout_ms) : 45000;

  const decision = new Promise((resolve) => {
    const settle = (allowed, reason) => {
      if (!pendingConfirms.has(id)) return;
      pendingConfirms.delete(id);
      // ⚠️ 一定要**清掉通知**：它带 requireInteraction:true，不会自己消失。
      //    只在点击路径清、超时路径不清的话，超时的确认会一直挂在通知栏，
      //    用户过一会儿再点它还会二次响应（那时早已 resolve 过了）。
      try { chrome.notifications.clear(id); } catch (_) {}
      sendEvent("user_confirmed", {
        confirm_id: id, allowed, reason,
        command: meta.command || "",
        action: meta.action || title,
        url: meta.url || "",
      });
      resolve(allowed);
    };
    pendingConfirms.set(id, settle);
    setTimeout(() => settle(false, "timeout"), waitMs);
  });

  await chrome.notifications.create(id, {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title: "KiraAI · " + title,
    message,
    buttons: [{ title: "允许" }, { title: "拒绝" }],
    requireInteraction: true,
    priority: 2,
  });

  return decision;
}

export function resolveConfirm(notifId, buttonIndex) {
  const settle = pendingConfirms.get(notifId);
  if (!settle) return false;
  settle(buttonIndex === 0, buttonIndex === 0 ? "approved" : "denied");
  // 通知的清理由 settle() 统一负责（超时路径也要清，见那边的说明），
  // 这里不再重复清一次。
  return true;
}

/**
 * 需要用户二次确认才能执行的命令（当 require_confirm 打开时）。
 *
 * ⚠️ 这里必须是**集中判定**。之前只在 navigate/click/type 里各写一次，
 * 结果 exec_js / upload / cookie_set 这三条高危命令完全绕过了确认 ——
 * 等于「我开了确认，但它悄悄执行了 JS、传了文件、改了 cookie」。
 */
export const PRIVILEGED_COMMANDS = new Set([
  "navigate", "click", "type", "scroll",
  "exec_js", "upload", "download", "cookie_set",
  "go_back", "refresh", "hover",
  "key_press", "key_down", "key_up",
  "mouse_click", "mouse_down", "mouse_up", "mouse_wheel", "mouse_drag",
  // ⚠️ 下面三个也是写操作，之前漏了 —— 开了「写操作需确认」时
  //    它们会被静默放行：AI 能在用户没批准的情况下**切走/关掉标签页**、
  //    或模拟鼠标移动（可能触发拖拽类交互）。
  //    这份清单必须与 Python 侧 protocol.py 的 WRITE_COMMANDS 保持同步。
  "activate_tab", "close_tab", "mouse_move",
]);

/**
 * 只读但**敏感**、同样需要用户确认的命令。
 *
 * ⚠️ 单独一个集合：cookie_get 只是读，不能塞进 PRIVILEGED_COMMANDS
 *    （那会把它误当成写操作，破坏只读模式/域名白名单的判定）；
 *    但导出的是 chrome.cookies.getAll 的**真实取值** = 登录态，
 *    用户应当看到"要导出 Cookie"并亲自批准。
 */
export const CONFIRM_ONLY_COMMANDS = new Set(["cookie_get"]);

/** 需要用户确认的全部命令（写操作 + 只读敏感） */
export const NEEDS_CONFIRM_COMMANDS = new Set([
  ...PRIVILEGED_COMMANDS, ...CONFIRM_ONLY_COMMANDS,
]);

/** 生成给用户看的确认文案 */
export function confirmPromptFor(name, params) {
  // ⚠️ 通知文案**不能带命令载荷里的敏感值** —— 通知会出现在锁屏、
  //    通知中心，以及任何能看屏幕的人眼前，而载荷里可能是：
  //      · 完整 URL（query 里常带 token / 会话 id）
  //      · 用户要 AI 输入的文字（可能是密码等私密内容）
  //      · 要执行的 JS 源码
  //      · 上传/下载的文件名
  //    所以**只给"动作 + 目标 + 载荷规模"**，不给实际取值。
  //    要看细节请打开扩展面板（那是用户主动的动作）。
  const _len = (v) => {
    if (v == null) return 0;
    if (typeof v === "string") return v.length;
    if (Array.isArray(v)) return v.length;
    try { return JSON.stringify(v).length; } catch (_) { return 0; }
  };
  const _host = (u) => {
    // 只取主机名，丢掉路径与 query（那里常有 token）
    try { return new URL(String(u)).host || "（未知站点）"; }
    catch (_) { return "（未知站点）"; }
  };
  const _short = (v, n = 40) => {
    const t = String(v == null ? "" : v);
    return t.length > n ? t.slice(0, n) + "…" : t;
  };
  switch (name) {
    case "navigate":
      return ["跳转页面", `AI 想让浏览器打开站点：${_host(params.url)}`];
    case "cookie_get":
      return ["导出 Cookie",
              `AI 想读取并导出站点 ${_host(params.url)} 的 Cookie。\n`
              + "这等于把登录态交给 AI，请确认是否允许。"];
    case "click":
      return ["点击元素",
        `AI 想点击页面上的元素：`
        + `${_short(params.selector || params.text) || "（未指定）"}`];
    case "type":
      return ["输入内容",
        `AI 想在 ${_short(params.selector)} 输入内容`
        + `（${_len(params.text)} 个字符，内容不在此显示）`];
    case "exec_js":
      return ["执行 JavaScript",
        `AI 想在当前页面执行一段 JavaScript`
        + `（${_len(params.script)} 个字符，源码不在此显示）。`];
    case "upload":
      return ["上传文件",
        `AI 想上传一个文件到 ${_short(params.selector)}`
        + `（文件名与内容不在此显示）`];
    case "download":
      return ["下载文件",
        `AI 想用你的浏览器会话从 ${_host(params.url)} 下载文件`
        + `（路径不在此显示）`];
    case "cookie_set":
      return ["写入 Cookie",
        `AI 想向浏览器写入 ${_len(params.cookies)} 条 cookie`];
    case "mouse_drag":
      return ["鼠标拖拽", `AI 想执行一次鼠标拖拽操作（坐标不在此显示）`];
    default:
      return [`执行 ${name}`, `AI 想执行浏览器操作：${name}`];
  }
}
