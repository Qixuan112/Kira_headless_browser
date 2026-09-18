# 全能浏览器 (All-in-One Browser)

> 让 KiraAI 真正会用浏览器 —— 能打开网页、点击、输入、上传下载、执行脚本。

**当前版本 2.1.48** ｜ 更新日志在[文末](#更新日志)（默认折叠）

---

## 这是什么

一个 KiraAI 插件，给 AI 一套「操作浏览器」的工具。

它有两种工作方式，**会自动挑**：

| | 用**你自己的**浏览器 | 用**插件自己的**浏览器 |
|---|---|---|
| 怎么做到 | 浏览器里装个配套扩展 | 插件用 Playwright 自己拉起一个 |
| 好处 | 登录状态、已开的标签页**直接能用** | 不装东西也能用，用完自动关 |
| 代价 | 需要装一次扩展 | 是一个全新浏览器，没有你的登录状态 |

**默认行为**：装了扩展就用你的浏览器；没装（或没连上）就自动用插件自己的。
平时不用管它，想固定也可以改配置（见 [`backend_strategy`](#两种工作方式怎么选)）。

> **为什么不是"直接接管你的浏览器数据目录"？**
> 旧版是那么做的，结果 Playwright 会**独占**那个目录，导致
> *你开着浏览器，插件就用不了；插件开着，你的浏览器打不开*。
> 现在两条路彻底分开：扩展桥根本不启动浏览器，无头后端只用自己（或复制出来）的目录。

---

## 快速开始

### 第一步：安装插件

把整个目录放进 KiraAI 的 `data/plugins/` 下（或在 WebUI 里上传 zip）。

依赖会自动安装（`playwright` + `aiohttp`）。浏览器本体在需要时也会自动下载。

### 第二步：直接开始用

不用做任何额外配置。对 AI 说一句：

> 「帮我打开 example.com，看看页面上写了什么」

它就会用无头浏览器去打开。

### 第三步（推荐）：装上扩展，让它用你的浏览器

装扩展之后，AI 操作的就是**你眼前这个浏览器**——登录状态、已开的标签页全都在。

1. 打开 Chrome，地址栏输入 `chrome://extensions`
2. 打开右上角**开发者模式**
3. 点**加载已解压的扩展程序**
4. 选择插件目录下的 `browser-bridge` 文件夹
5. 点扩展图标，把**接入令牌**粘进去（令牌在插件配置面板里复制）

> 💡 找不到路径或令牌？直接问 AI：
> **「怎么让你看我现在的浏览器？」**
> 它会调用 `browser_diag(action="extension")`，把路径、步骤、令牌都列出来。

---

## 支持的浏览器

| 浏览器 | 支持 | 说明 |
|---|---|---|
| **Chrome** | ✅ 135+ | 推荐 |
| **Edge** | ✅ 135+ | 同为 Chromium 内核，机制一致 |
| Brave / Vivaldi / Opera | ✅ | Chromium 系都可以 |
| Firefox | ❌ | 扩展机制不同（MV3 用 event page） |
| Safari | ❌ | 扩展格式完全不同 |

> **为什么是 135+**：扩展的「执行 JavaScript」能力依赖 `chrome.userScripts`，
> Chrome 135 起才默认可用。**低于 135 也不影响使用**——只是执行 JS 这项
> 会自动走无头后端，其它功能照常。

### 为什么不帮我自动装扩展？

因为 Chromium 没有给本地程序留"静默安装扩展"的正规接口。
能绕过的手段（改注册表、组策略）属于管理员操作，**插件不应该去动你的系统**。

所以这里选择把它做到「**一键可复制**」：扩展随插件打包好，
首次使用时会主动告诉你在哪、怎么装、令牌是什么。

---

## 两种工作方式，怎么选

配置项 `backend_strategy`：

| 值 | 行为 | 什么时候用 |
|---|---|---|
| `auto`（默认） | 优先你的浏览器，连不上就用无头 | 大多数人 |
| `extension` | **只用**你的浏览器，连不上就报错 | 必须用真实登录态时 |
| `headless` | **只用**插件自己的浏览器 | 不想装扩展 / 要隔离环境 |

### 无头后端用哪个浏览器

配置项 `browser_channel`，按顺序尝试，**全都失败会自动下载一个内置 Chromium**：

1. `auto` — 系统默认浏览器 → Chrome → Edge → Chromium → 内置下载
2. `chrome` / `msedge` / `chromium` — 只用指定的那个
3. `bundled` — 只用 Playwright 自带的

不想让它自动下载，把 `auto_download_browser` 关掉。

---

## 配置

> 全部都有合理默认值，**不改也能用**。这里只列常用的。

### 最常改的几个

| 配置项 | 默认 | 说明 |
|---|---|---|
| `enabled` | 开 | 插件总开关 |
| `extension_enabled` | 开 | 单独关掉「用你的浏览器」这条路 |
| `headless_enabled` | 开 | 单独关掉「回退到插件自己的浏览器」 |
| `headless` | 开 | 关掉就会**显示浏览器窗口**（看得见它在干什么） |
| `read_only` | 关 | 只读模式：写操作的工具会从 AI 的工具表里**整个拿掉**，不是"拦一下" |
| `require_confirm` | 关 | 写操作前弹通知让你点「允许」（仅扩展桥支持） |
| `idle_close_seconds` | 300 | 空闲这么久就关掉无头浏览器，释放 CPU / 内存。`0` = 不关 |

### 安全相关

| 配置项 | 默认 | 说明 |
|---|---|---|
| `local_access` | **开** | 允许访问本机与内网地址（`localhost:3000` 这类开发服务器、KiraAI 自己的面板）。关掉后回环 / 私有网段 / 链路本地 / CGNAT（含云厂商元数据端点）**一律拒绝**。细节见 [SECURITY_DESIGN.md](SECURITY_DESIGN.md) |
| `blocked_domains` | `["*.bank*","*.pay*"]` | 黑名单，**读写都拦** |
| `allowed_domains` | `[]` | 白名单，只限制**写操作**。留空 = 不限制 |
| `upload_allow_any_path` | **开** | 允许上传任意路径的文件。关掉后只允许 `upload_allowed_dirs` 里的目录 |
| `upload_allowed_dirs` | `["data/files","data/temp"]` | 上传目录白名单（仅在上项关闭时生效），路径会归一，能防 `../` 穿越 |

> ⚠️ **不要把 `127.0.0.1` / `localhost` 写进 `blocked_domains`。**
> 黑名单优先级最高，写进去会让 `local_access` 这个开关**失效**。
> 本机是否允许，由 `local_access` 决定。

> 📌 **`upload_allow_any_path` 默认开着是刻意的**，不是漏配。
> 本插件的定位是"给 bot 完整的浏览器能力"，把本地文件传进网盘是预期用法。
> 想收紧就把这一项关掉。

### 超时相关

| 配置项 | 默认 | 说明 |
|---|---|---|
| `command_timeout` | 20 | 扩展命令超时（秒），开二次确认会自动抬高 |
| `timeout` | 45 | 页面加载超时（秒） |
| `op_timeout` | 120 | 页面操作超时（秒） |
| `action_timeout` | 20 | 点击 / 输入等交互超时（秒） |
| `default_wait_until` | `domcontentloaded` | 等待策略。**不推荐**改成 `networkidle`——现代页面有轮询和长连接，可能永远不空闲，只会白等到超时 |
| `op_timeout_follows_framework` | 关 | 打开后把 `op_timeout` 限制在「框架工具超时 × `op_timeout_ratio`」之内 |

> **为什么 `op_timeout` 默认和框架脱钩**：框架的 `tool_call_timeout`（默认 60 秒）
> 到点会**直接取消**插件的协程，可能留下状态不明的页面。
> 所以默认让插件自己决定何时收手。

### 内容与上下文

| 配置项 | 默认 | 说明 |
|---|---|---|
| `content_page_size` | 8000 | `browser_page` 单次返回多少字符。**不是上限**，可以接着读 |
| `max_content_chars` | 8000 | 单次返回正文的字符上限 |
| `inject_page_state` | 关 | 把当前浏览状态注入提示词，AI 更容易知道你在看哪一页 |
| `panel_auth_required` | 开 | 配置面板需要登录 |

### 无头浏览器细节

| 配置项 | 默认 | 说明 |
|---|---|---|
| `browser_channel` | `auto` | 用哪个浏览器（见上） |
| `headless_profile_mode` | `inherit` | `inherit` = 复制你真实浏览器的数据来用；`persistent` = 插件自己的；`temp` = 用完即弃 |
| `custom_user_data_dir` | 空 | 自定义 profile 目录。⚠️ **不要填你真实浏览器的 User Data**，会互相抢锁 |
| `default_viewport` | `1920x1080` | 视口大小 |
| `user_agent` | 空 | 自定义 User-Agent |
| `auto_download_browser` | 开 | 找不到浏览器时自动下载一个 |
| `auto_download_timeout` | 600 | 自动下载超时（秒） |

### Cookie 与文件

| 配置项 | 默认 | 说明 |
|---|---|---|
| `cookies_dir` | `data/files/cookie` | 放 cookie JSON 的目录 |
| `load_cookies_on_start` | 开 | 启动时自动把该目录下的 cookie 灌回去（见下） |
| `screenshot_dir` | `<数据目录>/temp` | 截图保存位置（框架临时区，自动清理） |
| `download_dir` | `<数据目录>/files` | 下载保存位置（和框架 `<file>` 标签同一目录） |
| `screenshot_max_count` / `download_max_count` | 50 / 100 | 最多保留多少个 |
| `screenshot_auto_clean` / `download_auto_clean` | 开 | 自动清理旧的 |
| `download_max_bytes` | 2GB | 单个下载大小上限（下载是**流式落盘**，多大都不占内存） |
| `upload_max_bytes` | `268435456`（256 MB） | 上传大小上限。这是**硬顶**，配置超过也会被钳回来；上传是**分块流式**，单帧恒定约 340 KB，所以大文件不会把连接撑爆 |

#### `inherit` 模式与 Windows 上的一个例外

`inherit` 会**复制**一份你浏览器的数据来用，登录状态一般都能带过去。

> ⚠️ **Windows + Chrome 127 及以上**：Chrome 引入了应用绑定加密，
> 部分 Cookie 可能**解密失败**。这时不用折腾，用 cookie 导入即可：
>
> ```
> browser_cookie(action="export")     # 从你自己的浏览器导出
> browser_cookie(action="import",…)   # 写进无头后端（按域写入，不依赖解密）
> ```
>
> 复制失败时插件会**自动回退**到自己的 profile，而不是直接报错。

复制时会跳过 `Cache` / `GPUCache` / `Service Worker` 这些大目录（否则要复制几个 GB），
并删掉副本里的锁文件（否则 Playwright 会以为"这个 profile 正在被使用"）。

#### Cookie 自动加载是干什么的

重装插件、换 profile 模式、换机器之后，登录状态就没了。
先用 `browser_cookie(action="export")` 把 cookie 存成一个 JSON 放进 `cookies_dir`，
下次启动就会自动恢复。

- 两种格式都收：裸数组 `[...]`，或 `{"cookies": [...]}`
- 字段用浏览器扩展的命名（`expirationDate` / `sameSite` / `httpOnly`），会**自动转换**
- 哪个文件有问题就跳过哪个，不会连累其它站点、也不影响浏览器启动

---

## 工具一览（10 个）

工具按「**动作 + 传参**」组织：同类操作合并成一个工具，用 `action` 选具体做什么。
能力没少，但 AI 不用在一堆近义名字里挑。

| 工具 | 干什么 |
|---|---|
| `browser_navigate` | 打开网址 |
| `browser_page` | 读页面：正文 / 结构大纲 / 原始 HTML / 按选择器取 / 批量抽取 |
| `browser_interact` | 所有交互：点击、填写、输入、悬停、滚动、上传、前进后退、刷新、键盘、鼠标（18 个动作） |
| `browser_tabs` | 列出所有标签页 |
| `browser_screenshot` | 截图（整页 / 只截某个元素），可以直接发给你 |
| `browser_wait` | 等某个元素或文字出现（比干等几秒准） |
| `browser_script` | 执行 JavaScript，返回表达式的值 |
| `browser_file` | 下载 URL 到本地（会带上浏览器登录态）、列出下载/截图目录 |
| `browser_cookie` | 导出 / 写入 cookie，用来在两个后端之间搬登录态 |
| `browser_diag` | **查状态 / 排障**（4 个 action）：`status`=后端状态、profile 模式、超时、几张页面；`vlm`=截图分析用哪个模型；`visible`=打开测试页确认可视模式窗口真的显示了；`extension`=扩展装在哪、怎么装、接入令牌 |

<details>
<summary><b>展开看每个工具的详细参数</b></summary>

### 📄 `browser_page`

| 参数 | 说明 |
|---|---|
| `mode` | `info`（只要标题网址）· `text`（正文，默认）· `outline`（标题结构 + 可交互元素 + 链接）· `html`（原始 HTML）· `selector`（取某个选择器内的文本）· `extract`（批量抽结构化数据） |
| `selector` | `mode=selector/extract` 时的 CSS 选择器 |
| `attr` | `mode=extract`：取这个属性（如 `href`），省略则取文本 |
| `limit` | `mode=extract`：最多几条，默认 50 |
| `offset` | 从正文第几个字符开始读（续读长页面用） |
| `max_chars` | 本次最多返回多少字符 |

> **内容没有长度上限**：单次返回 8000 字符只是「一次给多少」。
> 返回值里带 `has_more` / `next_offset` / `total_chars`，
> AI 看到「还有 26512 字符未读」就会自己带 `offset` 接着读。

### 🖱️ `browser_interact` 的 18 个动作

| 分类 | action |
|---|---|
| 元素 | `click` · `fill` · `type` · `hover` · `scroll` · `upload` |
| 导航 | `go_back` · `refresh` |
| 键盘 | `key_press` · `key_down` · `key_up` · `key_type` |
| 鼠标 | `mouse_click` · `mouse_move` · `mouse_down` · `mouse_up` · `mouse_wheel` · `mouse_drag` |

常用参数：`selector` / `text` / `index`（定位）、`value`（填写内容）、
`key`（按键，如 `Control+a`）、`direction`、`file_path`、`x` / `y`。

### 🌐 `browser_navigate`

`url`、`new_tab`（在新标签页里打开）

### 📸 `browser_screenshot`

`full_page`（截整页还是只截可视区）、`selector`（只截某个元素）、
`send`（是否直接发给你，默认 true）

### ⏱️ `browser_wait`

给了 `selector` 或 `text` 就等它们出现（比干等更准）；都没有则等 `seconds` 秒。

### ⚡ `browser_script`

`script` —— 一段 JavaScript，返回表达式的值。

### 📁 `browser_file`

| mode | 说明 |
|---|---|
| `download` | 下载 URL 到本地并发给你（**会带上浏览器的登录态**） |
| `list` | 列出已下载 / 截图目录里的文件 |

上传文件不在这里，用 `browser_interact(action="upload", selector=…, file_path=…)`。

### 🍪 `browser_cookie`

| action | 说明 |
|---|---|
| `export` | 导出当前站点（或指定 url）的 cookie |
| `import` | 把 cookie 写进当前后端 |

典型用法：先从扩展桥导出，再写进无头后端 —— 这样降级到无头时也不用重新登录。

### 🔧 其余几个（不需要参数）

- `browser_tabs` —— 不需要参数，列出所有标签页
- `browser_diag` —— `status`=后端状态 / profile 模式 / 超时 / 页数；
  `vlm`=截图分析用的是哪个模型；`visible`=打开测试页确认窗口可见；
  `extension`=扩展路径、安装步骤、接入令牌

### ⚡ `browser_script` 需要额外开一个开关

用扩展桥执行任意 JS，需要你在扩展详情页打开「**允许用户脚本 / Allow User Scripts**」
（Chrome 138+ 的安全要求）。这是 Chrome 强制的，扩展无法代劳。

**只有这一个能力需要它**，其它（点击、输入、上传、下载、读页面）都不受影响。
没开时插件会把这个情况翻译成一句能照做的话。

</details>

---

## 两个后端能力对照

| 能力 | 用你的浏览器 | 用插件自己的 |
|---|---|---|
| 读页面 / 提取 / 列表签 | ✅ | ✅ |
| 跳转 / 点击 / 输入 / 滚动 | ✅ | ✅ |
| 截图 | ✅ | ✅ |
| 执行 JavaScript | ✅（需开 userScripts 开关） | ✅ |
| 上传 / 下载 / Cookie / 键鼠 | ✅ | ✅ |
| 用你现有的登录态 | ✅ 天然就有 | ✅ 靠 `inherit` 复制 |

**两边能力完全对称** —— 换后端不丢功能，区别只是"在谁的浏览器里做"。

---

## 常见用法

**看看 AI 现在在浏览什么**

```
browser_page(mode="outline")   # 先看结构，知道下一步能点哪
browser_page(mode="text")      # 再读正文
```

**搜索并点进结果**

```
browser_navigate(url="https://www.baidu.com")
browser_interact(action="fill", selector="#kw", value="Python 教程")
browser_interact(action="key_press", key="Enter")
browser_wait(selector="#content_left", timeout=10)
browser_interact(action="click", text="Python 官方教程")
```

**读完一篇长文**

```
r = browser_page(mode="text")               # 返回 has_more=true, next_offset=8000
r = browser_page(mode="text", offset=8000)  # 接着读
```

**下载需要登录的文件**

```
browser_file(mode="download", url="https://example.com/private/report.pdf")
```

**降级时也不丢登录态**

```
browser_cookie(action="export")                  # 从你的浏览器导出
browser_cookie(action="import", cookies=[...])   # 写进无头后端
```

**上传文件**

```
browser_interact(action="upload", selector="input[type=file]",
                 file_path="/path/to/resume.pdf")
```

**拖动滑块 / 拖动排序**

```
browser_interact(action="mouse_drag",
                 start_x=100, start_y=200, end_x=400, end_y=200, steps=15)
```

**直接取数据**

```
browser_script(script="[...document.querySelectorAll('.item a')].map(a => a.href)")
```

---

## 常见问题

**装了扩展之后，我的浏览器还能正常开吗？**
能。扩展桥这条路**根本不启动浏览器** —— 扩展自己连出来，插件借用的是你已经开着的那个。
没有第二个进程，就没有目录冲突。

**执行 JavaScript 提示"需要打开 Allow User Scripts"？**
Chrome 138+ 的安全要求。`chrome://extensions` → 找到 Kira Browser Bridge → 详情 →
打开「允许用户脚本」。只有执行 JS 需要它。

**工具一直说"页面已关闭"？**
现在有页面自愈：页面失效会自动换一张，连续两次失败会重建浏览器。不会永久卡死。

**CPU 占用高？**
先调小 `idle_close_seconds`（空闲自动关闭）。另外 `default_wait_until` 不要用
`networkidle` —— 现代页面可能永远不空闲，会白等到超时、期间一直在跑。

**磁盘占用一直在涨？**
截图和下载都有自动清理（`screenshot_max_count` / `download_max_count`）。
页面开出的弹窗也会被立即回收。

**下载大文件会撑爆内存吗？**
不会。下载是流式落盘（一块 64KB），多大都平。`download_max_bytes` 只是拦住异常的超大文件。

**内容太长 AI 只能看到一部分？**
不是。单次 8000 字符只是"一次给多少"。返回值会告诉 AI 还有多少没读、从哪接着读，
它自己会续读；也可以让它用 `mode="extract"` 只取要的那部分。

**工具调用总是卡在 60 秒然后失败？**
那是框架的 `tool_call_timeout`（默认 60s）。想让插件不超过它，打开
`op_timeout_follows_framework`。

---

## 故障排除

**报 `ImportError: playwright`**

```bash
pip install playwright aiohttp
```

插件带 `requirements.txt`，重装插件会自动执行。

**浏览器启动失败 / 找不到浏览器**

用 `browser_diag(action="status")` 看状态。它会依次尝试
系统默认浏览器 → Chrome → Edge → Chromium → 内置下载。
网络不通时可以手动装：

```bash
python -m playwright install chromium
```

**可视模式下看不到窗口**

1. 先用 `browser_diag(action="visible")` 打开测试页
2. 用 `browser_diag(action="status")` 确认 `headless` 是 `false`
3. 检查窗口是不是被别的窗口挡住了（Windows 上会最大化启动）

**扩展连不上**

1. 看扩展图标是不是灰的（点一下看状态）
2. 确认令牌是最新的（插件面板里复制）
3. 确认 KiraAI 的 WebUI 端口和扩展里填的一致
4. 用 `browser_diag(action="status")` 看 `bridge.connected`

**截图没有图片描述**

用 `browser_diag(action="vlm")` 自查。最常见的原因是**模型配错了组** ——
用于描述截图的模型必须放在「大语言模型」组，不能放「图像」组，哪怕它本身支持视觉。

---

## 安全

- 默认允许访问本机与内网（`localhost` 上的开发服务器、KiraAI 自己的面板都是正常工作目标）。
  想收紧就关掉 `local_access`，回环 / 私有网段 / 链路本地 / CGNAT 会**一律拒绝**。
- 不要用 `blocked_domains` 来"关本机" —— 那会让 `local_access` 失效，见上文。
- 想完全禁掉写操作，用 `read_only`（工具会从 AI 的工具表里整个消失）。
- 想每次写操作都问你一下，用 `require_confirm`。

完整的安全设计与威胁模型（包括残余风险）见 [SECURITY_DESIGN.md](SECURITY_DESIGN.md)。

---

## 更新日志

本插件迭代很快，完整历史收在下面（**默认折叠**）。点开对应分组即可。

<details>
<summary><b>2.1.x</b> — 49 个版本　·　最新的一系列：双后端重构、安全加固、以及大量审查修复</summary>

### v2.1.58（2026-09-18）

**`inject_page_state` 默认改为关（隐私）。**

原来默认开着：每轮请求都把「当前后端 / 你正在浏览的标题与网址 / 标签页数」
附进上下文。但它是**用户没主动触发就默认外发** ——

| | 开着 | 关掉（默认） |
|---|---|---|
| 隐私 | 你在看网银/体检报告/私信，**每一轮**请求都把标题+网址发给服务商 | 模型只在真正调用浏览器工具时才拿到，取的动作还留在对话记录里 |
| 冗余 | —— | 模型一旦用工具，返回里本来就有标题/网址/标签数 |
| 噪音 | 每轮都挂着"可读可写（无白名单限制）" | 只在该聊浏览器时出现 |
| token | 约 60~120 token/轮 | 0 |
| 附带 | 每 120 秒去戳一次你的浏览器（唤醒扩展 service worker） | 不戳 |

要"模型主动察觉我在看什么"的人，去设置里自己打开 —— 说明里写清了开着的代价。

新增检查 C9a/C9b：schema 与代码的默认值都必须是关，且**不能各说各话**。
反向验证：改回 `true` → C9a 立刻报红。

### v2.1.57（2026-09-18）

**目录语义对齐框架：`data/xxx` = KiraAI 数据目录下的 xxx。**

#### 问题（两个，都是我把"想当然"当成了"约定"）

**① 默认值放错了地方。** 我把下载默认放在 `<data>/plugin_data/<id>/downloads`
—— 那是插件的**内部状态目录**，用户翻不到、模型也没法用 `data/...` 引用。
后来又自作主张发明了一个 `<data>/downloads`，框架里根本没有这个约定。

**② 用户填的 `data/xxx` 被按 CWD 解释。** 框架自己的规矩
（`core/plugin/builtin_plugins/kira-ai/tags.py` 的 `<file>` 标签）是：

```python
if os.path.exists(value):        # ① 绝对路径 → 原样
elif value.startswith("data/"):  # ② → <get_data_path()>/<rel>
else: return []                  # ③ 其他相对路径 → 丢弃
```

也就是说 **`data/bs` 的意思是 `<数据目录>/bs`，不是 `<CWD>/data/bs`**。
按 CWD 解释时，只有"进程 CWD 恰好是 KiraAI 根目录、且数据目录就是
`<root>/data`"才对得上；换个启动目录、或 `--data-dir` 换过，就静默跑偏。

#### 现在

所有目录配置都过同一个解析器，**语义与框架 `<file>` 一致**：

| 你填什么 | 实际含义 |
|---|---|
| 留空 | 插件默认值（下载 `<数据目录>/files`、截图 `<数据目录>/temp`） |
| `data/xxx` | `<数据目录>/xxx` |
| `xxx`（裸名） | `<数据目录>/xxx`（框架是丢弃，配置框里丢掉更糟，统一同基准） |
| `/绝对/路径` | 原样 |

默认值也改成**跟随框架自己的目录约定**：

- 截图 → `<数据目录>/temp` —— 框架的 `AsyncTempMonitor` 本来就在清它
- 下载 → `<数据目录>/files` —— 框架 `<file>` 标签列给模型的"可发送文件"区
- Cookie → `<数据目录>/files/cookie`（`_clean_downloads` 用 `isfile()` 过滤，不碰子目录）

> 自动清理是**特性**：目录填到哪儿，就在哪儿享受清理。

#### 新增检查 `paths_default`（10 条）

C1 默认值不含相对字面量 / C3-C4 行为验证（默认情形与旧写法一致、
换 data-dir 时跟着框架走）/ C5 真构造对象看三个目录是否绝对 /
C6 `data/xxx` 按数据目录解释 / C7 留空回落到框架目录 /
C8-C9 自动清理不会被代码偷偷关掉。

套件 **394/394 全绿**。

### v2.1.56（2026-09-18）

**修注入位置：状态块原来注进了提示词缓存的"前缀"里。**

#### 问题

`inject_browser_state` 把"当前网址 / 标题 / 标签页数"追加进 **`system_prompt`**
的段里。而框架的拼装顺序（`core/provider/llm_model.py`）是：

- `system_prompt` → 插到 messages 的**位置 0**，是**最前面的前缀**
- `user_prompt` → 追加成**最后一条** user 消息

提示词缓存按**前缀**命中。这个状态块**每 2 分钟就可能变一次**，
放在前缀里 = **每次一变就把后面整段对话的缓存全部作废**（对话越长亏得越多）。

#### 修法

改注入到**动态段 `chat_env`** —— 框架有"动态段重定位"机制：

> `sessions` / `chat_env` / `time`（v2.33.1 起 `memory` 也是）在 assemble 时
> 会被标 `persist=False`、包上 `<system_reminder>`、**挪到最新 user 消息最前**，
> system prompt 因此跨轮稳定。

时机也正好：本钩子（`ON_LLM_REQUEST`）在 `message_manager` 里
**先于** `assemble_prompt()` 执行，所以往 `chat_env` 里加的内容会被那次重定位带走。

没有 `chat_env` 段时退化成 `req.user_prompt.insert(0, Prompt(..., persist=False))`
（skill 里写的两种方式）。

#### 顺带修：扩展探测到的端口没被采信

`discover()` 原来把**响应里报的** `port` 存下来。但那个值来自插件读
`webui.json`，某些部署下该文件不存在（插件会回落到默认 5267）——
于是会出现"**在 8080 上探测成功、却被记成 5267、然后连 5267 失败**"。

→ 改成**以探测到的端口为准**：我们刚刚就是在这个端口上跟它说上话的，
这是硬证据。

#### 新增守卫 A16

`inject_browser_state` 里，往 `system_prompt` 段追加内容时**必须是动态段**
（`chat_env` / `sessions` / `time` / `memory`）—— 否则报红。

首跑把正确写法也误报了（两者都是 `X.content += ...`，区别只在
**上几行有没有动态段的名字判断**），判据已收紧；
反向验证：写回旧版注入 → A16 报红并点名到行。

#### 结果

回归套件 **383/383 全绿**。版本 2.1.55 → 2.1.56。

### v2.1.55（2026-09-18）

**紧急修复：扩展启动即崩。**
`[KiraBridge] bootstrap 失败 TypeError: Cannot read properties of undefined
(reading 'length')`

#### 怎么回事

v2.1.53 重构"多连接"时，把配置从"一份 host/port/token"改成"实例列表"。
但 `getConfig()` 本体**忘了同步改**——它仍然返回旧形状（没有 `instances`），
而新调用方直接读 `cfg.instances.length` → `undefined.length` → 抛异常。

而且这个异常发生在 **bootstrap 阶段**，所以表现是"扩展装上去就没反应"。

#### 为什么所有检查都没抓到

改动过程中我在第一次尝试里改过 `getConfig()`，但后来把那版**回退**了
（因为发现重构范围比预估大），重新做时**漏掉了这一步**。

而更根本的问题是：**套件里没有任何东西真的启动过这个 Service Worker**。
静态检查（正则扫源码）看不出"函数之间的形状不匹配"——
`getConfig()` 返回什么、调用方读什么，两边各自看都没毛病。

#### 修法

1. 补上 `getConfig()` 的列表版 + 老配置一次性迁移
2. 补上 `upsertInstance()` 与 `STORE.INSTANCES`
3. **新增 I4「Service Worker 启动冒烟」**：stub 掉 chrome API，
   **真 import 一遍 background.js**、真跑 bootstrap，然后断言
   - 启动过程不报错
   - `getConfig()` 返回的是 **instances 数组**
   - 没配对时是**空数组**（不是 undefined）
   - 老的单份配置能迁移成列表
   - 空配置下 `connect()` 不抛异常

**反向验证**：把 `getConfig()` 换回出事的版本 → I4 **原样复现**用户的报错
（`Cannot read properties of undefined (reading 'length')`）。

> 这是这几天第一条"**真的把扩展跑起来**"的检查。之前覆盖的多是
> Python 侧（生命周期冒烟）和纯逻辑（多连接路由），
> **扩展的启动路径一直是空的**。

#### 结果

回归套件 **378/378 全绿**（新增 I4 的 5 条）。版本 2.1.54 → 2.1.55。

### v2.1.54（2026-09-18）

**跨实例提示**：让 bot 知道"页面在我操作期间被另一个实例动过了"。

#### 为什么

多连接之后，一个浏览器会同时被多个实例操作。有几件事是**共享资源的固有语义**，
不是 bug：A 点了链接跳走 → B 手里的 selector 指向的已经是上一个页面；
A 正在填表单、B 判定"可以提交了" → 点了提交。

不做仲裁（谁都能动），而是**让 bot 自己知道**。

#### 怎么做的（**省 token 是关键**）

判定放在扩展里，**只有真的发生时才带一个字段**：

```
data.other_writer = "kira-b"      ← 另一个实例在我上次收到结果之后写过页面
```

插件收到后追加一句：

> ⚠️ 另一个实例（kira-b）在你上次操作之后动过这个页面，内容可能已经变了 —— 建议重新读一次再继续。

**开销对比**：

| 情况 | 开销 |
|---|---|
| 平时（没有别的实例操作） | **0** —— 字段都不带，一个字都不多 |
| 真发生时 | 约 45 字符 ≈ **40 token**，而且**同一个事实只提醒一次** |

（每个连接有一条水位线：提醒过就把水位推上去，不会每次调用都重复念。）

**没加 URL**：加了反而会引导 bot 用一个可能已经过期地址；"重新读一次"更准，也更省。

#### 顺带

- 判定逻辑抽成 `shared.js` 的 `otherWriterFor(link)` —— 放那儿才能被 node 测试直接 import
- `_render` 外面包了一层（渲染分支改名 `_render_base`），契约检查跟着认两个名字

#### 验证

- 扩展侧：`multi_link.mjs` 新增 4 条（平时零开销 / 不提醒自己 / 提醒别人 / 不重复提醒）
- 插件侧：生命周期检查新增 4 条（同上，真把插件跑起来验）
- 回归套件 **373/373 全绿**

版本 2.1.53 → 2.1.54。

### v2.1.53（2026-09-18）

**扩展改成"多连接"**：一个浏览器可以同时被多个 KiraAI 实例操作。

#### 为什么改

原来的设计里扩展只能连**一个** KiraAI。一台机器跑了两个实例时，
就得"挑一个"——于是有了探测排序、面板交接、让用户选那一整套。

但那个前提本身是错的：

> 用户打开浏览器停在一个页面上，两个 bot 都装了插件，
> **她们本来就该都能看到同一个页面**，命令各自发、各自执行。
> 会抢鼠标，但那和"两个人都能看"是两件事。

所以改成：**发现几个就连几个**。不用挑、不会连错、
也没有"选错实例"这回事了。

#### 代价（说清楚）

它会变成"**一个浏览器两只手**"。除了抢鼠标，还有三件会真出问题的事：

| 现象 | 说明 |
|---|---|
| 上下文失效 | A 点了链接跳走 → B 手里的 selector 指向的已经是上一个页面 |
| 动作交错 | A 正在填表单（填了前三个字段），B 判定"可以提交了" → 点了提交 |
| 当前页被改 | A 新开一个标签 → B 眼里的"当前页"也变了 |

这不是 bug，是共享资源的固有语义。所以**不再是"谁独占"**，
而是让 bot 自己知道——这也是下一步要做的（返回里带 `meta`）。

#### 改了什么

- **`shared.js`**：发送层（`sendRaw` / `sendResult` / `sendChunk`）改成
  **必须显式带上目标连接**；`sendEvent` 默认**广播给所有连接**
  （标签页切换、页面加载是浏览器级的事实，每个实例都该知道）。
- **`background.js`**：单 socket → **连接表**（每条连接各自的重连/状态/探测槽位）；
  `connectAll()` 连上全部；状态变成聚合的实例列表。
- **`capabilities.js`**：下载分块带上发起它的那条连接。
- **`popup`**：从"一个连接状态" → **实例列表**；不再有"选一个"。
- 配置从"一份 host/port/token" → **实例列表**，并带一次性迁移
  （否则升级上来的用户会突然一个都连不上）。

#### ⚠️ 一个差点踩进去的坑

最省事的改法是搞一个"当前连接"全局变量，发送时读它。**16 处引用一次改完，看起来很香。**

**但它是错的，而且错得极隐蔽**：命令是 async 的 —— A（实例1）在 `await` 期间，
B（实例2）的命令进来会把它改掉，A 恢复后再 `sendResult` 就把**自己的响应发给了 B**。
现象是"跟 A 说话 A 没反应，B 却收到一堆不属于它的结果"，
而且**只在两个实例同时忙的时候才出现**。

所以 `link` 是**显式传下去**的。并且加了检查 **I3**：
并发交错地发两条命令，验证各自的响应回到各自的连接。
反向验证：把"当前连接"全局的错法注入进去 → **5 条断言立刻报红**。

#### 结果

回归套件 **365/365 全绿**（新增 I3 的 6 条）。版本 2.1.52 → 2.1.53。

### v2.1.52（2026-09-18）

**浏览器扩展的「零配置接入」**：装完扩展什么都不用填，端口和令牌自动配好。

#### 问题

扩展原来要用户手填 **服务地址 / 端口 / 令牌** 三样，而端口在代码里
**写死 5267**。用户只要改过 KiraAI 的端口就永远连不上，报错还只说
"连不上" —— 小白用户根本不知道该改哪里。

#### 做法：面板直接交给扩展（主路径，零歧义）

**KiraAI 的面板页本来就是那个实例自己服务的**，所以页面里的
`location.port` **就是它的真实端口**。于是：

1. 面板加载令牌时，把接入信息 `postMessage` 出去
2. 扩展的 content script 收到（**只在回环地址的页面上运行**），
   校验 `event.origin` 是回环后转给后台
3. 后台写好端口 + 令牌，并**直接连上**（用户既然打开了面板，就别让他再点一次「连接」）

> **多实例也不会认错**：一台机器上部署了 3 个 KiraAI 时，
> **用户在谁的面板里就配谁**。
>
> 顺带说明一件**做不到**的事：有用户问"能不能直接扫安装目录拿端口" ——
> **不行**。浏览器扩展读不了本地文件（浏览器的安全模型），除了用户主动选的
> 那种文件框。所以端口只能靠"问"（面板交接）或"探"（扫端口）。

#### 兜底：扩展自己探测

没打开过面板的用户，扩展会自己扫候选端口（KiraAI 默认 5267 + 常见 Web 端口）：

| 命中 | 行为 |
|---|---|
| 1 个 | 直接填好，零配置 |
| 0 个 | 提示去面板点「自动检测」或手工填 |
| **≥2 个** | **不猜**，在弹窗里列出来让用户选 |

最后一条是刻意的：选错的后果是"我对 A 说话，B 却动了我的浏览器"，
比多点一下严重得多。另外**存过的端口永远优先单独探测** ——
保证已经配好的人不会因为"并行探测谁先回"而漂到别的实例上去。

#### 插件侧新增

- **`GET /api/plugin/headless_browser/pair`**（免登录）：返回本实例的
  端口 + 令牌。之所以能免登录 —— 来调它的人正是"还没配好、连不上"的扩展，
  要求登录就没解决问题。改用**回环限制**兜底：只回答本机请求。
- 配对响应带 `instance` / `data_dir`，多实例时扩展能区分。
- 新配置项 **`allow_remote_pairing`**（默认关）：确实需要"浏览器和
  KiraAI 不在同一台机器"时才打开。

#### 顺带修的

- 弹窗的「保存」在令牌为空时**不再写入空值** —— 否则会把刚自动检测到的
  令牌擦掉（表现为"点了自动检测，一连接又变成未配置"）。
- 面板每 10 分钟的令牌轮询也会推送一次，所以后台**只在接入信息真的变了时**
  才动作 —— 否则用户手动点的「断开」会被每 10 分钟自动撤销一次。
- A14 检查放行 `{PLUGIN_ID}` 这类 **f-string 插值**（插的是常量，拼出来必然对），
  仍然拦得住硬编码的错 id。

#### 结果

回归套件 **350/350 全绿**。版本 2.1.51 → 2.1.52。

### v2.1.51（2026-09-18）

**新图标：二次元萌系立绘风格。** 顺带把图标体积从 1.25 MB 压到 420 KB。

#### 新图标

用 Agnes（`agnes-image-2.5-flash`）生成 —— 一位可爱的二次元少女，
双手捧着一块悬浮的浏览器窗口、指着里面的光标箭头。
配色沿用旧图标的品牌色（奶油白 / 青绿 / 琥珀金），"AI 在操纵网页"的意象也保留了。

**关于"参考图"**：本来打算把旧图标作为参考图喂给模型（`image` 字段做图生图），
但这个 provider 的 `/images/generations` **不支持图生图** —— 带上 `image` 字段就返回
一个误导性的 `Invalid API key`（纯文本 prompt 则完全正常）。
所以改为**在提示词里精确描述旧图标的配色与构图元素**，效果一样。

**裁剪**：模型生成的图带了一圈"圆角卡片 + 外留白"（四周各约 82px，
看着像"图标里又套了一个图标"）。检测出圆角方块的实际边界后裁掉外圈，
让画面铺满整个画布 —— 缩到 64px 时主体也更大更清楚。

#### 体积

| | 之前 | 之后 |
|---|---|---|
| 尺寸 | 1024×1024 | 1024×1024 |
| 体积 | **1.25 MB** | **420 KB** |

做法是**调色板量化到 256 色**。扁平插画（大色块 + 硬边）几乎没有损失，
但体积只有原来的三分之一。

#### 新增检查

- **B3b**：图标必须 < 500 KB（面板每次渲染插件列表都要加载它）
- **B3c**：图标必须正方形且 ≥ 256px

反向验证：把 1.25 MB 的旧图标换回去 → B3b 立刻报红。

#### 结果

回归套件 **357/357 全绿**。版本 2.1.50 → 2.1.51。

### v2.1.50（2026-09-18）

**紧急修复：插件起不来。**
`Failed to initialize plugin headless_browser: 'BrowserBridge' object has no
attribute 'clear_event_listeners'`

#### 怎么回事

`main.py` 的 `initialize()` 里有一行：

```python
# 事件回调（先清再注册，热重载不会重复累积）
self.bridge.clear_event_listeners()      # ← 这个方法从来没实现过
```

`BrowserBridge` 只有 `on_event` / `_dispatch_event` —— **没有
`clear_event_listeners`**。于是 `initialize()` 一跑到这行就
`AttributeError`，插件**整个起不来**（不是某个功能坏了，是插件加载失败）。

#### 为什么所有检查都没抓到

仓库里本来就有 **A1「`self.xxx()` 调用了但类里没定义」** 这条检查 ——
正是为这类"语法合法、一跑就崩"的问题准备的。但它只扫 **`self.xxx()`**，
而这一行是 **`self.bridge.xxx()`**（在**协作者对象**上调用），不在它的覆盖范围。

#### 修法

1. **补上方法**：`BrowserBridge.clear_event_listeners()` 清空
   `_event_listeners` 与 `_any_listener`（就是那行注释说的语义）
2. **补上检查 B1**：把调用图检查扩到**协作者对象上的调用** ——
   先收集 `self.X = SomeClass(...)` 的绑定，再验证 `self.X.method()`
   里的 `method` 在 `SomeClass` 上真的存在。
   反向验证：把 `clear_event_listeners` 删掉 → B1 立刻报红并点名到行：
   `main.py:270 BrowserPlugin.self.bridge.clear_event_listeners() ——
   BrowserBridge 里没有 clear_event_listeners()`

> 只有**插件自己定义的类**会被查（`Lock` 这类框架对象跳过），
> 避免误报。

#### 结果

回归套件 **348/348 全绿**（新增 B1 后）。版本 2.1.49 → 2.1.50。

### v2.1.49（2026-09-17）

**工具定义瘦身 40%**：13 个工具 → 10 个，每次请求的工具 schema 从
**6,984 字符（≈2,757 token）压到 4,740 字符（≈1,656 token）**。

#### 为什么要做

每个工具的名称 + 描述 + 参数 schema 都是**每次请求固定带上**的。
13 个工具加起来接近 2,800 token —— 对上下文小一点的模型是很大一块，
而且工具越多，模型选错的机会越大。

审计发现三件事：

1. `browser_interact` **一个就占 34%**（18 个动作、24 个参数）
2. **参数 JSON 占 59%**，描述文字只占 29% —— 光改描述不够
3. 描述里塞了大量**「为什么」和背景知识**，那些不该每次请求都带着

#### 做法一：把「为什么」挪出常驻区

工具定义里那些"讲一次就够"的说明，挪到**真正需要它的地方**：

| 原来常驻在描述里 | 挪到哪 |
|---|---|
| `browser_script`：「扩展桥需要打开『允许用户脚本』开关（Chrome 138+）」 | **直接删** —— 扩展在失败时**已经返回更详细的原因**（版本低 / 开关没开 / 怎么办），描述里那句是冗余 |
| `browser_cookie`：「典型用法：先从扩展桥导出，再写入无头后端…」 | export 的**成功返回**（用的时候才出现） |
| `browser_screenshot`：「（这样你才能『看到』页面：工具结果是文本…）」 | 删掉解释，只留「截图，并用视觉模型描述给你」 |

> ⚠️ 返回文本也不是免费的 —— 它在该工具**被调用后**才进上下文，
> 并留在会话历史里。所以能挂失败返回的就挂失败返回（最省），
> 其余的挂成功返回（按调用次数付）。

#### 做法二：合并 4 个「配置/排障」类工具

`browser_debug` / `browser_check_vlm` / `browser_test_visible` /
`browser_extension_help` —— 四个都是**零参数的"查情况"工具**，合成一个：

```
browser_diag(action)：
  status    后端状态（profile 模式、超时、空闲多久）
  vlm       截图分析用哪个视觉模型
  visible   打开测试页，确认可视模式窗口真的显示了
  extension 扩展装在哪、怎么装、接入令牌
```

判断标准不是"功能重叠"，而是**它们不是干活的工具** ——
用户说"帮我看看 example.com 写了什么"时，这 4 个永远不该被选中。

**顺带修正了一个只读模式的边界**：`browser_test_visible` 原来在
`WRITE_TOOL_NAMES` 里（它内部会 `navigate`）。合并后 `browser_diag`
**不**进那个名单 —— 这样只读模式下 `status`/`vlm`/`extension` 仍然可用
（纯查询），只有 `visible` 会在内部走 `for_write=True` 被拦住，
比"整个工具被摘掉"更精确。

#### 做法三：参数描述只留非自明的

`x` / `y` / `steps` / `click_count` / `delta_x` 这些**名字本身就说明问题**的
参数不再带 description；与 enum 重复的描述也删掉。

#### 效果

| | 工具数 | 字符 | token 估算 |
|---|---|---|---|
| 之前 | 13 | 6,984 | ≈2,757 |
| 之后 | **10** | **4,740** | **≈1,656** |
| | | **−40%** | **−40%** |

单个工具的降幅：

| 工具 | 之前 | 之后 |
|---|---|---|
| `browser_interact` | 3,360 | **2,270** |
| `browser_page` | 1,255 | 850 |
| `browser_screenshot` | 925 | 470 |
| `browser_file` | 874 | 700 |
| `browser_cookie` | 693 | 620 |

#### 能力零丢失验证

- **枚举值**（所有 action/mode）：旧 37 个，新 41 个，**旧的一个没少**
- **参数名**：逐工具比对，**无丢失**
- **被合并的 4 个诊断**：`browser_diag` 的 4 个 action + 4 个实现函数都在
- `regression/checks/tool_merge.py` 的 LEGACY 映射已更新，能力零丢失检查通过
- 回归套件 **346/346 全绿**

#### 为什么没有更激进

原方案里还有一档：把 11 个低层鼠标参数拆成独立工具、默认不注册
（能省到 **−58%**）。**没做**，因为 README 把「键盘鼠标也能模拟」
列为"全能"的一部分 —— 默认关掉会自相矛盾。

### v2.1.48（2026-09-17）

**清点历史遗留的未解决审查线程时，发现一个真 bug。**

#### 🔴 schema 里有 5 个字段的 `type` **框架根本不认识**

`create_field_from_schema()` 只认这些类型：
`string/text/sensitive/integer/int/float/list/enum/switch/bool/json/
markdown/yaml/editor/textarea/model_select/multi_select/persona_select/
session_select/section/info`。**不认识的一律兜底成 `StringField`**（文本框）。

而 schema 里写着：

| 字段 | 原类型 | 实际渲染 | 应为 |
|---|---|---|---|
| `allowed_domains` | `array` | **文本框** | `list` |
| `blocked_domains` | `array` | **文本框** | `list` |
| `upload_allowed_dirs` | `array` | **文本框** | `list` |
| `command_timeout` | `number` | **文本框** | `float` |
| `op_timeout_ratio` | `number` | **文本框** | `float` |

**这不只是"控件不对"**：列表字段退化成文本框后，整个列表被存成
**一串文本**，而插件侧读的是 `list(cfg[...])` ——

```python
list("*.bank*")  # → ['*', '.', 'b', 'a', 'n', 'k', '*']   逐字符！
```

于是用户在面板上改一次黑名单，**拦截就静默失效了**：看着配了，
实际每条规则只剩一个字符。`upload_allowed_dirs` 会变成
`['d','a','t','a','/',...]`。

**→ 两处修复：**
1. schema 的 5 个类型改成框架认得的（`array`→`list`、`number`→`float`）
2. 插件侧加 `_as_list()` 兜底：字符串按换行/逗号切分
   （`upload_allowed_dirs` 早就有这个兜底，两个域名列表漏了）
   → 即使面板存回字符串，也不会再退化成逐字符列表

**→ 新增检查 F5**：schema 的每个 `type` 必须在框架认得的集合里。
集合**优先从框架源码现场提取**（`KIRA_FW_DIR/core/config/config_field.py`），
拿不到才用内置清单 —— 这样它不会随着框架演进而失效。
反向验证：把 `array` 注回去 → F5 立刻报红并点名到字段。

#### 顺带：清点了 25 条未解决线程

捞出来逐条核实（很多只是因为行号没怎么变、GitHub 没标 outdated）：

| 状态 | 条数 | 说明 |
|---|---|---|
| **已修**（核实代码） | 3 | 只读模式的 `WRITE_TOOL_NAMES` 已是注册名；`content_dom` 的 PATH 已改用 `which` 的绝对路径；`static_audit` 的前置读取已加守卫 |
| **已在运行时兜住** | 1 | `op_timeout_ratio`：schema 没法约束（框架不读 `min`/`max`），但 `main.py` 已 clamp 到 `(0,1)` 并警告 |
| **本轮修掉** | 1 | `bridge.py` 的旧路由（见 v2.1.47）+ 本条 schema 类型 |
| **仍开着（设计级）** | 2 | 扩展的 `<all_urls>`（建议改 `optional_host_permissions` + 运行时申请）；`shared.js` 的 `Promise.race` 超时不会取消底层操作 |

#### 结果

`regression/run_all.py` → **346/346，16 组全绿**；`pyflakes` 干净。
版本 2.1.47 → 2.1.48。

### v2.1.47（2026-09-17）

**CodeRabbit 第四十七轮：4 条（3 条采纳、1 条部分不采纳）+ 同类自查 2 处。**

#### ① 陈旧的路由引用：`bridge.py` 的文件头（采纳）

`bridge.py` 的模块文档写着扩展连到
``/ws/plugin/kira_browser_bridge/bridge`` —— 那是**旧插件 id**。
真正的代码、扩展、面板早就是 `headless_browser` 了。危害不在运行
（那只是注释），而在**照着它去配就是 404**。

→ 改成 `headless_browser`；`extension_backend` 的类文档里那句
"包装 kira_browser_bridge 的 BrowserBridge" 一并改成"与浏览器扩展之间的
BrowserBridge"（说的是**当前**这个类，用旧插件名会误导）。

**⚠️ 但不采纳的部分**：`main.py` 顶部那段历史叙述里的
`kira_browser_bridge` **保留** —— 它写的是"**原来的两个插件**"（合并前的
`headless_browser` 和 `kira_browser_bridge`），是**准确的历史**，
改掉反而会让合并的来龙去脉讲不通。README 里那条同类注记同理。

**顺带补了检查的洞**：A14（"硬编码的插件 id 必须与 manifest 一致"）
原来**只扫 `web/index.html` 和 `browser-protocol.js`** ——
所以 `bridge.py` 文档里这个错路径一直没被抓住。
→ 扫描范围扩到 `.py`（`bridge.py` / `main.py` / `setup_guide.py` /
`backends/*.py`）。反向验证：把旧路径写回去，A14 立刻报红并点名到行。

#### ② 注释与实现不符（`regression/checks/__init__.py`）（采纳）

注释写着 `#: (模块, 是否默认启用)`，但 `ALL_CHECKS` 里的元素**就是模块**，
`run_all.py` 直接取 `m.TITLE` / 调 `m.run(report)`。
照着注释加一个元组进去，跑到那里就是 `AttributeError`。
→ 注释改正，并写明"要新增检查：import 进来，加到这个列表里即可"。

#### ③ `execJs` 的截取边界写死了 `upload`（`tool_merge`）（采纳）

`cap.split("async function execJs(")[-1].split("async function upload(")[0]`
—— 边界依赖"`upload` 恰好排在 `execJs` 后面"。一旦 `upload` 改名或换位置，
截取就**延伸到文件末尾**，于是后面**任意**函数里的
`chrome.userScripts.execute` 都会算数 —— 而"作用域"正是这条断言存在的理由。

→ 改成卡在**下一个顶层函数**处。
**实测**：把 `upload` 改名后，旧边界从 4341 字符暴涨到 **13186**
（= 整段剩余的 100%），新边界稳定不变。

#### ④ 桩的持久化上下文缺初始页（`regression/stubs/playwright`）（采纳）

真实的 `launch_persistent_context` 返回的上下文里**已经有一张页面**，
而桩给的是空 `pages`。这不只是"少了张页"——**插件默认走的就是这条路**
（profile 恒为真），于是"复用现有标签 vs 新建"这条分支在测试里
**和生产走了不同的路**。

→ 桩里补上初始页。
**但我要说清楚：这一条我给不出强的行为判别**（两种写法下
`pages_created` 与 `_page is pages[0]` 都相同），所以没写那种
"怎么改都能过"的弱断言，而是直接在 **H3 探针**里断言桩的**结构事实**：
持久化上下文带 1 张初始页、普通 `new_context()` 初始为空
（反向验证：去掉初始页 → 前者报红、后者仍绿）。

#### 同类自查（抓 2 处）

按 ③ 的模式扫所有"按函数名切分函数体"的写法：

| 位置 | 问题 |
|---|---|
| `static_audit` 的 upload 切片 | 边界写死 `uploadAbort`，找不到时**回退成整个文件** → 误报"SW 在累积" |
| `security_rules` 的 download 切片 | 边界是注释分隔符 `// ───`，被删就延伸到文件末尾 |

两处都改成"下一个顶层函数"。
（另两处 `tool_merge` / `runtime_behavior` 的同类写法**已经有正确边界**，未动。）

#### 结果

`regression/run_all.py` → **345/345，16 组全绿**；`pyflakes` 干净。
版本 2.1.46 → 2.1.47。

### v2.1.46（2026-09-17）

**CodeRabbit 第四十六轮：7 条全部为真 + 同类自查又抓 6 处。**

#### ① 上传时把本地绝对路径发给了扩展（`extension_backend`）

`CMD_UPLOAD` 里带着 `"path": resolved`（用户机器上的绝对路径）。
但扩展侧只是把它当显示名回显（`capabilities.js` 里
`path: params.path || res.name`）—— **并没有拿它去读盘**，文件内容是插件侧
分块推过去的。所以这条路径白白经过 WS 桥，没有收益（CWE-200）。
→ 不再下发。同时把 `d2.setdefault("path", resolved)` 改成**赋值** ——
不下发之后扩展回显的是文件名，`setdefault` 会留下它，两个后端的返回结构
就不一致了（headless 返回的是绝对路径）。
新增守卫 **C16f2 / C16f3**，反向验证过。

#### ② `configureWorld (` 会让检查**抛异常中断整组**（`execjs_gates`）

第 59 行用 `re.search(r'configureWorld\s*\(')`（容忍空白），
第 63 行却用 `code.index("configureWorld(")`（**字面量**）——
代码写成 `configureWorld (` 时前者找得到、后者抛 `ValueError`，
合法的 JS 排版却让整个检查组炸掉。
→ 用正则的 `match.start()`。
（同类自查：B2 的两处 `.index()` 前面**已有**存在性短路守卫，安全。）

#### ③ `EXT_DIR.iterdir()` 不防目录缺失（`static_audit`）

`browser-bridge/` 整个不在时抛 `FileNotFoundError` → **D 段中断**，
E 段也不会跑 —— 而 E1 恰恰是负责点名"`browser-bridge/*` 缺了什么"的那条，
**最该报出来的状态反而被吞掉**。
→ 目录不在时按"什么都不存在"处理。实测：删掉整个目录后 E1 现在能
**点名全部 12 个缺失文件**。

#### ④ `load_json_safe` 的兜底过宽（`harness`）

`except Exception → {}` 会把 `PermissionError` / `UnicodeDecodeError`
（`src_safe` 是**有意**让这两种往外抛的）悄悄转成"JSON 无效"——
**原因被换成了另一个原因**，排查会往完全错误的方向找。
→ 只吞 `json.JSONDecodeError`（缺文件时 `src_safe` 返回空串，
`json.loads("")` 抛的正是它）。实测权限/编码错误现在正常往外抛，
缺文件仍返回 `{}`。

#### ⑤ 截取窗口是固定字符数，会切进下一个函数（`cred_mode.mjs`）

`cap.slice(dlIdx, dlIdx + 4000)` —— 而 `downloadViaSession` 有 3634 字符，
窗口**已经切进了后面的 `cookieGet`**。后一个函数里的声明可能被当成前一个
函数的，判据就会给出错的结果，而且函数一变长还会继续漂。
→ 改成卡在**下一个顶层函数**处。

#### ⑥ 安全文档的措辞不够限定（`SECURITY_DESIGN.md`）

我上轮写的"跑在个人电脑上 → 该风险≈0"会被读成"风险全为 0"，
但 `local_access` 开着时本机与内网服务仍然可达。
→ 改成"**云元数据这一项**风险≈0"，并补一句说明本机/内网风险不受影响。

#### ⑦ 状态轮询也有同一个竞态（`web/index.html`）

上轮我修了 `loadToken` 的请求竞态，**漏了 `refresh()`** —— 它是**每 3 秒**
跑一次的，而一次 `/status` 比 3 秒还慢时，旧请求后到就会把新状态覆盖回去；
旧请求若失败，还会把已渲染好的内容改成"读取失败"。
→ 同样加递增请求序号（成功路径与 catch 路径都判）。
**实测反向验证**（用旧版 `index.html` 跑新探针）：旧版 2 条红、新版全绿。
新增探针 `status_race.mjs` + 接入 **I2**。

#### 同类自查（按惯例，抓 6 处）

| 类别 | 抓到 |
|---|---|
| 固定字符窗口截取 | `redirect_flow.mjs` 的 6000 字符窗口 —— **同一处问题** |
| 宽兜底伪装原因 | `security_rules` / `file_hygiene` / `static_audit` 各一处 `except Exception` |
| 可选导入兜底过宽 | `static_audit` / `tool_merge` 的 `except Exception` → 收窄到 `ImportError` |

#### 结果

`regression/run_all.py` → **343/343，16 组全绿**；`pyflakes` 干净。
版本 2.1.45 → 2.1.46。

### v2.1.45（2026-09-17）

**CodeRabbit 第四十五轮：3 条全部为真**，全部属于"**检查本身有洞**"。

#### ① `local_access` 转发检测漏了 keyword-only 参数

C6g 用 `fn.args.args` 找参数，而 `ast.arguments.args` **只含"位置或关键字"
参数**。写成 `def fetch(url, *, local_access=True)` 的包装器转发完全正确，
却会被判成"没这个参数" → **误报**（套件退出码变成 1）。
→ 改成同时看 `posonlyargs` / `args` / `kwonlyargs`，并加 **C6g2** 自检：
用**合成的 AST** 验四种参数形态都能认出来（不依赖仓库里现有代码恰好长什么样）。

#### ② 删文件矩阵的**假绿**（我自己的工具）

`crashed` 只看 `"未抛异常"`。可如果 `run_all.py` 在打印汇总**之前**就退出了
（导入失败 / 删掉的就是运行器本身），`tot` 是 `None`，而 `crashed` 仍是
`False` → 矩阵打出一个 ✓，后面跟着 `PASS ? / FAIL ?` ——
**什么都没验，却看着通过了**。
→ 判据补上 `tot is None`，并把两种情形**分开标**：
`未跑完`（套件没产出汇总）vs `整段中断`（有汇总但某段抛异常）。

实测：删 `regression/harness.py` 现在标 `未跑完`（修前是 ✓）；
删 `regression/checks/file_hygiene.py` 同样。

#### ③ "期望失败"的用例会**空转通过**

`upload_detach.mjs` 的 B 场景（元素被删除 → 上传必须失败）只断言
`rb.ok !== true`。可如果 setup（`upload_begin` / `upload_chunk`）自己就挂了，
`upload_finish` 也会因为**没有有效会话**而失败 → 断言照样成立，
**而它想验的"目标被移除时不得假报成功"根本没被验到**。
（"期望失败"的用例天生有这个陷阱：它和"什么都没做成"长得一样。）

→ 补上 `setupB = begunB.ok === true && chunkB.ok === true`，
断言变成 `setupB && rb.ok !== true`，detail 里也把 setup 结果打出来。

**实测反向验证**（把 B 的选择器改成不存在的 `#nope`，逼 setup 失败）：

| | 旧版 | 新版 |
|---|---|---|
| 断言结果 | ✅ **通过（空转）** | ❌ 失败（正确抓出） |
| detail | `{"__error":"上传会话不存在或已过期"}` | `setup=false …` |

#### 同类自查

按 ③ 的模式扫了 `regression/js/*.mjs` 里所有"期望失败"型断言
（`ok: … !== true` / `ok: !…`）—— **只有这一处**，已修。
Python 侧核对了 C 段：C1/C2/C4/C5 虽然只断言"被拒"，但同段有
**正对照**（C3 读操作放行、C6 默认放行本机、C6d 收紧后公网仍放行），
所以"机制整体坏成一律拒绝"这种失效模式会被挡住。

#### 结果

`regression/run_all.py` → **337/337，16 组全绿**；`pyflakes` 干净。
版本 2.1.44 → 2.1.45。

### v2.1.44（2026-09-17）

**`local_access=False` 漏了一整段地址：CGNAT `100.64.0.0/10`** ——
**阿里云的元数据端点 `100.100.100.200` 就在里面**。

#### 问题

开关的说明写着"关闭：本机 / 内网 / 链路本地一律拒绝（**含云厂商元数据端点**）"。
但实测（`check_url(url, local_access=False)`）：

| 目标 | 修前 | 修后 |
|---|---|---|
| `169.254.169.254`（AWS/Azure/GCP 元数据） | ⛔ 拒绝 | ⛔ 拒绝 |
| `100.100.100.200`（**阿里云元数据**） | ⚠️ **放行** | ⛔ 拒绝 |
| `100.64.0.1`（CGNAT 段） | ⚠️ **放行** | ⛔ 拒绝 |
| `8.8.8.8`（公网） | ✅ 放行 | ✅ 放行 |

根因：`100.64.0.0/10`（RFC 6598 载体级 NAT）**不在** Python `ipaddress` 的
`is_private` 里（实测 3.12 返回 `False`），而代码里也从没提过 CGNAT ——
于是整段都没被当成"内网"。一个**只想放行本机开发服务器**的用户，
把开关关掉之后，这台机器上的云凭据仍然可读。

#### 修复

在 `_ip_is_internal` 里显式特判 `100.64.0.0/10` → 视为内网。
**与 `198.18.0.0/15` 的区别**（那段是**有意排除**的）：`198.18` 是
Clash / mihomo 这类代理的 **fake-IP 占位段**，指向的是代理而不是内网服务；
`100.64/10` 在部署环境里就是真的内网 / 元数据地址，所以要拦。

#### 顺带把文档的说法校准

- `SECURITY_DESIGN.md`：补 CGNAT 与"主流云厂商元数据端点"对照表；
  补两句此前没写清的 —— **"默认放行本机"≠"默认随意"**（还有黑白名单
  两个开关），以及**残余风险取决于部署环境**（个人电脑上元数据端点
  根本连不上，云主机上才是真风险）。
- `schema.json` 的开关文案：原来只提 `169.254.169.254`，现在把阿里云
  `100.100.100.200` 一并写明；并补上 fake-IP 环境下的已知边界
  （那时主机名都解析到占位段，"解析后判内网"这一步天然判不出来 ——
  但该环境下浏览器同样走代理，本身到不了内网，口径是**一致**的）。

#### 新增守卫

- **C6m**：`local_access=False` 下**穷举特殊网段**（回环 / 三段私有 /
  链路本地 / CGNAT / IANA 保留 / 240/4 / IPv6 三类 + **两条"有意放行"
  防止一刀切误伤**）
- **C6m-self**：钉住"**为什么需要**这条特判"的先决条件 ——
  `100.100.100.200` 只能靠 CGNAT 特判拦住（通用规则兜不住）。
  哪天 Python 把它归进 `is_private`，这条会红、提示特判可以删
- **C6m-self2**：特判确实生效

反向验证：删掉 CGNAT 特判 → **C6m + C6m-self2 立刻报红**，C6m-self 保持
绿（它陈述的是先决条件，仍然成立）。

#### 结果

`regression/run_all.py` → **336/336，16 组全绿**。版本 2.1.43 → 2.1.44。

### v2.1.43（2026-09-17）

**CodeRabbit 第四十四轮：7 条意见全部核实为真，逐条修复** + **一次工具升级**
（自查工具从"手写名单"改成"自动推导"，又抓出 4 处同类问题）。

#### 🔴 ① 端口判据比它声称的弱（`execjs_gates` B1）

判据只查 `< 1` 和 `> 65535`。但 **`Number("abc")` 是 `NaN`，两个比较都是
`false`** —— 把"非数字"那半守卫删掉，判据**照样通过**，而 B1 的消息里
明明写着"否则 -1/70000/**abc** 会拼出非法 URL"。

→ 判据额外要求"非数字被拒绝"的证据（数字格式正则 / `Number.isXxx` /
`isNaN`），并加 **C4** 反向自检：只删非数字守卫时判据必须报红
（实测旧判据在该变形上返回 `True` —— 确实会漏）。

#### 🟠 ② 扩展 manifest 缺失 → 键错误中断整组

`ext_manifest()` 在文件缺失 / JSON 坏掉时返回 `{}`，而这里写的是
`exm["background"]["service_worker"]` → `KeyError` → **B~E 段全部消失**。
→ 逐层取默认值。

#### 🟠 ③ 模板插值里的 `}` 不一定是插值的结束（`harness`）

扫描器只按 `{`/`}` 计数，于是 `` `${"}"; socket.readyState}` `` 会在**字符串里
那个 `}`** 处提前收尾，剩下的 `"; socket.readyState}` 被当成模板文本丢掉
→ 一个真会抛 `ReferenceError` 的裸引用**漏检**。
→ 新增 `_copy_interp_body()`：逐个跳过**字符串 / 转义 / 注释 / 嵌套模板**，
连正则字面量也按经典启发式区分。实测旧逻辑吞掉、新逻辑保留。

#### 🟡 ④ 凭据探测会被"正确的那条"骗过（`cred_mode.mjs`）

选表达式用的是 `mHop ? mHop[1] : httpsExpr`。若**两个声明都存在**而
`credentials` 用的是 `isHttps`，探测会**拿正确的逐跳表达式去喂 `isHttps`**，
把坏掉的那个掩盖过去。
→ 改成按 `credentials` **引用的变量名**选。实测：
夹具里 `isHttps = true`（恒真、HTTP 也带凭据）+ `hopIsHttps` 正确
→ **旧版 5/5 全绿（被骗），新版正确报出 2 条红**。接入 **C8b2** 常驻自检。

#### 🟡 ⑤ 桩的 cookie 主机名按 `:` 切会截断 IPv6

`http://[::1]:8080/` 被切成 `[` → `[::1]` 的 cookie 永远匹配不上，
**桩悄悄返回了错的集合**。→ 改用 `urlsplit(...).hostname`。
顺带把过滤里的 `except Exception` 收窄到 `(TypeError, ValueError)` ——
原来的写法会让"忘了导入"伪装成"过滤失败返回全部"，比不过滤更糟。

#### 🟡 ⑥ 安全文档的断言与行为不符（`SECURITY_DESIGN.md`）

原文写着"想拦本机的用户在黑名单里写 `127.0.0.1` 就够了" —— **这是错的**：
黑名单是按主机名**文本**匹配（`_matches`），不做地址等价解析。实测
`blocked=["127.0.0.1"]` 时 **7 种写法只拦住 1 种**，包括**云元数据端点
`169.254.169.254` 都放过**；而 `local_access=False` **7 种全拦**。
→ 文档改成"拦本机要用 `local_access`，黑名单管的是特定主机名模式"，
并附实测表。接入 **C6j/C6k/C6l**：文档的说法与代码行为绑在一起，
哪天黑名单真加了归一化，检查会红、逼着同步改文档。

#### 🟡 ⑦ 面板令牌请求竞态（`web/index.html`）

定期轮询 `loadToken(false)` 与用户点「重新生成」的 `loadToken(true)` 并发，
而 fetch 不保证先发先回。轮询那条拿到的**旧令牌**晚到就会**覆盖**刚生成的
新令牌 —— 面板上显示回一枚**已作废**的令牌，用户以为"重新生成没生效"。
→ 加**递增请求序号**，只认最后一次发出的响应。实测旧版 3 条红
（旧令牌覆盖、指纹错误、失败响应也覆盖），新版全绿。接入 **I1**。

#### 🔧 工具升级：自查矩阵改成"自动推导"

上一轮的"逐个删文件跑全套"用的是**手写名单**，我列了 `manifest.json`
—— 那是插件根的，而 `ext_manifest()` 读的是 `browser-bridge/manifest.json`。
**名字像、路径不同**，于是"删了也没崩"的假绿骗过了我（CR 正好点在这一处）。

→ 重写成 `regression/delete_matrix.py`：**扫读取器里的路径字面量**自动推导
候选，删谁都不会漏。一跑就多抓出 **4 处同类问题**：

| 缺哪个文件 | 后果 |
|---|---|
| `security.py` | `load_module` 抛 `FileNotFoundError` → 整组消失 |
| `regression/stubs/playwright/async_api.py` | 桩导入失败 → 整组消失 |
| `browser-bridge/content.js` | 裸 `open()` → 整组消失 |
| `browser-bridge/manifest.json` | 裸 `open()` → 整组消失 |

全部改成"**结构性前提明确报因**"或走 `src_safe`/`ext_manifest`。
矩阵现已**固化进仓库**（不是一次性脚本），28 个候选**全部 0 崩溃**。

#### 🛡 新增守卫

- **G3c**：检查模块读**固定字面量**路径不许用裸 `open()`/`read_text`
  （首跑误报 3 处，查明是遍历 glob 的变量读取 —— 判据收紧到"必须跟引号"，
  反向验证过）
- **H1/H2/H3**：Playwright 桩的语义（`urlsplit` 模块级导入 / 不吞异常 /
  真跑 cookie 往返·副本·IPv6·子域过滤）
- **G1 词法夹具**：6 种插值陷阱（串 / 转义 / 行注释 / 块注释 / 嵌套模板 /
  正则）逐一钉住；改成旧逻辑后 5 种立刻漏检
- **C8b2 / I1**：两个"检查器自身要被验证"的反向自检

#### 结果

`regression/run_all.py` → **333/333，16 组全绿**；`pyflakes` 干净；
删文件矩阵 **28/28 无崩溃**。版本 2.1.42 → 2.1.43。

### v2.1.42（2026-09-17）

**按 CodeRabbit 第四十三轮审查修复 6 项** + **一轮主动自查**（发现问题比
审查报的多）。

#### 🔴 ① `harness.py` 里混进了检查代码（我上次提取函数时的损伤）

上一轮把 `strip_comments_only` 提取到 `harness.py` 时，**误把
`execjs_gates` 的 `_judge_port_guard` 和整个 `run()` 也带了过去** ——
harness 里于是多了一份"永远不会被调用"的重复实现。它不报错（没人在
harness 里调它），但会让人以为检查在那里跑。

→ 删除（-118 行），并加守卫 **G2**（用 AST 判，不看注释里的示例文字）。

#### 🟠 ② 下载：`resp.body` 可能是 `null`

204 / 304 等响应本来就没有正文，直接 `.getReader()` 会抛
`TypeError: Cannot read properties of null` —— 而那句话对用户毫无意义。
→ 按"零字节文件"处理，返回与正常路径**同一个结构**（`{ok, url, mime, bytes:0}`）。

#### 🟠 ③ content_dom 的两处"静默跳过"

- **结果为空**：`for item in data` 一次都不执行，报告上什么都不显示 ——
  但那是"**没检查**"，不是"检查通过"。→ 显式报失败。
- **三个上传探测脚本缺失**：`if X.is_file():` 直接跳过，
  会让人以为"上传链路已验证过"。→ 缺了就报失败。

#### 🟡 ④⑤ 两处"根本没有行为验证"的补强

- **重定向流程**：新增 `redirect_flow.mjs` —— 起一个**真实的 302 服务器**
  跑两跳，验证"跟得到底、`resp.url` 指向最终地址、经过了两次重定向"，
  并对"最终 URL 协议守卫"做真值表验证（起 HTTPS 落 HTTP → 拒绝）。
  接成检查 **C8d**。
- **tokens.py 的注释与实现矛盾**：注释说 `tv` 绑定"access_token + 代际号"，
  但 `_fingerprint_input()` **原样返回 access_token**（代际号那套早废弃了，
  掺进去会连新令牌一起被服务端拒）。作废走的是 `is_current_token()` 的
  **jti 闸门**。→ 改正注释。

#### 🔍 主动自查（比审查报的多）

审查只点了 `static_audit` 的**前置读取**会中断整组。我按同一模式自查，
写了"**逐个删文件跑全套**"的矩阵，结果抓出 **7 处同类问题**、横跨 5 个模块：

| 缺哪个文件 | 修前 | 修后 |
|---|---|---|
| main.py / extension_backend / headless_backend / schema.json / manifest.json / protocol.js / shared.js / bridge.py / protocol.py / cred_mode.mjs | **7 处崩溃**（`未抛异常`） | **0 处崩溃** |

现在删任何文件都是"**各段照跑、各自报错**"（几十条 FAIL，但报告完整、
知道缺的是什么）。做法：

- `harness` 的读取便捷函数全部改走 `*_safe`（`main_src`/`schema`/
  `manifest`/`ext_manifest`/`ext_file`…）——**一处修，所有检查受益**；
- 检查模块里的裸 `src()` 全部换成 `src_safe()`；
- `json.loads(空串)` 会抛 `JSONDecodeError` → 包 try；
- "结构性前提"（如 `bridge.py`/`protocol.py` 加载不了就无从测试）
  **明确报出原因**再停，而不是抛裸 `FileNotFoundError`。

**新增常驻守卫 G3a/G3b**：harness 的读取函数必须走 safe 变体、
检查模块不许出现裸 `src(` —— 防这类问题再回来。

#### 结果

`regression/run_all.py` → **313/313，16 组全绿**；`pyflakes` 只剩 3 处
**有意保留**（两个带 `# noqa` 的桩导入、一个要保留字面 `{PLUGIN_ID}` 的 f-string）。
版本 2.1.41 → 2.1.42。

### v2.1.41（2026-09-17）

**按 CodeRabbit 第四十二轮审查修复 3 项**（3 actionable）。

#### 🔴 ① 我上一轮的重定向改法**在浏览器里根本走不通**

上一轮我把下载改成 `redirect: "manual"` 自己跟重定向 —— 思路是
"每跳都重新判断协议"，看起来更安全。

**但它跑不起来**：`manual` 在浏览器里返回的是 **opaqueredirect** 响应 ——
`status` 是 0、**所有响应头都读不到**（包括 `Location`）。
（Fetch 规范如此。StackOverflow 上"Response headers not available for
fetch request with redirect: manual"的回答很直接：
*"No, it's not possible. The requirements in the Fetch spec prevent it."*）

所以我的代码**必然**走到"没有 Location 头"那个分支抛错 ——
等于把"重定向全失败"换了个写法。

→ 改用 `redirect: "follow"` 让浏览器跟随。这是**安全的**，因为浏览器在
**每一跳**会自己重算要发哪些 Cookie：Secure cookie 绝不会出现在 HTTP
请求上、域不匹配的不会发给别的站点；跳数上限也由浏览器保证。
跟随完成后**再检查最终 URL**：起始是 HTTPS 却落在 HTTP 上就中止。

> 教训：**看起来更保守的实现，可能因为平台限制而完全失效**。
> 我上一轮改完还做了"每跳凭据决策"的推演验证 —— 但那是验证**我的模型**，
> 不是验证**浏览器实际会怎么做**。涉及平台 API 语义时，先查规范/文档。

#### 🟡 ② Playwright 桩的 cookie 是空实现（往返测不到）

`FakeContext.add_cookies()` 直接 `return None`、`cookies()` 永远返回 `[]` ——
于是"加了 cookie 再读回来"这条链路**在测试里是空转**：
插件里任何依赖"写完确认"的逻辑（cookie 导入、导出→导入往返）都测不到。

→ 真的存进来（`_cookies`），`cookies()` 返回**副本**（不暴露内部列表）、
支持按 url 做同域/子域过滤。**实测**：往返成功、外部改动不影响内部、
同域/子域/异域过滤都正确。

#### 🟡 ③ VLM 描述链路可能一直走的是"空转"路径

`vlm_describe` 的探针脚本里，`describe_image` 会
`from core.utils.common_utils import desc_img` —— 如果导不到就
**静默走 except 返回空串**，而那几条断言（"返回了预期文本"）在空转路径上
**也可能成立**。

→ 在探针里加计数器：假客户端真的被调用时 +1，并断言
**B0b「描述链路真的走到了框架 desc_img」**。
**实测**：缺 `common_utils` 的框架目录下明确报红（不假绿）。

#### 连带的判据同步

改 ① 时两个旧检查报红，都是"实现改了、判据还在盯旧形态"：

- **B2.5** 原来断言 `redirect: "error"` —— 那是更早一版的写法。
  判据要盯**真正要保证的语义**（"会不会跨协议泄漏凭据"），
  而不是某个具体选项：现在守两条（不用读不到 Location 的 manual +
  有最终 URL 协议检查）。
- `tool_merge` 的 **C8c**（本轮新增）专门防退回 `manual`，
  判据要**剥注释**再查（注释里正解释"为什么不用 manual"，裸文本会自指）。

顺带把"只剥注释"的 `strip_comments_only` 提到 `harness.py` 与
`execjs_gates` 共用（原先两处各一份）。

#### 结果

`regression/run_all.py` → **302/302，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.40 → 2.1.41。

### v2.1.40（2026-09-17）

**按 CodeRabbit 第四十一轮审查修复 6 项**（5 actionable + 1 nitpick）。

#### 🔴 ① 「死代码检查」只写在标题里，从来没实现

`callgraph.py` 的 `TITLE` 写着"调用图完整性（未定义方法 / **死代码**）"，
但实际只有 A1/B1/C1/D1 四项，**没有任何死代码检查** ——
`FRAMEWORK_CALLED` 常量定义了却**从没被读过**（那段没写完的痕迹）。

→ **实现 E1**：找出"定义了但零引用"的方法。
判据保守（宁可漏报不误报）：带框架装饰器（`@register.*` / `@on.*`）的豁免、
`__xxx__` 豁免、`FRAMEWORK_CALLED` 豁免；引用形态覆盖三种
（`name(` / `.name` / `"name"` 字符串派发）—— 只查 `name(` 会一次性误报上百个，
检查立刻变噪音。

**第一次跑就精确抓到 `OpResult.as_text`**（唯一一个真死代码，零误报）——
它甚至什么都不做（`return text`）。已删除。
反向验证：注入一个零引用方法 → E1 点名。

#### 🟠 ② content_dom 的两处 `return` 跳过了独立的 U1–U5

点击脚本失败/输出解析失败时直接 `return` —— 但 U1~U5（分块上传）
用的是**另外三个脚本**，与"点击检查能否跑"互相独立。
跳过它们会让报告只显示 D0 红，误以为"只有点击有问题"。

→ 改成记失败后**继续**。**实测**：注入非法 JSON 让 D0 报红 →
U1~U5 照常执行并通过。

#### 🟠 ③ execjs_gates 的判据会被**注释**满足

三个判据（configureWorld 调用、CSP 的 `'unsafe-eval'`、端口校验）
原来都在**裸文本**里找关键字 —— 而注释里写一句
"官方文档：userScripts.configureWorld() 可以配置 CSP"就能骗过它们。

→ 改成**结构化解析**：先剥注释（状态机，能正确处理字符串里的 `//`），
在**代码态**里找调用与范围表达式；CSP 则先剥注释再抠 `csp: "..."` 字面量。
**实测**：全注释的假源码 → 三个判据全 False；真源码 → 全 True。
（修的过程中还发现自己的**端口判据改过头**：把错误消息文本也剥掉了，
而消息在字符串里 → 改成盯**校验表达式本身**。）

顺带把状态机剥离器抽到 `harness.py`（`strip_js_noise`）——
原先 `wiring.py` 与 `execjs_gates` 各有一份，正是"两份副本会漂移"的老问题。

#### 🟡 ④ upload_sweep 的 abort 用例可能**假通过**

只断言最后那次 `upload_chunk` 被拒绝。如果 `upload_begin` 或
`upload_abort` 自己就失败了，最后那次 chunk 也会"被拒绝" ——
测试照样绿，但它验证的是"会话不存在"，**不是"abort 让会话失效"**。

→ 加前置断言：`begun.ok && aborted.ok && rejected(r)`。

#### 🟡 ⑤ 事件桩与框架**不一致**（假保真度）

stub 的 `KiraMessageBatchEvent.session` 是**字符串**，而框架真实类型是
`Session` **对象**；框架的事件类还有一个 `sid` property
（`return self.session.sid`）。插件 `_sid_of()` 的第一分支正是取 `event.sid` ——
桩少了它，那条分支**永远走不到**：测试全绿，测的却是兜底路径。

→ 桩补上 `Session` 类（带 `sid` / `__str__`）与事件的 `sid` property，
与框架对齐（显式传字符串仍支持）。

#### 🟡 ⑥ 下载被 `redirect:"error"` 一刀切（很多正常下载会失败）

原来完全拒绝重定向 —— 最保守，但 CDN / 短链 / 对象存储几乎都靠 302 跳转，
**用户会遇到"下载不了"**。而 `redirect:"follow"` 又不行：浏览器会自动带着
凭据跳，跨协议时 Cookie 已经发出去了。

→ 改成**手动跟随**：`redirect:"manual"` 自己跟，
**每一跳都按该跳的 URL 重新决定要不要带凭据**（跳到 HTTP 时变 `omit`），
限制跳数（防环）、缺 `Location` 明确报错、相对 Location 按当前 URL 解析。
**实测**：`https → https → http` 的链上，末跳凭据正确降为 `omit`。

⚠️ 改这条时连带修了两个"定长切片"问题：
`tool_merge` 的 C8 用 `[:2000]` 切 `downloadViaSession` —— 函数一变长
后半段（含 `sendChunk`）就被切掉，检查无缘无故报红 → 改成切到**下一个顶层函数**。

#### 结果

`regression/run_all.py` → **300/300，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.39 → 2.1.40。

### v2.1.39（2026-09-17）

**按 CodeRabbit 第四十轮审查修复 3 项**（2 actionable + 1 nitpick）。

#### 🟡 ① 「只用无头」策略下的提示却说"扩展未连接"

`router.hint()` 只分了 `extension` 与"其余"两条分支 ——
在 **`headless` 策略**（只用无头）下，提示仍然是
"扩展未连接，且无头浏览器也未启动"。可那种配置下**扩展根本不参与**，
让用户去装扩展是**误导**。

→ 按三种策略各自给对应提示（`headless` 下只说无头怎么触发启动）。

#### 🟡 ② D-guard 的段标记用 `index()` 会中断整组

守卫从源码里切 D/E 段用的是 `str.index()` —— 标记被改名/重构掉时抛
`ValueError`，**整个检查组就此中断**（而那正是守卫自己想要防的那类问题）。

→ 改成 `src_safe()` + 先判标记存在；找不到就**明确报 FAIL**
（不静默通过、也不崩）。

⚠️ 修这条时**我自己引入了两个错**，都当场被检查抓出来了：

1. **自指**：判"标记在不在"时写成了 `'section("D. ...")' in 源码` ——
   可那个字符串字面量**就写在守卫自己的代码里**，永远为真。
   即使真正的 `section()` 调用被删掉，守卫也照样"找得到"。
   → 改成**正则匹配真正的 `section(...)` 调用**。
   （反向验证：把 `section("E. .gitignore")` 改名 → 守卫明确报 FAIL 且不中断整组。）
2. **变量遮蔽**：辅助函数里写 `src = src("protocol.py")`，遮蔽了模块级的
   `src`，后面再用就 `UnboundLocalError` → 改用不同变量名。

#### 🟡 ③ `WRITE_CMDS` 抄了一份字面量，而 protocol 里早有权威定义

`protocol.py` 里**早就有** `WRITE_COMMANDS`（用 `CMD_*` 常量拼的），
但 `extension_backend.py` 又抄了一份字面量集合。两份定义迟早漂移：
protocol 加了新写命令，那份字面量不会自动跟上 →
**那条命令静默绕过确认框**。

→ 改成派生：`WRITE_CMDS = set(_P_MOD.WRITE_COMMANDS)`。
这样"新增命令自动纳入确认"，不再需要人工同步。

**连带更新两处检查**（B2 / F1b）：它们的判据原来是"正则扫字面量集合"，
现在要认**派生形式** —— 改成去 `protocol.py` 解析 `WRITE_COMMANDS`
的**真实成员**（读真实值也顺带验证了"派生确实生效"）。
**反向验证**：从 `protocol.WRITE_COMMANDS` 删一条 → F1b 立刻点名缺失。

#### 结果

`regression/run_all.py` → **299/299，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.38 → 2.1.39。

### v2.1.38（2026-09-17）

**按 CodeRabbit 第三十九轮审查修复 6 项**（3 actionable + 3 nitpick）。

#### 🔴 ① 执行 JS 的 catch-and-retry 会让脚本**跑两遍**

`execJs` 原来是"先带 `world` 参数试，失败就不带 `world` 重试"。
但那个 catch 会接住**任何**失败 —— 包括"脚本已经注入之后才失败"
（比如用户脚本第一条语句就抛错）。于是同一个脚本**被执行两次**，
副作用重复且不可撤销。这和"页面操作超时不得换后端重试"是同一类危险。

→ 去掉重试，直接执行一次、失败如实上报。
（是否需要 `world` 参数已由 `ensureUserScriptWorld()` 在**事前**探测；
manifest 要求 Chrome 135+，而该参数自 userScripts API 起就有。）

#### 🟡 ② contract 夹具硬编码 `/tmp/_kira_*.png`

假 Playwright 的 `screenshot(path=...)` 会**真的写文件** ——
路径写死在 `/tmp` 里，每跑一次回归就留一份**永不清理**的残留
（并发跑还会互相覆盖）。

→ 截图/下载路径改到受管理的 tmp 下（和 `upload_file` 一样），
跑完自动清理。**实测**：跑完 `/tmp` 无残留。

#### 🟡 ③ `vlm_describe` 探针不校验退出码

只找 `RESULT:` 行 —— 脚本可能**已经打印了结果**，但在收尾阶段
（临时目录清理、解释器关停）出错而非零退出。那种结果不可信，
只看输出会把"跑挂了"当成"跑通了"。

→ 先校验 `returncode`。同理 `timeout_semantics` 的 `has_ret` 判据也收紧了：
原来看 `ast.dump(test)` 里有没有字段名字符串 —— **任何**出现都算命中
（比较的另一侧、别的调用参数）。改成精确解析
`getattr(<obj>, "field", ...)` 调用。

#### 🟡 ④⑤⑥ 三处"夹具与检查不是同一个东西"

- **`execjs_gates` 的 C1/C3 是重言式** ——
  `"X" not in s.replace("X", "Y") and "X" in s` 恒为真。→ 把 A1/A2/A3/B1
  的判据抽成**可复用函数**，反向自检直接把它跑在变形文本上。
  **这一改立刻抓出真问题**：原判据只看"有没有一个叫 ensureUserScriptWorld
  的函数"，而**调用被删掉时函数壳还在** → 判据仍通过。现在盯的是
  `configureWorld(` **调用本身**。
- **`static_audit` 的 C16e** 内联了一份与 `_scan_undeclared` 重复的扫描逻辑 ——
  夹具测的是 `_scan_undeclared`，真正断言用的是那份副本，
  **两份实现迟早漂移**（那时夹具守的东西和检查用的东西不是同一个）。
  → 合并成一处，夹具与检查共用同一条判据。**实测**：注入未声明变量能抓到。

#### 结果

`regression/run_all.py` → **299/299，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.37 → 2.1.38。

### v2.1.37（2026-09-17）

**按 CodeRabbit 第三十八轮审查修复 6 项**（3 actionable + 2 nitpick +
1 条它自己说"不需要改"但值得加防护的）。

#### 🟡 ① 断线检测用固定 `sleep(0.4)`

`bridge_e2e` 的"断开感知"测试是"杀掉进程 → 睡 400ms → 断言已断开"。
但进程死后 socket 关闭要经事件循环投递到 bridge，**机器负载高时 400ms 不够**
→ 偶发假失败。

→ 改成**轮询到超时**（最多 3 秒，每 50ms 查一次）：快机器立刻过，慢机器给足时间。

#### 🟡 ② D4 比的是文件名，不是相对路径

`f.name not in ALLOWED_MD` 只比**文件名** —— 于是
`browser-bridge/README.md`、`regression/README.md` 这些**子目录里的** README
会被当成"根级白名单里的 README.md"直接放行。
而规则的本意是"**插件本体（根目录）**只允许这两篇"。

→ 改成比**仓库相对路径**。**实测**：在 `browser-bridge/` 下塞一个 README →
现在会被抓到（修前放行）。

#### 🟡 ③ 回归文档没有说明"上传只验到 jsdom"

`upload_stream/sweep/detach` 都在 jsdom 里构造 `DataTransfer` + `File`，
能证明"分块拼装、顺序校验、上限、会话回收"这些**逻辑**正确，
但**不能**证明真实 Chrome / Edge 会接受这个合成 FileList。
文档里没写清楚，容易让人以为上传已经在真机验证过。

→ 补进"已知限制"，并写明真机验证方式。

#### 🟡 ④ 写命令清单两侧没有一致性检查

`extension_backend.py` 的 `WRITE_CMDS` 与扩展 `shared.js` 的
`PRIVILEGED_COMMANDS` **各自写着"必须与对方保持同步"**，但一直没人验。
它们决定"开了『写操作需确认』时哪些命令弹确认框"——
一边漏了，那条命令就会**静默放行**（历史上已经漏过一次：
`activate_tab`/`close_tab`/`mouse_move`）。

→ 新增检查 **F1b**：两侧清单必须逐字一致。
**实测**：Python 侧漏一条 / 扩展侧漏一条 / 扩展侧多加一条 → 三种都能抓到。
（CR 说"当前没问题、不必改"—— 对，现在是一致的；但**没有东西保证它一直一致**。）

#### 🟡 ⑤ 清理未使用的参数与死代码

- **`BackendRouter.__init__` 的 `on_fallback`** ——
  全仓**没有任何地方**传它或读 `self._on_fallback`，留着会让人以为
  "降级时会有回调"。→ 删掉（连带死掉的 `Callable` 导入）。
- 顺带跑了一遍 `pyflakes`，清掉几处**死导入/未使用变量**
  （`Text`、`BridgeError`/`BridgeNotConnected`/`BridgeTimeout`、
  `TabInfo`、`Dict`、`setup_guide` 里没用到的 `home`、`main.py` 里
  从没被读过的 `last_err`）与一处无占位符的 f-string。
  **现在 `pyflakes` 全净**（只剩 `security.py` 里那处**有意的**
  `publicsuffix2` 探测导入 —— 那是"先试可用性、再用"，不是冗余）。

#### 结果

`regression/run_all.py` → **299/299，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.36 → 2.1.37。

### v2.1.36（2026-09-17）

**按 CodeRabbit 第三十七轮审查修复 5 项**（6 条中 1 条评估后不改，理由见下）。

#### 🔴 ① D4 还在用裸文件清单（**同一个 bug 第四次**）

前几轮把 D1→D2/D3→D4 陆续改成"提交清单"，但每次都是**改一条漏一条** ——
这次 D4 又漏了。一个被 `.gitignore` 忽略的 `.md` 会报 D4 失败，
尽管 git 根本提交不了它。

→ D4 改用 `commit_files`，**并加了一条常驻守卫 D-guard** ——
它直接扫描 D 段的源码，**不允许再出现裸 `files` 用于断言**。
（守卫写完第一次跑就自指报红：它的正则字面量里也写着 `for ... in files`，
已把守卫自身那段排除；随后又把"降级路径里正确的
`commit_files = [f for f in files if not _is_ignored(...)]`"排除掉。）
**反向验证**：D4 改回裸 `files` → D-guard 立刻报红。

#### 🟠 ② 确认框的通知文案带**敏感载荷**

通知会出现在**锁屏**、通知中心，以及任何能看屏幕的人眼前 ——
而原来的文案里带着：完整 URL（query 里常有 token）、
用户要 AI 输入的**文字**（可能是密码）、**JS 源码**、
上传/下载的**文件名与路径**、cookie 的域名细节。

→ 改成**只给"动作 + 目标 + 规模"**：URL 只留主机名（丢掉路径与 query）、
输入内容/源码只报**字符数**、文件名不显示。
**实测** 7 类命令：载荷里的完整值**一个都没进通知文案**。

#### 🟡 ③ `mouse_drag` 的中间 `mousemove` 全发给起点元素

真实拖拽中鼠标下方的元素会**随位置变化**（拖过不同列表项、滑块、画布），
全发给起点元素的话，监听方收不到对应元素上的事件 ——
表现出来就是"拖拽没反应"。

→ 每个中间点发给**该点当前所在的元素**（`document.elementFromPoint`），
终点事件发给终点元素。**并且如实报告**：这些是合成 `MouseEvent`，
**不触发 HTML5 原生拖放**（`dragstart`/`dragover`/`drop`）——
不写清楚的话调用方会以为"拖放完成了"，而目标页面根本没收到
（比如把文件拖进上传区会静默失败）。

#### 🟡 ④ `browser_send_file` 被标成"有意合并"直接跳过校验

它登记为 `None`，于是**两个替代出口哪天被删掉也查不出来** ——
能力真丢了却显示"零丢失"。

→ 新增 `SEND_FILE_EXITS` + 检查 **C1b**，逐项验证两个出口都在：
`browser_screenshot` 的 `send` 参数、`browser_file` 的 `mode=download`。
**实测**：分别删掉任一个 → C1b 都精确点名。

#### 🟡 ⑤ 上传测试的 `size` 声明与实际不符

三处 `upload_begin` 声明 `size: 100`，实际只传 `"AAAA"`（解码 **3 字节**）。
虽然 `size` 当前只用于上限预检、不参与完成判断，
但声明与实际不符会让测试数据本身误导人，也容易掩盖"预检坏了"。
→ 全部改为 `3`。

#### ⏭️ 一条评估后不改：`<all_urls>` 改 optional

CR 建议把 `host_permissions` 的 `<all_urls>` 移到 `optional_host_permissions`
+ 逐站 `chrome.permissions.request()`。**核实后不改**：

1. **`content_scripts` 的静态声明也需要 host 权限** ——
   只挪 `host_permissions` 而不同时把 content script 改成
   `chrome.scripting.registerContentScripts()` 动态注册，
   会变成"声明与权限不一致"（注入会失败）。真要做得跨 5+ 文件重构注入链路。
2. **与产品定位冲突** —— 这是**用户自己安装**的扩展，
   用来操作自己的浏览器；AI 要访问哪个站点是**运行时才知道**的。
   逐站弹框 = 每换一个站点打断一次。
3. **真正的安全边界在插件侧** —— 域名黑白名单 + `local_access` 开关、
   「写操作需确认」**逐次**弹框（比整站授权更细）、
   扩展侧 `assertInjectable()` 拒绝特权页。逐站授权并不更严，只是多一层打断。

→ 写进 `SECURITY_DESIGN.md`（第 5 节，那文档正是为"有意设计"而存在），
**并加检查 A10b**：该取舍必须记录在案 ——
省得每轮自动审查把它当新缺陷重报一遍，也提醒后来者
"要改就得同时改 content_scripts"。

#### 结果

`regression/run_all.py` → **298/298，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.35 → 2.1.36。

### v2.1.35（2026-09-17）

**按 CodeRabbit 第三十六轮审查修复 7 项**（6 actionable + 1 outside-diff；
另 1 条 nitpick 评估后不改，理由见下）。

#### 🔴 ① `_close()` 清零 `_creating` → 计数变负、保护永久失效

`_new_page()` 会在进入时 `_creating += 1`、`finally` 里 `-= 1`；
而 `_on_new_page()` 靠 `_creating > 0` 判断"有页面正在创建、先别回收它"。

如果 `_close()` 在**创建还在途**（卡在 `await context.new_page()`）时把
`_creating = 0`，那个 finally 再 `-1` 就把它变成 **-1** ——
此后 `> 0` 永远不成立，**"正在创建的页面"保护彻底失效**，
弹窗回收逻辑会在不该动的时候关掉页面。

→ `_close()` 只做 `max(_creating, 0)`（有在途创建就保持 1，让它自己归零），
**不清零**。

#### 🟠 ② E1 的断言漏了 hello 握手

等待循环是"`connected` **且** 收到 hello"才 break，但断言只查了 `connected` ——
"连上了但从没握手成功"（协议字段全空、扩展版本报不出来）会照样通过。

→ 收集 `hello_received` 并**要求两者都成立**。

#### 🟠 ③ `C6g` 用 2000 字符宽段 → 后面的函数会给前面"背书"

判据原来是"从函数开头切 2000 字符，看里面有没有 `local_access=local_access`"。
切太宽时，**后面那个**正确转发的函数能替前面漏转发的封装通过检查。

→ 改用 **AST** 逐个函数看**它自己**的 `check_url` 调用关键字。
**实测**：让 `check_write_targets` 漏转发、并在文件末尾追加一个正确转发的函数
→ 旧判据假通过，新判据**精确点名** `check_write_targets`。

#### 🟠 ④ G1 的注释剥离会吃掉字符串里的 `//`

原来按"先剥行注释、再剥字符串"的正则顺序 —— 但 `//` 出现在字符串里极其常见
（`"https://..."`、`"ws://127.0.0.1:5267/ws"`），那种顺序会把**从 `//` 起的整行**
都当注释吃掉：真实代码被吞掉，后续的"裸标识符"检测失真（漏报）。
块注释 `/*` 同理（字符串里的 `/*` 会被误当注释起点）。

→ 换成**一次扫描的状态机**（按字符走、维护"当前在什么里"，
注释只在**代码态**才是注释）。**实测** 7 个用例全部正确：
`https://` / `ws://` / 模板串里的 `//` 不再截断，真注释照常剥掉，
`${...}` 插值里的代码完整保留。

#### 🟡 ⑤⑥ 两处"早退/漏项"

- **`vlm_describe` 的 schema 解析失败早退** —— A7~A12 与 B 段（真跑探针）
  与"schema 能否解析"**互相独立**，早退让它们的结果完全看不见。
  → 记 A7 失败 + `sch = {}` 继续。**实测**：塞坏 schema → A7/A8 报红的同时
  B 段探针**照常执行并通过**。
- **`WRITE_TOOL_NAMES` 漏了 `browser_test_visible`** —— 它内部会 `navigate`
  打开测试页（**确实改状态**）。只读模式下不摘掉的话，用户开了只读仍会被导航走。
  → 补进名单。

#### 🟡 ⑦ 补两条覆盖

- **`wss://` 显式输入**（用户会直接粘完整地址，这条路径与"裸主机名"不同）
  → 加 3 个用例。
- **E1 的 hello 断言**（见 ②）。

#### ⏭️ 一条评估后不改

`bridge.py` 的下载分块用同步 `sink["handle"].write(raw)`，CR 建议改成
per-sink 队列 + `to_thread`。**核实后不改**：

- **竞态：不存在**。从取 sink 引用到 `write()` 之间**没有任何 `await`** ——
  这段在事件循环里是原子的，`_abort_sink()` 插不进来，
  不会出现"写已关掉的句柄"。
- **阻塞：量极小**。分块 32KB（`step=0x8000`），写普通文件是微秒级。
- 引入 per-sink 队列要额外维护"写入 / abort / close 三者的生命周期协调"，
  为微秒级操作加并发复杂度不划算。

→ 只加说明注释（把"为什么不做"写清楚），不改代码。

#### 结果

`regression/run_all.py` → **295/295，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.34 → 2.1.35。

### v2.1.34（2026-09-17）

**按 CodeRabbit 第三十五轮审查修复 8 项**（5 actionable + 1 duplicate +
2 nitpick，全部为真）。

#### 🔴 ① 换页没有串行化 → 并发时建出一堆孤儿页面

`_ensure_page()` 在页面失效时会换一张新页，但它**没有锁**：
并发调用（模型一轮里同时发几个工具请求）会各自发现"页面死了"，
然后**各建一张新页** —— `_page`/`_own_page` 被后写的那个覆盖，
先前建出来的页面**没人引用也没人关**（常驻泄漏）。

→ 加独立的一把 `_page_lock`（**不能复用 `_op_lock`**：`_ensure_page` 会在
已经持有 `_op_lock` 的路径上被调用，复用会自锁死），
并把换页逻辑抽成 `_replace_page()`；拿到锁后**重新检查一次**页面存活
（等锁期间别人可能已经换好了）。

**实测**：并发 10 次调用 —— 修复前建 **10 张**页面（9 张泄漏），
修复后只建 **1 张**。

#### 🟠 ② host-only cookie 被升格成域 cookie

`cookieGet` 导出时**丢掉了 `hostOnly`**，`cookieSet` 导入时**无条件设置
`domain`** —— 于是 host-only 的 cookie（只该发给精确匹配的那个主机）
变成了"域 cookie"，**子域也能收到**。这是安全语义被悄悄放宽。

→ 导出带上 `hostOnly`；导入时仅在 `hostOnly !== true` 时设 `domain`
（`chrome.cookies.set` 不带 domain 会按 url 主机推断，正好还原原语义）。
缺字段时保持旧行为，兼容旧导出文件。

#### 🟡 ③ `sameSite=None` 的 cookie 没带 `Secure`（会被浏览器拒收）

规范要求 `SameSite=None` 必须搭配 `Secure`，否则浏览器**直接拒绝或静默丢弃**。
有些导出工具只写 `sameSite: "no_restriction"` 而不标 `secure` ——
照原样写进去等于这个 cookie **白导了**。

→ `cookies.py` 在 `sameSite` 解析为 `None` 时强制 `secure = True`。

#### 🟡 ④ content_dom 的 U1–U3 失败会**跳过**独立的 U4/U5

`upload_stream.mjs` 崩掉时直接 `return` —— 但 U4/U5 用的是**另外两个脚本**
（`upload_sweep` / `upload_detach`），与本次失败无关。跳过它们会让报告上
只看到 U1–U3 红，误以为"就这三项有问题"。

→ 改成 U1–U3 记失败后**继续跑 U4/U5**。
**实测**：让上传脚本 `exit 3` → U1–U3 报红的同时 **U4/U5 照常执行并通过**。

#### 🟡 ⑤ `tool_merge` 的具名参数检查用**定长切片**

`main[...][:1600]` 会越界切进函数体、甚至切进**下一个工具的定义** ——
前者让"参数被删"假通过（函数体内同名字符串兜住了），
后者让 A 工具缺的参数被 B 工具的同名参数满足。

→ 改为从 `name="<tool>"` 切到**它自己的** `async def` 为止（`_tool_segment()`）。
**实测**：删掉 `browser_wait` 的 `text` 参数 → C1 立刻报红并点名。

#### 🟡 ⑥ `op_timeout_ratio` 的钳制位置太靠后

上一轮把它放在"跟随框架"那条分支里 —— 而只有那条分支会纠正它，
其它路径（含 `browser_debug` 的展示）看到的仍是非法原值，
"显示 5.0、实际用 0.8"的对不上会一直存在。

→ 提前到**解析配置时**钳住 (0,1)。
⚠️ 顺带查证：**schema 里不能**用 `minimum`/`maximum` 表达这个约束 ——
框架的 `create_field_from_schema` 只读 `type/name/hint/default/options/locales`，
**不认这两个键**，写进去只是空头承诺（面板照样允许填非法值）。

#### 🟡 ⑦⑧ 两处 nitpick

- **用了 `tempfile` 的私有 API** `_get_candidate_names()`（两个文件都有）→
  改用公开的 `uuid.uuid4().hex`（私有 API 在小版本升级里可能被改名，会让检查直接崩）。
- **`download_timeout` 没有 schema 条目** —— 代码会读它，但面板上看不到、
  也改不了。→ 补上。

#### 结果

`regression/run_all.py` → **295/295，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.33 → 2.1.34。

### v2.1.33（2026-09-16）

**按 CodeRabbit 第三十四轮审查修复 7 项**（6 actionable + 1 nitpick，全部为真）。

#### 🔴 ① `inherit` 模式复制失败时**整个 profile 丢失**

`_profile_dir_async()`（真正启动走的那条路）在 inherit 模式下直接
`return await self._inherited_profile_dir()` —— 而后者在
"找不到真实浏览器 / 复制失败"时返回 `None`。
于是本次启动**既没继承、也没回退插件目录**，而用户以为开了 inherit 模式。

同步版 `_profile_dir()` 是有正确回退的（会走到 `browser_profile/`）——
**两条路径行为不一致**，而真正跑的是没回退的那条。

→ 加回退（并抽出 `_profile_dir_fallback()`，与同步版同一套判断，
含"指向真实浏览器目录就拒绝"那条）。
**实测**：模拟复制失败 → 正确回退到插件自带 profile 且目录真的建立；
能复制时仍保留继承目录。

#### 🟠 ② CSP 提示覆盖不到**最常见**的报错位置

上一轮加的"执行 JS 被 CSP 挡下"提示只检查了 `first.error` ——
但包装器内部有 `catch (e) { return { __error: ... } }`，
**EvalError 恰恰会被它吞成普通返回值**，于是 `first.error` 是空的，
用户拿到的仍然是一句裸 `EvalError` 原文 —— 而这正是那条提示要解决的问题。

→ 两处都查（`first.error` + `first.result.__error`）。
**实测**：四个用例（两处各一 + 脚本自身错误 + 正常结果）分类正确。

#### 🟡 ③ D4 还在用裸文件清单

上一轮把 D1–D3 改成"提交清单"判据，**D4 漏了** —— 一个被 `.gitignore`
忽略的 `.md` 会报 D4 失败，尽管 git 根本提交不了它。
→ 改用 `commit_files`。

#### 🟡 ④ `security_rules` 的两处判据

- **封装函数扫描只认 `def`**，不认 `async def` —— 封装函数改成异步后
  **扫不到**，C6g（开关必须一路传到底）会静默变成空集合、永远通过。
- **合法端口只验证"能解析成 URL"** —— 端口被悄悄换成默认值时 URL 依然合法，
  检查照样绿。→ 断言解析出的**实际端口**与期望一致。
  （写这条时它当场抓到一个真实行为：`:80` 在 URL 里被规范化成空串，
  因为 ws 的默认端口就是 80 —— 判据要按默认端口折算，不是简单比较。）

#### 🟡 ⑤ `tool_merge` 漏了 `browser_wait` 的 `text` 参数

`LEGACY_PARAMS` 里 `browser_wait` / `browser_wait_for` 都没列 `text` ——
而"等某段文字出现"正是这个工具的主要用法；参数被删掉也查不出来。
→ 补上。

#### 🟡 ⑥ `vlm_describe` 的 B2 断言**区分不出用了哪个模型**

两个假客户端返回同一句固定文本（"假VLM"），所以"配置了模型时优先用配置的"
这条断言，在**错误地走了 fallback** 时同样成立 —— 等于没测。
→ 假客户端返回**带自己 model_id** 的标识，断言改为"必须是我配的那个"。
**实测**：破坏"配置优先"逻辑 → B2 立刻报红（旧断言抓不到）。

#### 结果

`regression/run_all.py` → **295/295，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.32 → 2.1.33。

### v2.1.32（2026-09-16）

**按 CodeRabbit 第三十三轮审查修复 6 项**（逐条核实后全部为真）。

#### 🔴 ① D1–D3 又漏了同一类问题（我上轮只修了一半）

上一轮我把 **D1** 的判据改成"会不会被提交"，但 **D2/D3 还在扫文件系统** ——
正常用一次插件就会生成 `screenshots/` / `browser_profile/` / `__pycache__/`
（都已 `.gitignore`），于是 D2/D3 对**任何真实使用过的副本**必然误报。

→ 三条统一用「提交清单」判定：优先 `git ls-files`，无 git 时退回
"文件系统 + 排除 `.gitignore` 命中的路径"（并声明降级）。
**实测**：造出截图/profile/cookie/log/pycache 的"用过的副本" →
D1/D2/D3 全部 PASS（修前全红）。

#### 🟠 ② `spec_compliance` 的 B0 早退屏蔽了 C~G 全部检查

manifest 是坏 JSON 时直接 `return` —— 而入口点、路由、资源、文档一致性
这些检查与 manifest 是否合法**互相独立**，早退让它们的结果完全看不见。

→ 记 B0 失败 + `mf = {}` 继续往下走。
**实测**：坏 JSON / 非法顶层（数组）/ 空文件三种情形下，
B0 都报告了，**C~G 段照常执行**（各 9 项），无崩溃。
（顺带加了一条：合法 JSON 但不是对象时也按无效处理，否则后面 `.get()` 会炸。）

#### 🟡 ③ `execjs_gates` 的 A3 会因缺标记而整组中断

`cap.rindex("userScripts.execute")` 只守了前一个标记 —— 后一个被改名/重构掉
就抛 `ValueError`，异常逃出 `run()` → **A4~A6 与 B、C 段全不执行**。
（这正是本组检查自己在防的那类"整组中断"，讽刺。）

→ 两个标记都先判存在（B2 同样处理，顺手把绕口的三元表达式改清楚）。
**实测**：删掉该标记 → 只有 A3 报 FAIL，其余照常执行。

#### 🟡 ④ 两处探针的临时目录不清理

`lost_features` / `vlm_describe` 的嵌套探针用 `tempfile.mkdtemp()`，
每跑一次回归就在 `/tmp` 里留一份 cookie 夹具 / PNG。
→ 改用 `TemporaryDirectory`。**实测**：跑完残留数为 0。

#### 🟡 ⑤ 提示文案漏了 `http://`

`buildWsUrl` 把 `http://host:port` 映射成 `scheme === "ws"` 并走"非本机明文拒绝"
分支 —— 但提示只说"去掉 `ws://`"，而用户的输入里**根本没有 `ws://`**。
→ 提示补上 `http://`。

#### 🟡 ⑥ `ERR_TIMEOUT` 常量两侧各写一份

`protocol.js` 有 `ERR_TIMEOUT = "timeout"`，`protocol.py` 没有 ——
`extension_backend` 用裸字面量比较。这条链路决定"超时要不要禁止换后端重试"
（重复执行的风险），改一边另一边不会跟着动。
→ `protocol.py` 补同名常量，插件侧改用它。判据同步更新为
**同时接受字面量与常量**（否则一改常量就误报"识别逻辑不见了"）。

#### 结果

`regression/run_all.py` → **295/295，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.31 → 2.1.32。

### v2.1.31（2026-09-16）

**按 CodeRabbit 第三十二轮审查修复**（6 条，逐条核实后全部为真）。

> ⚠️ 这轮开始时我**只看到 4 条**：14:09 那条 review 里另有一块
> `Duplicate comments (2)` 折叠区，我第一次拉取只取了每线程的**第一条**评论，
> 于是漏了那 2 条。教训：拉审查意见要按**线程最后一条评论**排序，
> 并展开所有折叠区。

#### 🔴 ① 检查器会因为一个缺键而整组中断（5 处裸索引）

`exm["permissions"]` / `man["author"]` / `exm["background"]["service_worker"]`
这类**直接索引**，一旦 manifest 缺键或被改名就抛 `KeyError` ——
**整个检查中断**，后面所有段落都不执行，报告上只剩一条笼统失败，
完全看不出缺的是哪个键。

→ 全部改 `.get()` 安全取值，并且**每处只让自己的断言失败**，信息明确。
顺带把 CR 没点到的 3 处（`man["version"]` / `man["plugin_id"]`×2）一并修掉 ——
同一个风险，不修等于留着。

**实测**：删掉 `permissions` / `host_permissions` / `author` / `icon` /
`background` 五种键，每次都**只有自己那条**失败（各 1 FAIL），
`KeyError` 数量为 0。

#### 🟠 ② D5 查不出「已被跟踪」的依赖产物

D5 原来在检查前**整个排除** `node_modules` 目录。但 `.gitignore`
拦不住**已经跟踪**的文件（曾 `git add -f`，或先提交后再加 ignore），
所以已提交的依赖产物能稳稳通过检查。

→ 判据从"磁盘上有没有"改成"**会不会被提交**"：用 `git ls-files` 拿
**跟踪清单**再判。没有 git 时降级为文件系统扫描并记 WARN（说明覆盖不完整）。

**实测**：干净仓库 → PASS；`git add -f` 一个
`regression/js/node_modules/dep/index.js` → **D5 立刻报红**，修之前查不出来。

#### 🟡 ③ `callgraph` 的调用扫描漏了嵌套类

赋值扫描排除了 `_nested_nodes`，**调用扫描没有** —— 嵌套类里的
`self.method()` 会按**外层类**的成员去查，明明定义在嵌套类里也报"未定义"。

→ 调用扫描一并排除。**实测**：注入一个带嵌套类的类，
修复前报 `_NestedProbeOuter.self._inner_only() 未定义`（误报），修复后通过。

#### 🟡 ④ `contract` 不认异步 `_render()`

`_render()` 将来若改成 `async def`，AST 只认 `FunctionDef` 会**静默找不到**，
字段提取返回空 → F1 契约校验**变成空转**（看起来还是 PASS）。
→ 同时接受 `ast.AsyncFunctionDef`。

#### 🟡 ⑤ `wiring` 的自检夹具守的是**副本**，不是真逻辑

G1 的自检夹具内联了一份 `_scan()` —— 它和真扫描器**已经漂移了**
（夹具用 `code[m.end():...]`，真逻辑改成了局部变量 `after`）。
于是自检永远绿，真检查坏了也发现不了。

→ 抽出共享的 `_strip_js_noise()` / `_scan_naked_state()`，
**夹具与 G1 都调用同一个函数**。
**实测**：把共享扫描器的模板串处理改坏，夹具**立刻报红**（修之前照样绿）。

#### 🟡 ⑥ `regression/README.md` 的 checks 清单漏了 6 个模块

漏了 `claims` / `spec_compliance` / `vlm_describe` / `lost_features` /
`timeout_semantics` / `execjs_gates`。

→ 补全，**并新增守卫 G1**：README 的清单必须覆盖 `checks/__init__.py`
里登记的所有模块（登记表是唯一事实来源）。
**实测**：删掉任意一行 → G1 报红并精确指出缺哪个。（这条漂了很久没人发现，
就是因为没有任何检查盯着它。）

#### 结果

`regression/run_all.py` → **295/295，16 组全绿**
（1 个 WARN 是"工作副本非 git 仓库"时的预期降级提示）。
版本 2.1.30 → 2.1.31。

### v2.1.30（2026-09-16）

**按 CodeRabbit 第三十一轮审查修复**（6 条 actionable，逐条对当前代码核实后
全部确认为真实问题）。

#### 🔴 ① 执行 JS 会被 CSP 挡掉（USER_SCRIPT world）

`browser_script` 走 `chrome.userScripts` API，而 **USER_SCRIPT world 的 CSP
默认沿用 content script 那一套 —— 它禁止动态代码执行**（eval / new Function）。
而我们的 `execJs` 包装器**正是用 eval / new Function 跑用户脚本**，
于是会抛：

```
EvalError: Refused to evaluate a string as JavaScript because
'unsafe-eval' is not an allowed source of script in the following
Content Security Policy directive…
```

**这条极难自查**：扩展能装、能连、读页面/点击/截图全都正常，
**只有"执行 JS"这一个能力悄悄不可用**，报错还是浏览器原生文案。

→ 在 `ensureUserScripts()` 里加 `chrome.userScripts.configureWorld({csp: ...})`，
放行 `'unsafe-eval'`（以及 `'wasm-unsafe-eval'`、`blob:`）；
**不放行** `unsafe-inline` / 远端源 —— 只解决"动态执行"，不扩大攻击面。
被 CSP 挡下时给一句能照做的提示，而不是丢原生报错。

#### 🟠 ② 端口不校验 → 拼出非法 URL

`buildWsUrl` 不校验端口值域时，`-1` / `70000` / `abc` 会拼出
`ws://127.0.0.1:-1/...` 这种**非法 URL**，`new WebSocket()` 抛 "Invalid URL" ——
**用户完全看不出是端口填错了**。

→ 校验必须落在 1~65535 的整数，并给一句"去扩展面板检查端口"的提示。
顺带修：纯空白（`"  "`）应视为"没填"回落默认端口，而不是被当成非法值。

#### 🟡 ③ 其余修复（4 条，都是检查自己的问题）

- **`timeout_semantics` 的 B5 是重言式** —— 我上一轮写的
  `main.index("indeterminate") != main.index("declined")` 对两个不同字符串
  **永远为真**，等于没测。→ 改用 **AST** 找 `_call` 里真正的两个分支，
  确认字段不同、**且各自都直接 return**（新增 B6）。
- **`static_audit` 的 D 段用 `src()`** —— 文件被删/改名时抛
  `FileNotFoundError`，**整个 D 段中断**（后面全都"没跑"，报告上只剩一条异常）。
  → 改用 `src_safe`，并把"文件读不到"记成明确 FAIL。
- **`src_safe` 只该吞 `FileNotFoundError`** —— 原来吞所有 `OSError`，
  会把**权限错误/编码错误**也变成空串，于是检查拿空串去断言，
  把"读不了文件"伪装成"文件内容不对"。→ 收窄捕获范围。
- **`tool_merge` 的 C8b 会静默跳过** —— 探测脚本缺失时**什么都不报告**，
  套件照样通过（"通过但没执行"）。→ 脚本缺失记 FAIL（回归不完整），
  node 不在记 warning（环境问题）；顺带把裸 `"node"` 改成解析出的路径。

#### 新增常驻检查 `execjs_gates`（12 项）

守住 ① ② 两道关口 —— 它们的共同特点是**坏了也不报错，只是那个能力没了**。
结构断言之外带**反向自检**（C1/C2/C3：把关口拆掉，判据必须能发现）。

⚠️ 写这个检查时被自己抓到两个错：注释里写了"不含 `unsafe-inline`"
导致全文匹配误报（→ 只看 CSP 字符串字面量）；以及
`'wasm-unsafe-eval'` **包含** `unsafe-eval` 子串，
用 `"unsafe-eval" in cap` 判的话，真正的 `'unsafe-eval'` 被删掉也照样通过
（→ 精确匹配带引号的独立关键字）。**C2 反向自检正是因此才红起来的**。

#### 结果

`regression/run_all.py` → **294/294，16 组全绿**。
版本 2.1.29 → 2.1.30。

### v2.1.29（2026-09-16）

**按 CodeRabbit 新一轮审查修复**（共 20 条未解决线程，逐条对当前代码核实后
修复 8 项，其余 12 项为过期/误报或按需求保留，理由见下）。

#### 🔴 页面操作超时不再"可重试"（最重要的一项）

`callContent` 的 `Promise.race` 超时只是**本地不再等待**，
**并不能取消**已经发出去的操作 —— 慢点击/慢输入很可能在超时之后才真正完成。
而插件侧原来靠 `"超时" in msg` **文案匹配**来判定"结果不确定、禁止换后端重试"：
只要改一下提示文字（或换语言），这条安全逻辑就**静默失效**，
退化成"同一个点击被执行两次"。

→ 改成**显式错误类别**，一路透传到底：

```
shared.js          超时抛 Error，err.code = ERR_TIMEOUT
background.js      sendResult(..., e.code)     → WS 消息带 error_code
protocol.py        BridgeResult.error_code
bridge.py          BridgeError.err_code
extension_backend  err_code == "timeout" → OpResult.indeterminate_result
main.py            明说"可能已生效"，**不换后端重试**
```

文案匹配**保留为兜底**（兼容还没上报 `error_code` 的旧版扩展）。
新增常驻检查 **`timeout_semantics`（14 项）** 盯住整条链路 ——
4 个文件、3 种语言，任何一环断掉都会静默退化成"重复执行"。
反向验证：拆透传 → A6 FAIL；后端不识别类别 → A7/B2/B4 FAIL；
主插件不看 `indeterminate` → A8/A9/B5 FAIL；JS 不标记 → A2 FAIL。

#### 🟠 浏览器版本号与实际不符（用户装完会直接加载失败）

`browser-bridge/manifest.json` 的 `minimum_chrome_version` 早已从 120 提到
**135**，而 `setup_guide` 还在告诉用户"Chrome 120+ 可以" ——
用户在 128 上照着装，浏览器**直接拒绝加载扩展**，且失败提示与版本无关，
根本无从排查。

→ 版本号改为 135，并说明 120~134 会怎样、怎么自救。
**并补上一直缺失的检查 R9b**：`compatibility_report()` 里声明的 Chrome 版本
必须与 manifest 一致。（这条漂了十几轮才被发现，就是因为**没有任何检查盯着它**。）

#### 🟡 其余修复

- **`vlm_describe` A12 判据写成了 `or`** —— 只漏进**一项**（`HeadlessBackend`）
  也照样 PASS。改成独立禁止项清单 + `_leaks`，单项泄漏现在能抓到。
- **`vlm_describe` / `lost_features` 用裸 `["python3", ...]`** →
  改用 `sys.executable`（套件用别的解释器启动时，探针会落到另一套环境上）。
- **`content_dom` 用裸 `["node", ...]`** → 改用 `shutil.which("node")` 解析出的路径。
  原写法给子进程换了 env，裸名字会在**子进程里重新查 PATH**，
  Homebrew(Apple Silicon) / nvm 装的 node 不在那个 PATH 里 → FileNotFoundError，
  整个检查报 FAIL（是环境问题，不是产品问题）。
- **下载后未检查"发送"是否成功** —— 文件在本地、但用户没收到时，
  仍然回一句"📤 已发送给用户"。现在用 `_send_file` 的返回值区分，
  失败就明说"没能发出"。
- **`op_timeout_ratio` 的合法性校验嵌套太深** —— 读不到框架超时时，
  非法值（如 5.0）会原样留在 `self.op_timeout_ratio` 上，
  `browser_debug` 显示 5.0 而实际用兜底 0.8，**报告与现实对不上**。
  → 校验提到 `fw > 0` 之前，非法即改回 0.8。
- **`_send_chromium`（上轮新增的能力）同样改用 `sys.executable`**。

#### 按需求保留 / 判定为误报的 12 项

- **`upload_allow_any_path` 保持 `true`**（安全审查建议改 `false`）——
  本插件定位是"给 bot 完整浏览器能力"，上传任意本机文件是**预期功能**；
  这是有意的产品决定，README 里已写清理由与收紧方法。
- **`upload_max_bytes` 默认 256MB 不变**（建议降到 32MB）——
  审查意见基于"单条消息传整个文件"的旧实现；**分块流式上传早已实现**
  （审查给的两个选项之一），单帧恒定 ~340KB，实测 100MiB 通过、
  峰值内存 ≈1× 文件大小。已无需降级。
- **`extension_backend` 的 `display`** —— 审查说 `BrowserBridge.info` 是方法、
  当前代码会 `AttributeError`；实际它是 **`@property`**，当前写法正确，
  照审查建议改反而多绕一层。已实测两种写法（见提交说明）。
- `file_hygiene` 的 `dont_write_bytecode`、`tool_merge`/`spec_compliance`/
  `static_audit` 的 `src_safe` 守卫、`bridge_e2e` 的 node 版本门禁、
  `content_dom` 的 U5 空结果判定 —— **均已在更早的提交中修好**，
  审查基于旧快照（`outdated=true`）。

#### 🐛 顺手抓到一个「不稳定检查」：D1 判据错了

推送前连跑两次，第二次挂了 —— 追下去发现 `D1 无编译产物 / 日志 / 系统文件`
**判据本身有问题**：它扫的是**文件系统**，而 `data/log.log` 是
**框架导入插件时自己写的运行日志**（`.gitignore` 里早就排除了，
注释还写着"导入插件时会自动生成"）。

也就是说：**用户只要正常用过一次插件，这条检查就必然误报**
（而这不是产品问题）。原来一直没暴露，是因为我每次跑之前都手动清了它。

→ 判据改成"**会不会被提交**"：已声明为运行期产物的路径（`data/log.log`）
不再判红，同时**新增 D1b** 反向保护 —— 白名单里的路径**必须**真的被
`.gitignore` 覆盖，否则就变成"用白名单掩盖漏提交"。
反向验证：塞一个未被忽略的 `stray_debug.log` / `sub/foo.pyc` → D1 FAIL；
把能覆盖它的 gitignore 规则撤掉 → D1b FAIL。

现在**连跑 4 次（不清理）稳定 281/281**。

#### 结果

`regression/run_all.py` → **281/281，15 组全绿，连跑 4 次一致**。
版本 2.1.28 → 2.1.29。

### v2.1.28（2026-09-16）

**恢复 v2.1.0 重写时丢掉的另外三样能力**（逐个对照原版扫出来的）：

- 🔴 **cookie 目录自动加载**（原版 `_load_cookies`）——
  启动时把 `data/files/cookie/*.json` 全部灌进浏览器，重装/换机器/profile
  变化之后登录态还能找回来。丢之后 `data/files/cookie/` 成了**死目录**
  （`.gitignore` 里还留着它，但没有任何代码去读）。
  → 恢复为独立模块 `cookies.py`：兼容两种格式（裸数组 / `{"cookies":[...]}`）、
  自动转换 `sameSite` 与 `expirationDate`、**坏文件只跳过它不连累其它站点**、
  目录不存在自动创建、失败**不影响浏览器启动**。新增 `cookies_dir` /
  `load_cookies_on_start` 配置。
- 🔴 **自动下载内置 Chromium**（原版 `_download_chromium`）——
  启动回退的**第 4 级**：所有浏览器来源都起不来时自动
  `playwright install chromium`。丢之后只剩一句"请手动安装"的提示，
  **而 README 一直在承诺"全部失败会自动下载内置 Chromium"** ——
  **文档说有、代码没有**。→ 按原版恢复（带超时保护、失败给出手动命令），
  新增 `auto_download_browser` / `auto_download_timeout` 配置。
- **`browser_check_vlm` 工具** —— VLM 配置的自查入口。
  正好是刚恢复的截图描述功能最需要的排障工具（不然用户遇到"没描述"只能翻日志）。
  → 恢复并加强：直接指出**"模型配错组"**这个最常见的坑。

**新增常驻检查 `lost_features`（19 项）—— 守这三样别再丢第二次**：
结构（模块在不在、**接线在不在**、配置项、README 与代码是否一致）+
行为（真跑 cookie 加载：两种格式、坏文件隔离、sameSite 映射、
`expirationDate` 转换、目录不存在、context 为 None）。
反向验证：去掉接线 → A2 FAIL；删掉下载实现 → A5/A6 FAIL；删掉 `cookies.py`
→ A1 + B 段全 FAIL。

**顺带修一个检查误判**：`D3 无运行时数据目录` 原来是"路径里含 cookie 就报"，
把新模块 `cookies.py` 误伤了。→ 改为只在**路径片段**（`/cookie/`）上匹配，
实测真实数据目录仍能被抓到。

### v2.1.27（2026-09-16）

**恢复被弄丢的能力：截图 → VLM 描述（让 bot 能"看到"页面）**

- 🔴 **这个能力在原版 `headless_browser` 里是有的，合并时被我整体弄丢了** ——
  `grep vlm` 在本插件里一个字都没有。而**当时的套件完全发现不了**：
  缺功能不是"报错"，是"静默没有"。
- **为什么它重要**：插件能给**用户**发图，但 **bot 自己看不到图** ——
  工具结果是以 `role:"tool"` 的**文本**进模型的（框架
  `ToolResult.assemble_result()` 只把附件转成路径文本，图片不会成为
  多模态内容）。所以 bot 想"看到"页面，只能靠 VLM 把图转成描述。

**实现**（新增 `vlm.py`）：

- **模型三级回退**：
  1. 配置里的 `vlm_model`（显式指定时）
  2. **KiraAI 模型设置里的默认 VLM**（`provider_mgr.get_default_vlm()`）
     —— **配置留空就用这个，这是默认行为**
  3. 当前默认 LLM（如果它支持视觉）
- **是否描述由模型每次自己决定**：`browser_screenshot` 新增 `describe`
  参数（`describe=false` → 只截图不描述）。默认取插件配置
  `auto_describe_screenshot`（默认开）。「要不要看图」应该由模型按当前
  任务决定 —— 有时它只想把图发给用户。
- **两个后端都能用**：VLM 调用发生在**插件进程**里，跟图是扩展拍的还是
  无头拍的**无关**，所以不需要各写一套。
- **容错**：拿不到模型 / 超时 / 文件不在 → 返回空描述，**不让截图本身失败**
  （图照样保存、照样发给用户，只是这次 bot 没拿到描述）。

**新增配置项**（4 个）：`auto_describe_screenshot` / `vlm_model` /
`vlm_describe_prompt` / `vlm_timeout`。

**新增常驻检查 `vlm_describe`（21 项）——目的是防止它再次被弄丢**：
- 结构：`vlm.py` 在不在、三级回退在不在、截图工具**真的调用了它**、
  `describe` 参数在不在、4 个配置项齐不齐。
- 行为：用**假的 VLM 客户端真跑一遍**（不需要真模型），验证
  ①留空→用框架默认 VLM ②配置了→优先用它 ③没有 VLM→空串不抛
  ④超时→空串不抛 ⑤文件不在→空串不抛 ⑥视觉能力判定只排除明确的非视觉模型。
- **反向验证**：删掉 `vlm.py` → 5 条立即 FAIL；把调用点去掉 → A5 立即 FAIL。
  （也就是说，**这次如果再被弄丢，套件会立刻报红**。）

**⚠️ 关于"VLM 冲突"（早期版本踩过，这次也处理了）**：
框架要求用于描述的模型必须是 **`LLMModelClient`**，也就是
**放在「大语言模型」组里的视觉模型** —— **不能放到「图像」组**，
哪怕它本身支持视觉也不行。

框架的 `get_llm_client()` / `get_default_vlm()` 内部会做类型检查
（类型不对就当拿不到），所以**不会用错模型**；但代价是**静默返回 None**，
用户只看到"没有描述"、不知道原因。→ 本插件把原因**说清楚**：
区分"压根没配"和"配了但类型不对"，日志里直接给出怎么改，
工具返回里也写明这几种常见原因。

**说明**：原版那套"截图发送方式"的独立配置项**没有照搬** ——
当前 `browser_screenshot` 已经有 `send` 参数表达同一件事，再加一个
配置项只会让两处互相打架；这次只补"描述"这一层。

### v2.1.26（2026-09-16）

**按 CodeRabbit 第二十轮审查修复 10 项**（含 2 个只读模式失效）：

- 🔴 **只读模式下"写工具"根本没被摘掉**：`WRITE_TOOL_NAMES` 里写的是三个**早就被合并掉的旧工具名**
  （分别是点击 / 输入 / 滚动的旧名字，现在统一叫 `browser_interact`）——
  工具合并之后它们已经不存在了。
  而真正的写工具（`browser_interact` / `browser_script` / `browser_cookie`
  / `browser_file`）**一个都不在名单里**。
  → 用户开了只读模式，AI 照样能点击、输入、执行 JS。
  → 名单改为真实注册的 5 个写工具；并把原来**单向**的检查（只验"名单里的
  名字存在"）改成**双向**：A12a 名单里的必须是真实工具，**A12b 所有会改
  状态的工具必须都在名单里**（后半条才是能抓住这个 bug 的那一半）。
- 🔴 **`browser_script` 没标成写操作**：执行任意 JS 能干任何事，但不传
  `for_write=True` → **只读模式对它完全无效**，也不走域名白名单校验。
  → 补上 `for_write=True`。
- **钳制逻辑因为绝对导入而静默失效**：`from backends.extension_backend import ...`
  是绝对导入，而插件是以**包**的形式加载的（`<pkg>.main`），此时 `backends`
  不是顶层模块 → 导入失败 → 落进 `except` → **上传上限钳制形同虚设**。
  → 改用文件头已经导入好的 `ExtensionBackend`。
- **发送文件"假成功"**：下载流程之后直接 `_send_file` 并回"已发送给用户"，
  但文件可能根本不在（路径问题/上一步没走到）。→ 发送前确认文件存在，
  不在就明确说"**没有发送**"。
- **`cookie_get` 里同一句校验连写三遍**（我删过一次，重写那段时又带回来了）
  → 去掉，并加守卫 **C16n**。

**测试可信度 4 项**：
- **U5 / C5a 的"少跑不留痕"**：U5 输出为空列表时循环一次都不执行 →
  该用例**静默变成"没有检查"**；C5a 找不到标记时 `return` →
  **后面的 C5b~C9 全都不执行**。→ 两处都改成"记失败但继续跑"。
- **B2.12 依赖真实 `localhost` 解析** → 解析结果随环境而变（有的沙箱把一切
  解析成代理 fake-IP）。→ 换成**可控的解析器**，用 `internal.example → 10.0.0.5`
  这类固定映射来验，不依赖环境。
- **U9 / 上传流用例的"因错误的原因通过"**：`upload_begin` 失败时会话压根不存在，
  后面 `upload_chunk` 被拒是"没有会话"而不是"顺序/上限校验生效"。
  → 断言先确认 `begin` 成功，再判后续拒绝。
- **测试桩读文件缺保护**：`src()` 在文件缺失时抛异常 → **整个检查组中断**，
  后面的用例全不执行。→ 新增 `src_safe()` 返回空串，让检查跑完并各自记 FAIL
  （实测：删掉 `__init__.py` 后仍有 19 项跑完、精确报出 2 条失败，
  而不是整组崩掉）。

### v2.1.25（2026-09-16）

**按 KiraAI 最新规范核对交付形态**（对照上游 `KiraAI-Dev/KiraAI` **v2.34.4**）：

**一、拿最新框架真跑了一遍**（不是"看着像对"）：

| 核对项 | 结果 |
|---|---|
| 框架符号（`BasePlugin`/`PageMenu`/`PluginPage`/`on`/`register`/`LLMRequest`/消息元素/`get_data_path`） | 全部可导入 |
| 插件入口类 | `BrowserPlugin` 导入成功，确实继承 `BasePlugin` |
| 注册进框架的内容 | **钩子 2 / 工具 12 / WS 1 / API 3 / 页面 1** |
| 钩子被框架真触发（`(event, request, tag_set)` 三参） | 签名匹配，无 `TypeError` |
| `schema.json` 用框架的 `build_fields()` 解析 | 37 个字段全部解析通过 |

**二、回答一个关键问题：会不会变成两个插件？——不会。**

- `manifest.plugin_id` **仍是 `headless_browser`**（沿用原值），
  框架注册后组件表里**只有一条**：`['headless_browser']`。
- 用户是**覆盖原插件目录**，KiraAI 侧看到的还是同一个插件。
- `browser-bridge/` 是**浏览器扩展**（装进 Chrome），跟 KiraAI 的插件系统无关，
  不是第二个插件。
- 唯一"变多"的地方反过来了：**工具从 33 个减到 12 个**
  （`browser_interact` 用 `action` 合并了 click/type/hover/键盘/鼠标）。

**三、新增一个常驻检查**（`regression/checks/spec_compliance.py`，21 项）：
把上面这些**不依赖框架源码**的部分固化成回归项 —— 包结构（`__init__.py`
旁边的 `manifest.json`，框架靠它定位 `plugin_id`）、manifest 字段与
**identity 必须是原插件 id**、入口类继承 `BasePlugin` 并实现两个 async
抽象方法、注册装饰器用法、**路由路径与扩展侧一致**、随包资源齐全。

反向验证：改 `plugin_id` → B2/E1 立即 FAIL；删 icon → B3 FAIL；
把扩展的 WS 路径写错 → E1 FAIL。

### v2.1.24（2026-09-16）

**按 CodeRabbit 第十九轮审查修复 4 项**（含 1 个"假成功"）：

- 🔴 **上传可能"假报成功"**（尤其是大文件）：上传目标是**发起时**解析的，
  而 256MB 要传十几秒 —— 这段时间里 SPA 完全可能重新渲染，
  **旧 input 已经从文档里摘掉**。往脱离文档的元素上写 `el.files`
  **不会有任何效果**（表单里不会出现这个文件，用户点提交什么都没传上去），
  而过去这里照样 `return ok: true`。
  → 收尾时**重新解析**选择器、校验元素 `isConnected` 且仍是 `file` 输入框，
  并在赋值后再确认 `files` 真的挂上了。
  用 jsdom 真跑三种情况验证：正常 → 成功；重渲染但元素仍在 → 成功且挂到
  **新**元素上；元素被移除 → **必须失败**。
  反向验证：还原成旧写法 → U5 两条立即 FAIL（且能看到 `ok:true` 但 `files=0`）。
- **popup 读 `sendMessage` 结果前没判空**：background 没返回内容时它
  resolve 成 `undefined`（**不是 reject**），此时读 `r.ok` 会抛 TypeError，
  界面就永远停在"连接中…/正在测试…"。→ 两处都先判空，
  复用 `_renderBackendUnavailable()`。

**其余 2 项**：
- **`check_write_targets` 隐式依赖 `local_access` 默认值**：它当前没有被调用，
  但将来接上就会**绕过用户在配置里设的开关**（因为 `check_url` 默认 True）。
  → 显式接收并转发 `local_access`。新增守卫 **C6g**：扫出所有封装
  `check_url` 却没转发该参数的函数（反向验证：去掉转发 → 立即 FAIL）。
- **测试桩 `path_utils` 用固定的 `/tmp/kira_data`** → 并发跑或上次崩溃残留会
  两轮共用同一份目录。→ 改为每进程唯一的 `mkdtemp`。
  ⚠️ 这条上一轮**声称修过但根本没落盘**，这次补上并实测确认。

**新增守卫 C16m**：扫出 popup 里读取 `sendMessage` 结果但没先判空的地方。
（写这条时又踩到同一个坑：注释里也写着 `r.ok`，不剥注释会把自己写的说明
当成未保护的代码 —— 已改成先剥注释再扫。）

### v2.1.23（2026-09-16）

**本机 / 内网地址改为默认可访问**（产品决策 + 配套的开关与文档）：

- **`http://127.0.0.1:5267/overview` 这类地址，现在默认可访问。**
  本插件的定位就是**给 AI 当浏览器用** —— `localhost:3000` 这类本地开发
  服务器和 KiraAI 自己的面板都是**正常的工作目标**，不是攻击面。
  默认拦掉会让"帮我看看我本地这个页面"直接不可用，而用户只会以为插件坏了。
- 新增配置项 **`local_access`（「允许访问本机 / 内网」，默认开）**。
  想收紧的人关掉即可 —— 那时回环 / 私有 / 链路本地（含云元数据端点
  `169.254.169.254`）一律拒绝，公网站点不受影响。
- **同时修掉一个会让开关失效的坑**：默认黑名单里原本就有
  `127.0.0.1` 和 `localhost`，而**黑名单优先级最高** ——
  留着它们的话，即使 `local_access` 开着，本机地址照样被拦。
  → 默认黑名单改为 `["*.bank*", "*.pay*"]`，本机是否允许**统一由开关决定**。
  新增守卫 **C6e / C6f**（反向验证：把 `127.0.0.1` 放回默认黑名单 → 立即 FAIL）。
- **代码里那段"无条件拒绝本机"的原始理由已经不成立**：它担心
  `[::1]` / `2130706433` / `0.0.0.0` 绕过黑名单，但 `is_local_host()`
  现在已覆盖这些等价写法 —— 要拦就拦得住，不需要靠无条件拒绝兜底。
- **文档**：新增 [SECURITY_DESIGN.md](SECURITY_DESIGN.md)，逐条说明
  "哪些看起来可疑的行为是**有意设计**"（本机访问、任意路径上传、
  令牌放 query、无头后端禁用扩展、以及已知未解决的 TOCTOU 局限），
  并在 `check_url` 的注释里指向它 —— 目的是让自动审查**不要把这些
  报成缺陷**。D4 的文件清点规则相应加了白名单（仍是白名单，
  不是放开"允许任意 md"）。

### v2.1.22（2026-09-15）

**按 CodeRabbit 第十八轮审查修复 4 项**（含 1 个 SSRF 漏洞）：

- 🔴 **SSRF：内网地址完全没拦**。`is_local_host` 原本只判
  `is_loopback or is_unspecified`，于是这些都**直接放行**：
  - `10.0.0.5` / `192.168.1.1` / `172.16.0.1`（内网）
  - **`169.254.169.254`** —— 云厂商的**实例元数据端点**，
    拿到它就能读走云主机的临时凭据，是 SSRF 的典型目标
  - `fe80::1`（链路本地）、`::ffff:10.0.0.1`（v4-mapped 内网）
  → 改为按"内部地址"整体判定（回环 / 未指定 / 私有 / 链路本地 /
  保留段 / 组播），并处理 v4-mapped 与 6to4/Teredo 内嵌地址。
- 🔴 **只看字符串，不看解析结果**：`internal.corp` / `db.local` 这类
  主机名本身"不像本机"，但**解析出来可能就是 10.x**。
  → 新增 `resolved_url_is_internal()`：真的 `getaddrinfo` 一次，
  解析到内网就拒绝（在 `check_url` 里与字符串判定一起生效）。
  ⚠️ **如实说明局限**：校验与真正连接之间仍有 TOCTOU 窗口
  （DNS rebinding）。要彻底解决必须在**连接时**校验实际使用的 IP，
  这一层只能挡住"明显的内网目标"。已写进代码注释，不假装完备。
- ⚠️ **修这条时踩到的坑（差点造成大面积误伤）**：Python 把
  `198.18.0.0/15`（RFC 2544 基准测试段）也算作 `is_private`，
  而 **Clash / mihomo 这类代理默认就用它做 fake-IP**。
  一开始连 `example.com` 都被拒 —— 代理环境下**所有站点全废**。
  → 显式放行该段，并加了"公网地址不误判"的对照用例。
- **`update_cookies({}, ...)` 的 no-op 空转循环**（我删过一次，
  改别处时又带回来了）：传空 dict、吞异常，什么也不写入，
  却让人以为"这里处理了 cookie"。→ 删除，并加守卫 **C16l**
  （扫出任何传空 dict 的 `update_cookies`）。

**测试可信度 2 项**：
- **`C16k` 的断言太弱**：原判据是"存在 `= sendRaw(...)` 的赋值
  且出现了 `state.probe`" —— 但**赋值了却不用它做条件**照样能通过
  （`const s = sendRaw(...); if (true) probe()`）。
  → 改成**结构判定**：要求那个标识符真的出现在 `state.probe()`
  之前的条件里；并加了**变异夹具**（有守卫 → 必过；赋值但无守卫 →
  必须判不过；完全无守卫 → 必须判不过）。
  写夹具时还发现：不剥注释会被自己写的说明文字误判（假红）。
- **`contract.py` 的 upload 夹具用 `mkdtemp`**，落在受管理的
  `TemporaryDirectory` 之外 → 永远不会被清理。→ 移入同一个根之下。

**新增用例**：`B2.10`（内网/元数据地址必拦）、`B2.11`（公网地址与
代理 fake-IP 段不得误判）、`B2.12`（主机名解析到内网会被拦）。
三个都做了反向验证。

### v2.1.21（2026-09-15）

**按 CodeRabbit 第十七轮审查修复 6 项**（含 1 个"假成功"+ 3 处测试可信度）：

- 🔴 **链路测试会假报"正常"**：收到服务端 `PING` 后，原来的代码**无论
  PONG 有没有发出去**都会调 `state.probe()` —— 而收到 ping 只说明"我们能收"，
  `sendRaw` 返回 `false` 说明 socket 只能收不能发，链路其实是不通的。
  结果是弹窗显示"链路正常"，实际连命令都发不出去。
  → 只有 `sendRaw(...)` 返回真时才认定往返成立。新增守卫 **C16k**。
- **桩与真实 Playwright 不一致**：`regression/stubs` 里的 `mouse.down/up`
  只收 `button`，而 `HeadlessBackend.mouse_click` 会传 `click_count` ——
  桩直接 `TypeError`，**双击那条路在测试里根本走不到**。
  → 补上 `click_count` 参数。

**测试可信度 3 项**（都是"检查本身不够硬"）：
- **U4 / C8b 不判退出码**：脚本崩了却恰好留下能解析的输出时，逐项断言会
  "少报"（少报 = 漏检），甚至一项都不报。→ 都改成**先判 `returncode`**，
  并且要求结果完整（U4 非空、C8b 覆盖到必要场景）。
- **`cred_mode.mjs` 是"注入式"验证**：它把 `isHttps` 作为变量**直接喂进**
  凭据表达式 —— 那样只验证了三元表达式本身，**生产里 `isHttps` 是怎么算出来的
  完全没被覆盖**。把 `url.startsWith("https://")` 改成恒真（HTTP 也带 Cookie）
  照样通过。→ 改成**从 capabilities.js 抽出真实的 `isHttps` 定义行**，
  用真实 URL 驱动执行，并加大小写不敏感与本机 HTTP 两个用例。
  反向验证：`isHttps = true` → 立即 FAIL。
- **`upload_sweep.mjs` 只做"源码里有没有 setInterval"的间接检查** →
  改成用**可控定时器**（替掉 `setInterval` 与 `Date.now`）真跑回收：
  推进时钟到 10 分钟空闲后，被遗弃的会话必须收块失败、
  而"一直有活动"的慢速会话必须活着。另加"清理器随会话启停"一条。
  反向验证：判据改回 `created` → 慢速会话那条 FAIL；删掉 sweeper →
  遗弃会话那条 FAIL。

### v2.1.20（2026-09-15）

**按 CodeRabbit 第十六轮审查修复 9 项**（含 1 个内存泄漏、1 个权限收紧）：

- 🔴 **被遗弃的上传会话会一直占着内存**：上传到一半时如果插件崩溃 /
  连接断开 / 用户换页面，`upload_finish` 永远不来，那个会话连同已收到的
  分块（可能几百 MB）就**一直挂在页面里** —— 而回收只发生在
  "下次 `uploadBegin` 时顺手清"，下次上传可能是几小时之后。
  → 加了**定期清理器**（有活跃会话时启动、空了就停），
  并且回收判据用 **`lastActive`**（每次收块刷新）而不是 `created` ——
  否则一个传得很慢的**大文件**会在传输途中被误回收。
- **令牌落盘有一个"权限空窗"**：原来是先 `write_text` 写最终文件、
  再 `chmod(0o600)`。在写入与 chmod 之间，文件是**默认权限**
  （通常 0644，同机其他用户可读）；中途被杀掉时权限永远补不上。
  → 改成：目录建 `0o700` → 令牌写进同目录下 `mkstemp` 出来的临时文件
  （**创建时**就 `0o600`）→ `os.replace` **原子替换**。
  实测：文件 0o600、目录 0o700、内容一致、无临时残留。
- **`_v` 未初始化**（测试脚本）：`subprocess.run` 本身抛异常（超时/权限）时，
  下面的错误信息 f-string 会读未定义的 `_v` → `NameError`，
  把"node 版本判不出来"变成一句与版本无关的崩溃。→ 先给默认值。

**回归套件 5 项**：
- **`A1` 会误报"存起来的可调用"**：`self._sink = fn` 之后再 `self._sink()`
  是合法写法，但 A1 只收集 `def`、不收集属性赋值 → 报"未定义"。
  误报多了这条检查就没人看了。→ 收集本类的 `self.x = ...` 赋值，
  并且**排除嵌套类**（那个类的 `self` 是它自己）。两个方向都做了反向验证。
- **`C5a` 在找不到 `export const CMD = {` 时 `IndexError`** → 异常逃出
  `run()`，整组变成一条笼统失败、后面检查全不执行。→ 先判标记存在。
- **`callgraph` 的嵌套类处理**（同上）。
- **`cred_mode.mjs` 用 `URL.pathname`** → 改 `fileURLToPath`
  （Windows 上会留下 `/C:/...`，含空格/非 ASCII 也不解码）。
- **`run_all.py` 打印的是 `HERE.parent`** 而不是检查实际用的
  `PLUGIN_DIR` → 多副本/反向验证时会把人误导到别的树。→ 打印真实值。

**新增用例 U4**（上传会话回收行为，5 项）：用 jsdom 真跑 `content.js`，
验证"慢速传输中仍能收块"、"abort 后立即失效"、"存在周期性清理器"、
"回收判据基于活动时间"。

**清理**：删掉 `content.js` 里已不再使用的 `upload_blob`
（旧的一次性上传逻辑，分块流式上线后就没人调了）。

### v2.1.19（2026-09-15）

**按 CodeRabbit 第十五轮审查修复 13 项**（含 2 个运行期崩溃、3 个"假成功"）：

- 🔴 **`mode="selector"` 会在无头后端直接崩**：`main.py` 路由时会传
  `selector=`，但 `HeadlessBackend.get_page` 的签名里**没有这个参数** ——
  调用即 `TypeError: got an unexpected keyword argument 'selector'`，
  而且是在调度层抛出的，模型只会看到一句莫名其妙的报错。
  → 补上签名与实现（与扩展后端同形状：只取该元素的文本）。
  实测：`get_page(selector="#x")` 现在返回 `content='selector-text'`。
- 🔴 **`_force_close` 会取消自己**：心跳循环在发送失败时调
  `_force_close`，而它会 `cancel()` 自己的 task —— 当前协程在下一个
  `await` 点被取消，**后面的 `_close_ws` 根本执行不到**，
  socket 就那么留着（面板显示已断开、实际连接还在）。
  → 判断 `self._heartbeat_task is asyncio.current_task()` 时不自取消。
- **扩展后端截图"假成功"**：`screenshot(full_page=True)` / `selector=`
  被**默默忽略**，照样截一张视口图并返回成功 —— 调用方以为拿到了整页/
  元素截图。→ 明确返回失败，让路由回退到无头后端。
- **`get_page` 的 selector 同理**（见上）。
- **确认通知不会消失**：`chrome.notifications.create` 用了
  `requireInteraction: true`，但只有**点击**路径会 `clear`，**超时路径不会** ——
  超时的确认一直挂在通知栏，用户过一会儿再点它还会二次响应。
  → 把清理统一收进 `settle()`（点击/超时都走它），并去掉 `resolveConfirm`
  里的重复清理。
- **`state.probe` 并发互相踩**：它是**单个**槽位，第二个测试会覆盖第一个，
  而旧探测的超时定时器仍会触发、把**新**探测的回调清掉 ——
  表现为"点了测试没反应"。→ 有探测在跑时直接拒绝。
- **合成点击不触发 `dblclick`**：`mouse_click(click_count=2)` 只派发两次
  `click`，而**合成事件**不像真实输入那样由浏览器推导出 `dblclick` ——
  双击选词/双击打开这类交互完全不会触发。→ `n>=2` 时补一个 `dblclick`。
- **README 的 Edge 版本与其它地方矛盾**（120 vs 135）→ 统一为 **135**。
- **`setup_guide.py` 有句不实说明**："无头后端可以用 `--load-extension`
  把扩展预装进去" —— 代码里**没有**这条路（启动参数反而带
  `--disable-extensions`）。→ 改正。

**回归套件 4 项**：
- **`bridge_e2e` 只判"有没有 node"**：CLIENT_JS 用到 **Node 22+** 的
  API，Node 20/21 会在跑到一半时以难懂的方式炸。→ 预先判版本，低了就跳过。
- **`.gitignore` / `file_hygiene` 的名字对不上**：实际生成的是带唯一后缀的
  `kira_ext_client_*.mjs`，而两边都在匹配旧的确切名
  `_ext_client.mjs` → 残留永远清不出来、D5 会一直报脏。
- **`claims` 要求 `cookie_get` 必须是集合里第一个元素** → 改为位置无关；
  **`upload_max_bytes` 的钳制只判"标识符出现过"**（import/注释也算）→
  改为要求真的存在夹值逻辑。反向验证：把钳制换成"只提一句" → 立即 FAIL。
- **`tool_merge` 的 C8 只做语法检查** → 新增 **C8b 行为验证**：
  把凭据表达式在 HTTP/HTTPS 下**各真跑一次**。
  ⚠️ 这条很值：把条件写反（HTTPS→omit、HTTP→include）时
  **C8 照样通过**（表达式里两个字面量都在），只有 C8b 抓得住 ——
  而那个写法会让**会话 Cookie 在明文 HTTP 上被发出去**。

### v2.1.18（2026-09-15）

**按 CodeRabbit 第十四轮审查修复 9 项**（含 2 个安全项）：

- 🔴 **多级公共后缀漏判 → 规则形同虚设**：域名主体判定靠一张**硬编码**
  的 `MULTI_TLD` 表（com.cn / co.uk / …），那种写法永远补不全 ——
  `co.za` / `com.ar` / `co.il` 都不在表里，于是 `bank.co.za` 的主体被算成
  `co.za`，`*.bank*` 这类规则**匹配不上真正的银行域**。
  → 改用维护中的 **Public Suffix List**（`publicsuffix2`，已加进
  `requirements.txt`；拿不到时退回"最后两段"并给出警告）。
  实测：`bank.co.za` / `bank.com.ar` / `bank.co.il` 现在都能命中。
- 🔴 **归一化规则时把裸 IPv6 的尾组当端口削掉**：
  `re.sub(r":\d+$")` 会把 `2001:db8::1` 削成 `2001:db8:`、`::1` 削成 `:`，
  用户填的 IPv6 屏蔽词**永远匹配不上**。
  → 只从 `hostname:port` 或 `[IPv6]:port` 剥端口，裸 IPv6 原样保留。
- **`minimum_chrome_version` 定错**：清单写的是 120，但
  `chrome.userScripts.execute` 是**从 Chrome 135 起才默认可用**的
  （查证：Chromium extensions 组的公告）。低于 135 的用户会拿到一个
  "不支持"的报错却不知道为什么。→ 清单与 README 都改为 **135**。
- **`sendChunk` 丢掉发送结果**：`sendRaw` 在 socket 已关时返回 `false`，
  而 `sendChunk` 把它丢掉了 —— 下载会一路走到 `return {ok:true}`，
  调用方以为成功，**而磁盘上的文件缺了后面所有分块**。
  → `sendChunk` 回传结果，下载处检查失败即中止并抛错。
- **带端口的完整地址会连错端口**：用户粘 `http://127.0.0.1:8000` 时，
  端口 8000 被丢弃、改用端口字段（默认 5267）——**静默连到错误的端口**。
  → 解析出显式端口并优先使用。

**回归套件 4 项**：
- **`callgraph` 的 D1 现在只筛 `str(...)` 调用**，不再对 `logger.info(...)`
  这类属性调用做无谓判定。
- **`C16e` 又会漏掉模板插值里的未声明变量**：我在 G1 修过这个问题，
  但 `static_audit.py` 里**还有一份拷贝**用的是"整个模板串删掉"的老写法 ——
  `` `${foo}` `` 里的 `foo` 一并消失。→ 同样改为保留 `${...}` 内容，
  并加了**自检夹具**（只在插值里引用未声明变量 → 必须被抓到）。
- **`tool_merge` 的 C6 只在全文里找 `chrome.userScripts.execute`** →
  限定到 `execJs` 函数体内部（别处提到不算）。
- **`tool_merge` 的 C1 对非 action 式工具直接跳过** → `browser_wait`
  丢了 `seconds` 参数这种能力丢失查不出来。→ 增加按**具名参数**的校验
  （`LEGACY_PARAMS` 表），反向验证：删掉 `seconds` → 立即 FAIL。
- **`upload_stream.mjs` 用 `URL.pathname` 拼路径** → 改为 `fileURLToPath`。

**新增用例**：`B2.8`（PSL 多级后缀）、`B2.9`（裸 IPv6 不被削端口），
两个都做了反向验证（还原成旧写法 → 立即 FAIL）。

### v2.1.17（2026-09-15）

**按 CodeRabbit 第十三轮审查修复 8 项**（含 1 个内存泄漏 + 1 个测试假绿）：

- 🔴 **`uploadFinish` 失败时泄漏页面侧会话**：原来是先 `_uploadTabs.delete()`
  再调 `upload_finish` —— 一旦失败/超时，**页面侧的 `_upSessions` 就没人清了**，
  分块一直挂着（大文件就是几百 MB 的内存泄漏），而且下次同名上传还会
  撞上残留状态。→ 改成失败时**先发 `upload_abort` 清理页面会话、再删映射**；
  成功路径才直接删（页面在 `upload_finish` 内部已自清）。
- 🔴 **测试假绿（又是同一类）**：`content_dom` 只比对脚本的 stdout 标记，
  **不检查退出码** —— 脚本崩溃前恰好打完全部成功标记时会被误判为通过。
  → 非零退出码一律先记 U0 失败，并把 U1–U3 一并置失败。
  ⚠️ 修完后反向验证**仍然是绿的**，追下去发现更深一层：
  `harness.JS_DIR` 锚在套件自身目录（`HERE/js`），**不受 `KIRA_PLUGIN_DIR` 影响**，
  于是"检查脚本从默认目录读、被测的 content.js 从指定副本读" —— 两棵树混着用。
  → `JS_DIR` 改为跟随 `PLUGIN_DIR`。修完反向验证才真正变红。
- **popup 的 connect / test / disconnect 没接住 `sendMessage` 的 reject**：
  service worker 被回收时它会 reject，弹窗会卡在"连接中…/测试中…"不回来。
  → 三个调用点都补上，并抽出 `_renderBackendUnavailable()` 与 `refresh()`
  共用同一套渲染。新增守卫 **C16j**（扫出任何没被 try 兜住的 `sendMessage`）。
- **档案新鲜度误判**：`IndexedDB` 参与了"副本是否过期"的 mtime 扫描，
  但复制档案时 `IndexedDB` **在 IGNORE 名单里、根本不搬** ——
  于是源侧 IndexedDB 一变就判定过期、整份档案白重拷一遍。
  → 从扫描路径里去掉。
- **`schema.json` 的 hint 里有过时描述**：我上一轮只用 `replace` 换了尾巴，
  留下"整个文件要放进**一条**消息…单帧必须扛得住"这种**与现状矛盾**的旧说法
  （同时又说"单帧尺寸不再是约束"）。→ 重写为准确的流式 + 页面累积说明。
- **`callgraph` 的 B1/C1/D1 没有各自 catch `SyntaxError`**：任一文件语法错误
  会让异常逃出 `run()`，整组变成一条笼统失败、后面段落全不执行。
  → 三处都按 A 段的模式单独接住并记为该段的 FAIL。
- **`claims` 只验集合名存在**：`CONFIRM_ONLY_COMMANDS` 可以是空集合，
  检查照样通过。→ 收紧为"同一声明里必须同时出现集合名与 `cookie_get`"，
  两侧都加了；顺带删掉我自己重复的一条。
- **`upload_stream.mjs` 里 `rcap` 的结论没并入 `allOk`**：只打印不判，
  "误拒了"也照样 exit 0。→ 并入 `allOk`，并补一条"上限生效时必须真的被拒"
  的正向用例。

### v2.1.16（2026-09-15）

**上传：把分块的累积从 Service Worker 挪到页面上下文 —— 内存不再放大 2.67 倍**

v2.1.15 把上传改成"分块流式"解决了帧尺寸问题，但还有个更隐蔽的
性能问题：**分块仍然攒在 MV3 的 Service Worker 里**，而 SW 恰恰是
整个扩展里最容易被系统回收的地方（回收会让上传直接断掉），
并且它的峰值 = 文件 × 1.33（base64）+ 拼接副本 ≈ **文件 × 2.67**。

改成三段式：

```
插件 ──(upload_chunk)──▶ Service Worker ──(立即转发)──▶ 内容脚本（累积）
                              ↑
                      峰值恒定为一块（~0.3MB）
```

- **SW 只做转发**：收到一块就 `callContent` 转发给页面，自己不保存任何内容。
- **页面侧（content.js）负责累积**：每块 base64 立刻解码成 `Uint8Array`
  存进会话，`upload_finish` 时才 `new Blob(chunks)` → `new File([blob])`。
- 新增 `upload_begin`（此时就把 input 解析好，避免传完才发现选择器不对）、
  `upload_chunk`（**顺序校验**，乱序会让文件损坏，宁可明确报错）、
  `upload_finish`、`upload_abort`。

**实测（Node 基线，RSS，不中途 GC）**：

| 文件 | 改造前（SW 累积） | 改造后（页面累积） |
|---|---|---|
| 64 MB | 85 MB (1.33×) | **70 MB (1.10×)** |
| 200 MB | 267 MB (1.33×) | **200 MB (1.00×)** |
| 256 MB | 341 MB (1.33×) | **261 MB (1.02×)** |

**SW 侧峰值从"随文件线性增长"变成恒定的 ~0.3MB。**

**吞吐与正确性实测**（真实 uvicorn，逐块往返）：

| 文件 | 块数 | 用时 | 吞吐 | 内容校验 |
|---|---|---|---|---|
| 32 MB | 129 | 1.6s | 19.8 MB/s | ✓ SHA-256 一致 |
| 100 MB | 402 | 5.4s | 18.6 MB/s | ✓ 一致 |
| 256 MB | 1029 | 13.3s | 19.2 MB/s | ✓ 一致 |

→ 默认上限提到 **256MB**（约 13 秒传完，内存约 1.0× 文件大小）。

**新增守卫**：
- **C16h**：SW 侧上传路径**不许出现累积/拼接**（`parts.push` / `join(` 等）。
  反向验证：加回 `st.parts.push(data)` → 立即 FAIL。
- **C16i**：累积必须实现在 `content.js`。
- **U1/U2/U3**：用 jsdom **真跑** `content.js`，从 `input.files[0]` 把内容
  读回来**逐字节比对**（1MB/5MB/20MB），并验证乱序被拒、上限为 0 时不误拒。
  ⚠️ 这个用例第一版把插件路径**写死**了 —— 反向验证时"悄悄测的还是原目录
  的文件"，检查永远通过、等于没有检查。改成读 `KIRA_PLUGIN_DIR` 后才真正生效。

### v2.1.15（2026-09-15）

**上传改为分块流式 —— 顺带发现"单帧 16MiB 硬上限"这个隐藏约束**。

问："上传上限真不能大一点吗？"

查下来发现，之前配的 32MB **本身就发不出去**：

- KiraAI 用 **uvicorn**，其 `ws_max_size` 默认 **16 MiB**，
  框架**没有覆盖**它（`webui/app.py` 的 `uvicorn.Config` 里没这个参数）。
- 实测：整条帧超过 16 MiB → 对端回 `1009 (message too big)` 并
  **关闭整个 WebSocket 连接**。也就是说一次超大上传会**把连接打断**，
  连带后面所有命令一起崩，而不只是这一次上传失败。
- 而 base64 会放大 4/3 —— 所以"一条消息"能承载的文件上限其实只有
  **~12 MiB**。之前配的 32MB、以及更早的 200MB，全都发不出去。

**修法**：把上传改成**分块流式**（和下载方向对称）——
`upload` 只建立会话拿 `upload_id`，之后每块单独一条 `upload_chunk`
消息，`upload_finish` 时才在扩展侧拼成 `File` 塞进 `input[type=file]`；
中途失败用 `upload_abort` 丢弃。

实测对比（真实 uvicorn，默认配置）：

| 文件 | 旧做法（一条消息） | 新做法（分块流式） |
|---|---|---|
| 30 MiB | ❌ `ConnectionClosedError` | ✅ 完整传输，base64 校验一致 |
| 100 MiB | ❌ `ConnectionClosedError` | ✅ 完整传输，base64 校验一致 |

**那么现在上限由什么决定？内存。** 扩展侧要攒下全部分块的 base64
才能拼出一个完整 `File`，实测堆增量 ≈ 文件大小 × 2.67：

| 文件 | 扩展侧堆增量 |
|---|---|
| 32 MB | 85 MB |
| **64 MB** | **171 MB** |
| 100 MB | 267 MB |
| 200 MB | 532 MB |

MV3 的 Service Worker 常驻内存有限，200MB 那档有被系统回收的风险。
→ 默认取 **64MB**（帧尺寸已不再是约束，内存是）。

新增守卫 **C16f**（不许把整份文件塞进单条消息）、**C16g**
（扩展侧必须真的实现分块接收/收尾/中止 —— 查**函数定义**，
不能只查名字，否则 export 名单会让它"看起来存在"）。

### v2.1.14（2026-09-15）

**按 CodeRabbit 第十二轮审查修复 14 项**（含 2 个安全问题）：

- 🔴 **上传上限只改了一半**（**我上一轮的漏改**）：我把
  `ExtensionBackend.MAX_UPLOAD_BYTES` 降到 32MB，**却没改 schema.json /
  main.py / README 的默认值** —— 它们仍是 200MB 并会一路传下去，
  硬顶形同虚设。→ 四处默认值统一为 33554432，**并且在 main.py 里
  按 `MAX_UPLOAD_BYTES` 钳制配置值**（用户调大也不会突破单条消息的极限）。
  新增守卫 **H2** 逐处核对四个默认值 + 钳制是否存在。
- 🔴 **页面操作超时可能被当成"失败"从而换后端重试**：`callContent` 的
  超时意味着"命令**可能已经在页面里执行了**，只是回执没回来"。
  原样上报成普通失败，上层会换（无头）后端重试 →
  **同一个点击/输入被做两次**。
  → 给 `OpResult` 加 `indeterminate` 标志（与 `declined` 并列的
  "终止性结果"），超时类错误一律标成不确定，上层**不再换后端**，
  而是如实告诉模型"可能已生效，请先看页面状态"。
- **无头下载：不再去写 aiohttp 的私有属性 `_cookie_jar`**：
  上一轮为了"降级到 http 时丢 cookie"，直接替换了 session 的私有字段 ——
  那是实现细节，库一升级就碎。→ 改成**遇到非 HTTPS 跳直接停下**，
  既不外泄 Cookie，也不碰私有 API。
- **`buildWsUrl` 不认 `http://` / `https://`**：面板上用户很自然会粘
  `http://127.0.0.1:5267`，不认的话前缀会整个留在主机名里 →
  拼出 `ws://http://127.0.0.1:5267:5267/...` 这种废地址。
  → 认 http/https 并分别映射到 ws/wss。
- **连接超时会关掉 socket 并重排重连**、**popup 的 refresh 捕获
  `sendMessage` reject**（service worker 被回收时它会 reject，
  不接住会不断产生 unhandled rejection 且弹窗停在旧状态）、
  **`ExtensionBackend.display` 走公开的 `info`**、
  **`op_timeout_ratio` 校验 `0<ratio<1`** 且不再被 5 秒下限顶到框架超时之上。
- **`rotate()` 的文档与代码不符**：docstring 说"世代号一变旧令牌立即失效"，
  但实际 `tv` 是 `sha256(access_token)[:16]`、**与世代号无关** ——
  真正起作用的是 `is_current_token()` 里的 **jti 闸门**。→ 改正文档。

**回归套件 8 项**：
- **B2.7 改用 `new URL()` 做精确 origin 比较**（原来 `startsWith` 太松），
  并把 http/https 归一也纳入用例；顺带发现 `new URL()` 会规范化 IPv6
  （`0:0:0:0:0:0:0:1` → `[::1]`、`::ffff:127.0.0.1` → `[::ffff:7f00:1]`），
  期望值按规范形式写。
- **`bridge_e2e` 的假客户端不再响应 `wait_for`**：它会立即回结果，
  于是"取消泄漏"用例**永远走不到超时路径**（看起来在测超时，其实没测）。
- **`callgraph` 的 D1 改用 AST 结构判断**，不再用 `ast.unparse()` 的
  字符串前缀 —— 前缀匹配会被 `str(event.session_id)` 误命中。
- **`_check_tab_id` 被重复调用三次**、**cookie 导入里有个 no-op 循环**
  （传空 dict 的 `update_cookies` + 吞异常，什么都没做）→ 都删掉。
- **`stubs` 的固定 `/tmp/kira_data` 改为每次唯一的临时目录**。
- `.gitignore` 的 `_click_runner.mjs` 改为匹配 `_click_runner_*.mjs`。

**新增守卫 H2**（见上）。反向验证：把 schema 默认值改回 200MB
→ H2 立即 FAIL。

### v2.1.13（2026-09-15）

**按 CodeRabbit 第十一轮审查修复 12 项**（含 1 个"我声称修了但根本没改"的）：

- 🔴 **第七轮我声称修好的 `buildWsUrl` 其实一行都没改**：
  第七轮的提交信息和 README 都写着「`buildWsUrl` 把裸 IPv6 的冒号当端口
  剥掉 —— 已修」，但 **`protocol.js` 根本没进那次提交**。
  实测 ``::1`` 仍被剥成 ``::`` → 判不出回环 → 生成 `wss://::5267/...`
  这个非法 URL，**扩展连本机都连不上**。
  之后第八、九、十轮都没发现 —— 因为**没有任何检查会去回验"声称"**。
  → 这次真的改了（端口只从带方括号的 IPv6 或单冒号主机里剥；
  裸 IPv6 序列化时补方括号），并**新增行为探针 B2.7**（用 node 真跑
  `protocol.js`，行为不对就红）和**声称核对 H1**。
  B2.7/H1 都做了反向验证：还原成未修改版本 → 立即 FAIL。
- **连接超时后 socket 没收掉**：只 settle 不 close，socket 一直停在
  `CONNECTING`、`state.socket` 仍指向它 → 之后每次 `ensureAlive`/`connect`
  都以为"已有连接"而直接返回，**用户点多少次重连都没用**。
  → 超时即 close、只清自己的引用、并安排重连。
- **上传尺寸估算高估**：base64 长度按 `len*3/4` 硬算，没扣末尾的 `=`。
  `YQ==` 只有 1 字节却算成 3 → **真实大小刚好等于上限的文件被误判超限**。
  → 先减 padding 再换算，现在与真实字节数完全一致。
- **上传上限 200MB 单条消息扛不住**：内容一次性放进 `chunks` 随**一条**
  WebSocket 消息发出，base64 放大 1.33 倍、`json.dumps` 再复制一份 →
  峰值 >500MB，单帧 267MB 本身也会被协议端拒。
  → 默认降到 **32MB**（峰值约 85MB）。
- **`bridge.py` 分块写入失败不 resolve future**："超上限"分支会 resolve，
  写入失败分支只 abort sink → future 一直挂着，`send_command` 要干等到
  `download_timeout`（默认 **600 秒**）才报错。→ 补上 resolve。

**回归套件 6 项**：
- **`INHERITED_OK` 白名单混入通用方法名**（`get`/`append`/`format`/
  `create_task` 等）→ 等于给 A1 开洞：`self.get(...)` / `self.format(...)`
  写错永远不会被报出来。→ 只保留框架真正提供的名字。
  反向验证：加一个 `self.format("x")` → A1 立即 FAIL。
- **`bridge_e2e` 用共享的 `_ext_client.mjs`** → 并发跑会互相覆盖、
  甚至在 finally 里删掉对方的脚本。→ 改用唯一名字的临时文件。
- **`contract.py` 用 `mkdtemp` 不清理**，且**"两边后端都没有该字段就跳过"**
  → 那会放过"渲染层要读的字段两个后端都不返回"这种最严重的情况。
  → 用 `TemporaryDirectory`；去掉跳过。**去掉后立刻暴露真问题**：
  渲染层有个 `get_text` 分支，但没有任何后端方法/工具动作会产生它 ——
  是死代码，已删。
- **`runtime_behavior` 的 R2 未判启动失败就解引用 `p._page`**（启动失败时
  会抛 AttributeError，把"启动失败"伪装成无关崩溃）；**R4 只测一个方向**
  → 补 `R4b` 反向（screenshot_ 最新时应留下 screenshot_），
  否则"永远优先保留 element_"的 bug 也能通过。
- **`security_rules` 的 B2.6 不认简写属性** `{ name, path }` → 只匹配
  `path:` 的话，简写形式的路径泄露检测不出来。→ 同时识别简写。
  反向验证：改成 `{ name, path }` → B2.6 立即 FAIL。
- **`static_audit` 的 A13c 临时文件名写死** → 并发跑会互相覆盖/删文件；
  **`tool_merge` 的 C2 用全仓正则取 action** → 会命中别的工具的 enum。
  → A13c 名字唯一化；C2 改用 `_tool_enum()`。

**文档**：`setup_guide` 补上可选的「允许用户脚本 / Allow User Scripts」
步骤（Chrome 138+ 关着时该功能会提示"不可用"，看起来像浏览器太旧）。

### v2.1.12（2026-09-15）

**按 CodeRabbit 第十轮审查修复 7 项**：

- 🔴 **面板每 3 秒抛一次 ReferenceError**（**我上一轮改出来的回归**）：
  上一轮我把 `const ad = p.allowed_domains || [];` 删掉、改走 `_renderDomains`，
  但漏了下面 `if (!p.read_only && !ad.length)` 仍在用 `ad` →
  可写模式下**初次加载和每 3 秒的轮询都会在这一行抛错**，
  `catch` 只显示"读取失败"，后面的安全提示、确认记录、WebSocket 路径
  **全部停止更新**。
  ⚠️ 只读模式因短路求值（`!p.read_only` 先为 false）**不会**触发，
  所以这个 bug 在只读配置下完全看不出来 —— 极难发现。
  → 改用局部 `allowedCount`。
- **G1 会漏掉模板串插值里的裸标识符**：上一轮我为了修误报，把整个模板串
  替换成 ` `` `，于是 `` `${socket.readyState}` `` 里的 `socket` 也被删了 ——
  G1 报 PASS，运行时却 ReferenceError。
  → 改成**先保留 `${...}` 内容、再删其余模板文本**；
  并按建议加了**自检夹具**（只在插值里放未定义标识符，要求 G1 必须报错）。
- **`no_api` 的报错文案误导**：Chrome 138+ 关掉「允许用户脚本」开关会让
  `chrome.userScripts` **变成 undefined**，与"浏览器版本太低"表现完全一样，
  但原文案只提版本。→ 补上开关排查步骤（并说明这种情况看起来就像不支持）。
- **README 的 `screenshot_dir` 默认值**：写成了"插件数据目录/data/temp"
  把两个位置拼在一起，用户会去插件数据目录里找截图。
  → 改为"空（即用 `data/temp`）"。

**回归套件 4 项**：
- **R3 忽略 `start()` 的失败**：启动失败时 `p.available` 是 false，
  于是 `closed = not p.available` 把**启动失败误报成"空闲清理成功"**（假绿）。
  → 先判 `start()` 返回值。
- **E2 读 `icon.png` 未容错**：文件缺失时 `read_bytes()` 抛 `FileNotFoundError`，
  整个 run 在 E2 中止 → **E3/E4 永不执行**，只记一条笼统失败。
  → 包 try/except，让缺失只让 E2 FAIL。
- **stub 里 `ensure_future` 的 task 无强引用**：事件循环只持弱引用，
  task 可能在异步处理器跑完前被 GC → 弹窗清理/生命周期检查不稳定。
  → 用集合留住 task（完成即丢弃）。
- **G1 未覆盖模板插值**（见上，含自检夹具）。

**新增守卫 `C16e`（面板脚本未声明标识符扫描）**：
本轮那个 `ad` bug 之所以能溜过整个套件，是因为没有任何检查会扫
`index.html` 里的变量引用。新增的扫描会找出"用了但从没声明"的标识符，
并正确处理 `catch (e)` / 箭头函数参数，避免误报。
**反向验证：把 `allowedCount` 改回未声明的 `ad` → C16e 立即 FAIL。**

### v2.1.11（2026-09-15）

**按 CodeRabbit 第九轮审查修复 8 项**（含 2 个安全项）：

- 🔴 **面板存在 XSS**：`bridge.py` 会把扩展上报的事件数据**原样转发**，
  `main.py` 存进 `confirm_log`，而 `web/index.html` 把 `action`/`command`
  和 `reason` **拼进 `conflog.innerHTML`** —— 持有 bridge token 的一方
  可以注入 `<img onerror=...>`，在**已认证的面板**里执行脚本。
  `allowed_domains` / `blocked_domains` 也走同一个注入点。
  → 全部改用 DOM 节点 + `textContent` 渲染，不再拼 HTML 字符串。
- 🔴 **`cookie_get` 导出可以绕过用户确认**：它只读、所以不在
  `WRITE_COMMANDS` 里（正确 —— 不能破坏只读模式/域名白名单的判定），
  但导出的是 `chrome.cookies.getAll` 的**真实取值** = 登录态，
  却因为不在确认集合里被静默放行。
  → 两侧各加一个**「只读但敏感」确认集**（`CONFIRM_ONLY_CMDS` /
  `CONFIRM_ONLY_COMMANDS`），确认判定改用「写操作 ∪ 只读敏感」，
  并补上专门的确认文案。
- **`evaluate` 把脚本异常当成功返回**：注入的包装器会把脚本自身的异常
  吞成 `{ __error: "..." }`，而 `first.error` 只反映
  `chrome.userScripts.execute` 这一层失败 → 脚本抛错时命令被记为**成功**。
  这与 `shared.js` 里 `callContent` 把 `__error` 当错误的做法不一致。
  → 在 `evaluate` 里把 `__error` 翻成抛出的异常。
- **无坐标点击不触发双击**：坐标路径传了 `click_count`，无坐标路径仍在
  循环 `down`/`up`（每次 clickCount 都是 1）→ `dblclick` 永远不触发。
  → 两条路径统一传 `click_count`。
- **弹窗会显示「可读取到 undefined 个标签页」**：`tab_count` 只在
  `listTabs()` 成功时才有，且那个错误被吞掉。→ 渲染前判空。
- **README 的 `screenshot_dir` 默认值写错**：schema 是空串表示"用
  `data/temp`"，`main.py` 与 `HeadlessBackend` 都按 `data/temp` 兜底，
  但 README 指向了别的目录。→ 改为 `data/temp`。

**回归套件 2 项**：
- `_tool_enum()` 会把该工具段里**所有** enum 并起来 → 某个被删掉的
  action 只要还留在别的参数 enum 里，C1 就检测不出来。
  → 只提取 `action` / `mode` 属性自己的 enum。
- C3 只搜索 `main.py`，而 `headless_backend.py` 也是配置消费者
  → 那里的默认值写错不会被发现。→ 两个文件一起查。

### v2.1.10（2026-09-15）

**按 CodeRabbit 第八轮审查修复 4 项**：

- 🔴 **弹窗会假报「已连接」**：`setStatus` 会把 `connected` 一起持久化进
  `STORE.LAST_STATUS`。`status` 分支里 `...st` 被放在 `connected` **之后**，
  于是**存下来的旧值覆盖了实时值**。MV3 的 service worker 被回收重启后
  `state.socket` 是 `null`，但 `st.connected` 还是 `true` →
  弹窗显示「已连接」，实际根本没有 socket。
  → 改成**先铺 stored、再盖上实时字段**。
- 🔴 **回归套件会自己生成 `__pycache__` 把自己判失败**：
  `security_rules` 先于 `file_hygiene` 执行，它通过 `load_module()` 加载
  `security.py`；那条路径会写出 `PLUGIN_DIR/__pycache__/*.pyc`，
  而 `file_hygiene` 的 `_all_files()` 会把 `__pycache__` 算进去 →
  **D1/D2 随机失败**（取决于有没有缓存残留）。
  → 在 `run_all.py` **导入任何检查模块之前**设 `sys.dont_write_bytecode = True`。
- **`bridge_e2e` 每次跑留下一个含 ~1MiB `dl.bin` 的临时目录**
  → 改用 `TemporaryDirectory`，并在退出上下文**之前**读取 `dl_size`。
- **`tool_merge` 的 C8 只检查三个独立子串**：即使 `credentials` 被改成
  无条件的 `"include"`（HTTP 也带会话 Cookie → 明文泄漏），只要那三个词
  还在，断言照样通过。→ 限定在 `downloadViaSession` 内，并要求凭据表达式
  **带 HTTPS 条件且有 `"omit"` 分支**。

### v2.1.9（2026-09-15）

**按 CodeRabbit 第七轮审查修复 11 项**：

- 🔴 **上一轮我改出来的 Regression**：`test_ping` 里调用了
  `probeServerRoundTrip(5000)`，但**这个函数从未定义** —— 每次点"测试"
  都会抛 `ReferenceError`，被 catch 后统一显示"测试失败"。
  → 补上实现（挂一次性监听等**服务端心跳 ping** 到达并回 pong）；
  并把超时从 5 秒改成 **30 秒** —— 心跳间隔是 25 秒，
  用 5 秒会把**正常链路也判超时**。
- 🔴 **上传分块大小不是 3 的倍数**：插件侧按 `256 * 1024` 分块，
  而 `256*1024 % 3 = 1` —— base64 每 3 字节编 4 字符，块长不是 3 的倍数时
  **每块末尾都带 padding**，独立编码后直接拼接就不再是合法 base64，
  `atob` 会抛 `InvalidCharacterError`。**大于一块的文件上传必挂。**
  → 改为 255KB（能被 3 整除），并在扩展侧拼接前**去掉各块 padding** 兜底。
- 🔴 **无头下载的 HTTPS→HTTP 重定向会带出非 Secure cookie**（CWE-319）：
  aiohttp 只过滤 `Secure` cookie，同域降级到 http 时**普通会话 cookie 照样发出去**。
  → 带 cookie 时**不自动跟随重定向**，自己跟且**每一跳都要求 HTTPS**；
  一旦要降级就丢掉 cookie jar 再继续（宁可匿名，不明文带凭据）。
- 🔴 **SSRF：完整写法的 IPv6 回环被漏判**：`0:0:0:0:0:0:0:1`（即 `::1` 的完整写法）
  被我上一轮的"拆内嵌 IPv4"逻辑误拆成 `1` → 归一成 `0.0.0.1` →
  `is_local_host` 反而**漏掉**回环地址。→ 先判断是否为合法 IPv6，
  只有**真正的 v4-mapped** 才拆。
- **`buildWsUrl` 会把裸 IPv6 的冒号当端口剥掉**：`::1` → 剥成 `::`
  → 判定为非回环 → 生成 `wss://:::5267/...`，连接直接失败。
  → 只在「带方括号的 IPv6」或「单冒号主机」时才剥端口。
- **`headless_profile_mode` 的代码兜底值与 schema 不一致**：
  schema 默认 `inherit`（复制真实数据），而 `main.py` 的 `cfg.get` 兜底写的是
  `persistent` —— 配置文件缺这一项时会**静默退回插件自己的 profile**，
  用户以为继承了登录态其实没有。→ 改为 `inherit`。

**回归测试套件 5 项**：
- `runtime_behavior` 每次跑都在系统临时目录留一个 `kira_reg_*` 目录
  → 改用 `TemporaryDirectory`（正常/异常都会清理）。
- `R4` 只断"element_ 剩几张" → 改成**三条一起断**：总数到上限、
  element_ 未被全删、留下的确实是较新的那批。
  顺带修了随机性：测试里显式区分 mtime（同一 tick 创建的文件 mtime 相同，
  排序结果取决于文件名，断言会忽过忽不过）。
- `R10` 在 `scroll` 处理器被删/改名时会 `IndexError` **中断整组检查**、
  把后面的断言全跳过（假绿）→ 先判断分隔符存在再解析。
- `security_rules` 的"下载不跟随重定向"用全文搜 → 改成只在
  `downloadViaSession` 内部找。
- `tool_merge` 的 C1 在取不到 enum 时**跳过校验** → 改为判 FAIL；
  但**非 action 式**的工具（`browser_wait` 等）本来就没 enum，不该要求。

### v2.1.8（2026-09-15）

**按 CodeRabbit 第六轮审查修复 15 项**：

- 🔴 **上一轮我把 wss 守卫写反了**（自己引入的回归）：`buildWsUrl()` 对**所有**
  非回环主机抛错 —— 而"远程主机默认走 wss"本身是正确且安全的路径，
  结果把正常用法也堵死了。→ 改为：能解析用户填的 `ws://`/`wss://`；
  默认本机 `ws`、其它主机 `wss`；**只有显式要求明文连非本机时才拒绝**。
- 🔴 **二次确认漏了三个写命令**（CWE-862）：`activate_tab` / `close_tab` /
  `mouse_move` 不在 `PRIVILEGED_COMMANDS` 里 —— 开了「写操作需确认」时，
  AI 仍能在用户未批准的情况下**切走/关掉标签页**。
  → 补齐，并让 Python 侧与 JS 侧的命令集合**逐字一致**（新增检查盯着）。
- 🔴 **`test_ping` 报"链路正常"却没做任何服务端往返**：它只检查
  `readyState` 再调**本地**的 `listTabs()`（后者跑 `chrome.tabs.query`，
  根本不经过 WebSocket）。socket 半开或插件侧路由坏了时照样显示正常。
  → 改为挂一次性监听，**等服务端心跳 ping 到达并回 pong** 才算通过；
  5 秒没等到就明确报"链路可能不通"。
- **上传在内存里重建整份文件**：base64 → 解码成字节 → 再编码回 base64，
  同一份数据存三份，200MB 上传峰值可达 1GB，足以打挂 MV3 Service Worker。
  → 内容脚本要的就是 base64，**按长度校验后原样拼接**即可，不再解码重编码。
- **`mouse_move` 声称按着左键**：`mouseInit` 无条件给 `buttons: 1`，
  等于说"移动时左键按住"——拖拽敏感页面会在纯 hover 上开始拖拽。
  → 不传 `button` 时 `buttons: 0`。
- **Chrome 最低版本 116 → 120**：扩展声明了 `userScripts` 权限，
  而该 API 从 Chrome 120 起提供，116–119 装上也用不了 `browser_script`。
  → manifest / README / `setup_guide` 三处统一为 120。
- 扩展 manifest 描述里的「默认只读」已过时（实际默认可读写）→ 改为按
  "权限由 KiraAI 插件配置控制"表述。

**回归测试套件 8 项**（CR 连检查本身也审了，这几条都挺准）：
- `file_hygiene` 把 `__pycache__` 从清单里**剔除**了 → D1/D2 永远查不到它们，
  等于形同虚设。→ 让它们进清单，由检查判红。
- `callgraph` 的 A13b/A13c 只看 `sym(` 调用形式 → 漏掉 `MSG.PING`、`CMD.DOWNLOAD`
  这类**成员访问**与当值传递（运行时同样是 ReferenceError，
  而 `node --check` 不查未定义标识符）→ 扩展覆盖面。
- `tool_merge` 的 C1 用**全文搜索**找 action → 目标工具删了某动作、
  但别处还有同名动作时照样 PASS。→ 改为解析**目标工具自己的 enum**
  （且只取 schema 段，不含函数体）。**反向验证**过。
- `runtime_behavior` 的 R5 用 `<= 6` → 同时放过"多留一个"和"删多了"。
  → 改为精确等于上限。
- `security_rules` 的 B2 用子串判据判"不回传绝对路径"→ 格式化一下就能绕过。
  → 改为解析返回对象的**键**。
- `bridge_e2e` 失败路径不收子进程与服务（断言抛错时 node 还活着）→ 包 `try/finally`。
- `content_dom` 的 runner 文件名固定 → 并行执行会互相删。→ 加 PID 后缀。
- 假 Playwright 的 `_die_by_itself()` 没计入 `pages_closed` → 与"每次关闭都计数"
  的契约不符。

### v2.1.7（2026-09-15）

**按 CodeRabbit 第五轮审查修复 9 项**：

- 🔴 **非本机地址会用明文 `ws://` 传令牌**（CWE-319）：`buildWsUrl()` 无条件拼
  `ws://`，而接入令牌就在 query string 里。host 可由用户配置 ——
  一旦填远程主机，网络上的任何人都能抓到令牌，然后**拿到整个浏览器桥权限**。
  → 回环地址用 `ws://`（不出网卡），其它地址**必须 `wss://`**；
  用户填远程主机却想用 ws:// 时**直接报错**，而不是悄悄发明文。
- 🔴 **旧连接的 `onclose` 会清掉新连接**：`disconnect()` 异步关旧 socket 后
  立即允许重连；若旧 socket 的 `onclose` 在新 socket 已写入 `state.socket`
  之后才执行，它会把**新连接引用清成 null**，还可能为旧连接起一次重连。
  → 每次 `connect()` 捕获局部引用，所有回调先确认"自己仍是当前连接"。
- 🔴 **替换旧连接时没清在途命令与下载 sink**：`_close_ws()` 只关 socket，
  不清 `_pending` 也不收 `_sinks`；而旧连接的 `_cleanup` 又会因 session 已换
  而直接返回 —— 旧命令一直等到超时，下载句柄也一直开着。
  → 改用 `_force_close()`（一次做完 cancel 心跳 + 失败在途命令 + 收 sink）。
- **扩展下载无条件带凭据**（CWE-319）：`credentials: "include"` 对 HTTP 目标
  或 HTTPS→HTTP 重定向会送出非 Secure 的 Cookie。
  → 仅 HTTPS 带凭据，并把 `redirect` 设为 `error`（**根治**跨协议泄漏，
  而不是"跟随后再检查"——那时已经发出去了）。
- **下载列表回传本机绝对路径**（CWE-200）：`chrome.downloads.search()` 的
  `filename` 通常含用户名与本地目录结构，而扩展后端本来也用不了该路径。
  → 只回文件名与必要元数据。
- 回归检查 3 项：`bridge_e2e` 端口写死会撞车 → 改绑 `0` 让系统分配；
  `callgraph` 的豁免"文件里有一处合法就跳过整个文件" →
  改成按 AST 定位所属函数，只豁免 `_sid_of` 内部那处（并**反向验证**过：
  同文件里再插一处不安全用法能报出来）。
- `setup_guide` 的 Windows 浏览器路径只查一个环境变量 → 补
  `%PROGRAMFILES(X86)%` 等常见位置（Edge 在 64 位系统上装在 x86 目录），
  并跳过空环境变量（`Path("") / "x"` 会得到相对路径、误判本机存在）。

**`upload_allow_any_path` 保持默认 `true`**（按需求）：本插件的定位是给 bot
完整的浏览器能力，上传任意本机文件是预期功能。想收紧就把这项关掉，
白名单在 `upload_allowed_dirs`。README 配置表已与代码/schema 对齐。

### v2.1.6（2026-09-15）

**按 CodeRabbit 第四轮审查修复 10 项**（1 个 Critical + 9 个真实问题）：

- 🔴 **扩展模块直接语法错误**：`capabilities.js` 既 `import { sendChunk }`
  又在本地 `function sendChunk()` 声明了一遍 → `SyntaxError: Identifier
  'sendChunk' has already been declared` → **整个扩展加载不了**。
  → 删掉本地重复声明。
  → 新增检查 **A13c：用 module 模式检查 ES 模块语法**。
  这之前一直是盲区：`node --check xxx.js` 会把 `.js` 当 **CommonJS** 解析，
  "import 与本地声明重名"这类**模块级**语法错误根本查不出来。
- **`upload_allow_any_path` 的默认值分裂**：schema 写 `true`、代码也写 `true`，
  但**取值不安全**（可外传任意本机文件）。→ 两处统一改为 `false`（安全值），
  并新增检查 **C3：代码默认值必须与 schema 一致**
  （这条检查当场又揪出 `op_timeout` schema=120 / 代码=40 的真实分裂）。
- **SSRF：IPv4-mapped IPv6 可绕过**（CWE-918）—— `ipaddress` 对
  `::ffff:127.0.0.1` 的 `is_loopback` 是 **False**，而 Chromium 会真的连到回环。
  十进制/十六进制写法我上一轮堵了，这个映射形式漏了。已补（含
  `::ffff:7f00:1` / `::ffff:2130706433` 等变体），并加入用例表。
- **带凭据下载允许明文 HTTP**（CWE-319）→ 非 HTTPS 时**不带 Cookie**。
- **`available` 判据不对**：非持久化启动会**先赋 `_browser` 再建 `_context`**，
  并发调用能在 `_context` 还是 None 时绕过锁进来，自愈逻辑甚至会把
  对方**正在初始化**的浏览器关掉。→ 只认 `_context`。
- **`navigate(new_tab=True)` 不关旧页面**：每调一次多一张 Chromium 页面常驻，
  而 `_check_tab_id()` 又让调用方选不到它们 —— 纯泄漏。→ 建新页后关旧页。
- **chunk 写失败只 abort sink 不置 future**：调用方会一直等到自己的超时
  （下载默认 **600 秒**），磁盘满/非法 base64 表现为"工具卡 10 分钟"。
- **命令没到 bridge 时 sink 没人收**：扩展未连接 / 未知命令会从
  `send_command` 入口就抛，不走它内部的 try，于是句柄泄漏、磁盘留 0 字节文件。
  → 补 `abort_download_sink()` 公开入口并在失败路径调用。
- **profile 新鲜度漏了 Local Storage**：不少站点把登录 token 只存在
  Local Storage，漏了就一直复用旧副本，用户"重新登录了却还是登出状态"。
- **回归检查 C12 拿注释当判据**：注释还在、`el.click()` 被加回来时照样会过。
  → 改为检查**真正的代码**（并做了反向验证）。

### v2.1.5（2026-09-15）

**按 CodeRabbit 第三轮审查修复 13 项**（含又一批 ReferenceError 级问题）：

- 🔴 **`capabilities.js` 没有任何 import** —— 它调用的 `resolveTab` /
  `assertInjectable` / `callContent` / `sendRaw` / `sendChunk` / `MSG` 全都没导入，
  ES 模块严格模式下直接 `ReferenceError`：**执行JS、上传、Cookie 导出全不可用**，
  非空下载也会在 `sendChunk` 崩掉。（我上一轮"已修"其实没落到位。）
  → 补上 import，并新增检查 **A13b：用了但没 import 的符号**
  （上一轮加的 A13 只验了反方向，漏掉了这条）。
- 🔴 **上传路径白名单在合并时丢了** —— `upload_allow_any_path` /
  `upload_allowed_dirs` 两个配置项连同校验逻辑一起消失，
  模型可借"上传"把**本机任意文件**外传（CWE-200）。→ 已恢复，
  且校验放在**读文件之前**（用 realpath 归一，防 `../` 穿越）。
- **`github.*` 会匹配 `github.com.evil.test`** —— `fnmatch` 的 `*` 跨点号，
  等于把白名单授给了攻击者域（CWE-284）。→ 改为按标签边界逐段匹配。
- **弹窗回收会关掉自己正在创建的页面** —— Playwright 的 `context.new_page()`
  在 **await 返回之前**就派发 `page` 事件，那一刻 `_page` 还指着旧页，
  回收逻辑会把新建的这张关掉。→ 加"创建中"守卫。
- **`open_download_sink` 打不开文件时只记日志就 return** —— 后续 chunk 全被丢，
  `_finish_sink` 返回 None，调用方**报告下载成功但磁盘上没文件**。→ 改为抛出。
- **`userDisconnected` 没持久化** —— MV3 的 Service Worker 被回收再唤醒后标记丢失，
  用户点「断开」约 30 秒后连接自己回来，弹窗那句"自动重连已暂停"成了假话。
  → 存进 `chrome.storage.local`。
- **`exec_js` 的表达式/函数体回退会在任何异常时触发** ——
  一条"能解析但运行到一半抛错"的脚本（如 `items.forEach(i => post(i))`）
  会被**执行两遍**，副作用重复。→ 只在 `SyntaxError` 时回退。
- **`scroll`/`mouse_wheel` 会滚双倍距离** —— `dispatchEvent` 返回 false 说明
  页面已 `preventDefault` 自己处理了，代码却照样再滚一次窗口。
- **`click_count` 不产生双击** —— 循环 down/up 会让页面收到"两次独立单击"，
  `dblclick` 永不触发。→ 改用 `mouse.click(click_count=n)`。
- **`navigate` 取标题失败时漏 `title` 字段** —— `_send` 把失败转成 `OpResult`
  而非抛异常，`except` 分支根本不走，兜底 `setdefault` 被跳过，破坏两后端契约。
- 文档修正：popup 的「默认只读」已过时（实际默认可读写）；
  `first_run_notice` 把 `inherit` 模式说成"没有登录态"是错的；
  README 补充 **Windows App-Bound Encryption**（Chrome 127+）会让部分 Cookie
  无法跨应用解密，并建议此时改用 `browser_cookie` 导出/导入。

另有 5 项是**回归测试套件自身**：`PATH` 写死导致找不到 node、子进程引用
可能被 GC 提前回收、`defined` 没算类体赋值、schema 直接下标会让整组中断、
以及上一轮那个"顶层模块全被跳过"的 A1（等于大部分文件没验）。

### v2.1.4（2026-09-15）

**按 CodeRabbit 第二轮审查修复 13 项**（1 个 Critical + 12 个真实问题）：

- 🔴 **扩展里 `socket` 未定义 → 扩展永远连不上**：把 `socket` 挪进
  `shared.js` 的 `state` 之后，`background.js` 里还留着 `socket.onopen = ...`
  这类裸引用。ES 模块是严格模式，直接 `ReferenceError`，
  而且 `connect()` 里那句是无条件执行的 —— **每次连接都失败**。
  → 全部改为 `state.socket`，并新增检查 **G1：不允许裸的状态标识符**。
- **替换旧连接时没取消旧心跳任务**：旧连接的 `_cleanup` 因 session 已换而直接返回，
  旧心跳继续活着，还会往**新连接**发 ping。每次重连多留一个协程。
  → 替换前先 cancel。
- **下载 sink 在失败路径不关闭**：超时/异常/`ok=false` 时不收 sink，
  文件句柄挂到进程退出、磁盘留半成品。→ 三条路径都 `_abort_sink`，`close()` 也清。
- **上传上限在解码后才检查**：超限文件已经完整占住内存，上限形同虚设。
  → 先按 base64 长度估算拦截，再边解码边累计兜底。
- **`exec_js` 强制表达式语法**：`(function(){ return (${script}); })()` 只接受单条
  表达式，多语句（`const a=1; return a;`）会语法错误。
  → 先试表达式、失败落函数体模式，两种写法都支持。
- **`userScripts` 探测结果被缓存（含失败态）**：用户按提示打开开关后再试仍是失败，
  必须重载扩展。→ 只缓存成功结果。
- **下载最后一块缓冲没查上限**：刚好卡边界的文件能绕过限制。
- **`--disable-...` 之外**：启动失败的半成品实例没关就置 None（泄漏孤儿 Chromium 进程）；
  `copytree` 同步阻塞事件循环（几 GB 会把整个 KiraAI 卡住）；
  `custom_user_data_dir` 可以指向真实浏览器目录（正是要避免的抢锁场景）；
  用**目录** mtime 当 profile 缓存版本（`Cookies` 改了目录 mtime 不变 → 一直用旧副本，
  新登录读不到）；idle 看门狗自我取消导致"正常收尾"变异常退出。
- **下载时 cookie 语义丢失**：用 `{name: value}` 更新 CookieJar 会丢掉
  domain/path/secure/expires → 跨域重定向可能带错 cookie。→ 逐个 `add_cookie` 保留完整语义。
- **无头后端的 `tab_id` 被静默忽略**：传了别的 tab_id 不报错也不生效，
  模型以为操作了那张标签页。→ 明确告知"无头只有一张页"。

另有 6 项是**回归测试套件自身**的问题（CR 也一并审了）：
`py_compile` 会往源码树写 `.pyc`（污染文件清点）、jsdom 缺失后没 return、
`bridge_e2e` 没先检查 node、`callgraph` 的 async 检查是死代码（永远报不出）、
`tool_merge` 只验工具名不验 action、`harness` 文档写的是旧契约。

### v2.1.3（2026-09-15）

**全量通读代码修出的 2 个严重问题**（都是"语法没问题、跑起来才炸"）：

- 🔴 **`_send_image` / `_send_file` 被调用但从未定义**：这两个方法在之前的
  工具层重构中丢了，只剩调用点 —— 截图发送、文件发送会直接
  `AttributeError` 崩掉。而所有语法检查（`py_compile`）和既有回归检查**全绿**，
  因为它们只看"名字有没有出现"，不看"定义有没有存在"。
  → 已补回，并新增检查组：**调用图完整性**（扫描 `self.xxx()` 是否有定义）。
- 🔴 **配置面板的 API 路径是旧的插件 id**：面板写死
  `/api/plugin/kira_browser_bridge`，而插件 id 早已是 `headless_browser`
  （框架把插件 API 挂在 `/api/plugin/{plugin_id}/...`）。
  → 结果就是面板一打开「令牌读取失败」，重载也不会有反应。
  → 已修正，并新增检查：**硬编码的插件 id 必须与 manifest 一致**
  （面板 API / WS 路径 / 扩展路径都依赖它）。

另外确认了**框架契约合规**：工具签名 `(self, event, …)`、hook 签名
`(self, event, req, …)`、`event.sid` 取会话标识 —— 与框架内置插件的写法一致。

### v2.1.2（2026-09-15）

**两后端返回契约完全对齐**（真正可互换）。

- 🔴 **两个后端返回的字段不一致（22 处差异）**：同一个工具因为路由到不同后端，
  返回的字段形状不同 —— 模型看到的信息时有时无，这类问题极难排查
  （"昨天还能读出标题，今天不行了"）。
  已逐条对齐：`click` 补 `navigated`/`changed`/`match`，`navigate` 补 `title`/`tab_id`，
  `type_text` 补 `submitted`，`upload_file` 补 `name`/`size`，
  `download` 补 `url`/`mime`，`cookie_set` 统一 `written`/`skipped`，
  `list_tabs` 补 `tab_count`，`execute_js`/`hover`/键盘鼠标补 `url`，
  `scroll`/`mouse_wheel` 去掉多余字段……
  **现在两个后端可以任意互换而模型无感。**
- ✅ 新增回归检查组：**两后端返回契约一致性**（真的把两个后端都调一遍，
  收集实际返回的字段，与渲染层要读的字段比对）

### v2.1.1（2026-09-15）

**全量复查修出的 5 个问题**（都是"看着实现了、实际不生效"那类）：

- 🔴 **二次确认完全没生效**：`require_confirm` 配置项存在、扩展也实现了，
  但**插件从不把开关下发给扩展** → 打开了也没有任何反应。
  现在所有写命令自动带上 `require_confirm` 与 `confirm_timeout`。
- 🔴 **用户拒绝后仍会执行**：扩展侧用户点了「拒绝」，却被当成"执行失败"，
  路由于是**换到无头后端把同一件事做了** —— 用户以为自己拦住了，其实没有。
  现在 `OpResult` 区分「被拒绝」与「失败」，拒绝即终止，绝不重试。
- 🟠 **`browser_cookie(export)` 返回空**：导出的是**数据**，但渲染层没处理它，
  落到默认分支只回一句「✅ 完成」，cookie 被静默丢掉。
  另外 15 个（键盘/鼠标/返回/刷新/文件列表/上传…）也是同样问题，一并补全。
- 🟠 **并发工具调用会互相踩**：`asyncio.Lock` 只保护"启动浏览器"，
  不保护页面操作。模型一轮里并发调 `navigate` + `click` 时，
  `goto` 还没完成就会有人在同一张页面上 click。现在页面操作有独立互斥锁。
- 🟠 **扩展 `scroll` 报"已滚动"但页面还没动**：用了 `behavior: "smooth"`
  （异步动画），函数立刻返回而页面还在慢慢滚 —— 紧接着截图会拿到旧位置；
  而且无条件回 `changed: true`，即使已经在底部也报告"变了"。
  现在改为瞬时滚动并返回**真实位移**。

另外给扩展的三个生命周期回调加了异常兜底：
MV3 的 unhandled rejection 是 worker 级错误，可能直接让扩展掉线。

### v2.1.0（2026-09-15）

**扩展桥能力补齐 + 工具合并。**

- ✨ **扩展桥补齐三项关键能力**：执行任意 JS（走 `chrome.userScripts`，
  绕开 MV3 下页面 CSP 对 eval 的拦截）、上传文件（插件分块送内容 +
  扩展用 `DataTransfer` 塞进 `input.files`）、下载（扩展用用户会话 fetch +
  分块回传，**能下登录态资源**）
- ✨ **Cookie 导出/导入**：把浏览器的登录态带到无头后端，降级时不用重新登录
- ✨ 扩展侧补齐 `getInfo`/`goBack`/`refresh`/`hover`/键盘 3 个/鼠标 6 个/
  `listFiles`/`debugInfo`，**两个后端接口完全对称**
- 🔀 **工具合并 31 → 12 个**，按「动作 + 传参」组织（`browser_interact` 用
  `action` 选 18 种动作，`browser_page` 用 `mode` 选读什么）。**能力零丢失**，
  逐条映射核对过
- ✨ **内容分页续读**：`browser_page` 支持 `offset`/`max_chars`，
  返回值带 `has_more`/`next_offset`，AI 自己决定读多少
- ⚙️ `op_timeout` **与框架工具超时脱钩**（默认），由插件自己管，避免被硬取消
- ⚙️ `headless_profile_mode=inherit`：**复制**真实浏览器数据（不抢锁），
  登录态完整保留
- ⚙️ `read_only` 默认改为 `false`（bot 有完整读写能力）
- ⚙️ `download_max_bytes` 默认 2GB（流式落盘，不占内存）
- 🐛 修复：`upload_max_bytes` 配置项加了但没接线

</details>

<details>
<summary><b>2.0.x</b> — 1 个版本　·　双后端架构的第一版</summary>

### v2.0.0（2026-09-15）

**双后端架构 + CPU/内存修复。**

- ✨ **双后端自动路由**：扩展桥（用户自己的浏览器，零冲突）↔ 无头后端
  （插件自己的浏览器），没连上自动回退；策略可固定为其中一种
- 🔴 **修复 CPU 问题（三条根因）**：
  - 删除旧版**反向**加上的 `--disable-background-timer-throttling` /
    `--disable-backgrounding-occluded-windows` / `--disable-renderer-backgrounding`
    （Chromium 的后台节流能把后台标签 CPU 降到 1/5，而 bot 的浏览器窗口
    常年被挡在后面，正好全命中）
  - 补齐 `--disable-dev-shm-usage`（`/dev/shm` 写满会让渲染进程崩溃→反复重载→CPU 飙升）、
    `--disable-gpu`、`--js-flags=--max-old-space-size=512`、`--renderer-process-limit=N`
  - 默认等待 `networkidle` → `domcontentloaded`（前者官方标注 DISCOURAGED）
- 🔴 **修复"卡死"真凶**：旧版 `_ensure_browser()` 从不检查页面死活，
  用户一关标签页插件就**永久失败且不自愈**。现在有页面自愈 + 致命错误重建
- 🔴 **修复"互相抢锁"**：不再直接占用真实 profile（见
  「为什么装了扩展之后，我的浏览器还能正常开」）
- 🐛 **修复内存持续增长**：弹窗页面无人回收、`element_*.png` 从不被清理、
  下载目录无清理 → 全部补上
- 🐛 **修复下载漏洞**：旧版把整个文件读进内存且无大小上限、不限协议
  → 改为流式落盘 + 大小上限 + 只允许 http/https
- ✨ **空闲回收**：`idle_close_seconds`（默认 300），空闲后自动关闭释放 CPU 内存
- ✨ 有头模式补回窗口可见性参数（`--start-maximized` / `--window-position` /
  `--force-device-scale-factor`）
- ✨ 首次运行会主动提示扩展的安装方法

</details>

<details>
<summary><b>1.x</b> — 1 个版本　·　早期版本</summary>

### v1.2.1

- 浏览器来源四级回退（接管真实浏览器 / 插件持久 profile / 系统浏览器 / 内置 Chromium）
- 下载超时保护、cookie 按域隔离、CodeRabbit 审查修复

---

</details>

---

## 致谢

- 原始插件：nyx
- 扩展桥（Kira Browser Bridge）：随插件提供，Chrome / Edge / Brave 等 Chromium 系可用

## 许可

见仓库 LICENSE。
