"""
无头浏览器插件 - Headless Browser Plugin

让 AI 能够控制无头浏览器进行网页浏览、截图、下载等操作
功能包括：
- 浏览器控制：访问页面、点击、填写表单、滚动等
- 截图功能：截取页面或元素，返回给 AI 查看
- 文件管理：下载文件、保存截图到指定目录
- 页面信息获取：标题、URL、HTML内容、页面文本等
"""

import asyncio
import base64
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal

from core.plugin import BasePlugin, logger, register, on
from core.chat.message_utils import MessageChain
from core.chat.message_elements import Image, Text, File


# ============ VLM 提示词 ============
VLM_TOOL_OPTIMIZED_PROMPT = """你是一名专业的网页分析助手。请分析这张网页截图，提取对后续自动化操作有用的信息。

## 请按以下格式输出：

### 1. 页面基本信息
- 页面标题：
- 当前URL（如有显示）：
- 页面类型（搜索页/表单页/内容页/错误页等）：

### 2. 可交互元素清单（关键！）
请列出所有可见的按钮、链接、输入框：
- 搜索框：是否有？位置大概在哪？placeholder文字是什么？
- 按钮：列出所有按钮的文字和大概位置（如"左上角搜索按钮"）
- 链接：重要的导航链接
- 表单字段：有哪些输入框、下拉菜单

### 3. 当前状态
- 页面是否已完全加载？
- 是否有加载中/转圈动画？
- 是否有错误提示、弹窗、警告？
- 是否需要登录才能操作？

### 4. 关键内容
- 页面的主要内容/搜索结果是什么？
- 是否有验证码、人机验证？
- 是否有弹窗广告遮挡？

### 5. 建议的下一步操作
基于当前页面，建议：
- 如果要搜索：点击哪里、输入什么
- 如果要点击某个内容：建议点击哪个元素（用CSS选择器描述，如 #id、.class）
- 如果要填写表单：每个字段填什么
- 如果需要等待：建议等待什么元素出现

### 6. 坐标参考（如需要鼠标操作）
- 重要元素的大致坐标（基于1920x1080分辨率）
- 如：搜索框在屏幕中央偏上 (960, 450)

请尽量详细，让另一个AI能根据你的描述直接调用浏览器工具完成操作。"""


# ============ 工具使用提示 ============
BROWSER_TOOLS_PROMPT = """\
## 无头浏览器工具使用说明

你可以使用浏览器工具帮助用户完成网页操作任务。

### 📸 截图发送模式（重要）

根据 `auto_send_screenshot` 配置：

**auto 模式（默认）：**
- `browser_screenshot()` 截图后会【自动发送】图片给用户
- 你只需告诉用户"截图已发送，可以看到..."
- 【严禁】再次调用 `browser_send_file()`

**manual 模式：**
- `browser_screenshot()` 截图后【不会自动发送】
- 你会收到截图的 VLM 分析描述
- 根据内容决定是否发送：`browser_send_file(filepath="...", as_image=true)`

**下载文件：**
- `browser_download()` 下载后会【自动发送】文件给用户
- 【严禁】再次调用 `browser_send_file()`

### 🛠️ 工具分类

**页面导航：**
- `browser_navigate(url)` - 访问网页
- `browser_click(selector)` - 点击元素（推荐）
- `browser_fill(selector, value)` - 填写表单
- `browser_scroll(direction)` - 滚动页面
- `browser_go_back()` / `browser_refresh()` - 返回/刷新

**内容获取：**
- `browser_screenshot()` - 截图
- `browser_get_text(selector)` - 获取页面文本
- `browser_get_info()` - 获取标题和URL
- `browser_execute_js(script)` - 执行JS

**等待：**
- `browser_wait(seconds)` - 等待秒数
- `browser_wait(selector="...")` - 等待元素出现

**键盘模拟：**
- `browser_keyboard_type(text)` - 输入文本
- `browser_keyboard_press(key)` - 按键（支持组合键如 "Control+a"）
- `browser_keyboard_down_up(action, key)` - 按住/释放键

**鼠标模拟：**
- `browser_mouse_move(x, y)` - 移动鼠标
- `browser_mouse_click(x, y)` - 点击（不传坐标则在当前位置点击）
- `browser_mouse_down_up(action, button)` - 按住/释放鼠标键
- `browser_mouse_wheel(delta_y)` - 滚轮滚动
- `browser_mouse_drag(start_x, start_y, end_x, end_y)` - 拖拽

### ⌨️ 键盘常用按键

- 单键: `Enter`, `Tab`, `Escape`, `Backspace`, `Delete`, `ArrowUp`, `ArrowDown`, `ArrowLeft`, `ArrowRight`
- 组合键: `Control+a`, `Control+c`, `Control+v`, `Control+Enter`
- 修饰键: `Shift`, `Control`, `Alt`（用于 browser_keyboard_down_up）

### 🖱️ 鼠标坐标系

- 左上角为原点 (0, 0)
- X 向右增加，Y 向下增加
- 视口大小默认为 1920x1080

**参数区分：**
- 键盘工具用 `key`: `browser_keyboard_down_up(action="down", key="Control")`
- 鼠标工具用 `button`: `browser_mouse_down_up(action="down", button="left")`

### 📋 标准操作流程

**推荐步骤：**
1. `browser_navigate(url="...")` - 访问页面
2. `browser_screenshot()` - 截图确认页面状态
3. 根据 VLM 分析，使用 `browser_click(selector)` 或 `browser_fill(selector, value)` 操作
4. `browser_wait(seconds=2)` - 等待加载
5. `browser_screenshot()` - 查看结果

**示例：搜索操作**
```
browser_navigate(url="https://www.baidu.com")
browser_screenshot()
browser_click(selector="#kw")  # 或 browser_mouse_click(x=960, y=450)
browser_keyboard_type(text="Python教程")
browser_keyboard_press(key="Enter")
browser_wait(selector="#content_left", seconds=3)
browser_screenshot()
```

**示例：鼠标拖拽**
```
browser_mouse_move(x=100, y=200)
browser_mouse_down_up(action="down", button="left")
browser_mouse_move(x=400, y=200, steps=10)
browser_mouse_down_up(action="up", button="left")
browser_keyboard_press(key="Control+c")
```

### 🖼️ VLM 截图描述

VLM 会分析截图并返回结构化信息：
1. 页面基本信息（标题、URL、类型）
2. 可交互元素清单（按钮、输入框位置）
3. 当前状态（加载完成、错误弹窗）
4. 关键内容（验证码、广告）
5. 建议的下一步操作
6. 坐标参考（用于鼠标操作）

### 🔧 处理隐藏元素

如果按钮存在但不可见（CSS display:none）：
1. 使用 JS 点击: `browser_execute_js(script="document.querySelector('#id').click()")`
2. 或直接按 Enter 提交表单
3. 尝试点击其他可见按钮

**表单提交备选方案：**
- 点击提交按钮: `browser_click(selector="#submit")`
- 按 Enter 键: `browser_keyboard_press(key="Enter")`
- JS 提交: `browser_execute_js(script="document.querySelector('form').submit()")`
"""


class HeadlessBrowserPlugin(BasePlugin):
    """
    无头浏览器插件主类
    基于 Playwright 实现浏览器自动化控制
    """
    
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        # 解析 headless 配置（处理字符串和布尔值）
        headless_val = cfg.get("headless", True)
        if isinstance(headless_val, str):
            self.headless: bool = headless_val.lower() in ("true", "1", "yes", "on")
        else:
            self.headless: bool = bool(headless_val)
        self.default_viewport = self._parse_viewport(cfg.get("default_viewport", "1920x1080"))
        self.timeout: int = cfg.get("timeout", 60)
        self.user_agent: Optional[str] = cfg.get("user_agent") or None
        self.auto_send: str = cfg.get("auto_send_screenshot", "auto")
        self.auto_describe: bool = bool(cfg.get("auto_describe_screenshot", True))
        self.vlm_model: str = cfg.get("vlm_model", "")
        self.vlm_describe_prompt: str = cfg.get("vlm_describe_prompt", "")
        self.vlm_timeout: int = cfg.get("vlm_timeout", 10)
        
        # 设置目录
        data_dir = ctx.get_plugin_data_dir()
        # 截图默认保存到 data/temp，支持自动清理
        self.screenshot_dir = cfg.get("screenshot_dir") or str(Path("data/temp"))
        self.download_dir = cfg.get("download_dir") or str(data_dir / "downloads")
        self.screenshot_max_count: int = cfg.get("screenshot_max_count", 50)  # 最多保留50张截图
        self.screenshot_auto_clean: bool = bool(cfg.get("screenshot_auto_clean", True))  # 自动清理开关
        
        # 浏览器实例
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._initialized = False
        
    def _parse_viewport(self, viewport_str: str) -> dict:
        """解析视口大小字符串"""
        try:
            width, height = map(int, viewport_str.lower().split("x"))
            return {"width": width, "height": height}
        except:
            return {"width": 1920, "height": 1080}
    
    async def initialize(self):
        """插件初始化"""
        # 创建目录
        os.makedirs(self.screenshot_dir, exist_ok=True)
        os.makedirs(self.download_dir, exist_ok=True)
        
        # 如果浏览器已在运行，先关闭（支持配置热重载）
        if self._browser is not None:
            logger.info("[HeadlessBrowser] 检测到浏览器已在运行，关闭以应用新配置")
            await self._close_browser()
        
        logger.info(f"[HeadlessBrowser] 无头浏览器插件已加载")
        logger.info(f"[HeadlessBrowser] 无头模式: {self.headless}")
        logger.info(f"[HeadlessBrowser] 视口大小: {self.default_viewport}")
        logger.info(f"[HeadlessBrowser] 截图目录: {self.screenshot_dir}")
        logger.info(f"[HeadlessBrowser] 截图自动清理: {'开启' if self.screenshot_auto_clean else '关闭'} (最大保留 {self.screenshot_max_count} 张)")
        logger.info(f"[HeadlessBrowser] 下载目录: {self.download_dir}")
        
        if not self.headless:
            logger.info("[HeadlessBrowser] 当前为可视模式，浏览器窗口将会显示")
            import platform
            if platform.system() == "Windows":
                logger.info("[HeadlessBrowser] Windows 系统：请确保未最小化浏览器窗口")
    
    async def terminate(self):
        """插件卸载清理"""
        await self._close_browser()
        logger.info("[HeadlessBrowser] 无头浏览器插件已卸载")
    
    async def _ensure_browser(self):
        """确保浏览器已启动"""
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright
                
                self._playwright = await async_playwright().start()
                
                # Windows 可视模式需要额外参数
                launch_args = {
                    "headless": self.headless,
                    "downloads_path": self.download_dir
                }
                
                # 非无头模式下的特殊处理
                if not self.headless:
                    import platform
                    if platform.system() == "Windows":
                        # Windows 可视模式需要的关键参数
                        launch_args["args"] = [
                            "--start-maximized",
                            "--window-position=100,100",
                            "--window-size=1920,1080",
                            "--force-device-scale-factor=1",
                            "--disable-background-timer-throttling",
                            "--disable-backgrounding-occluded-windows",
                            "--disable-renderer-backgrounding",
                            "--disable-features=TranslateUI",
                            "--disable-extensions",
                            "--disable-plugins",
                            "--no-sandbox",
                            "--disable-setuid-sandbox"
                        ]
                        # 使用较慢的启动确保窗口可见
                        launch_args["slow_mo"] = 100
                        logger.info("[HeadlessBrowser] Windows 可视模式已启用")
                        logger.info(f"[HeadlessBrowser] 窗口参数: {launch_args['args']}")
                
                # 启动浏览器
                logger.info(f"[HeadlessBrowser] 正在启动浏览器，headless={self.headless}")
                self._browser = await self._playwright.chromium.launch(**launch_args)
                logger.info(f"[HeadlessBrowser] 浏览器对象已创建: {self._browser is not None}")
                
                # 创建上下文 - 可视模式下不使用固定视口
                context_options = {
                    "accept_downloads": True
                }
                
                # 无头模式下使用固定视口，可视模式下使用默认视口
                if self.headless:
                    context_options["viewport"] = self.default_viewport
                else:
                    # 可视模式下不设置固定视口，让浏览器使用实际窗口大小
                    context_options["viewport"] = None
                    context_options["no_viewport"] = True
                
                if self.user_agent:
                    context_options["user_agent"] = self.user_agent
                
                logger.info(f"[HeadlessBrowser] 创建上下文，参数: {context_options}")
                self._context = await self._browser.new_context(**context_options)
                logger.info(f"[HeadlessBrowser] 上下文已创建: {self._context is not None}")
                
                # 创建页面
                self._page = await self._context.new_page()
                self._page.set_default_timeout(self.timeout * 1000)
                
                logger.info("[HeadlessBrowser] 浏览器已启动")
            except ImportError:
                raise ImportError("请先安装 Playwright: pip install playwright && playwright install chromium")
            except Exception as e:
                logger.error(f"[HeadlessBrowser] 启动浏览器失败: {e}")
                raise
    
    async def _close_browser(self):
        """关闭浏览器"""
        if self._page:
            await self._page.close()
            self._page = None
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("[HeadlessBrowser] 浏览器已关闭")
    
    def _generate_filename(self, prefix: str = "screenshot", ext: str = "png") -> str:
        """生成带时间戳的文件名"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{timestamp}.{ext}"
    
    def _clean_old_screenshots(self):
        """自动清理旧的截图文件，保留最新的指定数量"""
        if not self.screenshot_auto_clean:
            return
        
        try:
            import glob
            # 获取所有截图文件
            pattern = os.path.join(self.screenshot_dir, "screenshot_*.png")
            files = glob.glob(pattern)
            
            if len(files) <= self.screenshot_max_count:
                return
            
            # 按修改时间排序
            files.sort(key=lambda x: os.path.getmtime(x))
            
            # 删除最旧的文件
            files_to_delete = files[:len(files) - self.screenshot_max_count]
            deleted_count = 0
            
            for file_path in files_to_delete:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    logger.debug(f"[HeadlessBrowser] 删除旧截图失败: {file_path}, {e}")
            
            if deleted_count > 0:
                logger.info(f"[HeadlessBrowser] 自动清理了 {deleted_count} 张旧截图，保留最新的 {self.screenshot_max_count} 张")
        
        except Exception as e:
            logger.debug(f"[HeadlessBrowser] 清理旧截图时出错: {e}")
    
    async def _send_image_to_session(self, session_str: str, image: Image) -> bool:
        """
        通过适配器直接发送图片到指定会话
        """
        try:
            parts = session_str.split(":")
            if len(parts) != 3:
                logger.error(f"[HeadlessBrowser] 无效的session格式: {session_str}")
                return False
            
            adapter_name, chat_type, pid = parts
            logger.debug(f"[HeadlessBrowser] 准备发送图片，适配器: {adapter_name}, 类型: {chat_type}, ID: {pid}")
            
            adapter = self.ctx.adapter_mgr.get_adapter(adapter_name)
            if not adapter:
                logger.error(f"[HeadlessBrowser] 未找到适配器: {adapter_name}")
                return False
            
            from core.chat.message_utils import MessageChain
            chain = MessageChain([image])
            
            if chat_type == "gm":
                logger.debug(f"[HeadlessBrowser] 调用 send_group_message，群ID: {pid}")
                result = await adapter.send_group_message(pid, chain)
            else:
                logger.debug(f"[HeadlessBrowser] 调用 send_direct_message，用户ID: {pid}")
                result = await adapter.send_direct_message(pid, chain)
            
            logger.debug(f"[HeadlessBrowser] 发送结果: {result}, ok={getattr(result, 'ok', False)}")
            
            if result and getattr(result, 'ok', False):
                logger.info(f"[HeadlessBrowser] 图片发送成功: {session_str}")
                return True
            else:
                logger.error(f"[HeadlessBrowser] 图片发送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"[HeadlessBrowser] 发送图片异常: {e}")
            import traceback
            logger.debug(f"[HeadlessBrowser] 发送异常详情: {traceback.format_exc()}")
            return False
    
    async def _send_file_to_session(self, session_str: str, file_obj: File) -> bool:
        """
        通过适配器直接发送文件到指定会话
        """
        try:
            parts = session_str.split(":")
            if len(parts) != 3:
                logger.error(f"[HeadlessBrowser] 无效的session格式: {session_str}")
                return False
            
            adapter_name, chat_type, pid = parts
            logger.debug(f"[HeadlessBrowser] 准备发送文件，适配器: {adapter_name}, 类型: {chat_type}, ID: {pid}")
            
            adapter = self.ctx.adapter_mgr.get_adapter(adapter_name)
            if not adapter:
                logger.error(f"[HeadlessBrowser] 未找到适配器: {adapter_name}")
                return False
            
            from core.chat.message_utils import MessageChain
            chain = MessageChain([file_obj])
            
            if chat_type == "gm":
                logger.debug(f"[HeadlessBrowser] 调用 send_group_message，群ID: {pid}")
                result = await adapter.send_group_message(pid, chain)
            else:
                logger.debug(f"[HeadlessBrowser] 调用 send_direct_message，用户ID: {pid}")
                result = await adapter.send_direct_message(pid, chain)
            
            logger.debug(f"[HeadlessBrowser] 发送结果: {result}, ok={getattr(result, 'ok', False)}")
            
            if result and getattr(result, 'ok', False):
                logger.info(f"[HeadlessBrowser] 文件发送成功: {session_str}")
                return True
            else:
                logger.error(f"[HeadlessBrowser] 文件发送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"[HeadlessBrowser] 发送文件异常: {e}")
            import traceback
            logger.debug(f"[HeadlessBrowser] 发送异常详情: {traceback.format_exc()}")
            return False
    
    def _is_vision_model(self, model_client) -> bool:
        """
        宽松判断模型是否可用于视觉任务。
        KiraAI 的 desc_img 本身不做视觉能力校验，模型是否支持视觉由实际调用决定，
        这里只排除明确不具备视觉能力的模型类型，避免硬编码关键词误杀视觉模型。
        """
        if not model_client or not model_client.model:
            return False
        model_id = model_client.model.model_id.lower()
        # 仅排除明确无视觉能力的类型/模型
        non_vision_markers = ['embedding', 'rerank', 'tts', 'stt', 'davinci', 'babbage', 'whisper']
        return not any(marker in model_id for marker in non_vision_markers)
    
    async def _get_vlm_client(self):
        """获取用于图片描述的VLM客户端（必须是LLMModelClient）"""
        from core.provider import LLMModelClient
        
        # 优先使用插件配置的VLM模型
        if self.vlm_model:
            try:
                client = self.ctx.get_llm_client(model_uuid=self.vlm_model)
                if client and isinstance(client, LLMModelClient):
                    if self._is_vision_model(client):
                        logger.info(f"[HeadlessBrowser] 使用配置的VLM模型: {self.vlm_model}")
                        return client
                    else:
                        logger.warning(f"[HeadlessBrowser] 配置的模型 {self.vlm_model} 不支持视觉")
                else:
                    logger.warning(f"[HeadlessBrowser] 配置的模型 {self.vlm_model} 不是LLM类型")
            except Exception as e:
                logger.warning(f"[HeadlessBrowser] 获取配置的VLM模型失败: {e}")
        
        # 回退到系统默认VLM（default_vlm，即系统默认识图模型）
        try:
            vlm_client = self.ctx.provider_mgr.get_default_vlm()
            if vlm_client and isinstance(vlm_client, LLMModelClient):
                if self._is_vision_model(vlm_client):
                    logger.info(f"[HeadlessBrowser] 使用系统默认VLM模型: {vlm_client.model.model_id}")
                    return vlm_client
                else:
                    logger.warning(f"[HeadlessBrowser] 系统默认VLM模型 {vlm_client.model.model_id} 不支持视觉")
        except Exception as e:
            logger.warning(f"[HeadlessBrowser] 获取系统默认VLM失败（可能未配置）: {e}")
        
        # 最后尝试当前默认LLM（如果是视觉模型）
        try:
            current_llm = self.ctx.get_default_llm_client()
            if current_llm and self._is_vision_model(current_llm):
                logger.info(f"[HeadlessBrowser] 使用默认LLM模型(支持视觉): {current_llm.model.model_id}")
                return current_llm
        except Exception as e:
            logger.warning(f"[HeadlessBrowser] 获取默认LLM失败: {e}")
        
        return None
    
    async def _describe_screenshot(self, image: Image) -> str:
        """
        使用VLM描述截图内容（带超时保护）
        """
        from core.utils.common_utils import desc_img
        from core.provider import LLMModelClient
        
        try:
            # 获取VLM客户端
            vlm_client = await self._get_vlm_client()
            
            if not vlm_client:
                logger.debug("[HeadlessBrowser] 未找到可用的VLM模型，跳过描述")
                return ""
            
            # 检查模型类型
            if not isinstance(vlm_client, LLMModelClient):
                logger.warning("[HeadlessBrowser] VLM模型不是LLM类型，跳过描述")
                return ""
            
            # 检查模型是否支持视觉
            if not self._is_vision_model(vlm_client):
                model_id = vlm_client.model.model_id if vlm_client.model else "unknown"
                logger.warning(f"[HeadlessBrowser] 模型 {model_id} 不支持视觉，跳过描述")
                return ""
            
            model_id = vlm_client.model.model_id if vlm_client.model else "unknown"
            logger.info(f"[HeadlessBrowser] 使用模型 {model_id} 描述截图")
            
            # 使用自定义提示词（如果有），否则使用默认工具优化提示词
            prompt = self.vlm_describe_prompt if self.vlm_describe_prompt else VLM_TOOL_OPTIMIZED_PROMPT
            
            # 使用VLM描述图片（带超时）
            description = await asyncio.wait_for(
                desc_img(
                    client=vlm_client,
                    image=image,
                    prompt=prompt
                ),
                timeout=self.vlm_timeout
            )
            return description
        except asyncio.TimeoutError:
            logger.warning(f"[HeadlessBrowser] VLM描述超时（{self.vlm_timeout}秒），跳过描述")
            return ""
        except Exception as e:
            logger.warning(f"[HeadlessBrowser] VLM描述失败: {e}")
            return ""
    
    # ============ LLM提示注入 ============
    
    @on.llm_request(priority=10)
    async def inject_tools_prompt(self, *args, **kwargs):
        """向AI注入浏览器工具使用说明"""
        from core.prompt_manager import Prompt
        # args: (event, req, ...)
        if len(args) >= 2:
            req = args[1]
        else:
            req = kwargs.get('req')
        if req and hasattr(req, 'system_prompt'):
            req.system_prompt.append(Prompt(
                name="headless_browser_tools",
                content=BROWSER_TOOLS_PROMPT
            ))
    
    # ============ 浏览器控制工具 ============
    
    @register.tool(
        name="browser_navigate",
        description="访问指定URL，打开网页。如果超时失败，可以尝试使用 wait_until='domcontentloaded' 或 'load'",
        params={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要访问的网址URL"},
                "wait_until": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle"], "description": "等待页面加载完成的状态。networkidle等待网络空闲(较慢但完整)，domcontentloaded等待DOM加载(较快)，load等待load事件。默认为networkidle", "default": "networkidle"}
            },
            "required": ["url"]
        }
    )
    async def navigate(self, event, url: str, wait_until: str = "networkidle") -> str:
        """访问指定URL"""
        await self._ensure_browser()
        try:
            await self._page.goto(url, wait_until=wait_until)
            title = await self._page.title()
            return f"✅ 已成功访问页面\n📄 标题: {title}\n🔗 URL: {self._page.url}"
        except Exception as e:
            return f"❌ 访问页面失败: {str(e)}"
    
    @register.tool(
        name="browser_screenshot",
        description="截取当前页面或指定元素的截图。根据auto_send_screenshot配置，图片可以自动发送或让AI决定何时发送",
        params={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS选择器，如果指定则截取该元素，否则截取整个页面", "default": ""},
                "filename": {"type": "string", "description": "截图文件名（可选，默认自动生成）", "default": ""},
                "full_page": {"type": "boolean", "description": "是否截取完整页面（仅整页截图时有效）", "default": False},
                "send_now": {"type": "boolean", "description": "是否立即发送图片（仅当auto_send_screenshot为manual时有效）", "default": False}
            }
        }
    )
    async def screenshot(self, event, selector: str = "", filename: str = "", full_page: bool = False, send_now: bool = False) -> str:
        """截图并返回图片"""
        await self._ensure_browser()
        
        try:
            # 生成文件名
            if not filename:
                filename = self._generate_filename("screenshot" if not selector else "element", "png")
            
            # 确保有扩展名
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                filename = filename + ".png"
            
            filepath = os.path.join(self.screenshot_dir, filename)
            
            # 截图
            if selector:
                element = await self._page.query_selector(selector)
                if not element:
                    return f"❌ 未找到元素: {selector}"
                await element.screenshot(path=filepath)
            else:
                await self._page.screenshot(path=filepath, full_page=full_page)
            
            # 清理旧截图
            self._clean_old_screenshots()
            
            # 创建图片对象
            image_obj = Image(image=filepath)
            
            # 判断是否自动发送
            should_send = (self.auto_send == "auto") or (self.auto_send == "manual" and send_now)
            
            if should_send:
                # 发送图片给用户
                sent = await self._send_image_to_session(str(event.session), image_obj)
                
                # 如果使用VLM自动描述（仅在自动发送时进行描述）
                description = ""
                if self.auto_describe:
                    try:
                        description = await self._describe_screenshot(image_obj)
                    except Exception as e:
                        logger.warning(f"[HeadlessBrowser] VLM描述截图失败: {e}")
                
                if sent:
                    if description:
                        return f"✅ 截图已保存: {filepath}\n✅ 图片已发送\n\n🖼️ 图片描述:\n{description}"
                    return f"✅ 截图已保存: {filepath}\n✅ 图片已发送"
                else:
                    if description:
                        return f"✅ 截图已保存: {filepath}\n❌ 图片发送失败\n\n🖼️ 图片描述:\n{description}"
                    return f"✅ 截图已保存: {filepath}\n❌ 图片发送失败"
            else:
                # 手动模式：不发送，只返回信息让AI决定
                # 使用VLM分析截图（如果配置了VLM）
                description = ""
                try:
                    vlm_client = await self._get_vlm_client()
                    if vlm_client and self._is_vision_model(vlm_client):
                        from core.utils.common_utils import desc_img
                        # 使用自定义提示词（如果有），否则使用默认工具优化提示词
                        prompt = self.vlm_describe_prompt if self.vlm_describe_prompt else VLM_TOOL_OPTIMIZED_PROMPT
                        description = await asyncio.wait_for(
                            desc_img(
                                client=vlm_client,
                                image=image_obj,
                                prompt=prompt
                            ),
                            timeout=self.vlm_timeout
                        )
                except asyncio.TimeoutError:
                    logger.debug(f"[HeadlessBrowser] VLM分析截图超时（{self.vlm_timeout}秒），跳过")
                except Exception as e:
                    logger.debug(f"[HeadlessBrowser] VLM分析截图失败: {e}")
                
                result = f"✅ 截图已保存: {filepath}\n"
                result += "⏳ 图片未发送（当前为手动模式，你可以查看截图内容后决定是否发送给用户）\n"
                result += f"\n📂 文件路径: {filepath}\n"
                
                if description:
                    result += f"\n🖼️ 截图内容分析:\n{description}\n"
                
                result += "\n💡 如需发送此图片给用户，请使用: browser_send_file(filepath=\"{}\", as_image=true)".format(filepath)
                return result
        except Exception as e:
            return f"❌ 截图失败: {str(e)}"
    
    @register.tool(
        name="browser_click",
        description="点击页面上的元素",
        params={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS选择器，指定要点击的元素"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "鼠标按钮，默认为left", "default": "left"},
                "count": {"type": "integer", "description": "点击次数，默认为1", "default": 1}
            },
            "required": ["selector"]
        }
    )
    async def click(self, event, selector: str, button: str = "left", count: int = 1) -> str:
        """点击页面元素"""
        await self._ensure_browser()
        try:
            await self._page.click(selector, button=button, click_count=count)
            return f"✅ 已点击元素: {selector}"
        except Exception as e:
            return f"❌ 点击失败: {str(e)}"
    
    @register.tool(
        name="browser_fill",
        description="在表单字段中填写文本",
        params={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS选择器，指定要填写的输入框"},
                "value": {"type": "string", "description": "要填写的文本内容"},
                "clear_first": {"type": "boolean", "description": "是否先清空字段，默认为true", "default": True}
            },
            "required": ["selector", "value"]
        }
    )
    async def fill(self, event, selector: str, value: str, clear_first: bool = True) -> str:
        """填写表单字段"""
        await self._ensure_browser()
        try:
            if clear_first:
                await self._page.fill(selector, value)
            else:
                await self._page.type(selector, value)
            return f"✅ 已在 {selector} 填写文本"
        except Exception as e:
            return f"❌ 填写失败: {str(e)}"
    
    @register.tool(
        name="browser_get_text",
        description="获取页面的文本内容，可指定选择器获取特定元素文本",
        params={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS选择器，如果指定则获取该元素文本，否则获取页面所有文本", "default": ""},
                "max_length": {"type": "integer", "description": "返回文本的最大长度，默认为3000", "default": 3000}
            }
        }
    )
    async def get_text(self, event, selector: str = "", max_length: int = 3000) -> str:
        """获取页面文本内容"""
        await self._ensure_browser()
        try:
            if selector:
                element = await self._page.query_selector(selector)
                if not element:
                    return f"❌ 未找到元素: {selector}"
                text = await element.inner_text()
            else:
                text = await self._page.inner_text("body")
            
            # 截断过长文本
            if len(text) > max_length:
                text = text[:max_length] + f"\n\n... (已截断，共 {len(text)} 字符)"
            
            return f"📄 页面文本内容:\n{text}"
        except Exception as e:
            return f"❌ 获取文本失败: {str(e)}"
    
    @register.tool(
        name="browser_get_info",
        description="获取当前页面的基本信息（标题、URL等）",
        params={
            "type": "object",
            "properties": {}
        }
    )
    async def get_info(self, event) -> str:
        """获取页面基本信息"""
        await self._ensure_browser()
        try:
            title = await self._page.title()
            url = self._page.url
            return f"📄 页面标题: {title}\n🔗 URL: {url}"
        except Exception as e:
            return f"❌ 获取信息失败: {str(e)}"
    
    @register.tool(
        name="browser_scroll",
        description="滚动页面",
        params={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["down", "up", "bottom", "top"], "description": "滚动方向"},
                "amount": {"type": "integer", "description": "滚动距离（像素），默认为800", "default": 800}
            },
            "required": ["direction"]
        }
    )
    async def scroll(self, event, direction: str, amount: int = 800) -> str:
        """滚动页面"""
        await self._ensure_browser()
        try:
            if direction == "down":
                await self._page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction == "up":
                await self._page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "bottom":
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "top":
                await self._page.evaluate("window.scrollTo(0, 0)")
            
            return f"✅ 已向{direction}滚动"
        except Exception as e:
            return f"❌ 滚动失败: {str(e)}"
    
    @register.tool(
        name="browser_go_back",
        description="返回上一页",
        params={
            "type": "object",
            "properties": {}
        }
    )
    async def go_back(self, event) -> str:
        """返回上一页"""
        await self._ensure_browser()
        try:
            await self._page.go_back()
            return f"✅ 已返回上一页\n📄 当前页面: {await self._page.title()}"
        except Exception as e:
            return f"❌ 返回失败: {str(e)}"
    
    @register.tool(
        name="browser_refresh",
        description="刷新当前页面",
        params={
            "type": "object",
            "properties": {}
        }
    )
    async def refresh(self, event) -> str:
        """刷新页面"""
        await self._ensure_browser()
        try:
            await self._page.reload()
            return f"✅ 页面已刷新\n📄 当前页面: {await self._page.title()}"
        except Exception as e:
            return f"❌ 刷新失败: {str(e)}"
    
    @register.tool(
        name="browser_execute_js",
        description="在页面中执行JavaScript代码并返回结果",
        params={
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "要执行的JavaScript代码"}
            },
            "required": ["script"]
        }
    )
    async def execute_js(self, event, script: str) -> str:
        """执行JavaScript代码"""
        await self._ensure_browser()
        try:
            result = await self._page.evaluate(script)
            return f"✅ JavaScript执行结果:\n{result}"
        except Exception as e:
            return f"❌ 执行失败: {str(e)}"
    
    @register.tool(
        name="browser_download",
        description="下载指定URL的文件到本地，下载完成后会自动发送给用户",
        params={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要下载的文件URL"},
                "filename": {"type": "string", "description": "保存的文件名（可选，默认从URL提取）", "default": ""}
            },
            "required": ["url"]
        }
    )
    async def download(self, event, url: str, filename: str = "") -> str:
        """下载文件"""
        try:
            import aiohttp
            
            # 确定文件名
            if not filename:
                filename = os.path.basename(url.split("?")[0]) or f"download_{int(time.time())}"
            
            filepath = os.path.join(self.download_dir, filename)
            
            # 下载文件
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.read()
                        with open(filepath, "wb") as f:
                            f.write(content)
                        
                        file_size = len(content)
                        
                        # 发送文件给用户
                        file_obj = File(file=filepath, name=filename, size=str(file_size))
                        sent = await self._send_file_to_session(str(event.session), file_obj)
                        if not sent:
                            return f"⚠️ 文件已下载: {filepath}\n📦 大小: {file_size} 字节\n❌ 但文件发送失败，请检查适配器配置"
                        
                        return f"✅ 文件已下载: {filepath}\n📦 大小: {file_size} 字节"
                    else:
                        return f"❌ 下载失败，HTTP状态码: {response.status}"
        except Exception as e:
            return f"❌ 下载失败: {str(e)}"
    
    @register.tool(
        name="browser_wait",
        description="等待指定时间或等待元素出现",
        params={
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "description": "等待秒数（如果指定了selector则忽略此项）", "default": 1},
                "selector": {"type": "string", "description": "CSS选择器，等待该元素出现", "default": ""}
            }
        }
    )
    async def wait(self, event, seconds: int = 1, selector: str = "") -> str:
        """等待"""
        await self._ensure_browser()
        try:
            if selector:
                await self._page.wait_for_selector(selector)
                return f"✅ 元素 {selector} 已出现"
            else:
                await asyncio.sleep(seconds)
                return f"✅ 已等待 {seconds} 秒"
        except Exception as e:
            return f"❌ 等待失败: {str(e)}"
    
    @register.tool(
        name="browser_list_files",
        description="列出下载目录或截图目录中的文件",
        params={
            "type": "object",
            "properties": {
                "dir_type": {"type": "string", "enum": ["downloads", "screenshots"], "description": "目录类型"},
                "limit": {"type": "integer", "description": "最多显示的文件数", "default": 20}
            },
            "required": ["dir_type"]
        }
    )
    async def list_files(self, event, dir_type: str, limit: int = 20) -> str:
        """列出文件"""
        try:
            if dir_type == "downloads":
                target_dir = self.download_dir
            else:
                target_dir = self.screenshot_dir
            
            files = os.listdir(target_dir)
            files.sort(key=lambda x: os.path.getmtime(os.path.join(target_dir, x)), reverse=True)
            
            if not files:
                return f"📂 {target_dir}\n暂无文件"
            
            lines = [f"📂 {target_dir}", f"共 {len(files)} 个文件（显示最新 {limit} 个）：", ""]
            
            for i, f in enumerate(files[:limit], 1):
                filepath = os.path.join(target_dir, f)
                size = os.path.getsize(filepath)
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"{i}. {f} ({size} bytes, {mtime})")
            
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 列出文件失败: {str(e)}"
    
    @register.tool(
        name="browser_test_visible",
        description="【可视模式测试】打开一个明显的测试页面，用于验证浏览器窗口是否可见。如果看不到窗口，请检查插件配置中的 headless 是否为 false",
        params={
            "type": "object",
            "properties": {}
        }
    )
    async def test_visible(self, event) -> str:
        """测试浏览器是否可见"""
        await self._ensure_browser()
        try:
            # 创建一个本地测试页面
            test_html = """<!DOCTYPE html>
<html>
<head>
    <title>浏览器可视模式测试</title>
    <style>
        body { 
            font-family: Arial, sans-serif; 
            text-align: center; 
            padding: 50px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
            margin: 0;
        }
        h1 { font-size: 48px; margin-bottom: 20px; }
        p { font-size: 24px; }
        .box {
            background: rgba(255,255,255,0.2);
            padding: 30px;
            border-radius: 20px;
            margin: 30px auto;
            max-width: 600px;
        }
    </style>
</head>
<body>
    <div class="box">
        <h1>🎉 浏览器窗口可见！</h1>
        <p>如果您能看到这个页面，说明浏览器正在以可视模式运行。</p>
        <p>当前时间：<span id="time"></span></p>
    </div>
    <script>
        document.getElementById('time').textContent = new Date().toLocaleString();
    </script>
</body>
</html>"""
            
            # 保存测试页面
            test_path = os.path.join(self.screenshot_dir, "test_visible.html")
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(test_html)
            
            # 打开测试页面
            await self._page.goto(f"file:///{test_path}")
            
            if self.headless:
                return f"⚠️ 当前为无头模式，浏览器窗口不可见\n测试页面已保存: {test_path}\n\n要看到浏览器窗口，请将插件配置中的 headless 改为 false 并重载插件"
            else:
                return f"✅ 可视模式测试页面已打开！\n\n如果您能看到一个紫色渐变背景的浏览器窗口，说明可视模式正常工作。\n如果看不到窗口，请检查:\n1. 窗口是否被其他窗口遮挡\n2. 是否在远程桌面环境（可能需要特殊配置）\n3. 尝试最小化其他窗口"
        except Exception as e:
            return f"❌ 测试失败: {str(e)}"
    
    @register.tool(
        name="browser_debug",
        description="调试浏览器状态，检查浏览器是否正常运行",
        params={
            "type": "object",
            "properties": {}
        }
    )
    async def debug_browser(self, event) -> str:
        """调试浏览器状态"""
        import platform
        info = [
            "🔍 浏览器调试信息:",
            "",
            f"操作系统: {platform.system()} {platform.release()}",
            f"无头模式: {self.headless}",
            f"浏览器已启动: {self._browser is not None}",
            f"页面已创建: {self._page is not None}",
        ]
        
        if self._page:
            try:
                url = self._page.url
                title = await self._page.title()
                info.extend([
                    f"当前URL: {url}",
                    f"当前标题: {title}",
                ])
            except:
                info.append("当前页面状态: 无法获取")
        
        if not self.headless:
            info.extend([
                "",
                "💡 可视模式排查:",
                "- 配置状态: headless=false（应该显示窗口）",
                "- 如果看不到窗口，请尝试:",
                "  1. 按 Alt+Tab 切换窗口，看是否有 Chrome/Chromium 窗口",
                "  2. 检查任务栏是否有浏览器图标",
                "  3. 尝试重启插件（配置更改后必须重载）",
                "  4. 在远程桌面环境下，可能需要保持远程会话活跃",
                "",
                "🔧 快速测试:",
                "调用 browser_test_visible 工具打开测试页面",
            ])
        else:
            info.extend([
                "",
                "ℹ️ 当前为无头模式（后台运行）",
                "如需显示浏览器窗口，请:",
                "1. 在插件配置中将 headless 改为 false",
                "2. 点击保存",
                "3. 重载插件或重启 KiraAI",
            ])
        
        return "\n".join(info)
    
    @register.tool(
        name="browser_check_vlm",
        description="检查VLM模型配置状态，显示当前使用的图片分析模型",
        params={
            "type": "object",
            "properties": {}
        }
    )
    async def check_vlm(self, event) -> str:
        """检查VLM配置"""
        from core.provider import LLMModelClient
        
        info = ["🔍 VLM模型配置检查:", ""]
        
        # 检查配置的VLM
        if self.vlm_model:
            info.append(f"✅ 插件配置的VLM: {self.vlm_model}")
        else:
            info.append("⚠️ 未在插件中配置专用VLM模型，将使用系统默认")
        
        # 检查描述配置
        # 获取实际使用的提示词（模板或自定义）
        actual_prompt = self.vlm_describe_prompt if self.vlm_describe_prompt else VLM_TOOL_OPTIMIZED_PROMPT
        prompt_preview = actual_prompt[:100] + "..." if len(actual_prompt) > 100 else actual_prompt
        info.extend([
            "",
            "📝 VLM 描述配置:",
            f"  自定义提示词: {'是' if self.vlm_describe_prompt else '否（使用默认模板）'}",
            f"  超时时间: {self.vlm_timeout} 秒",
            f"  提示词预览: {prompt_preview}",
        ])
        
        # 检查当前使用的VLM
        try:
            vlm_client = await self._get_vlm_client()
        except Exception as e:
            vlm_client = None
            info.append(f"❌ 获取VLM客户端异常: {e}")
        if vlm_client and vlm_client.model:
            model_id = vlm_client.model.model_id
            provider_id = vlm_client.model.provider_id
            model_uuid = f"{provider_id}:{model_id}"
            info.append(f"✅ 当前实际使用的VLM: {model_uuid}")
            
            if self._is_vision_model(vlm_client):
                info.append("✅ 该模型支持视觉分析")
            else:
                info.append("❌ 该模型不支持视觉分析，截图后将无法自动描述")
        else:
            info.append("❌ 未找到可用的VLM模型")
        
        # 列出所有可用的LLM模型
        info.extend(["", "📋 系统中已配置的LLM模型:"])
        try:
            vision_models = []
            other_models = []
            
            # 遍历所有 provider 获取模型
            all_providers = self.ctx.provider_mgr.get_all_providers()
            for provider_id, provider in all_providers.items():
                model_infos = self.ctx.provider_mgr.get_model_infos(provider_id)
                for model_info in model_infos:
                    if model_info.model_type.value == "llm":
                        model_uuid = f"{provider_id}:{model_info.model_id}"
                        # 简单判断是否为视觉模型
                        if any(kw in model_info.model_id.lower() for kw in ['vision', 'vl', 'gpt-4o', 'claude-3', 'kimi-k2', 'qwen-vl', 'yi-vl', 'glm-4v']):
                            vision_models.append(f"  👁️ {model_uuid}")
                        else:
                            other_models.append(f"  {model_uuid}")
            
            if vision_models:
                info.extend(["  推荐的视觉模型:"] + vision_models)
            if other_models:
                info.extend(["  其他模型:"] + other_models[:5])
            
            if not vision_models and not other_models:
                info.append("  ⚠️ 未找到任何LLM模型")
        except Exception as e:
            info.append(f"  获取模型列表失败: {e}")
        
        # 检查系统默认VLM配置
        info.extend(["", "🔧 系统默认VLM检查:"])
        try:
            default_vlm = self.ctx.provider_mgr.get_default_vlm()
            if default_vlm:
                if default_vlm.model:
                    info.append(f"  系统默认VLM: {default_vlm.model.provider_id}:{default_vlm.model.model_id}")
                    info.append(f"  类型: {type(default_vlm).__name__}")
                    info.append(f"  是否支持视觉: {self._is_vision_model(default_vlm)}")
                else:
                    info.append("  ⚠️ 系统默认VLM没有模型信息")
            else:
                info.append("  ⚠️ 未配置系统默认VLM模型")
                info.append("  请前往: 设置 → 默认模型 → 默认多模态模型")
        except Exception as e:
            info.append(f"  获取系统默认VLM失败: {e}")
        
        # 提示如何配置
        info.extend([
            "",
            "💡 配置说明:",
            "1. 在插件配置中选择 vlm_model（下拉框会显示所有已配置的模型）",
            "2. 建议选择带有 👁️ 标记的视觉模型",
            "3. 或在系统设置-默认模型中设置VLM模型",
        ])
        
        return "\n".join(info)
    
    @register.tool(
        name="browser_set_vlm_mode",
        description="【已弃用】VLM现在固定使用工具优化模式",
        params={
            "type": "object",
            "properties": {}
        }
    )
    async def set_vlm_mode(self, event) -> str:
        """【已弃用】临时切换VLM描述模式"""
        return "⚠️ 该功能已弃用。VLM 现在固定使用工具优化模式进行分析。\n如需自定义提示词，请在插件配置中设置 vlm_describe_prompt。"
    
    @register.tool(
        name="browser_send_file",
        description="发送指定文件给用户",
        params={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "文件完整路径"},
                "as_image": {"type": "boolean", "description": "是否作为图片发送（图片文件时建议设为true）", "default": False}
            },
            "required": ["filepath"]
        }
    )
    async def send_file(self, event, filepath: str, as_image: bool = False) -> str:
        """发送文件给用户"""
        try:
            if not os.path.exists(filepath):
                return f"❌ 文件不存在: {filepath}"
            
            file_size = os.path.getsize(filepath)
            filename = os.path.basename(filepath)
            
            if as_image:
                image_obj = Image(image=filepath)
                sent = await self._send_image_to_session(str(event.session), image_obj)
                if not sent:
                    return f"❌ 图片发送失败: {filename}"
            else:
                file_obj = File(file=filepath, name=filename, size=str(file_size))
                sent = await self._send_file_to_session(str(event.session), file_obj)
                if not sent:
                    return f"❌ 文件发送失败: {filename}"
            return f"✅ 文件已发送: {filename}"
        except Exception as e:
            return f"❌ 发送文件失败: {str(e)}"
    
    # ============ 键盘和鼠标模拟工具 ============
    
    @register.tool(
        name="browser_keyboard_type",
        description="模拟键盘输入文本到当前聚焦的元素",
        params={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要输入的文本"},
                "delay": {"type": "integer", "description": "每个字符之间的延迟（毫秒），默认为0", "default": 0}
            },
            "required": ["text"]
        }
    )
    async def keyboard_type(self, event, text: str, delay: int = 0) -> str:
        """模拟键盘输入文本"""
        await self._ensure_browser()
        try:
            await self._page.keyboard.type(text, delay=delay)
            return f"✅ 已输入文本: {text[:50]}{'...' if len(text) > 50 else ''}"
        except Exception as e:
            return f"❌ 输入失败: {str(e)}"
    
    @register.tool(
        name="browser_keyboard_press",
        description="模拟按下键盘按键，支持组合键（如 Ctrl+A、Enter、Tab 等）",
        params={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "按键名称，如 'Enter'、'Tab'、'Control+a'、'Shift+Tab' 等"}
            },
            "required": ["key"]
        }
    )
    async def keyboard_press(self, event, key: str) -> str:
        """模拟按键"""
        await self._ensure_browser()
        try:
            await self._page.keyboard.press(key)
            return f"✅ 已按下按键: {key}"
        except Exception as e:
            return f"❌ 按键失败: {str(e)}"
    
    @register.tool(
        name="browser_keyboard_down_up",
        description="模拟按住和释放键盘按键（用于组合键操作）",
        params={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["down", "up"], "description": "按下(down)或释放(up)按键"},
                "key": {"type": "string", "description": "按键名称，如 'Control'、'Shift'、'Alt'、'a' 等"}
            },
            "required": ["action", "key"]
        }
    )
    async def keyboard_down_up(self, event, action: str, key: str) -> str:
        """模拟按键按下/释放"""
        await self._ensure_browser()
        try:
            if action == "down":
                await self._page.keyboard.down(key)
                return f"✅ 已按住按键: {key}"
            else:
                await self._page.keyboard.up(key)
                return f"✅ 已释放按键: {key}"
        except Exception as e:
            return f"❌ 操作失败: {str(e)}"
    
    @register.tool(
        name="browser_mouse_move",
        description="模拟鼠标移动到指定坐标位置",
        params={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X坐标（像素）"},
                "y": {"type": "integer", "description": "Y坐标（像素）"},
                "steps": {"type": "integer", "description": "移动步数，越大越平滑，默认为1", "default": 1}
            },
            "required": ["x", "y"]
        }
    )
    async def mouse_move(self, event, x: int, y: int, steps: int = 1) -> str:
        """模拟鼠标移动"""
        await self._ensure_browser()
        try:
            await self._page.mouse.move(x, y, steps=steps)
            return f"✅ 鼠标已移动到: ({x}, {y})"
        except Exception as e:
            return f"❌ 移动失败: {str(e)}"
    
    @register.tool(
        name="browser_mouse_click",
        description="在指定坐标模拟鼠标点击，如果未指定坐标则在当前位置点击",
        params={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X坐标（像素），不指定则在当前位置点击", "default": None},
                "y": {"type": "integer", "description": "Y坐标（像素），不指定则在当前位置点击", "default": None},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "鼠标按钮，默认为left", "default": "left"},
                "click_count": {"type": "integer", "description": "点击次数，默认为1", "default": 1}
            }
        }
    )
    async def mouse_click(self, event, x: int = None, y: int = None, button: str = "left", click_count: int = 1) -> str:
        """模拟鼠标点击"""
        await self._ensure_browser()
        try:
            if x is not None and y is not None:
                # 先移动鼠标到指定位置，再点击
                await self._page.mouse.move(x, y)
                await self._page.mouse.down(button=button)
                await self._page.mouse.up(button=button)
                if click_count > 1:
                    for _ in range(click_count - 1):
                        await self._page.mouse.down(button=button)
                        await self._page.mouse.up(button=button)
                return f"✅ 已在 ({x}, {y}) 进行{button}键点击 {click_count} 次"
            else:
                await self._page.mouse.down(button=button)
                await self._page.mouse.up(button=button)
                return f"✅ 已在当前位置进行{button}键点击"
        except Exception as e:
            return f"❌ 点击失败: {str(e)}"
    
    @register.tool(
        name="browser_mouse_down_up",
        description="模拟鼠标按下或释放（用于拖拽操作）。注意：使用'button'参数指定鼠标按钮，不要用'key'",
        params={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["down", "up"], "description": "按下(down)或释放(up)鼠标"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "鼠标按钮(left/right/middle)，默认为left"}
            },
            "required": ["action"]
        }
    )
    async def mouse_down_up(self, event, action: str, button: str = "left") -> str:
        """模拟鼠标按下/释放"""
        await self._ensure_browser()
        try:
            if action == "down":
                await self._page.mouse.down(button=button)
                return f"✅ 已按下{button}键"
            else:
                await self._page.mouse.up(button=button)
                return f"✅ 已释放{button}键"
        except Exception as e:
            return f"❌ 操作失败: {str(e)}"
    
    @register.tool(
        name="browser_mouse_wheel",
        description="模拟鼠标滚轮滚动",
        params={
            "type": "object",
            "properties": {
                "delta_x": {"type": "integer", "description": "水平滚动距离（像素），默认为0", "default": 0},
                "delta_y": {"type": "integer", "description": "垂直滚动距离（像素），正数向下滚动，负数向上滚动", "default": 0}
            }
        }
    )
    async def mouse_wheel(self, event, delta_x: int = 0, delta_y: int = 0) -> str:
        """模拟鼠标滚轮"""
        await self._ensure_browser()
        try:
            await self._page.mouse.wheel(delta_x, delta_y)
            direction = "下" if delta_y > 0 else "上" if delta_y < 0 else ""
            return f"✅ 已滚动{direction} {abs(delta_y)} 像素"
        except Exception as e:
            return f"❌ 滚动失败: {str(e)}"
    
    @register.tool(
        name="browser_mouse_drag",
        description="模拟鼠标拖拽：从起始位置按住，移动到目标位置，然后释放",
        params={
            "type": "object",
            "properties": {
                "start_x": {"type": "integer", "description": "起始X坐标"},
                "start_y": {"type": "integer", "description": "起始Y坐标"},
                "end_x": {"type": "integer", "description": "目标X坐标"},
                "end_y": {"type": "integer", "description": "目标Y坐标"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "鼠标按钮，默认为left", "default": "left"},
                "steps": {"type": "integer", "description": "移动步数，越大越平滑，默认为10", "default": 10}
            },
            "required": ["start_x", "start_y", "end_x", "end_y"]
        }
    )
    async def mouse_drag(self, event, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left", steps: int = 10) -> str:
        """模拟鼠标拖拽"""
        await self._ensure_browser()
        try:
            # 移动到起始位置
            await self._page.mouse.move(start_x, start_y)
            # 按下鼠标
            await self._page.mouse.down(button=button)
            # 移动到目标位置
            await self._page.mouse.move(end_x, end_y, steps=steps)
            # 释放鼠标
            await self._page.mouse.up(button=button)
            return f"✅ 已从 ({start_x}, {start_y}) 拖拽到 ({end_x}, {end_y})"
        except Exception as e:
            # 确保释放鼠标
            try:
                await self._page.mouse.up(button=button)
            except:
                pass
            return f"❌ 拖拽失败: {str(e)}"
    
    @register.tool(
        name="browser_hover",
        description="将鼠标悬停在指定元素上（触发 hover 效果）",
        params={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS选择器，指定要悬停的元素"}
            },
            "required": ["selector"]
        }
    )
    async def hover(self, event, selector: str) -> str:
        """悬停在元素上"""
        await self._ensure_browser()
        try:
            await self._page.hover(selector)
            return f"✅ 已悬停在元素: {selector}"
        except Exception as e:
            return f"❌ 悬停失败: {str(e)}"
