import { MSG } from "./protocol.js";
import {
  resolveTab, assertInjectable, callContent, sendRaw, sendChunk,
} from "./shared.js";

/**
 * 扩展桥补齐的三项能力（在 background.js 里实现）：
 *
 *   1. exec_js    —— 执行任意 JS。MV3 下 `chrome.scripting.executeScript` 的
 *                    eval 会被**页面 CSP** 挡掉（MV3 起不再豁免），所以走
 *                    `chrome.userScripts` API —— 官方专为"运行任意代码字符串"
 *                    设计、明确豁免远端代码策略。
 *                    ⚠️ Chrome 138+ 需要用户在扩展详情页手动打开
 *                    「Allow User Scripts」开关，否则会报错。这里会把这种情况
 *                    翻译成一句用户能照做的话。
 *
 *   2. upload     —— 把本地文件塞进 input[type=file]。MV3 拿不到真实文件路径，
 *                    所以改由**插件把文件内容分块送过来**，扩展在页面里
 *                    用 `DataTransfer` + `new File([blob])` 构造 FileList 塞进去。
 *                    （这正好绕开了"扩展读不到本地文件"的限制，因为内容是从
 *                    插件那边来的。）
 *
 *   3. download   —— 用**用户浏览器的会话**去抓 URL，再分块回传给插件落盘。
 *                    比 `chrome.downloads` 好：能带用户的 Cookie/登录态，
 *                    也不会把文件塞进 Chrome 的下载目录。
 */

// ─── 1. 执行任意 JS ──────────────────────────────────────────────────────

// ⚠️ 只缓存**成功**结果。
//    如果连"开关没打开"也缓存，用户按提示去打开开关之后再试，
//    仍然会拿到缓存的失败结果 —— 只能重载扩展才行，体验很糟。
let userScriptsUsable = null;

/**
 * 给 USER_SCRIPT world 配一个允许 eval / new Function 的 CSP。
 *
 * ⚠️ **不配这个，exec_js 会直接失败**：
 *    USER_SCRIPT world 的 CSP **默认沿用 content script 那一套**，
 *    它**禁止动态代码执行**（eval / new Function）——
 *    而下面的 wrap 正是用 eval / new Function 去跑用户传来的脚本，
 *    于是会抛 `EvalError: Refused to evaluate a string as JavaScript
 *    because 'unsafe-eval' is not an allowed source of script in the
 *    following Content Security Policy directive…`。
 *
 *    这条很容易漏：**扩展能装、能连、其它命令都正常**，
 *    只有"执行 JS"这一个能力悄悄不可用。
 *
 * 官方文档：userScripts.configureWorld() 可以配置 USER_SCRIPT world 的 CSP；
 * MDN 关于默认值的说明是 "Defaults to the default CSP for content scripts,
 * which prohibits dynamic code execution, such as eval and new Function"。
 *
 * 这里额外放行 `wasm-unsafe-eval` 与 `blob:`：
 *   * WebAssembly —— 用户脚本里用 wasm 时不该无谓失败；
 *   * blob: —— 有些页面脚本会动态建 blob URL 再加载。
 * 仍然**不含** `unsafe-inline` / 远端源：我们只放行"动态执行"，
 * 不放行"注入任意内联脚本"或"加载远端代码"。
 */
let worldConfigured = false;

async function ensureUserScriptWorld() {
  if (worldConfigured) return true;
  // 老版本没有 configureWorld —— 不报错，让执行时的真实结果说话
  if (!chrome.userScripts || !chrome.userScripts.configureWorld) return false;
  try {
    await chrome.userScripts.configureWorld({
      csp: "script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob:",
    });
    worldConfigured = true;
    return true;
  } catch (e) {
    // 配置失败不直接终止：某些版本可能只接受部分关键字。
    // 记录下来，让 exec_js 的真实报错去解释（比在这里编一个错更准）。
    console.warn("[KiraBridge] configureWorld 失败（执行 JS 可能受限）", e);
    return false;
  }
}

async function ensureUserScripts() {
  if (userScriptsUsable && userScriptsUsable.ok) return userScriptsUsable;
  if (!chrome.userScripts) {
    userScriptsUsable = { ok: false, reason: "no_api" };
    return userScriptsUsable;
  }
  try {
    // 探测开关是否已打开：读一下配置即可，没权限会抛
    await chrome.userScripts.getScripts({});
    // ⚠️ 开关确认打开后，**必须**先配 world 的 CSP，
    //    否则下面的 eval / new Function 会被默认 CSP 挡掉。
    await ensureUserScriptWorld();
    userScriptsUsable = { ok: true };
  } catch (e) {
    userScriptsUsable = { ok: false, reason: "toggle_off", detail: e.message };
  }
  return userScriptsUsable;
}

async function execJs(params) {
  const { script, tab_id } = params;
  if (!script || !script.trim()) throw new Error("缺少 script");

  const tab = await resolveTab(tab_id);
  await assertInjectable(tab);

  const chk = await ensureUserScripts();
  if (!chk.ok) {
    if (chk.reason === "no_api") {
      throw new Error(
        "chrome.userScripts 不可用。可能的原因：\n" +
        "  1）浏览器版本低于 Chrome/Edge 120；\n" +
        "  2）Chrome 138+ 下**没有打开**扩展详情页里的「允许用户脚本 / " +
        "Allow User Scripts」开关 —— 关掉它会让 chrome.userScripts " +
        "直接变成 undefined，\n" +
        "     这种情况看起来就像是「浏览器不支持」。\n" +
        "请先在 chrome://extensions → Kira Browser Bridge → 详情 里检查该开关；\n" +
        "若确认已打开仍不行，可改用无头后端执行 JavaScript。"
      );
    }
    throw new Error(
      "执行任意 JavaScript 需要在扩展页手动打开一个开关：\n" +
      "  打开 chrome://extensions → 找到 Kira Browser Bridge → 详情 → " +
      "打开「允许用户脚本 / Allow User Scripts」，然后重试。\n" +
      "（这是 Chrome 138+ 的安全要求，扩展无法代劳。）"
    );
  }

  // ⚠️ 不要强制包成表达式 `(${script})` ——
  //    那样只能接受**单条表达式**，多语句（`const a=1; return a;`）会语法错误。
  //    正确做法：整段当**函数体**执行，用户既可以直接写表达式
  //    （自动补 return），也可以写多语句 + 显式 return。
  // ⚠️ **只在 SyntaxError 时**才退回函数体模式。
  //    如果对任何异常都退回，一条"能解析但运行到一半抛错"的表达式
  //    （例如 `items.forEach(i => post(i))`）会被**执行两遍** ——
  //    副作用重复，这比报错危险得多。
  const wrapped = [
    "(function(){",
    "  const __src = " + JSON.stringify(script) + ";",
    "  let expr;",
    "  try {",
    "    // 用 new Function 只做**语法检查**，不执行",
    "    new Function('return (' + __src + ')');",
    "    expr = true;",
    "  } catch (e) {",
    "    if (e instanceof SyntaxError) { expr = false; }",
    "    else { return { __error: String(e && e.message || e) }; }",
    "  }",
    "  try {",
    "    if (expr) { return eval('(' + __src + ')'); }",
    "    return (new Function(__src))();",
    "  } catch (e) { return { __error: String(e && e.message || e) }; }",
    "})()",
  ].join("\n");

  const jsPayload = [{ code: wrapped }];
  // ⚠️ **不要**用"先带 world 试，失败再不带 world 重试"那种 catch-and-retry。
  //    它在**任何**失败时都会重试 —— 包括"脚本已经开始注入之后才失败"
  //    （比如用户脚本里第一条 console 就抛错、或注入过程被中断）。
  //    那会让用户脚本**被执行两次**，副作用重复，且不可撤销。
  //    这和"页面操作超时不得换后端重试"是同一类危险。
  //
  //    是否需要 world 参数，已经在**事前**由 ensureUserScriptWorld()
  //    探测过了（它内部会判断浏览器是否支持 configureWorld）。
  //    所以这里直接执行一次，失败就如实往上报。
  const results = await chrome.userScripts.execute({
    target: { tabId: tab.id },
    js: jsPayload,
    world: "USER_SCRIPT",
    injectImmediately: true,
  });

  const first = (results && results[0]) || {};
  // ⚠️ CSP 拦截的错误**可能出现在两个地方**，两处都要认：
  //    · `first.error` —— chrome.userScripts.execute 这一层失败；
  //    · `first.result.__error` —— **更常见**：包装器内部的
  //      `catch (e) { return { __error: ... } }` 会把 EvalError
  //      吞成普通返回值，于是 first.error 是空的。
  //    只查 first.error 的话，用户拿到的是一句裸 EvalError 原文，
  //    而不是"该怎么修"的指引 —— 这正是这条提示想解决的问题。
  const _errText = String(first.error || "") +
    (first.result && typeof first.result === "object"
      ? String(first.result.__error || "") : "");
  if (_errText && /unsafe-eval|Content Security Policy|EvalError/i.test(_errText)) {
    throw new Error(
      "执行 JS 被浏览器的内容安全策略挡下了（需要允许动态执行）。\n" +
      "  请更新扩展后重试；若仍失败，改用无头后端执行 JavaScript。\n" +
      "  原始错误：" + _errText
    );
  }
  if (first.error) throw new Error("执行出错：" + first.error);
  // ⚠️ 注入的包装器会把**脚本自身的异常**吞成 `{ __error: "..." }` 返回
  //    （见上面的 wrap）。first.error 只能反映 chrome.userScripts.execute
  //    这一层失败，脚本抛错时 first.error 是空的 —— 若不在这里翻出来，
  //    就会以"成功"回给插件（sendResult(id, true, ...)），
  //    和 shared.js 里 callContent 把 __error 当错误的做法**不一致**。
  const res = first.result ?? null;
  if (res && typeof res === "object" && "__error" in res) {
    throw new Error(String(res.__error));
  }
  return { url: tab.url, result: res };
}

// ─── 2. 上传文件（内容由插件分块送来）──────────────────────────────────

/**
 * 上传中转。
 *
 * ⚠️ 这里**刻意不累积任何文件内容** —— 每收到一块就立刻转发给内容脚本。
 *
 * 原因：MV3 的 Service Worker 常驻内存很紧，恰恰最容易被系统回收，
 * 而回收会让正在进行的上传直接断掉。相比之下，页面上下文（内容脚本）
 * 的内存宽松得多。所以：
 *
 *    插件 ──(upload_chunk)──▶ service worker ──(立即转发)──▶ 内容脚本累积
 *                                    ↑
 *                            峰值恒定为一块（~0.3MB），与文件大小无关
 *
 * 实测（Node 基线）：文件 200MB 时，若在 SW 里攒 base64，峰值 ≈ 267MB。
 */

//: 只记"这次上传对应哪个 tab"，**不记文件内容**
const _uploadTabs = new Map();

function _uploadKey(id) {
  return String(id || "");
}

/** 开始一次上传：解析 tab、把会话建到内容脚本里。 */
async function upload(params) {
  const { selector, name, mime, limit, size, tab_id } = params;
  if (!selector) throw new Error("缺少 selector");
  if (!name) throw new Error("缺少文件名");

  const declared = Number(size) || 0;
  const cap = Number(limit) || 0;
  if (cap > 0 && declared > cap) {
    throw new Error(`文件过大（${declared} > 上限 ${cap} 字节），已拒绝上传`);
  }

  const tab = await resolveTab(tab_id);
  await assertInjectable(tab);

  const id = "up_" + Date.now().toString(36) + "_"
    + Math.random().toString(36).slice(2, 10);

  // 会话建在**页面侧**（那里负责累积）
  await callContent(tab, "upload_begin", {
    upload_id: id, selector, name,
    mime: mime || "application/octet-stream",
    size: declared, limit: cap,
  }, 30000);

  _uploadTabs.set(_uploadKey(id), { tabId: tab.id, created: Date.now() });
  for (const [k, v] of _uploadTabs) {
    if (Date.now() - v.created > 10 * 60 * 1000) _uploadTabs.delete(k);
  }
  return { ok: true, upload_id: id, url: tab.url };
}

/** 收一块就**立刻转发**，本层不留任何数据。 */
async function uploadChunk(params) {
  const key = _uploadKey(params.upload_id);
  const st = _uploadTabs.get(key);
  if (!st) throw new Error("上传会话不存在或已过期（请重新发起上传）");
  const { index, data } = params;
  if (typeof data !== "string" || !data) throw new Error("分块内容为空");

  const tab = await resolveTab(st.tabId);
  // ⚠️ 转发后立即返回、不保存 data —— 这一层的内存占用与文件大小无关。
  return await callContent(tab, "upload_chunk", {
    upload_id: params.upload_id, index, data,
  }, 30000);
}

/** 收尾：让内容脚本拼 File 并塞进 input。 */
async function uploadFinish(params) {
  const key = _uploadKey(params.upload_id);
  const st = _uploadTabs.get(key);
  if (!st) throw new Error("上传会话不存在或已过期（请重新发起上传）");

  const tab = await resolveTab(st.tabId);
  let res;
  try {
    res = await callContent(tab, "upload_finish", {
      upload_id: params.upload_id,
    }, 120000);
  } catch (e) {
    // ⚠️ 失败/超时时必须先把**页面侧**的会话收掉再去掉映射。
    //    否则 _upSessions 里的分块会一直挂着（大文件就是几百 MB 的内存
    //    泄漏），而且下一次同名上传还会撞上残留状态。
    //    页面可能已经关了，所以这里尽力而为、不再抛。
    try {
      await callContent(tab, "upload_abort", { upload_id: params.upload_id }, 10000);
    } catch (_) { /* 页面可能已关闭 */ }
    _uploadTabs.delete(key);
    throw e;
  }

  // 成功：页面侧在 upload_finish 内部已经删掉自己的会话
  _uploadTabs.delete(key);
  return { ok: true, url: tab.url, name: res.name,
           path: params.path || res.name, size: res.size,
           matched: res.matched };
}

/** 放弃这次上传（插件侧发块失败时会调）。 */
async function uploadAbort(params) {
  const key = _uploadKey(params.upload_id);
  const st = _uploadTabs.get(key);
  _uploadTabs.delete(key);
  if (st) {
    try {
      const tab = await resolveTab(st.tabId);
      await callContent(tab, "upload_abort", { upload_id: params.upload_id }, 10000);
    } catch (_) {
      // 尽力而为：页面可能已经关了
    }
  }
  return { ok: true };
}

// ─── 3. 下载（用用户会话抓取，分块回传）────────────────────────────────

const MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024;

// ⚠️ `link` 是**必须**的：分块要发回**发起下载的那条连接**。
//    多条连接共存时不能靠"当前连接"这类全局（异步交错会发错人）。
async function downloadViaSession(params, cmdId, link) {
  const { url, max_bytes } = params;
  if (!url) throw new Error("缺少 url");

  const limit = Number(max_bytes) > 0 ? Number(max_bytes) : MAX_DOWNLOAD_BYTES;

  // 在扩展自己的上下文里 fetch —— 会带上浏览器已存的 Cookie（同源）
  // ⚠️ 凭据按**起始 URL 的协议**决定：
  //    明文 HTTP 一律不带凭据（CWE-319）；HTTPS 才允许带上。
  const isHttps = url.toLowerCase().startsWith("https://");
  //
  // ⚠️ 关于重定向：用浏览器的 `redirect: "follow"`，**不要**自己用
  //    `redirect: "manual"` 去跟 —— 那个思路在浏览器里**根本走不通**：
  //    manual 返回的是 **opaqueredirect** 响应：`status` 是 0、
  //    **所有响应头都读不到**（包括 `Location`）。
  //    （Fetch 规范如此。StackOverflow 上 "Response headers not available
  //     for fetch request with redirect: manual" 的回答很直接：
  //     "No, it's not possible. The requirements in the Fetch spec prevent it."）
  //    所以"自己跟"读不到下一跳地址 —— 那等于把"重定向全失败"
  //    换个写法而已（上一版就犯了这个错）。
  //
  //    让浏览器跟随是**安全**的，因为它在**每一跳**会自己重新计算要发
  //    哪些 Cookie：
  //      · Secure cookie 永远不会出现在 HTTP 请求上（浏览器保证）；
  //      · domain 不匹配的 cookie 不会发给别的站点。
  //    跳数上限也由浏览器保证（重定向过多会直接失败），不用我们自己数。
  //
  //    跟随完成后**再检查最终 URL**：起始是 HTTPS 却落在 HTTP 上时中止 ——
  //    那可能是站点配置问题，也可能是中间人。
  const resp = await fetch(url, {
    credentials: isHttps ? "include" : "omit",
    redirect: "follow",
  });
  {
    const finalUrl = resp.url || url;
    const finalIsHttps = finalUrl.toLowerCase().startsWith("https://");
    if (isHttps && !finalIsHttps) {
      throw new Error(
        `下载地址在重定向后从 HTTPS 变成了明文 HTTP（${finalUrl}），已中止。`
        + `请确认这是站点的正常行为；若确实需要，请直接用该 HTTP 地址下载。`)
    }
  }
  if (!resp.ok) throw new Error(`下载失败，HTTP ${resp.status}`);

  const declared = Number(resp.headers.get("Content-Length") || 0);
  if (declared && declared > limit) {
    throw new Error(`文件过大（${declared} 字节 > 上限 ${limit}），已拒绝`);
  }

  const mime = resp.headers.get("Content-Type") || "application/octet-stream";
  // ⚠️ `resp.body` 可能是 **null** —— 有些响应本来就没有正文
  //    （204 No Content、304 Not Modified、HEAD 请求的响应等）。
  //    直接 `.getReader()` 会抛 `TypeError: Cannot read properties of null`，
  //    而那句话对用户毫无意义。这里按"零字节文件"处理：
  //    返回与正常路径**同一个结构**（ok/url/mime/bytes），bytes=0，
  //    调用方不必为这种情况写特例。
  if (!resp.body) {
    return { ok: true, url, mime, bytes: 0 };
  }
  const reader = resp.body.getReader();
  const CHUNK = 256 * 1024;          // 每块 256KB
  let total = 0;
  let buf = new Uint8Array(0);

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // 把新到的拼到残留缓冲后面
    const merged = new Uint8Array(buf.length + value.length);
    merged.set(buf, 0);
    merged.set(value, buf.length);
    buf = merged;

    while (buf.length >= CHUNK) {
      const slice = buf.slice(0, CHUNK);
      buf = buf.slice(CHUNK);
      total += slice.length;
      if (total > limit) {
        try { await reader.cancel(); } catch (_) {}
        throw new Error(`文件超过上限 ${limit} 字节，已中止`);
      }
      // ⚠️ 发失败（socket 已关）必须中止下载并抛错：
      //    否则会一路走到 return {ok:true}，调用方以为下载成功，
      //    而磁盘上的文件其实缺了后面所有分块。
      if (!sendChunk(cmdId, slice, link)) {
        try { await reader.cancel(); } catch (_) {}
        throw new Error("连接已断开，下载分块无法回传，已中止");
      }
    }
  }
  if (buf.length) {
    total += buf.length;
    // ⚠️ 最后这一块同样要在**回传前**查上限 ——
    //    否则一个刚好卡在边界外的文件会绕过限制被完整传出。
    if (limit > 0 && total > limit) {
      throw new Error(`文件超过上限 ${limit} 字节，已中止`);
    }
    if (!sendChunk(cmdId, buf, link)) {
      throw new Error("连接已断开，下载分块无法回传，已中止");
    }
  }

  return { ok: true, url, mime, bytes: total };
}

// sendChunk 由 shared.js 提供（这里不能再声明一次：
// 与 import 的同名绑定冲突会让整个模块语法错误）

// ─── 4. Cookie 导出 / 导入（打通两个后端的登录态）──────────────────────

async function cookieGet(params) {
  const tab = await resolveTab(params.tab_id);
  const url = params.url || tab.url;
  if (!url || !/^https?:/i.test(url)) {
    throw new Error("只能导出 http/https 页面的 cookie");
  }
  const cookies = await chrome.cookies.getAll({ url });
  return {
    url,
    // ⚠️ 必须带上 hostOnly —— 它是**安全语义**，不是可选元数据：
    //    host-only 的 cookie 只发给**精确匹配**的那个主机；
    //    丢了它、导入时又无条件设置 domain，这个 cookie 就会
    //    变成"域 cookie"，**子域也能收到** —— 作用域被悄悄放宽了。
    cookies: cookies.map((c) => ({
      name: c.name, value: c.value, domain: c.domain, path: c.path,
      secure: c.secure, httpOnly: c.httpOnly, sameSite: c.sameSite,
      expirationDate: c.expirationDate, hostOnly: c.hostOnly,
    })),
  };
}

async function cookieSet(params) {
  const list = params.cookies || [];
  let ok = 0, failed = 0;
  for (const c of list) {
    if (!c || !c.name || !c.domain) { failed++; continue; }
    const host = String(c.domain).replace(/^\./, "");
    const scheme = c.secure ? "https" : "http";
    const details = {
      url: `${scheme}://${host}${c.path || "/"}`,
      name: c.name,
      value: c.value == null ? "" : String(c.value),
      path: c.path || "/",
      secure: !!c.secure,
      httpOnly: !!c.httpOnly,
    };
    // ⚠️ host-only 的 cookie **不能**带 domain 字段 ——
    //    带了就等于把它升格成"域 cookie"，子域也收得到（作用域被放宽）。
    //    chrome.cookies.set 不带 domain 时会按 url 的主机推断，
    //    正好还原 host-only 的语义。
    //    （只有 hostOnly 明确为 false 时才写 domain；缺字段时按旧行为设，
    //      兼容还没带这个字段的旧扩展/旧导出文件。）
    if (c.hostOnly !== true) details.domain = c.domain;
    const ss = String(c.sameSite || "").toLowerCase();
    if (ss === "strict") details.sameSite = "strict";
    else if (ss === "lax") details.sameSite = "lax";
    else if (ss === "none" || ss === "no_restriction") details.sameSite = "no_restriction";
    if (c.expirationDate) details.expirationDate = Number(c.expirationDate);
    try {
      await chrome.cookies.set(details);
      ok++;
    } catch (_) {
      failed++;
    }
  }
  // 字段名与无头后端保持一致：written/skipped/failed/total
  // （否则同一个工具因为路由到不同后端而给出不同形状的结果）
  return { ok, written: ok, skipped: 0, failed, total: list.length };
}

/**
 * 读书签（数据接口，**不碰页面**）。
 *
 * ⚠️ 为什么要它：`edge://bookmarks` 是**浏览器内部页**，任何扩展都注入不进去
 *    （硬边界），所以"打开书签页去读"这条路是死的。
 *    但书签**数据**本身可以通过 `chrome.bookmarks` 拿 ——
 *    这才是用户真正想要的东西（要的是书签，不是那个页面）。
 *    需要 manifest 里有 `bookmarks` 权限。
 *
 * @param {object} params
 *   - query        : 关键词（匹配标题或网址，不区分大小写）
 *   - max          : 最多返回多少条（默认 200，防一次刷爆上下文）
 *   - folders_only : 只要文件夹（不要书签条目）
 */
async function bookmarks(params = {}) {
  if (!chrome.bookmarks) {
    throw new Error("chrome.bookmarks 不可用 —— 扩展可能没重新加载"
                  + "（本功能需要 manifest 里的 bookmarks 权限）");
  }
  const query = String(params.query || "").trim().toLowerCase();
  const max = Math.max(1, Math.min(2000, Number(params.max) || 200));
  const foldersOnly = !!params.folders_only;

  const tree = await chrome.bookmarks.getTree();
  const out = [];
  let total = 0;

  const walk = (nodes, path) => {
    for (const n of nodes || []) {
      const here = path ? `${path}/${n.title || "(未命名)"}` : (n.title || "");
      if (n.url) {
        total += 1;
        const hit = !query
          || (n.title || "").toLowerCase().includes(query)
          || n.url.toLowerCase().includes(query);
        if (!foldersOnly && hit && out.length < max) {
          out.push({ title: n.title || "", url: n.url, folder: path || "(根)" });
        }
      } else {
        if (foldersOnly && out.length < max && (!query
            || (n.title || "").toLowerCase().includes(query))) {
          out.push({ title: n.title || "", url: "", folder: path || "(根)",
                     is_folder: true });
        }
        walk(n.children, here);
      }
    }
  };
  walk(tree, "");

  return { count: out.length, total_bookmarks: total,
           truncated: out.length >= max, query: params.query || "",
           bookmarks: out };
}

/**
 * 读浏览**历史**（chrome.history）。和书签同理：要的是数据，不是那个页面。
 *  @param {object} params - query（关键词）/ max（默认 100）/ days（只取最近几天）
 */
async function historySearch(params = {}) {
  if (!chrome.history) {
    throw new Error("chrome.history 不可用 —— 扩展可能没重新加载"
                  + "（本功能需要 manifest 里的 history 权限）");
  }
  const query = String(params.query || "").trim();
  const max = Math.max(1, Math.min(2000, Number(params.max) || 100));
  const days = Number(params.days) || 0;
  const startTime = days > 0 ? Date.now() - days * 86400000 : 0;
  const arr = await chrome.history.search(
    { text: query, maxResults: max, startTime });
  return {
    count: arr.length, query,
    items: arr.map((h) => ({
      title: h.title || "", url: h.url,
      visits: h.visitCount || 0,
      last: h.lastVisitTime ? new Date(h.lastVisitTime).toISOString() : "",
    })),
  };
}

/**
 * 剪贴板读写（`navigator.clipboard`）。
 *
 * ⚠️ **不能用 execJs**：那条路走 `chrome.userScripts`，用户没在扩展详情页
 *    打开"允许用户使用脚本"就整个不可用 ✗ —— 剪贴板是常用功能，
 *    不能绑在那个开关上。这里改用 `chrome.scripting.executeScript` 的
 *    **ISOLATED**（普通内容脚本）world —— 不需要那个开关 ✓
 *
 * ⚠️ 已知限制：**读**剪贴板要求页面**处于聚焦状态**
 *    （浏览器隐私限制，`readText()` 在后台标签会抛 NotAllowedError）。
 *    这里会把原因说清楚，而不是笼统报失败。
 */
async function clipboardOp(params = {}) {
  const { mode } = params;
  if (!params.tab_id && !params.any_tab) {
    // 不传 tab_id 时就找当前活动标签
  }
  const tab = await resolveTab(params.tab_id);
  const fn = mode === "write"
    ? (text) => navigator.clipboard.writeText(text).then(() => text)
    : () => navigator.clipboard.readText();

  let results;
  try {
    results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: "ISOLATED",                       // ← 关键：不需要 userScripts
      func: mode === "write" ? (t) => navigator.clipboard.writeText(t)
                             : () => navigator.clipboard.readText(),
      args: mode === "write" ? [String(params.text ?? "")] : [],
    });
  } catch (e) {
    const msg = String(e && e.message || e);
    if (/Cannot access|chrome:\/\/|edge:\/\//i.test(msg)) {
      throw new Error("当前是浏览器内部页，不能在里面读写剪贴板"
                    + "（和内部页读不了 DOM 是同一个硬边界）");
    }
    if (/NotAllowedError|not focused|Document is not focused/i.test(msg)) {
      throw new Error("读剪贴板要求**页面处于聚焦状态**（浏览器隐私限制）—— "
                    + "点一下目标标签让它在前台，再试一次");
    }
    throw e;
  }
  const val = results && results[0] ? results[0].result : undefined;
  return mode === "write"
    ? { mode, ok: true, length: String(params.text ?? "").length, text: "" }
    : { mode, text: typeof val === "string" ? val : String(val ?? "") };
}

export { execJs, upload, uploadChunk, uploadFinish, uploadAbort,
         downloadViaSession, cookieGet, cookieSet, ensureUserScripts, bookmarks, historySearch, clipboardOp };
