/**
 * 协议常量 —— 与插件侧 protocol.py 保持镜像。
 * 改动任何一侧都必须同步另一侧。
 */

export const PROTOCOL_VERSION = 1;

// 消息类型
export const MSG_HELLO = "hello";
export const MSG_WELCOME = "welcome";
export const MSG_CMD = "cmd";
export const MSG_RESULT = "result";

/** 错误类别标记（result.error_code）。
 *
 * ⚠️ 加这个是因为**别靠错误文案判断语义**：
 *    插件侧原来用 `"超时" in msg` 来判定"结果不确定，禁止换后端重试" ——
 *    只要有人改一下提示文字（或换个语言），这条安全逻辑就静默失效，
 *    变成"同一个点击被执行两次"。现在改成显式字段。
 */
export const ERR_TIMEOUT = "timeout";
export const MSG_EVENT = "event";
export const MSG_PING = "ping";
export const MSG_PONG = "pong";
export const MSG_ERROR = "error";

/** 分组形式，便于 `MSG.HELLO` 这样书写。与上面的常量是同一批值。 */
export const MSG = {
  CHUNK: "chunk",
  HELLO: MSG_HELLO,
  WELCOME: MSG_WELCOME,
  CMD: MSG_CMD,
  RESULT: MSG_RESULT,
  EVENT: MSG_EVENT,
  PING: MSG_PING,
  PONG: MSG_PONG,
  ERROR: MSG_ERROR,
};

// 命令名
export const MSG_EXTRA = { CHUNK: "chunk" };

export const CMD = {
  LIST_TABS: "list_tabs",
  GET_PAGE: "get_page",
  GET_SELECTION: "get_selection",
  EXTRACT: "extract",
  SCREENSHOT: "screenshot",
  WAIT_FOR: "wait_for",
  ACTIVATE_TAB: "activate_tab",
  CLOSE_TAB: "close_tab",
  MUTE_TAB: "mute_tab",
  PIN_TAB: "pin_tab",
  NAVIGATE: "navigate",
  SCROLL: "scroll",
  CLICK: "click",
  TYPE: "type",
  EXEC_JS: "exec_js",
  UPLOAD: "upload",
  // 上传分块 / 收尾 / 中止 —— 与下载方向对称（见 capabilities.js 的说明：
  // 单条 WS 帧有 16 MiB 硬上限，塞不下整份文件，超限还会断开连接）
  UPLOAD_CHUNK: "upload_chunk",
  UPLOAD_FINISH: "upload_finish",
  UPLOAD_ABORT: "upload_abort",
  DOWNLOAD: "download",
  COOKIE_GET: "cookie_get",
  COOKIE_SET: "cookie_set",
  // 把无头后端有、扩展桥原先缺的能力补齐
  GET_INFO: "get_info",
  GO_BACK: "go_back",
  REFRESH: "refresh",
  HOVER: "hover",
  KEY_PRESS: "key_press",
  KEY_DOWN: "key_down",
  KEY_UP: "key_up",
  MOUSE_MOVE: "mouse_move",
  MOUSE_CLICK: "mouse_click",
  MOUSE_DOWN: "mouse_down",
  MOUSE_UP: "mouse_up",
  MOUSE_WHEEL: "mouse_wheel",
  MOUSE_DRAG: "mouse_drag",
  LIST_FILES: "list_files",
  DEBUG: "debug",
  BOOKMARKS: "bookmarks",
  HISTORY: "history",
  CLIPBOARD: "clipboard",
  // CDP 透传（chrome.debugger）：trusted 输入 / 整页截图等 DOM 合成事件
  // 做不到的能力。与插件侧 protocol.py 的 CMD_CDP 镜像。
  CDP: "cdp",
};

// 事件名
export const EVT = {
  PAGE_LOADED: "page_loaded",
  TAB_ACTIVATED: "tab_activated",
  TAB_CLOSED: "tab_closed",
  NAVIGATED: "navigated",
  USER_CONFIRMED: "user_confirmed",
};

// 默认服务端地址（与 KiraAI WebUI 同端口）
export const DEFAULT_HOST = "127.0.0.1";
export const DEFAULT_PORT = 5267;
// ⚠️ 这里的插件 id 必须与 manifest.json 的 plugin_id 一致。
// 默认按安装时填的令牌自动发现；如果路由变了，改这一处即可。
export const WS_PATH = "/ws/plugin/headless_browser/bridge";

/** 本机地址判定（ws:// 只允许用在回环） */
function isLoopbackHost(h) {
  const x = String(h || "").trim().toLowerCase().replace(/^\[|\]$/g, "");
  if (x === "localhost" || x === "127.0.0.1" || x === "::1"
      || x === "0.0.0.0" || x.endsWith(".localhost") || x === "127.0.0.1.") {
    return true;
  }
  // ⚠️ 与 security.py 的 is_local_host 对齐：IPv6 的各种等值写法
  //    也算回环 —— 否则 `::ffff:127.0.0.1` / `0:0:0:0:0:0:0:1`
  //    会被判成"远程主机"而强制要求 wss，连本机反而连不上。
  const bare = x.replace(/\.$/, "");
  if (bare.includes(":")) {
    // 全部展开成 8 组再比较，避免 `0:0:0:0:0:0:0:1` 这类写法漏判
    const parts = _expandV6(bare);
    if (parts && parts.slice(0, 7).every((p) => p === "0")
        && (parts[7] === "1" || parts[7] === "0")) {
      return true;
    }
  }
  // v4-mapped：::ffff:a.b.c.d
  const vm = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/.exec(bare);
  if (vm) return vm[1] === "127.0.0.1";
  return false;
}

/** 把 IPv6 展开成 8 个十六进制组（失败返回 null）。处理 `::` 缩写。 */
function _expandV6(h) {
  if ((h.match(/::/g) || []).length > 1) return null;
  let head = [], tail = [];
  if (h.includes("::")) {
    const [a, b] = h.split("::");
    head = a ? a.split(":") : [];
    tail = b ? b.split(":") : [];
  } else {
    head = h.split(":");
  }
  const need = 8 - head.length - tail.length;
  if (need < 0) return null;
  const all = [...head, ...Array(need).fill("0"), ...tail];
  if (all.length !== 8) return null;
  const norm = all.map((g) => (g === "" ? "0" : g.replace(/^0+(?=.)/, "").toLowerCase()));
  return norm.every((g) => /^[0-9a-f]{1,4}$/.test(g)) ? norm : null;
}

/**
 * 拼出完整的 WebSocket 地址。
 *
 * ⚠️ 令牌是放在 **query string** 里的。`ws://` 是明文传输 ——
 *    只要 host 不是本机，网络上的任何人都能抓到这枚令牌，
 *    然后拿到整个浏览器桥的权限。所以：
 *      * 回环地址 → `ws://`（本机，不出网卡，安全）
 *      * 其它地址 → **必须 `wss://`**（证书校验由浏览器完成）
 *    如果用户填的是远程主机又想用 ws://，这里直接抛错，
 *    而不是悄悄把令牌明文发出去。
 */
export function buildWsUrl(host, port, token) {
  const raw = (host || DEFAULT_HOST).trim();
  // ⚠️ 先 trim 再判空：`"  "`（纯空白）应当等同于"没填" → 用默认端口，
  //    而不是因为 `"  "` 是真值就被当成一个（非法的）端口值。
  let p = String(port ?? "").trim();
  if (!p || p === "0") p = String(DEFAULT_PORT);
  // 解析出 scheme（用户可能填 `ws://` / `wss://` / 误填 `http://` / 裸主机名）
  // ⚠️ 必须认 http/https：面板上让用户填地址时，他们很自然会粘
  //    `http://127.0.0.1:5267`。不认的话前缀会整个留在主机名里，
  //    拼出 `ws://http://127.0.0.1:5267:5267/...` 这种废地址。
  let scheme = "";
  let h = raw;
  const m = /^(wss?|https?):\/\//i.exec(raw);
  if (m) {
    const sc = m[1].toLowerCase();
    // http→ws、https→wss：语义上都是"这个地址的 WebSocket 端口"
    scheme = sc === "http" ? "ws" : sc === "https" ? "wss" : sc;
    h = raw.slice(m[0].length);
  }
  h = h.replace(/\/.*$/, "");                        // 去掉可能的路径
  // ⚠️ 端口解析：用户可能把**带端口的完整地址**粘进来
  //    （`http://127.0.0.1:8000`），这时要用他给的端口，
  //    而不是拿端口字段去覆盖 —— 否则会静默连到错误的端口上。
  //    · `[IPv6]:port` → 取方括号里的部分 + 那个端口
  //    · `host:port`（只有一个冒号）→ 拆成主机 + 端口
  //    · 裸 IPv6（`::1`）里本来就有冒号，**绝不能**当端口剥，
  //      否则会变成 `::`（判不出回环、拼出 `wss://::5267/...` 这种非法 URL）
  let embeddedPort = "";
  if (/^\[.*\]:\d+$/.test(h)) {
    const i = h.lastIndexOf("]:");
    embeddedPort = h.slice(i + 2);
    h = h.slice(0, i + 1);                 // 保留方括号
  } else if (!h.startsWith("[") && h.split(":").length === 2
             && /^[^:]+:\d+$/.test(h)) {
    const i = h.lastIndexOf(":");
    embeddedPort = h.slice(i + 1);
    h = h.slice(0, i);
  }
  if (embeddedPort) {
    // 显式端口优先于端口字段
    p = embeddedPort;
  }

  // ⚠️ 端口必须是 1~65535 的整数。
  //    不校验的话，`-1` / `70000` / `abc` 会拼出
  //    `ws://127.0.0.1:-1/...` 这种**非法 URL**，
  //    `new WebSocket()` 直接抛错 —— 而报错信息只会说
  //    "Invalid URL"，用户完全看不出是端口填错了。
  //    在这里拦下来，给一句能直接照做的话。
  if (!/^\d+$/.test(p) || Number(p) < 1 || Number(p) > 65535) {
    throw new Error(
      `端口无效：${p}（必须是 1~65535 的整数）。`
      + `请在扩展面板里检查「端口」这一项。`
    );
  }

  const loopback = isLoopbackHost(h);
  // 默认：本机用 ws（不出网卡），其它主机用 wss（令牌在 query 里，必须加密）
  if (!scheme) scheme = loopback ? "ws" : "wss";
  // 唯一会拒绝的情况：**显式**要求用明文连非本机 —— 那才是真危险
  if (scheme === "ws" && !loopback) {
    throw new Error(
      `拒绝以明文 ws:// 连接非本机地址 ${h} —— 接入令牌会暴露在网络上。`
      // ⚠️ 提示要覆盖 **http://**：用户粘 `http://host:port` 时，
      //    scheme 会被映射成 "ws" 并走到这个分支 —— 而他的输入里
      //    根本没有 "ws://"，照提示去找会一头雾水。
      + `请把地址里的 ws:// 或 http:// 改成 wss:// / https://，`
      + `或直接只填主机名（默认会用 wss://）。`
    );
  }
  // 裸 IPv6 在 URL 里必须加方括号，否则 `::1:5267` 无法解析。
  const wireHost = (h.includes(":") && !h.startsWith("[")) ? `[${h}]` : h;
  return `${scheme}://${wireHost}:${p}${WS_PATH}?token=${encodeURIComponent(token)}`;
}

export { isLoopbackHost };

// 保活：MV3 的 Service Worker 会被回收，用 alarms 定期唤醒
export const KEEPALIVE_ALARM = "kira-bridge-keepalive";
export const KEEPALIVE_PERIOD_MINUTES = 0.5; // 30 秒，Chrome 允许的最小值

// 重连退避（毫秒）
export const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000, 30000];

/**
 * 二次确认弹窗的兜底等待时间（毫秒）。
 * 正常情况下插件会在命令参数里带 `confirm_timeout`（秒），这里只是它没带时的
 * 兜底值。与插件侧 main.py 的 CONFIRM_WAIT_SECONDS 对应 —— 那边是 45 秒。
 */
export const DEFAULT_CONFIRM_TIMEOUT_MS = 45000;

// 存储键
export const STORE = {
  TOKEN: "kb_token",
  HOST: "kb_host",
  PORT: "kb_port",
  AUTO_CONNECT: "kb_auto_connect",
  LAST_STATUS: "kb_last_status",
  /** 用户是否手动点过「断开」—— 必须持久化：
   *  MV3 的 Service Worker 会被回收，内存标记撑不过一次回收。 */
  USER_DISCONNECTED: "kb_user_disconnected",
  /** 已配对的 KiraAI 实例列表（可以同时有多个 —— 扩展会**全部连上**）。
   *  老版本存的是单个 HOST/PORT/TOKEN，读取时会自动迁移成这个列表。 */
  INSTANCES: "kb_instances",
  /** 自动发现的退避状态（上次尝试时间 / 累计失败次数）。
   *  ⚠️ 存在的理由：发现失败一次之后**必须还会再试**，但不能每 30 秒
   *     把 15 个端口扫一遍 —— 那在"KiraAI 就是不在这台机器上"的情况下
   *     会变成永久的后台噪音。所以按退避表拉开重试间隔。 */
  DISCOVER_TRIES: "kb_discover_tries",
  DISCOVER_AT: "kb_discover_at",
  /** 扩展侧"看着 OPEN 其实不通、自己换了一条新连接"的累计次数（半开连接自愈）。
   *  为什么落盘：MV3 的 Service Worker 会被回收，内存计数撑不过一次回收；
   *  而用户问"它是不是老在断"时，要的是一个**能看的数字**，不是翻日志。 */
  STALE_RECONNECTS: "kb_stale_reconnects",
  /** 本扩展实例的稳定随机 id（hello 上报给插件）。
   *  用途：让服务端分清「同一个扩展重连」（MV3 回收唤醒，正常）与
   *  「**另一处**连接顶号」（两台浏览器互踢，要告警）。
   *  必须落盘：Service Worker 被回收后内存 id 会丢，那样每次唤醒都像是
   *  "另一处连接"，告警就失去意义。 */
  CLIENT_ID: "kb_client_id",
};

/**
 * 主机名归一化 —— 实例去重的**唯一**口径。
 *
 * ⚠️ 为什么必须有：实例列表与连接表都用 `host:port` 当去重键，而
 *  `localhost:5267` 和 `127.0.0.1:5267` 是**同一台服务器**的两个写法 ——
 *  不归一的话它们会被存成两条实例、各开一条连接，服务端只认一条 →
 *  两条连接互踢（日志里每几秒一次"主动断开旧连接"的风暴就是这么来的）。
 *  面板推送配对时发的是 `location.hostname`（可能是 localhost），
 *  自动发现固定填 127.0.0.1 —— 两条途径一混用就出事。
 *
 * 归一只做"板上钉钉等价"的：localhost 族 / ::1 / 尾点写法 → 127.0.0.1。
 * **不做** DNS 解析（那会变成网络调用，而且多网卡机器上语义不明）。
 */
export function normalizeHost(h) {
  let x = String(h || "").trim().toLowerCase();
  x = x.replace(/^\[|\]$/g, "");          // 剥 IPv6 方括号
  x = x.replace(/\.$/, "");               // 尾点（"localhost."）
  if (!x) return "127.0.0.1";
  if (x === "localhost" || x.endsWith(".localhost")) return "127.0.0.1";
  if (x === "::1" || x === "0:0:0:0:0:0:0:1") return "127.0.0.1";
  if (x === "::ffff:127.0.0.1") return "127.0.0.1";
  return x;
}

/** 实例的去重键（归一化之后）。所有列表/连接表一律用它。 */
export function instanceKey(inst) {
  const host = normalizeHost((inst && inst.host) || "127.0.0.1");
  const port = Number((inst && inst.port) || 0) || 5267;
  return `${host}:${port}`;
}

// ─── 零配置接入（自动发现 KiraAI 实例）────────────────────────────────────
/** 插件提供的配对端点：返回**实际端口 + 接入令牌**。
 *  它是免登录的（否则用户还得先手工找令牌，就没解决问题），
 *  由插件侧做「只回答本机请求」的限制。 */
export const PAIR_PATH = "/api/plugin/headless_browser/pair";

/** 自动探测的候选端口。
 *
 *  为什么要探测：端口在扩展里原来是**写死 5267** 的。用户只要改过
 *  KiraAI 的端口，扩展就永远连不上，而报错只说"连不上" —— 小白用户
 *  根本不知道该改哪里。
 *
 *  顺序有讲究：`5267` 是 KiraAI 框架的默认值，排最前；
 *  其余是常见的 Web 端口，覆盖"用户自己改过端口"的大多数情况。
 *  （`http://127.0.0.1/*` 这条 host 权限在 Chrome 里是**端口无关**的，
 *  所以能直接探测任意端口。） */
/** **只读**命令（不影响页面状态）。
 *
 *  其余命令一律当作"写" —— 包括以后新加的：默认按**保守**方向走
 *  （多提醒一句，比该提醒没提醒安全）。
 *
 *  用途只有一个：判断"页面在我上次操作之后有没有被**别的实例**动过"，
 *  好让 bot 知道它记忆里的页面可能已经变了。
 *  （和插件侧的「只读模式」是两回事：那边关心的是"能不能操作"，
 *    这里关心的只是"有没有改到东西"。） */
export const READ_COMMANDS = new Set([
  "read_page", "screenshot", "list_tabs", "debug_info",
  "list_files", "cookie_get", "probe",
]);

export const CANDIDATE_PORTS = [
  5267,
  8080, 8000, 3000, 5000, 8001, 8081, 8888, 9000, 9090, 10000,
  4000, 7000, 7777, 9527, 12345,
];
