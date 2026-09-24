/**
 * 扩展侧 file:// 行为的**真跑**验证（mock chrome API + 真 shared.js）。
 *
 * ⚠️ 为什么必须真跑：静态扫描只能证明"代码里写了 isAllowedFileSchemeAccess"，
 *    证明不了"开关关着时真的会抛那句可照做的错"、"开着时真的放行"。
 *    这里给出一个最小的 chrome 桩，直接 import 真正的 shared.js 跑用例。
 *
 * 用法：node regression/js/file_access.mjs
 * 输出：RESULT:{json}
 */

const FILE = process.env.KIRA_SHARED_JS;
if (!FILE) {
  console.log("RESULT:" + JSON.stringify({ error: "缺 KIRA_SHARED_JS" }));
  process.exit(0);
}

const OUT = { cases: [] };

// ── 最小 chrome 桩 ──────────────────────────────────────────────────
function makeChrome({ fileAccess, probeThrows = false }) {
  return {
    extension: {
      isAllowedFileSchemeAccess: async () => {
        if (probeThrows) throw new Error("API 不可用");
        return fileAccess;
      },
    },
    tabs: {
      get: async () => ({ id: 1, url: "about:blank", title: "t" }),
      query: async () => [{ id: 1, url: "about:blank", title: "t", active: true }],
      sendMessage: async () => { throw new Error("no receiver"); },
      captureVisibleTab: async () => "data:image/png;base64,",
    },
    scripting: { executeScript: async () => [] },
    windows: { get: async () => ({ state: "normal" }) },
    runtime: { getManifest: () => ({ version: "1.0.0" }), lastError: null },
  };
}

const mod = await import(FILE);
// 每轮重新 import 一份，避免模块级缓存串味
async function fresh({ fileAccess, probeThrows }) {
  const url = new URL(FILE, "file://");
  url.searchParams.set("t", String(Math.random()));
  globalThis.chrome = makeChrome({ fileAccess, probeThrows });
  const m = await import(url.href);
  m.invalidateFileAccessCache();
  return m;
}

async function probe(label, opts, tabUrl) {
  const m = await fresh(opts);
  let threw = null;
  try {
    await m.assertInjectable({ url: tabUrl, id: 1 });
  } catch (e) {
    threw = String(e.message || e);
  }
  OUT.cases.push({ label, tabUrl, threw });
}

// ① 开关开着 → file:// 放行
await probe("file+allowed", { fileAccess: true }, "file:///C:/Users/me/a.png");
// ② 开关关着 → 必须抛出**可照做**的错
await probe("file+denied", { fileAccess: false }, "file:///C:/Users/me/a.png");
// ③ 探测 API 抛异常 → 不能因此把用户拦死（按允许处理，让真实错误浮现）
await probe("file+probe-error", { fileAccess: false, probeThrows: true },
            "file:///tmp/a.pdf");
// ④ chrome:// 仍是硬边界（开关开不开都一样）
await probe("chrome+allowed", { fileAccess: true }, "chrome://settings");
await probe("chrome+denied", { fileAccess: false }, "chrome://settings");
// ⑤ 普通网页不受影响
await probe("https", { fileAccess: false }, "https://example.com/");

// ⑥ 缓存行为：探测失败**不能**被缓存
{
  const m1 = await fresh({ fileAccess: false, probeThrows: true });
  const a = await m1.isFileAccessAllowed();          // 抛异常 → 应为 true 且不缓存
  const m2 = await fresh({ fileAccess: false, probeThrows: false });
  const b = await m2.isFileAccessAllowed();          // 真值 false
  OUT.cache = { afterProbeError: a, freshDenied: b };
}

console.log("RESULT:" + JSON.stringify(OUT));
