# 无头浏览器插件 (Headless Browser Plugin) 1.1.0

让 KiraAI 能够控制无头浏览器进行网页浏览、截图、下载、上传等操作，支持自动加载 cookie 文件实现各账号的半持久化登录。

## 功能特性

- 🌐 **浏览器控制**: 访问网页、点击元素、填写表单、滚动页面
- 📸 **截图功能**: 截取页面或元素，自动发送给 AI 查看
- 📁 **文件管理**: 下载文件、保存截图、发送文件给用户
- 🔧 **JS执行**: 在页面中执行 JavaScript 代码
- 🍪 **Cookie管理**: 自动加载 `data/files/cookie/` 目录下所有网站的 Cookie 文件，多站点独立存储，分享插件时安全隔离
- ⚙️ **灵活配置**: 支持无头/可视模式、自定义视口、User-Agent 等

## 安装依赖（重要！第二行必须手动在cmd内输入，无法通过requirements.txt自动安装！）

```bash
pip install playwright aiohttp
playwright install chromium
```

## 配置说明

在 WebUI 的插件配置中设置以下选项：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `headless` | boolean | `true` | 是否以无头模式运行（后台运行） |
| `default_viewport` | string | `1920x1080` | 浏览器视口大小 |
| `screenshot_dir` | string | `插件数据目录/screenshots` | 截图保存路径 |
| `download_dir` | string | `插件数据目录/downloads` | 文件下载路径 |
| `user_agent` | string | - | 自定义 User-Agent |
| `timeout` | integer | `60` | 页面加载超时时间（秒） |
| `auto_send_screenshot` | enum | `auto` | 截图发送模式：`auto`=自动发送，`manual`=AI决定何时发送 |
| `auto_describe_screenshot` | boolean | `true` | 是否使用VLM自动描述截图 |
| `vlm_model` | model_select | - | 选择用于描述截图的VLM模型（下拉框显示所有已配置模型） |
| `vlm_describe_prompt` | string | - | 自定义VLM提示词（可选，未设置则使用默认模板） |
| `vlm_timeout` | integer | `10` | VLM描述超时时间（秒） |
| `cookies_dir` | string | `data/files/cookie` | Cookie文件存放目录，启动时自动加载该目录下所有 *.json 文件 |
| `upload_allow_any_path` | switch | `true` | 是否允许上传任意目录的文件（true=允许任何路径，false=仅允许白名单目录） |
| `upload_allowed_dirs` | list | `["data/files", "data/temp"]` | 允许上传的目录白名单（每行一个，仅在 `upload_allow_any_path=false` 时生效） |

### 截图发送模式

**`auto` 模式（默认）：**
- 截图后自动发送给用户
- AI 会收到 VLM 对截图的描述
- 适合快速响应，不需要 AI 判断的场景

**`manual` 模式：**
- 截图后不会自动发送
- AI 会先查看截图内容（通过 VLM 分析）
- AI 可以根据内容决定是否发送给用户
- 适合需要 AI 判断截图是否有价值的场景
- AI 可以使用 `browser_send_file` 手动发送

**切换模式：**
在插件配置中修改 `auto_send_screenshot` 选项，然后重载插件。

### VLM 模型配置

截图后插件可以使用 VLM（视觉语言模型）自动分析截图内容，提取页面信息供后续 AI 调用工具使用。

**重要说明：**
基于KiraAI框架传统，用于描述截图的 VLM 模型必须是 **LLM 类型**（不是图像类型）。即使模型支持视觉分析，也需要在 LLM 模型组中配置才能用于描述功能。

**配置步骤：**
1. 在**提供商**设置中，将视觉模型（如 Qwen-VL）添加到 **大语言模型** 组（而不是图像组）
2. 保存提供商配置
3. 在插件配置的 `vlm_model` 下拉框中选择该模型

**支持的视觉模型：**
- `Qwen/Qwen2-VL-72B-Instruct` (硅基流动)
- `gpt-4o` (OpenAI)
- `claude-3-opus` (Anthropic)
- `kimi-k2-0905` (Moonshot)

**方式二：使用系统默认VLM**
在系统设置-默认模型中配置VLM模型，插件会自动使用。

**检查VLM配置：**
调用 `browser_check_vlm` 工具查看当前配置状态和可用模型列表。

### VLM 提示词模板

插件内置了专门为**浏览器自动化优化**的 VLM 提示词模板。当 VLM 分析截图时，会输出以下结构化信息：

```
### 1. 页面基本信息
- 页面标题、URL、页面类型

### 2. 可交互元素清单（关键！）
- 搜索框：位置、placeholder文字
- 按钮：文字和大概位置
- 链接：重要导航链接
- 表单字段：输入框、下拉菜单

### 3. 当前状态
- 页面是否已完全加载？
- 是否有错误提示、弹窗、警告？
- 是否需要登录才能操作？

### 4. 关键内容
- 页面的主要内容/搜索结果是什么？
- 是否有验证码、人机验证？
- 是否有弹窗广告遮挡？

### 5. 建议的下一步操作
- 如果要搜索：点击哪里、输入什么
- 如果要点击：建议的CSS选择器
- 如果要填写表单：每个字段填什么

### 6. 坐标参考
- 重要元素的大致坐标（基于1920x1080）
```

这样后续 LLM 拿到描述后，可以直接调用浏览器工具完成操作！

**自定义提示词：**
如需覆盖默认模板，在插件配置中填写 `vlm_describe_prompt`。自定义提示词将完全替代默认模板。

### 🍪 Cookie 管理

插件支持自动加载 **多个网站** 的 Cookie，方便 AI 以已登录状态操作各类网站。

**存储方式：**
- Cookie 文件统一存放在 `data/files/cookie/` 目录
- 每个网站一个独立的 JSON 文件，如 `chatgpt.json`、`claude.json`、`gemini.json`
- 插件启动或浏览器重启时，自动扫描并加载该目录下所有 `*.json` 文件

**文件格式（标准 Chrome 导出格式）：**
```json
[
  {
    "name": "session-token",
    "value": "xxx",
    "domain": ".chatgpt.com",
    "path": "/",
    "secure": true,
    "httpOnly": true,
    "sameSite": "Lax",
    "expirationDate": 11451418881
  }
]
```
支持嵌套格式（如 `{"cookies": [...]}`），插件会自动解包。

**如何使用：**
1. 从浏览器扩展（如 EditThisCookie、Get cookies.txt）导出对应网站的 Cookie
2. 保存为 JSON 文件，放入 `data/files/cookie/` 目录，插件启动时自动加载（cookie 值仅注入浏览器会话，不会出现在 AI 可见的上下文中）
3. 建议按站点名命名方便管理，如 `chatgpt.json`
4. 重载插件或重启 KiraAI 即可自动加载

**安全隔离：**
`data/files/cookie/` 目录位于项目数据目录下，**不随插件文件打包**：已在 `manifest.json` 的 `exclude` 字段中声明打包排除，并在仓库 `.gitignore` 中忽略该目录。分享插件源码时，你的 Cookie 信息不会泄露。如需分享，请确保移除该目录。
**然而必须注意，你发送的任何内容实际上都经手了你的模型提供商与服务商，请自行评估风险**

## 可用工具

### 浏览器控制

- **`browser_navigate`** - 访问指定 URL
  - `url`: 要访问的网址
  - `wait_until`: 等待状态 (`load`/`domcontentloaded`/`networkidle`)

- **`browser_click`** - 点击页面元素
  - `selector`: CSS 选择器
  - `button`: 鼠标按钮 (`left`/`right`/`middle`)

- **`browser_fill`** - 填写表单字段
  - `selector`: CSS 选择器
  - `value`: 要填写的文本
  - `clear_first`: 是否先清空字段

- **`browser_scroll`** - 滚动页面
  - `direction`: 方向 (`down`/`up`/`bottom`/`top`)
  - `amount`: 滚动距离（像素）

- **`browser_go_back`** - 返回上一页

- **`browser_refresh`** - 刷新页面

### 截图与内容获取

- **`browser_screenshot`** - 截图（根据配置自动发送或由AI决定）
  - `selector`: 元素选择器（可选，默认截取整页）
  - `filename`: 文件名（可选）
  - `full_page`: 是否截取完整页面
  - `send_now`: 是否立即发送（仅manual模式下有效）

- **`browser_get_text`** - 获取页面文本内容
  - `selector`: 元素选择器（可选）
  - `max_length`: 最大返回长度

- **`browser_get_info`** - 获取页面基本信息（标题、URL）

### JavaScript 执行

- **`browser_execute_js`** - 执行 JavaScript 代码
  - `script`: JS 代码字符串

### 文件管理

- **`browser_upload_file`** - 上传文件到指定文件输入框（绕过系统文件对话框）
  - `selector`: 文件输入框的 CSS 选择器（如 `#upload-files`、`input[type=file]`）
  - `file_path`: 要上传文件的**绝对路径**（默认允许任意目录；可通过 `upload_allow_any_path=false` 限定仅允许白名单目录内的文件，出于安全考虑会拒绝其他路径）
  - 返回: 上传成功或失败的信息

- **`browser_download`** - 下载文件（自动发送给用户）
  - `url`: 文件 URL
  - `filename`: 保存文件名（可选）

- **`browser_list_files`** - 列出下载/截图目录的文件
  - `dir_type`: 目录类型 (`downloads`/`screenshots`)
  - `limit`: 最大显示数量

- **`browser_send_file`** - 发送指定文件给用户
  - `filepath`: 文件完整路径
  - `as_image`: 是否作为图片发送

### 键盘模拟

- **`browser_keyboard_type`** - 模拟键盘输入文本
  - `text`: 要输入的文本
  - `delay`: 每个字符之间的延迟（毫秒）

- **`browser_keyboard_press`** - 模拟按下按键
  - `key`: 按键名称，如 `Enter`, `Tab`, `Control+a`, `Shift+Tab`

- **`browser_keyboard_down_up`** - 按住或释放键盘按键（用于复杂组合键）
  - `action`: `down` 或 `up`
  - `key`: 按键名称

### 鼠标模拟

- **`browser_mouse_move`** - 移动鼠标到指定坐标
  - `x`: X坐标
  - `y`: Y坐标
  - `steps`: 步数（越大越平滑）

- **`browser_mouse_click`** - 在指定坐标点击
  - `x`, `y`: 坐标（可选，不指定则在当前位置点击）
  - `button`: 按钮 (`left`/`right`/`middle`)
  - `click_count`: 点击次数

- **`browser_mouse_down_up`** - 按住或释放鼠标按键
  - `action`: `down`/`up`
  - `button`: 按键 (`left`/`right`/`middle`)

### 等待

- **`browser_wait`** - 等待加载
  - `selector`: 等待元素出现（可选）
  - `seconds`: 等待秒数（默认1秒）

## 常见问题

### Q: 为什么截图没有自动发送？
检查 `auto_send_screenshot` 配置是否为 `auto`，以及 `auto_describe_screenshot` 是否为 `true`。

### Q: VLM 描述不生效？
确认在 LLM 模型组中配置了视觉模型，并已在插件配置中选择。

### Q: Cookie 没有自动加载？
确认 cookie JSON 文件位于 `cookies_dir` 配置的目录下（默认 `data/files/cookie/`），且文件为标准的 Chrome 导出格式。

### Q: 如何分享插件而不泄露 Cookie？
`data/files/cookie/` 已被 `manifest.json` 的 `exclude` 字段声明为打包排除项，同时被 `.gitignore` 忽略。分享前请确认该目录不在你的分享内容中。
