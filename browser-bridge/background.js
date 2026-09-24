/**
 * Kira Browser Bridge —— 后台 Service Worker
 *
 * 职责：
 *   1. 维持与 KiraAI 插件的 WebSocket 长连接（含保活与自动重连）
 *   2. 接收插件下发的命令，在浏览器里执行并回传结果
 *   3. 主动上报浏览事件（页面加载、标签切换）供 AI「可感知」
 *
 * MV3 注意事项：
 *   - Service Worker 会被浏览器回收，WebSocket 会随之断开。这里用
 *     chrome.alarms 定期唤醒，唤醒后检测连接并按需重连。
 *   - chrome.scripting.executeScript 只能传函数，不能传字符串脚本。
 *     所有页面内操作都放在 content.js 里，通过 sendMessage 调用。
 */

import {
  PROTOCOL_VERSION, MSG, CMD, EVT,
  buildWsUrl, KEEPALIVE_ALARM, KEEPALIVE_PERIOD_MINUTES, RECONNECT_DELAYS, STORE,
  DEFAULT_CONFIRM_TIMEOUT_MS, PAIR_PATH, CANDIDATE_PORTS, READ_COMMANDS,
} from "./protocol.js";
import { execJs, upload, uploadChunk, uploadFinish, uploadAbort,
         downloadViaSession, cookieGet, cookieSet, bookmarks, historySearch, clipboardOp } from "./capabilities.js";
import {
  state, links, activity, otherWriterFor,
  sendRaw, sendResult, sendEvent, sendChunk,
  resolveTab, assertInjectable, callContent, detectBrowser,
  isFileAccessAllowed, invalidateFileAccessCache, fileAccessHelp,
  askUser, confirmTimeoutMs, resolveConfirm,
  NEEDS_CONFIRM_COMMANDS, confirmPromptFor,
  isLinkStale, WS_STALE_MS, staleLogDecision,
} from "./shared.js";
import {
  getInfo, goBack, refresh, hover, keyPress, keyDownUp,
  mouseMove, mouseClick, mouseDownUp, mouseWheel, mouseDrag,
  listFiles, debugInfo,
} from "./commands.js";

// ─── 连接状态 ────────────────────────────────────────────────────────────────







/**
 * 用户是否手动点过「断开」。
 *
 * 与 state.intentionalClose 的区别：state.intentionalClose 只在本次 close 事件里有效，
 * 而 alarms 保活每 30 秒就会调用一次 ensureAlive() —— 如果它不看这个标记，
 * 用户点完「断开」，半分钟后连接又自己回来了，弹窗里那句"自动重连已暂停"
 * 就成了假话。只有手动点「连接」才会清掉它。
 */


// ─── 状态持久化（popup 需要读） ──────────────────────────────────────────────

async function setStatus(patch) {
  const cur = (await chrome.storage.local.get(STORE.LAST_STATUS))[STORE.LAST_STATUS] || {};
  const next = Object.assign({}, cur, patch, { updatedAt: Date.now() });
  await chrome.storage.local.set({ [STORE.LAST_STATUS]: next });
}

/** 已配对的实例列表（扩展会**全部连上**，不是挑一个）。
 *
 *  ⚠️ 老版本只存单个 host/port/token —— 这里做一次性迁移，
 *     否则升级上来的用户会突然"一个都连不上"。
 *  ⚠️ 这个函数**必须**返回 `instances` 数组：调用方直接读 `.length`，
 *     返回 undefined 会在 bootstrap 阶段就抛异常、整个扩展起不来。
 */
// 导出给**冒烟测试**用：`getConfig()` 的返回形状是调用方直接依赖的
// （`cfg.instances.length`），漏了就会在 bootstrap 阶段炸掉整个扩展。
export async function getConfig() {
  const s = await chrome.storage.local.get([
    STORE.INSTANCES, STORE.AUTO_CONNECT, STORE.HOST, STORE.PORT, STORE.TOKEN,
  ]);
  let list = s[STORE.INSTANCES];
  if (!Array.isArray(list)) {
    list = [];
    if (s[STORE.TOKEN]) {
      list.push({
        host: s[STORE.HOST] || "127.0.0.1",
        port: Number(s[STORE.PORT]) || 5267,
        token: s[STORE.TOKEN],
        label: "",
      });
    }
  }
  return {
    instances: list.filter((x) => x && x.token && Number(x.port) > 0),
    autoConnect: s[STORE.AUTO_CONNECT] !== false,
  };
}

/** 把一个实例写进列表（按 host:port 去重，已存在就更新令牌与标签）。 */
export async function upsertInstance(inst) {
  const cfg = await getConfig();
  const key = (x) => `${x.host || "127.0.0.1"}:${Number(x.port)}`;
  const list = cfg.instances.filter((x) => key(x) !== key(inst));
  list.push(Object.assign({ host: "127.0.0.1", label: "" }, inst,
                          { port: Number(inst.port) }));
  await chrome.storage.local.set({ [STORE.INSTANCES]: list });
  return list;
}

// ─── 零配置接入：自动发现本机的 KiraAI 实例 ──────────────────────────────────
//
//  为什么需要：扩展原来要用户手填 服务地址 / 端口 / 令牌 三样，而端口在
//  代码里**写死 5267**。用户只要改过 KiraAI 的端口就连不上，且报错只说
//  "连不上" —— 小白用户根本不知道该改哪里。
//
//  做法：向候选端口发一个 GET 到插件的配对端点，谁回了就把它的
//  **端口 + 令牌**存下来。插件侧对这个端点做了"只回答本机请求"的限制，
//  所以不需要登录也不会把令牌漏给网络上的其他人。

/** 探测单个端口；命中返回插件给的接入信息，否则 null。 */
export async function probePort(port, timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`http://127.0.0.1:${port}${PAIR_PATH}`, {
      signal: ctrl.signal,
      cache: "no-store",
    });
    if (!r.ok) return null;
    const j = await r.json();
    if (!j || !j.ok || !j.token) return null;
    // ⚠️ **端口以"探测到的"为准**，不用响应里报的那个。
    //    我们刚刚就是在这个端口上跟它说上话的 —— 这是硬证据。
    //    而响应里的 port 是插件读 `webui.json` 得来的，某些部署下该文件
    //    不存在（插件会回落到默认 5267）—— 于是会出现
    //    "在 8080 探测成功、却被记成 5267、然后连 5267 失败"。
    return Object.assign({}, j, { port });
  } catch (e) {
    return null;                  // 端口没人听 / 不是 KiraAI / 超时
  } finally {
    clearTimeout(timer);
  }
}

/** 把探测到的接入信息写进存储。 */
async function applyPair(hit) {
  const host = hit.host || "127.0.0.1";
  const port = Number(hit.port) || 5267;
  // ⚠️ 必须写**新格式**（instances 列表），不能只写旧版单实例键。
  //    原来这里只 `set({kb_host, kb_port, kb_token})`，而 `getConfig()`
  //    仅在 `kb_instances` **不是数组**时才把旧键迁移成列表 ——
  //    于是"已经配对过实例"的用户再配一个新的（比如点「自动检测」），
  //    新实例会被**静默丢弃**：界面看着像成功了，实际什么都没变。
  await upsertInstance({
    host, port, token: hit.token, label: hit.label || "",
  });
  // 旧键同步写一份：万一用户回滚到老版本还能用（且此时列表已是数组，
  // migration 不会再拿旧键去覆盖它）。
  await chrome.storage.local.set({
    [STORE.HOST]: host,
    [STORE.PORT]: port,
    [STORE.TOKEN]: hit.token,
  });
  // 配对成功就把"重试发现"的退避清零 —— 否则用户手动连上之后，
  // 那次退避还会让后台的自动重试等很久才开始。
  await chrome.storage.local.set({
    [STORE.DISCOVER_TRIES]: 0, [STORE.DISCOVER_AT]: 0,
  });
  return { host, port, token: hit.token };
}

/**
 * 自动发现 KiraAI 实例并写好配置。
 *
 * ⚠️ **一台机器上可能有多个 KiraAI**（不同端口、不同数据目录），
 *    它们都装了本插件。所以这里的原则是：
 *
 *    1. **先单独探"用户存过的端口"** —— 保证已经配好的人永远连同一个实例，
 *       不会因为"并行探测谁先回"而漂到别的实例上去。
 *    2. 扫其余候选端口，收集**全部**命中。
 *    3. 命中 0 个 → 报错并给手动办法。
 *    4. 命中 1 个 → 直接填好（小白的默认路径，零配置）。
 *    5. 命中 **≥2 个 → 不猜**，把列表交回去让用户选。
 *       猜错的后果是"我对 A 说话，B 却动了我的浏览器"，比多点一下严重得多。
 */
export async function discover({ timeoutMs = 1500 } = {}) {
  const saved = await getConfig();

  // ① 存过的端口优先，单独探，命中就锁定
  if (saved.port) {
    const hit = await probePort(saved.port, timeoutMs);
    if (hit) return { ok: true, single: await applyPair(hit) };
  }

  // ② 扫其余候选端口
  const ports = [];
  for (const p of CANDIDATE_PORTS) {
    const n = Number(p);
    if (Number.isInteger(n) && n > 0 && n < 65536
        && n !== Number(saved.port) && !ports.includes(n)) ports.push(n);
  }
  const results = await Promise.all(ports.map((p) => probePort(p, timeoutMs)));
  const hits = [];
  for (const r of results) {
    if (r && r.ok && r.token && !hits.some((h) => Number(h.port) === Number(r.port))) {
      hits.push(r);
    }
  }

  if (hits.length === 0) {
    // ⚠️ 这条文案必须是**能照做**的。
    //    原来写的是"去插件面板点「复制接入配置」" —— 面板上**没有这个按钮**
    //    （它只在页面里 postMessage 自动配对，没做剪贴板那套），
    //    用户照着找不到，等于把人指到一条不存在的路上。
    //    这里改成两条**真实存在**的路：
    //      ① 从 127.0.0.1 / localhost 打开插件面板 → 页面自动把接入信息推过来
    //      ② 或手动填：服务地址 + 端口 + 令牌（令牌在插件面板上点「复制」拿）
    return {
      ok: false,
      // 把**试过哪些端口**一起带回去：用户一看就知道"我的端口不在这个列表里"，
      // 而不是对着一句"没找到"猜。
      triedPorts: CANDIDATE_PORTS.slice(),
      // ⚠️ 措辞别再写"从 127.0.0.1 或 localhost 打开" —— 范围太窄：
      //    检测对**任何私网地址**都生效（127/localhost/::1/10.x/192.168.x/
      //    172.16-31.x/*.local），而且**不限于插件面板页**，随便哪个 KiraAI
      //    页面都行。写窄了会让用户以为必须用某个特定地址。
      error: "没有在本机找到 KiraAI 实例。可能是它用了不常见的端口 —— "
           + "最简单的办法：**打开一次你的 KiraAI 页面**（平时聊天用的"
           + "那个地址就行），扩展会从页面地址认出端口并自动配对；"
           + "或者在下面手动填「服务地址 / 端口 / 令牌」"
           + "（令牌在插件面板上点「复制」拿）。",
    };
  }
  if (hits.length === 1) {
    return { ok: true, single: await applyPair(hits[0]) };
  }
  // ③ 多个实例 —— 交回给用户选，绝不替用户猜
  return {
    ok: false,
    multiple: hits.map((h) => ({
      host: h.host || "127.0.0.1",
      port: Number(h.port),
      token: h.token,
      instance: h.instance || "",
      data_dir: h.data_dir || "",
    })),
    error: `本机找到 ${hits.length} 个 KiraAI 实例，请选一个。`,
  };
}

// ─── 连接管理：**多连接** ─────────────────────────────────────────────────────
//
//  ⚠️ 为什么不是"选一个连"：一台机器上可以同时跑多个 KiraAI 实例，它们都装了
//     本插件、都想操作这**同一个**浏览器。所以扩展不是挑一个，而是**全都连上**。
//
//      好处一：不用挑 —— 根本不存在"选错实例"这回事
//              （原来那套"面板交接 / 让用户选"是为了绕开"只能连一个"这个
//                自设的限制，现在整个不需要了）。
//      好处二：两个 bot 可以**同时看着同一个页面**。
//      代价  ：它会变成"一个浏览器两只手"。会抢，而且**互相看不见对方刚做了什么** ——
//              最危险的不是抢鼠标，是"我以为页面还是我上次看到的样子"。
//              所以每条命令的返回里都带上 `meta.url` 和 `meta.last_actor`
//              （上次**写**操作来自哪个实例），让 bot 自己发现页面被动了。

/** 扩展侧"半开连接自愈"的统计：换了几次、日志最后一次是什么时候喊的。
 *
 *  ⚠️ 为什么要降噪：链路真半开时这个动作**每分钟**都会发生（阈值 60 秒），
 *     一条条打进控制台 = 换了个地方刷屏，而这件事本来是为了让日志变干净的。
 *     同一窗口内只喊一次，其余只累加计数 —— 数字在弹窗里看得到。
 *  ⚠️ 计数要落盘：MV3 的 Service Worker 会被回收，内存里的数字撑不过一次回收。
 */
const staleStat = { count: 0, logAt: 0, suppressed: 0 };

// 启动时（每次 Service Worker 唤醒都会重跑）把累计数读回来
chrome.storage.local.get([STORE.STALE_RECONNECTS])
  .then((s) => { staleStat.count = Math.max(0, Number(s[STORE.STALE_RECONNECTS]) || 0); })
  .catch(() => {});

/** 一条到某个 KiraAI 实例的连接。 */
export class Link {
  constructor(inst) {
    this.inst = Object.assign(
      { host: "127.0.0.1", port: 5267, token: "", label: "" }, inst || {});
    this.ws = null;
    this.intentionalClose = false;
    this.reconnectTimer = null;
    this.reconnectAttempt = 0;
    this.lastError = "";
    this.connecting = null;
    //: 最后一次收到服务端数据的时间（epoch ms）。保活闹钟醒来时用它判断
    //: "看着 OPEN、其实半开"的链路（见 shared.js 的 isLinkStale）。
    this.lastInboundAt = 0;
  }

  get key() { return `${this.inst.host}:${this.inst.port}`; }
  get label() { return this.inst.label || this.key; }
  get open() { return !!this.ws && this.ws.readyState === WebSocket.OPEN; }

  status() {
    let s = "disconnected";
    if (this.ws) {
      if (this.ws.readyState === WebSocket.OPEN) s = "connected";
      else if (this.ws.readyState === WebSocket.CONNECTING) s = "connecting";
    }
    return { key: this.key, label: this.label, host: this.inst.host,
             port: this.inst.port, status: s, error: this.lastError };
  }

  sendRaw(obj) {
    if (!this.open) return false;
    try { this.ws.send(JSON.stringify(obj)); return true; } catch (_) { return false; }
  }

  /** 建立连接。并发调用共用同一个 promise，不会连出两条。 */
  connect() {
    if (this.open) return Promise.resolve({ ok: true, already: true });
    if (this.connecting) return this.connecting;
    this.intentionalClose = false;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.connecting = this._doConnect().finally(() => { this.connecting = null; });
    return this.connecting;
  }

  _doConnect() {
    let url;
    try {
      url = buildWsUrl(this.inst.host, this.inst.port, this.inst.token);
    } catch (e) {
      this.lastError = e.message;
      scheduleReconnect(this);
      return Promise.resolve({ ok: false, error: e.message });
    }
    console.log("[KiraBridge] 正在连接", this.label,
                url.replace(/token=.*/, "token=***"));

    let ws;
    try {
      ws = new WebSocket(url);
      this.ws = ws;
    } catch (e) {
      this.lastError = "创建连接失败：" + e.message;
      scheduleReconnect(this);
      return Promise.resolve({ ok: false, error: this.lastError });
    }

    return new Promise((resolve) => {
      let settled = false;
      const settle = (v) => { if (!settled) { settled = true; resolve(v); } };

      const openTimeout = setTimeout(() => {
        this.lastError = "连接超时：确认 KiraAI 正在运行，且插件已启用";
        // ⚠️ 超时后必须**真的把这个 socket 收掉**：
        //    只 settle 的话它会一直停在 CONNECTING，this.ws 仍指向它 →
        //    之后 ensureAlive/connect 都看到"已有连接"而直接返回，
        //    用户点多少次重连都没用（既连不上也没人重试）。
        try { ws.close(); } catch (_) {}
        if (this.ws === ws) this.ws = null;
        scheduleReconnect(this);
        settle({ ok: false, error: this.lastError });
      }, 8000);

      // ⚠️ 所有回调都先确认"我还是这条连接当前的 socket"。
      //    否则：disconnect() 关旧 socket → 用户马上重连 →
      //    旧 socket 的 onclose 在新 socket 写入之后才执行，
      //    于是它把**新连接**的引用清成 null，还可能给旧连接起一次重连。
      ws.onopen = () => {
        if (this.ws !== ws) return;
        clearTimeout(openTimeout);
        this.reconnectAttempt = 0;
        this.lastError = "";
        this.lastInboundAt = Date.now();
        console.log("[KiraBridge] 已连接", this.label);
        this.sendRaw({
          type: MSG.HELLO,
          protocol: PROTOCOL_VERSION,
          extension_version: chrome.runtime.getManifest().version,
          browser: detectBrowser(),
        });
        refreshBadgeAndStatus();
        settle({ ok: true, label: this.label });
      };

      ws.onmessage = (ev) => {
        if (this.ws !== ws) return;
        // 记下"最后一帧是什么时候到的" —— 保活闹钟醒来时会用它判断链路是否半开
        this.lastInboundAt = Date.now();
        handleMessage(ev.data, this)
          .catch((e) => console.error("[KiraBridge] 消息处理异常", e));
      };

      ws.onerror = () => {
        if (this.ws !== ws) return;
        // onerror 后必然跟 onclose，这里不重连，避免双触发
        this.lastError = "连接出错，请确认 KiraAI 正在运行";
      };

      ws.onclose = (ev) => {
        clearTimeout(openTimeout);
        if (this.ws !== ws) { settle({ ok: false, error: "连接已被替换" }); return; }
        console.log("[KiraBridge] 连接关闭", this.label, ev.code, ev.reason);
        this.ws = null;
        if (!this.lastError) this.lastError = `连接已断开 (${ev.code})`;
        refreshBadgeAndStatus();
        settle({ ok: false, error: this.lastError });
        if (!this.intentionalClose) scheduleReconnect(this);
      };
    });
  }

  close(reason = "closed") {
    this.intentionalClose = true;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const cur = this.ws;
    this.ws = null;
    if (cur) { try { cur.close(1000, reason); } catch (_) {} }
  }
}



// 活动记录与判定都挪到了 shared.js —— 那边能被 node 测试直接 import，
// 这里只用它。（`activity` / `otherWriterFor`）



export function getLinks() {
  return Array.from(links.values()).map((l) => l.status());
}

function upsertLink(inst) {
  const key = `${inst.host || "127.0.0.1"}:${inst.port}`;
  let l = links.get(key);
  if (!l) {
    l = new Link(inst);
    links.set(key, l);
  } else {
    l.inst = Object.assign(l.inst, inst);
  }
  return l;
}

function refreshBadgeAndStatus() {
  const list = getLinks();
  const n = list.filter((x) => x.status === "connected").length;
  chrome.action.setBadgeText({ text: n ? String(n) : "" });
  chrome.action.setBadgeBackgroundColor({ color: "#16a34a" });
  return setStatus({
    connected: n > 0,
    count: n,
    instances: list,
    error: list.find((x) => x.error && x.status !== "connected")?.error || "",
  });
}

/** 连上所有已配对的实例（并发）。 */
export async function connectAll({ manual = false } = {}) {
  const cfg = await getConfig();

  if (manual) await setUserDisconnected(false);
  else if (await isUserDisconnected()) return { ok: false, error: "用户已手动断开" };

  // 一条都没配对过 → 先自动发现（首次安装的默认路径）
  if (!cfg.instances.length) {
    const d = await discover();
    if (!d.ok) {
      await setStatus({ connected: false, count: 0, error: d.error,
                        triedPorts: d.triedPorts || [] });
      return { ok: false, error: d.error, triedPorts: d.triedPorts };
    }
  }

  const all = (await getConfig()).instances;
  for (const inst of all) upsertLink(inst);

  const results = await Promise.all(
    Array.from(links.values()).map((l) => l.connect()));
  await refreshBadgeAndStatus();
  const okN = results.filter((r) => r.ok).length;
  return { ok: okN > 0, count: okN, total: all.length,
           error: okN ? "" : (results[0]?.error || "没有连上任何实例") };
}

/** 兼容旧名字（后台保活、popup 都在用）。 */
export async function connect(opts) { return connectAll(opts); }

export async function disconnect() {
  await setUserDisconnected(true);
  for (const l of links.values()) l.close("user disconnected");
  await refreshBadgeAndStatus();
  return { ok: true };
}

/** 用户是否手动断过 —— 读持久化值（Service Worker 会被回收，内存不可靠） */
async function isUserDisconnected() {
  try {
    const s = await chrome.storage.local.get(STORE.USER_DISCONNECTED);
    return s[STORE.USER_DISCONNECTED] === true;
  } catch (_) {
    return state.userDisconnected;
  }
}

async function setUserDisconnected(v) {
  state.userDisconnected = !!v;
  try {
    await chrome.storage.local.set({ [STORE.USER_DISCONNECTED]: !!v });
  } catch (_) {}
}

/** 给某条连接安排一次重连。 */
function scheduleReconnect(link) {
  if (!link || link.intentionalClose) return;
  if (link.reconnectTimer) return;
  if (state.userDisconnected) return;

  const delay = RECONNECT_DELAYS[
    Math.min(link.reconnectAttempt, RECONNECT_DELAYS.length - 1)];
  link.reconnectAttempt += 1;
  console.log(`[KiraBridge] ${link.label} ${delay}ms 后重连（第 ${link.reconnectAttempt} 次）`);
  link.reconnectTimer = setTimeout(async () => {
    link.reconnectTimer = null;
    const cfg = await getConfig();
    if (!cfg.autoConnect) return;
    if (await isUserDisconnected()) return;
    // ⚠️ 反复失败时，问题多半**不是"连不上"，而是"令牌作废了"**：
    //    插件侧的令牌与 KiraAI 的鉴权状态**绑定** —— KiraAI 重启、或轮换
    //    access_token 之后旧令牌**当场作废**。而扩展这边只会拿旧令牌一遍遍
    //    重连、**永远不会回去重新配对**，于是面板上「扩展连接」永远显示未连接
    //    （"昨天还好好的，今天又连不上了"）。这里补上自救。
    if (link.reconnectAttempt >= REPAIR_AFTER_ATTEMPTS) {
      if (await repainKnownInstance(link)) {
        link.reconnectAttempt = 0;
        await link.connect();
        return;
      }
    }
    await link.connect();
  }, delay);
}

/** 连续失败几次之后，就回**已知的那个地址**重新领一枚令牌并重连。
 *
 *  为什么不重扫端口：地址我们是知道的（就是 link.inst 里的 host:port），
 *  直接回那个地址问一次 `/pair` 就行 —— 快，而且**不依赖候选端口列表**
 *  （KiraAI 装在 5274 这种非常见端口时，重扫是扫不到的）。
 *
 *  返回 true 表示拿到了新令牌（调用方接着重连）。
 */
async function repainKnownInstance(link) {
  const { host, port } = link.inst || {};
  if (!host || !port) return false;
  try {
    const r = await fetch(`http://${host}:${port}${PAIR_PATH}`, { cache: "no-store" });
    if (!r.ok) return false;
    const j = await r.json();
    if (!j || !j.ok || !j.token) return false;
    if (j.token === link.inst.token) return false;   // 令牌没变，重连也没用
    console.log("[KiraBridge] 令牌已失效，重新配对成功", link.label);
    await upsertInstance({ host, port: Number(port), token: j.token,
                           label: link.inst.label || "" });
    link.inst.token = j.token;
    return true;
  } catch (_) {
    return false;      // 网络不通 / 不是 KiraAI —— 下次再说
  }
}

/** 连续失败几次之后就去重新配对（令牌作废是最常见的"连不上"原因）。
 *  取 3：前两次给真实的网络抖动留余地，第三次基本可以断定是令牌问题了。 */
const REPAIR_AFTER_ATTEMPTS = 3;

/** 保活与自愈：alarms 唤醒后调用（对所有连接生效）。 */
export async function ensureAlive() {
  const cfg = await getConfig();
  if (!cfg.autoConnect) return;
  // ⚠️ 必须从 storage 读，不能只看内存里的 state ——
  //    MV3 的 Service Worker 空闲会被回收，保活闹钟（30s）再把它唤醒。
  //    唤醒后内存里的 userDisconnected 又变回 false，
  //    于是「断开」大约半分钟后连接自己回来了，弹窗那句
  //    「自动重连已暂停」就成了假话。
  if (await isUserDisconnected()) return;

  // ⚠️ 没有实例时**主动重试发现**（带退避）。
  //
  //    其实顶层 `bootstrap` 每次 Service Worker 被唤醒时都会重跑，里面
  //    也会调 connect() → discover()，所以**重试本身是一直有的**。
  //    这里补的是两件事：
  //      ① **节奏**：原来每次唤醒（30 秒闹钟）都把 15 个候选端口扫一遍，
  //         "这台机器上根本没有 KiraAI"时要一直白扫。加上退避后前几次
  //         很快、之后最多 5 分钟一次。
  //      ② **不依赖顶层脚本**：把"没实例就重试"这件事放在保活路径里显式
  //         表达出来，而不是靠"顶层代码每次都会重跑"这个隐式前提。
  if (!cfg.instances.length) {
    await maybeRediscover();
    return;
  }

  for (const l of links.values()) {
    if (!l.ws || l.ws.readyState === WebSocket.CLOSED
        || l.ws.readyState === WebSocket.CLOSING) {
      l.reconnectAttempt = 0;
      await l.connect();
      continue;
    }
    // ── 看着 OPEN、其实不通的"半开连接" ────────────────────────────
    //  服务端每 25 秒发一次心跳 ping，正常情况绝不会静默 60 秒。
    //  静默这么久 = 对面已经收不到我们的东西（典型场景：Service Worker
    //  被回收又唤醒，socket 留在半开状态）。
    //  ⚠️ 由**扩展自己**换一条新连接，而不是等服务端把这条判死：
    //     前者是"主动重连"，日志干净；后者在服务端是"判定连接已失效"，
    //     看起来像故障，还会刷屏。
    if (l.ws.readyState === WebSocket.OPEN && isLinkStale(l.lastInboundAt)) {
      const shout = staleLogDecision(staleStat);
      if (shout) {
        console.log("[KiraBridge] 超过", Math.round(WS_STALE_MS / 1000),
                    "秒没收到服务端数据，链路已半开，主动换一条新连接", l.label,
                    `（累计第 ${staleStat.count} 次；同一窗口内只提示一次，`
                    + `想复核请打开 KiraAI 面板的「连接状态」）`);
      } else {
        // 降噪：其它次只留一行 debug（控制台默认看不到），计数照记
        console.debug("[KiraBridge] 半开链路换连接（已降噪，不重复告警）",
                      l.label, `第 ${staleStat.count} 次`);
      }
      // 累计数落盘：弹窗要显示"换过几次"，重启 Service Worker 也不能丢
      try {
        chrome.storage.local.set({ [STORE.STALE_RECONNECTS]: staleStat.count });
      } catch (_) {}
      l.reconnectAttempt = 0;
      try { l.ws.close(4000, "stale"); } catch (_) {}
      continue;      // onclose 里会自动重连
    }
    // 还活着：发一条保活 ping 让服务端也看得见"扩展这边醒着"。
    //  MV3 里这条尤其有用 —— 保活闹钟每次唤醒 Service Worker 都会走到这里，
    //  服务端的空闲计时因此被重置，就不会出现"对面明明活着却被判死"。
    if (l.ws.readyState === WebSocket.OPEN) {
      try {
        l.sendRaw({ type: MSG.PING, ts: Date.now() });
      } catch (_) { /* 发不出去也不额外处理：下一轮会走上面的陈旧分支 */ }
    }
  }
}

/** 自动发现的退避表（分钟）。前几次很快 —— KiraAI 正在启动的那几十秒里
 *  就能接上；后面越拉越开，免得"这台机器上根本没有 KiraAI"时一直扫端口。 */
// 上限**故意压在 5 分钟**：退避太久的话，用户在浏览器开着之后才启动
// KiraAI，会干等半天才被接上。5 分钟既不至于每 30 秒扫一遍 15 个端口，
// 也不让人等太久。（用户随时可以点「自动检测」/ 打开面板立刻接上。）
const REDISCOVER_BACKOFF_MIN = [0.5, 1, 2, 5];

/** 发现失败过就按退避重试；成功过（instances 非空）就不会走到这里。 */
async function maybeRediscover() {
  try {
    const s = await chrome.storage.local.get([STORE.DISCOVER_TRIES, STORE.DISCOVER_AT]);
    const tries = Math.max(0, Number(s[STORE.DISCOVER_TRIES]) || 0);
    const lastAt = Number(s[STORE.DISCOVER_AT]) || 0;
    const waitMs = REDISCOVER_BACKOFF_MIN[
      Math.min(tries, REDISCOVER_BACKOFF_MIN.length - 1)] * 60_000;
    if (lastAt && Date.now() - lastAt < waitMs) return;   // 还没到下次

    await chrome.storage.local.set({ [STORE.DISCOVER_AT]: Date.now() });
    const d = await discover();
    if (d && d.ok) {
      // 找到了 —— discover() 只负责"配对并记下来"，**连接要另外发起**。
      await chrome.storage.local.set({ [STORE.DISCOVER_TRIES]: 0 });
      await connectAll();
      return;
    }
    await chrome.storage.local.set({
      [STORE.DISCOVER_TRIES]: Math.min(tries + 1, REDISCOVER_BACKOFF_MIN.length),
    });
  } catch (_) {
    // 重试本身失败不该影响别的（下次闹钟再来）
  }
}


// ─── 消息分发 ────────────────────────────────────────────────────────────────

/**
 * 验证与服务端的**真实往返**。
 *
 * 插件每 25 秒发一次心跳 ping，扩展回 pong。这里挂一个一次性监听：
 * 只要收到服务端的 ping（说明 socket 可收 + 对端在跑），并成功回 pong
 * （说明我们可发），往返就算成立。
 *
 * ⚠️ 超时必须**大于心跳间隔 25 秒**，否则正常链路也会被判超时。
 * ⚠️ 不要反过来给插件发 ping —— bridge.py 只发不收，它只处理扩展回的 pong。
 */
function probeServerRoundTrip(timeoutMs = 30000, link) {
  return new Promise((resolve) => {
    // 没指定就挑第一条活着的连接 —— 有多条时测哪条都算"链路通"。
    const target = link || Array.from(links.values()).find((l) => l.open);
    if (!target || !target.open) {
      resolve({ ok: false, error: "未连接到 KiraAI（请先点连接）" });
      return;
    }
    // ⚠️ 同一时刻只允许一个探测在跑。
    //    probe 槽位是**每条连接各一个**：多条连接同时探测时互不覆盖。
    //    于是旧探测的超时定时器仍会触发，并把**新**探测的回调清掉 ——
    //    表现为"点了测试没反应"或者拿到上一个的结果。
    if (target.probe) {
      resolve({ ok: false, error: "已有一次链路测试在进行中，请稍候" });
      return;
    }
    let done = false;
    const t0 = Date.now();
    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      target.probe = null;
      resolve({
        ok: false,
        error: `${Math.round(timeoutMs / 1000)} 秒内没收到服务端心跳，`
             + `链路可能不通（socket 开着但对端不响应）`,
      });
    }, timeoutMs);

    target.probe = () => {
      void 0;
      if (done) return;
      done = true;
      clearTimeout(timer);
      target.probe = null;
      resolve({
        ok: true,
        socket: "OPEN",
        rtt_ms: Date.now() - t0,
        note: "已与服务端完成一次真实心跳往返",
      });
    };
  });
}

async function handleMessage(raw, link) {
  let msg;
  try { msg = JSON.parse(raw); } catch { return; }

  switch (msg.type) {
    case MSG.WELCOME:
      console.log("[KiraBridge] 服务端协议版本", msg.protocol);
      break;

    case MSG.PING: {
      // ⚠️ 只有 **PONG 真的发出去了**，这次往返才算成立。
      //    收到 ping 说明"我们能收"，但发不出去 = socket 只能收不能发，
      //    链路其实是不通的。原来无论 sendRaw 成功与否都调探测回调
      //    → 弹窗显示"链路正常"，而实际连命令都发不出去（假成功）。
      const pongSent = sendRaw({ type: MSG.PONG, ts: Date.now() }, link);
      if (pongSent && link && typeof link.probe === "function") {
        try { link.probe(); } catch (_) {}
      }
      break;
    }

    case MSG.CMD:
      // ⚠️⚠️ `link` 必须一路传下去 —— `sendRaw` 开头是
      //       `if (!link || !link.open) return false;`
      //     漏传的后果不是"发错人"，而是**一条都发不出去**：
      //     插件发来命令 → 扩展执行完 → 结果被 sendRaw 静默吞掉 →
      //     插件干等 op_timeout（20 秒）→ 报"扩展没有响应/超时"。
      //     表面看像"扩展没反应/没连上"，实际连着的，只是回话没人接。
      await runCommand(msg.id, msg.name, msg.params || {}, link);
      break;

    default:
      break;
  }
}

async function runCommand(id, name, params, link) {
  try {
    // ⚠️ 二次确认必须**集中在这里**判定。
    //    之前只在 navigate/click/type 里各写一次，导致 exec_js / upload /
    //    cookie_set 等高危命令完全绕过确认 —— 用户明明开了「写操作需确认」，
    //    扩展却静默执行了 JS、传了文件、改了 cookie。
    if (params && params.require_confirm && NEEDS_CONFIRM_COMMANDS.has(name)) {
      const [title, message] = confirmPromptFor(name, params);
      const ok = await askUser(title, message, {
        command: name,
        action: title,
        url: params.url || "",
        timeout_ms: confirmTimeoutMs(params),
      });
      if (!ok) {
        sendResult(id, true, { declined: true }, null, null, link);
        return;
      }
    }

    // 下载需要边收边回传分块，得知道自己的 cmdId
    const data = name === CMD.DOWNLOAD
      ? await downloadViaSession(params, id, link)
      : await execute(name, params);
    if (data && data.__declined) {
      sendResult(id, true, { declined: true }, null, null, link);
    } else {
      // ── "页面被别的实例动过"的提示（**只在真发生时才带**）──
      //
      //  为什么放在这里：这是"一个浏览器两只手"的补偿 —— 不做仲裁（谁都能动），
      //  但要让 bot **自己知道**页面可能已经变了。否则它会拿旧的 selector
      //  去点，而页面早被另一个实例换掉了。
      //
      //  ⚠️ 平时一个 token 都不花：只有"别的实例在我上次收到结果之后
      //     写过页面"时才加这一个字段。
      if (!READ_COMMANDS.has(name)) {
        activity.lastWriter = link ? link.label : "";
        activity.lastWriteTs = Date.now();
      }
      if (link) {
        const who = otherWriterFor(link);      // 没发生就返回 ""（零开销）
        if (who && data && typeof data === "object" && !Array.isArray(data)) {
          data.other_writer = who;
        }
        link.lastResultTs = Date.now();
      }
      sendResult(id, true, data, null, null, link);
    }
  } catch (e) {
    console.error(`[KiraBridge] 命令 ${name} 失败`, e);
    // ⚠️ 把**错误类别**也传回去（e.code）。插件侧据此判断"结果不确定"，
    //    而不是靠解析错误文案里的"超时"两个字 —— 文案一改，安全逻辑就没了。
    sendResult(id, false, null, e.message || String(e), e && e.code, link);
  }
}

async function execute(name, params) {
  switch (name) {
    case CMD.LIST_TABS:    return await listTabs();
    case CMD.GET_PAGE:     return await getPage(params);
    case CMD.GET_SELECTION:return await getSelection(params);
    case CMD.EXTRACT:      return await extract(params);
    case CMD.WAIT_FOR:     return await waitFor(params);
    case CMD.SCREENSHOT:   return await screenshot(params);
    case CMD.ACTIVATE_TAB: return await activateTab(params);
    case CMD.CLOSE_TAB:    return await closeTab(params);
    case CMD.MUTE_TAB:     return await muteTab(params);
    case CMD.PIN_TAB:      return await pinTab(params);
    case CMD.NAVIGATE:     return await navigate(params);
    case CMD.SCROLL:       return await scroll(params);
    case CMD.CLICK:        return await click(params);
    case CMD.TYPE:         return await typeText(params);
    case CMD.EXEC_JS:      return await execJs(params);
    case CMD.UPLOAD:        return await upload(params);
    case CMD.UPLOAD_CHUNK:  return await uploadChunk(params);
    case CMD.UPLOAD_FINISH: return await uploadFinish(params);
    case CMD.UPLOAD_ABORT:  return await uploadAbort(params);
    case CMD.COOKIE_GET:   return await cookieGet(params);
    case CMD.COOKIE_SET:   return await cookieSet(params);
    case CMD.GET_INFO:     return await getInfo(params);
    case CMD.GO_BACK:      return await goBack(params);
    case CMD.REFRESH:      return await refresh(params);
    case CMD.HOVER:        return await hover(params);
    case CMD.KEY_PRESS:    return await keyPress(params);
    case CMD.KEY_DOWN:     return await keyDownUp(params, true);
    case CMD.KEY_UP:       return await keyDownUp(params, false);
    case CMD.MOUSE_MOVE:   return await mouseMove(params);
    case CMD.MOUSE_CLICK:  return await mouseClick(params);
    case CMD.MOUSE_DOWN:   return await mouseDownUp(params, true);
    case CMD.MOUSE_UP:     return await mouseDownUp(params, false);
    case CMD.MOUSE_WHEEL:  return await mouseWheel(params);
    case CMD.MOUSE_DRAG:   return await mouseDrag(params);
    case CMD.LIST_FILES:   return await listFiles(params);
    case CMD.BOOKMARKS:    return await bookmarks(params);
    case CMD.HISTORY:      return await historySearch(params);
    case CMD.CLIPBOARD:    return await clipboardOp(params);
    case CMD.DEBUG:        return await debugInfo(params);
    default:
      throw new Error(`未知命令：${name}`);
  }
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

// ─── 只读命令实现 ────────────────────────────────────────────────────────────

async function listTabs() {
  const tabs = await chrome.tabs.query({});
  const out = tabs
    .filter((t) => t.url && !t.url.startsWith("chrome-extension://"))
    .map((t) => ({
      id: t.id,
      title: t.title || "",
      url: t.url || "",
      active: !!t.active,
      pinned: !!t.pinned,
      windowId: t.windowId,
    }));
  // 激活的排前面
  out.sort((a, b) => Number(b.active) - Number(a.active));
  return { tabs: out, tab_count: out.length };
}

async function getPage(params) {
  const tab = await resolveTab(params.tab_id);
  await assertInjectable(tab);

  const detail = params.detail || "text";
  const res = await callContent(tab, "get_page", { detail }, 20000);

  return {
    url: tab.url || res.url || "",
    title: tab.title || res.title || "",
    content: res.content || "",
    detail,
  };
}

async function getSelection(params) {
  const tab = await resolveTab(params.tab_id);
  const res = await callContent(tab, "get_selection", {});
  return { url: tab.url, title: tab.title, content: res.content || "" };
}

async function extract(params) {
  const tab = await resolveTab(params.tab_id);
  const res = await callContent(tab, "extract", {
    selector: params.selector,
    attr: params.attr || null,
    limit: params.limit || 50,
  });
  // tab_url 交给插件侧做域名校验 —— 提取和读正文一样属于读操作
  return { url: tab.url, tab_url: tab.url, title: tab.title, items: res.items || [] };
}

async function waitFor(params) {
  const tab = await resolveTab(params.tab_id);
  const started = Date.now();
  const res = await callContent(tab, "wait_for", {
    selector: params.selector || null,
    text: params.text || null,
    timeout: params.timeout || 10,
  }, ((params.timeout || 10) + 5) * 1000);

  return {
    found: !!res.found,
    elapsed: ((Date.now() - started) / 1000).toFixed(1),
    url: tab.url,
    tab_url: tab.url,
  };
}

async function screenshot(params) {
  const tab = await resolveTab(params.tab_id);
  // ⚠️ captureVisibleTab 截的是**该窗口当前活动标签**，而我们可能被要求
  //    截一张后台标签。那样会把「别的标签的内容」当成目标标签的截图返回，
  //    既是信息泄露，也让 AI 拿到错的画面。
  //    这里先确认目标就是活动标签，不是就报错（不擅自激活，避免打断用户）。
  if (!tab.active) {
    throw new Error(
      `标签页「${tab.title || tab.id}」不在前台，无法截图（截图只能截当前活动标签）。` +
      `请先用 activate_tab 切过去，或改为对当前活动标签截图。`
    );
  }
  const image = await captureVisibleWithRestore(
    tab.windowId, { restoreWindow: params.restore_window !== false });
  return { url: tab.url, title: tab.title, image };
}

//: 窗口不可见时：恢复窗口后等多久、最多试几次（等合成器出一帧）
const SHOT_RESTORE_WAIT_MS = 220;
const SHOT_RESTORE_TRIES = 3;

/** 是不是"拿不到画面"这一类错误？
 *
 *  ⚠️ 只有这一类才值得去**动用户的窗口**。别的错误（没权限、标签不对…）
 *     一律原样抛出，绝不为了重试把用户的窗口弹出来 —— 那是打扰。
 */
function isCaptureUnavailable(e) {
  const m = String((e && e.message) || e || "");
  return /readback|capture tab|capturevisibletab|no frame|not visible|minimi[sz]ed|hidden/i.test(m);
}

function captureUnavailableMessage(wasMinimized, triedRestore) {
  const why = wasMinimized ? "窗口处于「最小化」" : "窗口完全不可见（最小化或被挡住）";
  return `${why}，系统读不到画面，截图失败。`
    + (triedRestore ? "已试着临时恢复窗口，仍然拿不到画面。" : "")
    + "把窗口恢复出来（至少露出一部分）再试。";
}

/** 截可视区域；窗口最小化/被遮挡时**短暂借一下窗口**，截完恢复原状。
 *
 *  ⚠️ 为什么要有它（用户报的）：bot 的常见用法正是"把浏览器丢在后台自己截图看"，
 *     而窗口最小化时 captureVisibleTab 必然失败 —— Chromium 拿不到可回读的帧，
 *     抛的是 "Failed to capture tab: image readback failed"。以前我们把这句原文
 *     直接丢给用户：看不懂，也没法照做。
 *  ⚠️ 恢复原状是**义务**：我们是借用户的窗口一瞬，用完必须还回去（原来最小化就
 *     还它最小化）。
 *  ⚠️ 不抢焦点：只用 `state`，不加 `focused: true`。
 */
async function captureVisibleWithRestore(winId, { restoreWindow = true } = {}) {
  const attempt = () => chrome.tabs.captureVisibleTab(winId, { format: "png" });

  let wasMinimized = false;
  try {
    const win = await chrome.windows.get(winId);
    wasMinimized = !!(win && win.state === "minimized");
  } catch (_) { /* 拿不到窗口信息也不影响截图本身 */ }

  try {
    return await attempt();
  } catch (e) {
    if (!isCaptureUnavailable(e)) throw e;
    if (!restoreWindow) throw new Error(captureUnavailableMessage(wasMinimized, false));

    let image = null;
    try {
      await chrome.windows.update(winId, { state: "normal" });
      for (let i = 0; i < SHOT_RESTORE_TRIES && !image; i++) {
        await new Promise((r) => setTimeout(r, SHOT_RESTORE_WAIT_MS));
        try { image = await attempt(); } catch (_) { /* 再等一帧 */ }
      }
    } finally {
      if (wasMinimized) {
        try { await chrome.windows.update(winId, { state: "minimized" }); } catch (_) {}
      }
    }
    if (image) {
      console.log("[KiraBridge] 截图时窗口不可见：已临时恢复窗口，截完还原");
      return image;
    }
    throw new Error(captureUnavailableMessage(wasMinimized, true));
  }
}

// ─── 写命令实现 ──────────────────────────────────────────────────────────────

async function activateTab(params) {
  const tab = await resolveTab(params.tab_id);
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
  return { ok: true, tab_id: tab.id, url: tab.url };
}

async function muteTab(params) {
  const tab = await resolveTab(params.tab_id);
  await chrome.tabs.update(tab.id, { muted: params.muted !== false });
  return { ok: true, tab_id: tab.id, muted: params.muted !== false };
}

async function pinTab(params) {
  const tab = await resolveTab(params.tab_id);
  await chrome.tabs.update(tab.id, { pinned: !!params.pinned });
  return { ok: true, tab_id: tab.id, pinned: !!params.pinned };
}

async function closeTab(params) {
  const tab = await resolveTab(params.tab_id);
  await chrome.tabs.remove(tab.id);
  return { ok: true, closed: tab.id };
}

/** 等某个标签**加载完**（或超时）。

 * ⚠️ 为什么必须有：`chrome.tabs.update` / `chrome.tabs.create` 只负责
 *    **发起**导航，不等页面加载完就 resolve。所以原来 navigate 一返回
 *    就去读页面，读到的是**旧页面** —— 标题、正文全是旧的，
 *    表现为"导航反馈滞后半拍"（用户实测：打开 B站后工具返回的还是上一个
 *    tab 的标题和内容）。后面点视频也是同理。
 *
 * 返回为什么结束等待："complete" / "already" / "timeout" / "closed" ——
 * 超时也照样返回，不能让一个慢站点把工具卡死。
 */
function waitForLoad(tabId, timeoutMs = 12000) {
  return new Promise((resolve) => {
    let done = false;
    const onUpd = (id, info) => {
      if (id === tabId && info && info.status === "complete") finish("complete");
    };
    const onRm = (id) => { if (id === tabId) finish("closed"); };
    function finish(why) {
      if (done) return;
      done = true;
      try { chrome.tabs.onUpdated.removeListener(onUpd); } catch (_) {}
      try { chrome.tabs.onRemoved.removeListener(onRm); } catch (_) {}
      resolve(why);
    }
    try { chrome.tabs.onUpdated.addListener(onUpd); } catch (_) {}
    try { chrome.tabs.onRemoved.addListener(onRm); } catch (_) {}
    // 先查一次：可能已经加载完了（about:blank 这类瞬间完成）
    try {
      chrome.tabs.get(tabId).then((t) => {
        if (t && t.status === "complete") finish("already");
      }).catch(() => finish("gone"));
    } catch (_) { finish("gone"); }
    setTimeout(() => finish("timeout"), timeoutMs);
  });
}

async function navigate(params) {
  // ⚠️ 打开本机文件（file://）时**先看用户有没有打开那个开关**。
  //    不开的话 `chrome.tabs.update` 会抛
  //    "Cannot navigate to a file URL without local file access" ——
  //    那句话对模型毫无用处（它不知道去哪开、甚至不知道这是浏览器设置）。
  //    这里提前换成一段能照做的说明。
  if (/^file:/i.test(params.url || "") && !(await isFileAccessAllowed())) {
    throw new Error(fileAccessHelp(params.url));
  }
  if (params.new_tab) {
    const tab = await chrome.tabs.create({ url: params.url, active: true });
    // ⚠️ 等它真的加载完再返回 —— 否则上层立刻读页面会读到旧内容
    const load = await waitForLoad(tab.id, params.wait_ms || 12000);
    return { ok: true, tab_id: tab.id, url: params.url, navigated: true, load };
  }

  const tab = await resolveTab(params.tab_id);
  try {
    await chrome.tabs.update(tab.id, { url: params.url, active: true });
  } catch (e) {
    // ⚠️ 兜底：探测说"允许"、真导航时却被拒（用户刚在里面关掉开关，
    //    或浏览器版本差异）。这里把原始报错翻译成同一段可照做的说明。
    const m = String((e && e.message) || e || "");
    if (/file URL|file:\/\//i.test(m)) {
      invalidateFileAccessCache();      // 缓存作废，下次重新问
      throw new Error(fileAccessHelp(params.url));
    }
    throw e;
  }
  const load = await waitForLoad(tab.id, params.wait_ms || 12000);
  return { ok: true, tab_id: tab.id, url: params.url, navigated: true, load };
}

async function scroll(params) {
  const tab = await resolveTab(params.tab_id);
  const res = await callContent(tab, "scroll", {
    direction: params.direction,
    amount: params.amount || null,
  });
  return { ok: true, changed: !!res.changed };
}

async function click(params) {
  const tab = await resolveTab(params.tab_id);
  await assertInjectable(tab);

  const beforeUrl = tab.url;

  const res = await callContent(tab, "click", {
    selector: params.selector || null,
    text: params.text || null,
    index: params.index ?? null,
  }, 20000);

  // 点击可能触发跳转，稍等一下再读一次状态
  await new Promise((r) => setTimeout(r, 700));
  let afterUrl = beforeUrl;
  let navigated = false;
  try {
    const fresh = await chrome.tabs.get(tab.id);
    afterUrl = fresh.url;
    navigated = afterUrl !== beforeUrl;
  } catch (_) { /* 标签可能被关掉了 */ }

  return {
    ok: true,
    match: res.match || null,
    changed: !!res.changed,
    navigated,
    url: afterUrl,
  };
}

async function typeText(params) {
  const tab = await resolveTab(params.tab_id);
  await assertInjectable(tab);

  const beforeUrl = tab.url;
  const res = await callContent(tab, "type", {
    selector: params.selector,
    text: params.text,
    submit: !!params.submit,
    clear_first: params.clear_first !== false,
  }, 20000);

  await new Promise((r) => setTimeout(r, 700));
  let afterUrl = beforeUrl;
  let navigated = false;
  try {
    const fresh = await chrome.tabs.get(tab.id);
    afterUrl = fresh.url;
    navigated = afterUrl !== beforeUrl;
  } catch (_) {}

  return { ok: true, submitted: !!params.submit, navigated, url: afterUrl };
}

// ─── 用户确认（通过通知实现，避免被页面遮挡） ────────────────────────────────

chrome.notifications.onButtonClicked.addListener((notifId, btnIdx) => {
  resolveConfirm(notifId, btnIdx);
});

chrome.notifications.onClicked.addListener((notifId) => {
  // 点通知本体（未点按钮）视为放弃本次操作
  resolveConfirm(notifId, -1);
});

// ─── 事件上报（可感知） ──────────────────────────────────────────────────────

chrome.webNavigation.onCompleted.addListener(async (details) => {
  if (details.frameId !== 0) return; // 只关心主框架
  try {
    const tab = await chrome.tabs.get(details.tabId);
    sendEvent(EVT.PAGE_LOADED, {
      tab_id: tab.id,
      title: tab.title || "",
      url: tab.url || "",
    });
  } catch (_) {}
});

chrome.tabs.onActivated.addListener(async (info) => {
  try {
    const tab = await chrome.tabs.get(info.tabId);
    const all = await chrome.tabs.query({});
    sendEvent(EVT.TAB_ACTIVATED, {
      tab_id: tab.id,
      title: tab.title || "",
      url: tab.url || "",
      tab_count: all.length,
    });
  } catch (_) {}
});

chrome.tabs.onRemoved.addListener((tabId) => {
  sendEvent(EVT.TAB_CLOSED, { tab_id: tabId });
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.url) {
    sendEvent(EVT.NAVIGATED, {
      tab_id: tabId,
      title: tab.title || "",
      url: tab.url || "",
    });
  }
});

// ─── 生命周期与保活 ──────────────────────────────────────────────────────────

// ⚠️ 这三个回调都是 async，必须自己兜住异常。
//    MV3 的 background 是 Service Worker：回调里抛出的
//    unhandled rejection 会被当成 worker 级错误，可能直接把 worker 干掉，
//    表现就是"扩展莫名其妙掉线了"。
async function safeRun(label, fn) {
  try {
    await fn();
  } catch (e) {
    console.error(`[KiraBridge] ${label} 失败`, e);
    try {
      await setStatus({ connected: false, error: `${label} 失败：${e.message || e}` });
    } catch (_) {}
  }
}

chrome.runtime.onInstalled.addListener(() => safeRun("onInstalled", async () => {
  chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: KEEPALIVE_PERIOD_MINUTES });
  const cfg = await getConfig();
  // 已经配对过至少一个实例？没有就先跑自动发现（connect 内部会做）
  if (cfg.autoConnect) {
    await connect();
  } else {
    await setStatus({ connected: false, count: 0,
                      error: "尚未配对任何 KiraAI 实例" });
  }
}));

chrome.runtime.onStartup.addListener(() => safeRun("onStartup", async () => {
  chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: KEEPALIVE_PERIOD_MINUTES });
  const cfg = await getConfig();
  // 已经配对过至少一个实例？没有就先跑自动发现（connect 内部会做）
  if (cfg.autoConnect) {
    await connect();
  }
}));

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === KEEPALIVE_ALARM) {
    return safeRun("keepalive", ensureAlive);
  }
});

// popup 发来的控制指令
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    switch (msg.action) {
      case "connect":
        sendResponse(await connect({ manual: true }));
        break;
      case "page_pair": {
        // KiraAI 面板页直接把手里的接入信息交过来。
        // ⚠️ 端口取自**页面实际所在的那个实例**（content script 用的是
        //    `location.port`）—— 所以用户有多个 KiraAI 时，他在谁的面板里
        //    就配谁，**不会认错**，不需要探测也不需要让用户选。
        const p = msg.payload || {};
        if (!p.token || !p.port) {
          sendResponse({ ok: false, error: "接入信息不完整" });
          break;
        }
        // ⚠️ 只在**接入信息真的变了**的时候才动作。
        //    面板每次加载（含 10 分钟一次的令牌轮询）都会推一遍 ——
        //    若无条件 `setUserDisconnected(false)` + `connect()`，
        //    用户手动点的「断开」会被每 10 分钟**自动撤销**一次。
        const before = await getConfig();
        const changed = before.token !== p.token || Number(before.port) !== Number(p.port);
        const saved = await applyPair(p);
        if (!changed) {
          // ⚠️⚠️ **但"信息没变"不等于"什么都不用做"**。
          //    原来这里直接 break —— 于是"令牌没变、可连接就是掉了"这种
          //    情况**永远不会被这一路救回来**。用户明明正开着 KiraAI 面板、
          //    明明扩展就是断的，它却什么都不做（"又连不上了"就是这个）。
          //    正确规则：
          //      · 用户手动点过「断开」→ 尊重他，别动（保持原意）
          //      · 否则，这条实例**现在没连上** → 连它
          const live = links.get(`${p.host}:${p.port}`);
          if (live && live.open) {
            sendResponse({ ok: true, single: saved, unchanged: true });
            break;
          }
          if (await isUserDisconnected()) {
            sendResponse({ ok: true, single: saved, unchanged: true,
                           skipped: "用户已手动断开" });
            break;
          }
          await connect();
          sendResponse({ ok: true, single: saved, reconnected: true });
          break;
        }
        // 用户主动打开面板来的，就别让他再点一次「连接」
        await setUserDisconnected(false);
        if ((await getConfig()).autoConnect) {
          await connect();
        }
        sendResponse({ ok: true, single: saved });
        break;
      }
      case "add_instance": {
        // 弹窗里手动添加一个实例（自动探测覆盖不到的端口用这个兜底）
        const inst = msg.inst || {};
        if (!inst.token || !(Number(inst.port) > 0)) {
          sendResponse({ ok: false, error: "实例信息不完整" });
          break;
        }
        await upsertInstance({
          host: inst.host || "127.0.0.1",
          port: Number(inst.port),
          token: inst.token,
          label: inst.label || "",
        });
        await setUserDisconnected(false);
        if ((await getConfig()).autoConnect) await connect();
        sendResponse({ ok: true });
        break;
      }
      case "discover": {
        // 弹窗上的「自动检测」按钮：只探测并写好配置，不直接连
        // （让用户看得见检测到了什么，再决定要不要连）。
        const d = await discover();
        sendResponse(d);
        break;
      }
      case "use_instance": {
        // 探测到多个实例时，用户在弹窗里选定了一个
        const hit = msg.hit || {};
        if (!hit.token || !hit.port) {
          sendResponse({ ok: false, error: "实例信息不完整" });
          break;
        }
        sendResponse({ ok: true, single: await applyPair(hit) });
        break;
      }
      case "disconnect":
        sendResponse(await disconnect());
        break;
      case "status": {
        const st = (await chrome.storage.local.get(STORE.LAST_STATUS))[STORE.LAST_STATUS] || {};
        // ⚠️ 顺序很重要：**先铺存下来的，再盖上实时的**。
        //    setStatus 会把 `connected` 一起持久化进 STORE.LAST_STATUS。
        //    MV3 的 service worker 被回收重启后连接表是空的，
        //    但 st.connected 还是 true —— 若把 ...st 放后面，弹窗就会
        //    显示「已连接」，而实际根本没有 socket（和 test_ping
        //    要防的是同一种假阳性）。
        // 从**连接表**实时算，不用内存里的单 socket（那条路已经没有了）
        const _list = getLinks();
        const _n = _list.filter((x) => x.status === "connected").length;
        // 扩展侧"半开连接自愈"的累计次数：弹窗上显示一个**数字**，
        // 用户就不用去翻控制台了（也为回答"它是不是老在断"）
        const _stale = (await chrome.storage.local.get(STORE.STALE_RECONNECTS))[
          STORE.STALE_RECONNECTS];
        sendResponse({
          ...st,
          connected: _n > 0,          // 只要有一条通，就算"已连接"
          count: _n,
          instances: _list,           // 弹窗按这个渲染**实例列表**
          readyState: _n ? 1 : -1,
          staleReconnects: Math.max(0, Number(_stale) || 0),
        });
        break;
      }
      case "test_ping":
        // ⚠️ 必须真的走一遍**服务端往返**。
        //    原来只调本地 listTabs()，就算 WebSocket 早断了也会返回成功，
        //    于是弹窗显示"链路正常"而实际根本连不上。
        try {
          const _live = Array.from(links.values()).find((l) => l.open);
          if (!_live) {
            sendResponse({ ok: false, error: "未连接到 KiraAI（请先点连接）" });
            break;
          }
          // ⚠️ 只检查 readyState + 调本地 listTabs() 是**不够**的：
          //    `listTabs()` 完全在扩展本地跑（chrome.tabs.query），
          //    根本没经过 WebSocket。socket 开着但应用层坏了
          //    （插件侧 handler 没注册、协议版本不匹配）时，
          //    弹窗照样显示"链路正常"。
          //
          //    真正能证明链路通的是**收到服务端发来的 ping 并回 pong** ——
          //    这需要"socket 可收 + 对端在跑 + 我们可发"三者同时成立。
          //    做法：发一条 probe，等服务端心跳 ping 到达并触发 pong。
          // 心跳间隔 25s，超时给 30s（否则正常链路也会被误判）
          const okRtt = await probeServerRoundTrip(30000);
          if (okRtt && okRtt.ok) {
            try {
              const tabs = await listTabs();
              okRtt.tab_count = tabs.tab_count;
            } catch (_) {}
          }
          sendResponse(okRtt);
        } catch (e) {
          sendResponse({ ok: false, error: e.message });
        }
        break;
      default:
        sendResponse({ ok: false, error: "unknown action" });
    }
  })();
  return true; // 异步响应
});

// SW 启动时确保 alarm 存在（被回收后重启会走到这里）
safeRun("bootstrap", async () => {
  const existing = await chrome.alarms.get(KEEPALIVE_ALARM);
  if (!existing) {
    chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: KEEPALIVE_PERIOD_MINUTES });
  }
  const cfg = await getConfig();
  // 已经配对过至少一个实例？没有就先跑自动发现（connect 内部会做）
  if (cfg.autoConnect) {
    await connect();
  }
});

console.log("[KiraBridge] Service Worker 已启动");
