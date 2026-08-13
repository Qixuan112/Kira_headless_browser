# 无头浏览器插件 (Headless Browser Plugin) 1.1.0

让 KiraAI 能够控制无头浏览器进行网页浏览、截图、下载、上传等操作，支持通过给AI发送cookie半持久化登录各种账号。

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
- 页面是否已完全加载
- 是否有错误提示、弹窗、警告
- 是否需要登录才能操作

### 4. 关键内容
- 页面的主要内容/搜索结果
- 是否有验证码、人机验证
- 是否有弹窗广告遮挡

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
2. 保存为 JSON 文件，放入 `data/files/cookie/` 目录；或通过各种形式完整发送给AI读取后让其自行处理（需要其具有读写相应路径文件的权限）
3. 建议按站点名命名方便管理，如 `chatgpt.json`
4. 重载插件或重启 KiraAI 即可自动加载

**安全隔离：**
`data/files/cookie/` 目录位于项目数据目录下，**不随插件文件打包**。分享插件源码时，你的 Cookie 信息不会泄露。如需分享，请确保移除该目录。
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
  - `steps`: 移动步数（越大越平滑）

- **`browser_mouse_click`** - 在指定坐标点击
  - `x`, `y`: 坐标（可选，不指定则在当前位置点击）
  - `button`: 按钮 (`left`/`right`/`middle`)
  - `click_count`: 点击次数

- **`browser_mouse_down_up`** - 按住或释放鼠标按键
  - `action`: `down` 或 `up`
  - `button`: 鼠标按钮

- **`browser_mouse_wheel`** - 鼠标滚轮滚动
  - `delta_x`: 水平滚动距离
  - `delta_y`: 垂直滚动距离（正数向下）

- **`browser_mouse_drag`** - 鼠标拖拽
  - `start_x`, `start_y`: 起始坐标
  - `end_x`, `end_y`: 目标坐标
  - `button`: 鼠标按钮
  - `steps`: 移动步数

- **`browser_hover`** - 将鼠标悬停在指定元素上
  - `selector`: CSS选择器

### 其他

- **`browser_wait`** - 等待元素出现或等待指定时间
  - `seconds`: 等待秒数
  - `selector`: 等待该元素出现

### 调试工具

- **`browser_debug`** - 调试浏览器状态

- **`browser_check_vlm`** - 检查VLM模型配置状态

- **`browser_test_visible`** - 测试浏览器可视模式

## 使用示例

### 示例 1: 访问网页并截图

```
用户: 帮我打开 https://www.example.com 并截图看看

AI:
1. browser_navigate(url="https://www.example.com")
2. browser_screenshot()
```

### 示例 2: 填写表单

```
用户: 打开登录页，输入用户名 test 和密码 123456

AI:
1. browser_navigate(url="https://example.com/login")
2. browser_screenshot()  # 查看页面结构
3. browser_fill(selector="#username", value="test")
4. browser_fill(selector="#password", value="123456")
5. browser_click(selector="#submit-btn")
6. browser_screenshot()  # 确认结果
```

### 示例 3: 下载文件

```
用户: 下载这个文件 https://example.com/file.pdf

AI:
browser_download(url="https://example.com/file.pdf", filename="document.pdf")
```

### 示例 4: 执行 JavaScript

```
用户: 获取当前页面的 cookie

AI:
browser_execute_js(script="document.cookie")
```

### 示例 5: 使用键盘操作

```
用户: 在搜索框输入 "Python" 然后按回车搜索

AI:
1. browser_navigate(url="https://www.baidu.com")
2. browser_click(selector="#kw")  # 聚焦搜索框
3. browser_keyboard_type(text="Python")
4. browser_keyboard_press(key="Enter")
5. browser_wait(seconds=2)
6. browser_screenshot()
```

### 示例 6: 使用鼠标点击坐标

```
用户: 点击屏幕中央（假设按钮在 960, 540）

AI:
1. browser_navigate(url="https://www.example.com")
2. browser_mouse_move(x=960, y=540)
3. browser_mouse_click()  # 在当前位置点击
4. browser_screenshot()
```

### 示例 7: 鼠标拖拽

```
用户: 把左边的滑块拖到右边

AI:
1. browser_navigate(url="https://www.example.com/drag")
2. browser_mouse_drag(start_x=100, start_y=300, end_x=400, end_y=300, steps=20)
3. browser_screenshot()
```

### 示例 8: 模拟组合键

```
用户: 全选页面内容并复制

AI:
1. browser_click(selector="body")  # 聚焦页面
2. browser_keyboard_press(key="Control+a")  # 全选
3. browser_keyboard_press(key="Control+c")  # 复制
4. browser_keyboard_type(text="已复制页面内容")
```

## 注意事项

1. **首次使用需要安装 Playwright**: 运行 `playwright install chromium` 安装浏览器
2. **截图会自动发送**: 使用 `browser_screenshot` 后，图片会自动发送给用户
3. **下载文件会自动发送**: 使用 `browser_download` 后，文件会自动发送给用户
4. **文件保存位置**: 截图和下载的文件保存在插件数据目录下

## 故障排除

### ImportError: playwright
```bash
pip install playwright
playwright install chromium
```

### 页面加载超时
- 检查网络连接
- 增加 `timeout` 配置值
- 使用 `wait_until="domcontentloaded"` 替代 `networkidle`

### 元素找不到
- 先截图查看页面结构
- 检查 CSS 选择器是否正确
- 等待页面完全加载后再操作

## 许可证

AGPL-3.0 License
