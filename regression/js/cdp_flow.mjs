/**
 * CDP（chrome.debugger）扩展侧行为探针 —— 真跑 capabilities.js 的 cdp() /
 * screenshotViaCdp()，用可控的 chrome.debugger 桩验证：
 *
 *   1. attach → sendCommand → detach 的调用序列与参数（版本 "1.3"、tabId）
 *   2. **detach 是义务**：sendCommand 失败时也必须摘（页面黄条不能留着）
 *   3. attach 失败的翻译：已有调试会话 / 浏览器内部页 → 给出能照做的话
 *   4. 整页截图：captureBeyondViewport、clip 来自 layoutMetrics、
 *      高度钳到 16000px 并标 truncated
 *   5. 元素截图：DOM.getDocument→querySelector→getContentQuads→clip
 *
 * 输出最后一行是 JSON（供 Python 侧解析）。
 */
const PLUGIN = process.env.KIRA_PLUGIN_DIR || "..";
const results = [];
const push = (name, ok, detail = "") => results.push({ name, ok, detail });

// ── chrome 桩 ──────────────────────────────────────────────────────────────
const dbg = {
  attaches: [], detaches: [], sends: [],
  failAttach: null, failSend: null,
  layout: { cssContentSize: { width: 1280, height: 20000 } },
  quads: { quads: [[10, 20, 110, 20, 10, 70, 110, 70]] },
};
globalThis.chrome = {
  tabs: {
    async query() {
      return [{ id: 31, title: "T", url: "https://a/", active: true,
                windowId: 5, pinned: false }, ];
    },
    async get(id) {
      return { id, title: "T", url: "https://a/", active: true, windowId: 5 };
    },
  },
  windows: { async update() {}, async get() { return { state: "normal" }; } },
  debugger: {
    async attach(target, version) {
      dbg.attaches.push([target.tabId, version]);
      if (dbg.failAttach) throw new Error(dbg.failAttach);
    },
    async detach(target) { dbg.detaches.push(target.tabId); },
    async sendCommand(target, method, params) {
      dbg.sends.push([target.tabId, method, params]);
      if (dbg.failSend) throw new Error(dbg.failSend);
      if (method === "Page.getLayoutMetrics") return dbg.layout;
      if (method === "DOM.getDocument") return { root: { nodeId: 1 } };
      if (method === "DOM.querySelector") return { nodeId: 2 };
      if (method === "DOM.getContentQuads") return dbg.quads;
      if (method === "Page.captureScreenshot") return { data: "UFBQ" };
      return {};
    },
  },
  storage: { local: { async get() { return {}; }, async set() {} } },
  runtime: { getManifest: () => ({ version: "1.6.0-test" }) },
  scripting: { async executeScript() { return []; } },
  notifications: { async create() { return "n"; }, async clear() {} },
  cookies: {}, history: {}, bookmarks: {},
};

const P = `${PLUGIN}/browser-bridge/`;
let cap;
try {
  cap = await import(`${P}capabilities.js`);
} catch (e) {
  push("__skip__", false, `导入 capabilities.js 失败：${e.message}`);
  console.log(JSON.stringify(results));
  process.exit(0);
}
const { cdp, screenshotViaCdp } = cap;

// ── 1. cdp()：attach → sendCommand → detach ──
try {
  dbg.attaches = []; dbg.sends = []; dbg.detaches = [];
  const r = await cdp({ method: "Input.dispatchMouseEvent",
                        params: { type: "mouseMoved", x: 640, y: 400 } });
  const seqOk = dbg.attaches.length === 1 && dbg.attaches[0][0] === 31
    && dbg.attaches[0][1] === "1.3"
    && dbg.sends.length === 1
    && dbg.sends[0][1] === "Input.dispatchMouseEvent"
    && dbg.sends[0][2].x === 640
    && dbg.detaches.length === 1 && dbg.detaches[0] === 31;
  push("cdp()：attach(1.3)→sendCommand(原样参数)→detach 全序列正确",
       seqOk && r.method === "Input.dispatchMouseEvent",
       JSON.stringify({ attaches: dbg.attaches, sends: dbg.sends.map(s => s[1]),
                        detaches: dbg.detaches }));
} catch (e) {
  push("cdp()：attach→sendCommand→detach 全序列正确", false, String(e));
}

// ── 2. sendCommand 失败也必须 detach（黄条不许留着）──
try {
  dbg.attaches = []; dbg.detaches = []; dbg.failSend = "boom";
  let threw = false;
  try {
    await cdp({ method: "Page.enable" });
  } catch (_) { threw = true; }
  dbg.failSend = null;
  push("cdp()：sendCommand 失败时仍然 detach（用完即摘是义务）",
       threw && dbg.detaches.length === 1 && dbg.detaches[0] === 31,
       `threw=${threw} detaches=${JSON.stringify(dbg.detaches)}`);
} catch (e) {
  push("cdp()：sendCommand 失败时仍然 detach", false, String(e));
}

// ── 3. attach 失败翻译（另一个调试会话 / 内部页）──
{
  dbg.failAttach = "Another debugger is already attached to the tab";
  let msg1 = "";
  try { await cdp({ method: "Page.enable" }); } catch (e) { msg1 = e.message; }
  dbg.failAttach = "Cannot access a chrome:// URL";
  let msg2 = "";
  try { await cdp({ method: "Page.enable" }); } catch (e) { msg2 = e.message; }
  dbg.failAttach = null;
  push("cdp()：attach 失败翻译成能照做的话（调试会话冲突 / 内部页）",
       msg1.includes("调试会话") && msg2.includes("内部页"),
       `msg1=${msg1.slice(0, 60)} | msg2=${msg2.slice(0, 60)}`);
}

// ── 4. 整页截图：captureBeyondViewport + 高度钳制 + truncated ──
try {
  dbg.attaches = []; dbg.sends = []; dbg.detaches = [];
  const r = await screenshotViaCdp({ id: 31, title: "T", url: "https://a/" },
                                   { fullPage: true });
  const shot = dbg.sends.find(s => s[1] === "Page.captureScreenshot");
  const okClip = shot && shot[2].captureBeyondViewport === true
    && shot[2].clip && shot[2].clip.height === 16000
    && shot[2].clip.width === 1280;
  push("整页截图：captureBeyondViewport + 高度钳 16000 并标 truncated",
       !!okClip && r.truncated === true
         && r.image.startsWith("data:image/png;base64,")
         && dbg.detaches.length === 1,
       JSON.stringify({ clip: shot && shot[2].clip,
                        truncated: r.truncated, detach: dbg.detaches.length }));
} catch (e) {
  push("整页截图：captureBeyondViewport + 高度钳制", false, String(e));
}

// ── 5. 元素截图：quads → clip ──
try {
  dbg.attaches = []; dbg.sends = []; dbg.detaches = [];
  const r = await screenshotViaCdp({ id: 31, title: "T", url: "https://a/" },
                                   { selector: "#x" });
  const shot = dbg.sends.find(s => s[1] === "Page.captureScreenshot");
  const okClip = shot && shot[2].clip
    && shot[2].clip.x === 10 && shot[2].clip.y === 20
    && shot[2].clip.width === 100 && shot[2].clip.height === 50;
  const steps = dbg.sends.map(s => s[1]);
  push("元素截图：DOM 三步定位 + clip 正确 + detach",
       !!okClip
         && steps.includes("DOM.getDocument")
         && steps.includes("DOM.querySelector")
         && steps.includes("DOM.getContentQuads")
         && dbg.detaches.length === 1,
       JSON.stringify({ clip: shot && shot[2].clip, steps }));
} catch (e) {
  push("元素截图：DOM 三步定位 + clip", false, String(e));
}

console.log(JSON.stringify(results));
process.exit(0);
