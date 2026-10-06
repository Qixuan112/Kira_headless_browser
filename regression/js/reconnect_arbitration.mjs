/**
 * 重连纪律（扩展侧）行为探针 —— 钉住 2026-10-06 重连风暴的修法。
 *
 * 背景：扩展持有两条到**同一台服务器**的连接（localhost vs 127.0.0.1
 * 两个写法各存了一条实例），服务端单连接模型踢一个 → 被踢的 1 秒后重连
 * → 反踢回去 → 无限乒乓；又因为 onopen 就清零退避，退避永远停在 1 秒档。
 *
 * 这里真跑 background.js（chrome/WebSocket 用桩），验证：
 *   1. normalizeHost / instanceKey 归一化
 *   2. upsertInstance 的身份合并（同地址归一 / 同令牌合并 / 同 data_dir 合并）
 *   3. Link 被 4001 踢下后进入退让期（不立即重连），普通断开才按退避表
 *   4. onopen **不**清零退避（稳定存活才清）
 *   5. 孤儿 socket（this.ws !== ws 的迟到 onopen）被立即处死
 *   6. page_pair：令牌没变时不动（尤其不撤销用户手动断开）；变了才动作
 *
 * 输出最后一行是 JSON（供 Python 侧解析）。
 */
const PLUGIN = process.env.KIRA_PLUGIN_DIR || "..";
const results = [];
const push = (name, ok, detail = "") => results.push({ name, ok, detail });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// console 间谍：重连日志里的延迟毫秒数是断言依据
const logLines = [];
const realLog = console.log;
console.log = (...a) => { logLines.push(a.map(String).join(" ")); };

// ── chrome 桩（listeners 要被捕获，才能驱动 onMessage）─────────────────────
const store = {};
const listeners = {};
function listenerSlot(name) {
  return { addListener(fn) { listeners[name] = fn; }, removeListener() {} };
}
globalThis.chrome = {
  storage: {
    local: {
      async get(keys) {
        // ⚠️ 真实 chrome.storage.local.get 接受**字符串** / 数组 / 对象三种
        //    入参 —— 只按"数组/对象"处理的话，字符串键会被拆成逐字符索引，
        //    `kb_user_disconnected` 永远读不到（这条探针第一次就踩了）。
        const arr = typeof keys === "string" ? [keys]
          : Array.isArray(keys) ? keys : Object.keys(keys || {});
        const out = {};
        for (const k of arr) out[k] = store[k];
        return out;
      },
      async set(obj) { Object.assign(store, obj); },
    },
  },
  action: { setBadgeText() {}, setBadgeBackgroundColor() {} },
  alarms: { get: async () => null, create() {}, onAlarm: listenerSlot("alarm") },
  runtime: {
    getManifest: () => ({ version: "1.6.0-test" }),
    onInstalled: listenerSlot("installed"), onStartup: listenerSlot("startup"),
    onMessage: listenerSlot("message"),
    sendMessage: async () => ({}),
  },
  tabs: {
    onActivated: listenerSlot("tact"), onRemoved: listenerSlot("trm"),
    onUpdated: listenerSlot("tupd"),
    query: async () => [], get: async () => null, create: async () => ({}),
    remove: async () => {}, update: async () => ({}),
    captureVisibleTab: async () => "",
  },
  notifications: { onClicked: listenerSlot("nc"), onButtonClicked: listenerSlot("nb") },
  scripting: { executeScript: async () => [] },
  webNavigation: { onCompleted: listenerSlot("wn") },
  windows: { update: async () => {} },
};

// ── 可控 WebSocket（close 只触发一次 onclose，防桩自震）──
const wsBox = [];
globalThis.WebSocket = class FakeWS {
  constructor(url) {
    this.url = url;
    this.readyState = 0;          // CONNECTING
    this.sent = [];
    this.closeCalls = 0;
    this.closedWith = null;
    wsBox.push(this);
  }
  send(s) { this.sent.push(JSON.parse(s)); }
  close(code, reason) {
    this.closeCalls += 1;
    if (this.closedWith) return;                 // 只关一次
    this.closedWith = [code, reason];
    this.readyState = 3;
    if (this.onclose) queueMicrotask(
      () => this.onclose({ code: code || 1000, reason: reason || "" }));
  }
  fireOpen() { this.readyState = 1; if (this.onopen) this.onopen(); }
  fireClose(code, reason = "") {
    if (this.closedWith) { this.closedWith = [code, reason]; }
    this.readyState = 3;
    if (this.onclose) this.onclose({ code, reason });
  }
};
globalThis.WebSocket.OPEN = 1;
globalThis.WebSocket.CONNECTING = 0;
globalThis.WebSocket.CLOSING = 2;
globalThis.WebSocket.CLOSED = 3;
globalThis.fetch = async () => { throw new Error("no network in test"); };

const P = `${PLUGIN}/browser-bridge/`;

// ── 1. 纯函数：归一化与去重键 ──
const proto = await import(`${P}protocol.js`);
{
  const n = proto.normalizeHost;
  const cases = [
    ["localhost", "127.0.0.1"], ["LOCALHOST", "127.0.0.1"],
    ["localhost.", "127.0.0.1"], ["foo.localhost", "127.0.0.1"],
    ["::1", "127.0.0.1"], ["[::1]", "127.0.0.1"],
    ["::ffff:127.0.0.1", "127.0.0.1"],
    ["", "127.0.0.1"],
    ["192.168.1.8", "192.168.1.8"],          // 非回环不动
    ["example.com", "example.com"],
  ];
  const bad = cases.filter(([i, want]) => n(i) !== want);
  push("normalizeHost 归一化（localhost 族/IPv6 回环 → 127.0.0.1，其余不动）",
       bad.length === 0,
       bad.map(([i, w]) => `${i}→${n(i)}(want ${w})`).join("; "));
  push("instanceKey 对两种写法给出同一个键",
       proto.instanceKey({ host: "localhost", port: 5267 })
         === proto.instanceKey({ host: "127.0.0.1", port: 5267 }),
       proto.instanceKey({ host: "localhost", port: 5267 }));
}

// ── 2. upsertInstance 身份合并 ──
const mod = await import(`${P}background.js`);
await sleep(100);   // 让 bootstrap 跑完（fetch 被拒，不影响）
{
  await mod.upsertInstance({ host: "localhost", port: 5267, token: "T1" });
  await mod.upsertInstance({ host: "127.0.0.1", port: 5267, token: "T1b" });
  let cfg = await mod.getConfig();
  push("同一服务器的两种写法合并成一条（且 host 归一）",
       cfg.instances.length === 1 && cfg.instances[0].host === "127.0.0.1"
         && cfg.instances[0].token === "T1b",
       JSON.stringify(cfg.instances));

  // 同一枚令牌换了端口写法 → 合并（令牌相同 = 同一实例）
  await mod.upsertInstance({ host: "127.0.0.1", port: 5999, token: "T1b" });
  cfg = await mod.getConfig();
  push("同一令牌换端口 → 合并更新（不留双胞胎）",
       cfg.instances.length === 1 && cfg.instances[0].port === 5999,
       JSON.stringify(cfg.instances));

  // 不同令牌 = 不同实例 → 两条都留
  await mod.upsertInstance({ host: "127.0.0.1", port: 6000, token: "T2",
                             data_dir: "/data-b" });
  cfg = await mod.getConfig();
  push("不同令牌的两个实例共存",
       cfg.instances.length === 2, `count=${cfg.instances.length}`);

  // data_dir 相同 → 合并
  await mod.upsertInstance({ host: "localhost", port: 6001, token: "T2x",
                             data_dir: "/data-b" });
  cfg = await mod.getConfig();
  const merged = cfg.instances.find((x) => x.data_dir === "/data-b");
  push("同一数据目录 → 合并（token 更新到最新）",
       cfg.instances.length === 2 && merged && merged.token === "T2x"
         && merged.port === 6001,
       JSON.stringify(cfg.instances));
}

// ── 3. Link：4001 退让 vs 普通断开退避 ──
{
  const link = new mod.Link({ host: "127.0.0.1", port: 5267, token: "x" });
  const p = link._doConnect();
  await sleep(0);   // _doConnect 先 await getClientId() 才建 socket
  const ws = wsBox[wsBox.length - 1];
  ws.fireOpen();
  await p;
  push("连接成功（onopen 后 resolve ok）", link.open === true,
       `readyState=${ws.readyState}`);

  const helloMsg = ws.sent.find((m) => m.type === "hello");
  push("hello 携带持久化 client_id",
       !!helloMsg && typeof helloMsg.client_id === "string"
         && helloMsg.client_id.length > 0,
       JSON.stringify(helloMsg || null));

  // onopen 没清退避：构造"第 4 次重连中"的状态，开连接后仍是 4
  link.reconnectAttempt = 4;
  // 直接再触发一次 onopen（重复事件，等价"又一次连上"）
  ws.fireOpen();
  push("onopen 不重置 reconnectAttempt",
       link.reconnectAttempt === 4, `attempt=${link.reconnectAttempt}`);

  // 普通断开（1006）→ 按退避表安排（第 4 次 → 15000ms），不进退让期
  logLines.length = 0;
  ws.fireClose(1006, "abnormal");
  await sleep(10);
  const normalDelay = (logLines.join("\n").match(/(\d+)ms 后重连/) || [])[1];
  push("普通断开按退避表重连（不进退让期）",
       Number(normalDelay) === 15000 && !(link.parkUntil > Date.now()),
       `delay=${normalDelay}ms parkUntil=${link.parkUntil}`);
  clearTimeout(link.reconnectTimer); link.reconnectTimer = null;

  // 4001 → 退让：第 1 次 → 30s 档
  logLines.length = 0;
  const link2 = new mod.Link({ host: "127.0.0.1", port: 5267, token: "x" });
  const p2 = link2._doConnect();
  await sleep(0);
  const ws2 = wsBox[wsBox.length - 1];
  ws2.fireOpen();
  await p2;
  ws2.fireClose(4001, "Replaced by a new connection");
  await sleep(10);
  const d1 = (logLines.join("\n").match(/(\d+)ms 后重连/) || [])[1];
  push("被 4001 顶替后进入退让期（重连延迟 >= 退让时长）",
       (link2.parkUntil || 0) > Date.now() && link2.replacedStreak === 1
         && Number(d1) >= 29000,
       `parkIn=${Math.round(((link2.parkUntil || 0) - Date.now()) / 1000)}s `
       + `delay=${d1}ms streak=${link2.replacedStreak}`);
  clearTimeout(link2.reconnectTimer); link2.reconnectTimer = null;

  // 连续被踢 ≥3 次 → 退让升级到分钟级
  const link3 = new mod.Link({ host: "127.0.0.1", port: 5267, token: "x" });
  link3.replacedStreak = 3;
  const p3 = link3._doConnect();
  await sleep(0);
  const ws3 = wsBox[wsBox.length - 1];
  ws3.fireOpen();
  await p3;
  ws3.fireClose(4001, "Replaced by a new connection");
  await sleep(10);
  const parkSec = Math.round((link3.parkUntil - Date.now()) / 1000);
  push("连续被踢 ≥3 次 → 退让升级到分钟级",
       parkSec >= 200 && link3.replacedStreak === 4, `park=${parkSec}s`);
  clearTimeout(link3.reconnectTimer); link3.reconnectTimer = null;
}

// ── 4. 孤儿 socket 处死 ──
{
  const link = new mod.Link({ host: "127.0.0.1", port: 5267, token: "x" });
  const p = link._doConnect();
  await sleep(0);
  const orphan = wsBox[wsBox.length - 1];
  // 模拟"服务端 accept 迟到，扩展已超时放弃"：this.ws 被换掉/清空
  link.ws = null;
  orphan.fireOpen();              // 迟到的 onopen：this.ws !== ws
  await sleep(5);
  push("迟到的 onopen 会立即处死孤儿 socket（不留幽灵）",
       orphan.closeCalls >= 1 && orphan.readyState === 3,
       `closeCalls=${orphan.closeCalls}`);
  await p.catch(() => {});
  clearTimeout(link.reconnectTimer); link.reconnectTimer = null;
}

// ── 5. page_pair：没变不动（不撤销手动断开），变了才动作 ──
{
  store.kb_user_disconnected = true;
  store.kb_auto_connect = true;
  const onMessage = listeners.message;
  const call = (msg) => new Promise((res) => { onMessage(msg, null, res); });
  // 已有实例（上面 upsert 过）：127.0.0.1:5999 / token T1b
  const r1 = await call({ action: "page_pair",
                          payload: { host: "localhost", port: 5999, token: "T1b",
                                     instance: "a", data_dir: "/d" } });
  push("page_pair 令牌没变 → 不动（unchanged，且尊重手动断开）",
       r1 && r1.unchanged === true && store.kb_user_disconnected === true,
       JSON.stringify(r1));
  const r2 = await call({ action: "page_pair",
                          payload: { host: "localhost", port: 5999, token: "NEW-T",
                                     instance: "a", data_dir: "/d" } });
  push("page_pair 令牌变了 → 更新并解除手动断开",
       r2 && r2.ok === true && store.kb_user_disconnected === false,
       JSON.stringify(r2));
}

// ⚠️ 必须走 realLog：console.log 已被间谍替换（断言"重连延迟"全靠它），
//    直接 console.log 会把结果吞进 logLines，stdout 永远没有 JSON。
realLog(JSON.stringify(results));
process.exit(0);
