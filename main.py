"""浏览器插件（合并版）—— 一个插件，两种后端，自动挑选。

## 为什么合并

原来的两个插件各自只能覆盖一半场景：

  * `headless_browser`：能操作，但 Playwright 必须独占 user-data-dir，
    **和用户开着的浏览器互斥**（用户开着 → 插件用不了；插件开着 → 用户打不开浏览器）。
  * `kira_browser_bridge`：用扩展驱动用户自己的浏览器，**零冲突**，
    但需要用户在浏览器里装扩展并保持连接。

合并后按可用性自动挑：**扩展连上就用扩展（用户自己的浏览器，登录态天然可用），
扩展没连上就自动起无头**。并且无头后端**永不碰用户真实 profile** ——
所以"抢锁"这件事从设计上就不存在了。

## CPU 侧的改动（详见 backends/headless_backend.py 文件头）

1. 删掉 `--disable-background-timer-throttling` /
   `--disable-backgrounding-occluded-windows` / `--disable-renderer-backgrounding`
   这三个**反向**参数（原版在 Windows 可视模式下主动加了它们）。
2. 补上 `--disable-dev-shm-usage` / `--disable-gpu` /
   `--js-flags=--max-old-space-size=512` / `--renderer-process-limit=N`。
3. 默认等待从 `networkidle`（官方标注 DISCOURAGED）改成 `domcontentloaded`。
4. 空闲回收：默认 300 秒没用就关掉无头浏览器。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

# ⚠️ FastAPI 的 Request：配对端点要用它判断"请求是不是来自本机"。
#    插件跑在 KiraAI 进程里，FastAPI 一定在；这里仍然兜一下，
#    免得以后有人单独 import main.py 做静态检查时炸掉。
try:
    from fastapi import HTTPException, Request
except ImportError:  # pragma: no cover
    HTTPException = Request = None  # type: ignore

from core.plugin import BasePlugin, Priority, PageMenu, PluginPage, on, register
from core.logging_manager import get_logger
from core.provider import LLMRequest
from core.chat.message_elements import File, Image
from core.chat.message_utils import MessageChain, KiraMessageBatchEvent

from . import protocol as P
from . import security
from . import setup_guide
from . import vlm
from .backends import BackendRouter, ExtensionBackend, HeadlessBackend
from .bridge import BrowserBridge
from .tokens import ensure_token, is_current_token, token_expiry

logger = get_logger("browser_merged", "cyan")

def _read_plugin_id() -> str:
    """插件 id 以 manifest.json 为准，避免代码与清单两处硬编码跑偏
    （跑偏的后果：扩展连到不存在的 WS 路由）。"""
    try:
        import json as _json
        with open(Path(__file__).resolve().parent / "manifest.json",
                  encoding="utf-8") as f:
            return _json.load(f).get("plugin_id") or "headless_browser"
    except Exception:
        return "headless_browser"


PLUGIN_ID = _read_plugin_id()

#: 扩展侧二次确认弹窗的等待秒数（与 browser-bridge/protocol.js 对齐）
CONFIRM_WAIT_SECONDS = 45

#: 写工具名 —— 只读模式下从当次请求的工具表里摘掉。
#
# ⚠️ 这份名单必须与**实际注册的工具名**一致。
#    它原来是 `browser_click` / `browser_type` / `browser_scroll` ——
#    这三个名字在工具合并之后**已经不存在了**（现在叫 browser_interact，
#    用 action 区分动作）。结果就是：只读模式下这些工具**一个都没被摘掉**，
#    用户开了只读，AI 照样能点击/输入/执行 JS。
#
#    当前会改状态的工具：
#      browser_interact —— 点击/输入/滚动/键盘/鼠标（用 action 选）
#      browser_navigate —— 跳转
#      browser_script   —— 执行任意 JS（能做任何事）
#      browser_cookie   —— 写 cookie（import 动作）
#      browser_file     —— 上传/下载（会改变页面与本地状态）
#  ⚠️ `browser_diag` **不在**这个名单里：它的 status / vlm / extension
#     是纯查询，只读模式下也该能用；只有 visible 会 navigate 打开测试页，
#     那条路径内部走 `_call(..., for_write=True)`，由 `_check_write`
#     在只读模式下拦住（比"整个工具被摘掉"更精确）。
WRITE_TOOL_NAMES = (
    "browser_interact", "browser_navigate", "browser_script",
    "browser_cookie", "browser_file",
)


def _manifest_version() -> str:
    """从 manifest.json 读版本 —— 面板显示用，避免两处写死。"""
    try:
        p = Path(__file__).with_name("manifest.json")
        return str(json.loads(p.read_text(encoding="utf-8")).get("version") or "")
    except Exception:
        return ""


_MANIFEST_VERSION = _manifest_version()


class BrowserPlugin(BasePlugin):
    """合并后的浏览器插件。"""

    #: 面板上显示的版本（见 _manifest_version）
    PLUGIN_VERSION = _MANIFEST_VERSION

    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.bridge = BrowserBridge()
        # ⚠️ 顺序要紧：覆盖值必须在 `_apply_config` **之前**加载 ——
        #    `_apply_config` 会把它们叠在框架配置之上（覆盖优先）✓
        self._cfg_overrides = self._load_overrides()
        # 记住框架给的配置：侧边栏热更新时要基于它重新摊平
        self.plugin_cfg = dict(cfg or {})
        self._apply_config(cfg)

        self._last_state: dict = {}
        self._confirm_log: list = []
        self._token: Optional[str] = None
        self._headless: Optional[HeadlessBackend] = None
        self.router: Optional[BackendRouter] = None
        # 首次运行引导：只在"扩展没连上"且还没提醒过时提醒一次
        self._setup_notice: Optional[str] = None
        self._setup_notified = False

    # ══════════════════════════════════════════════════════════════════
    #  配置
    # ══════════════════════════════════════════════════════════════════

    def _resolve_data_dir(self, value) -> str:
        """把白名单里的一项目录解析成**绝对路径**，语义与插件落盘一致。

        ⚠️ 为什么必须有这一步：KiraAI 里 `data/files` 指的是
           **`<框架数据目录>/files`**（见 `backends/headless_backend.py` 的
           `_resolve_user_dir`，框架自己的 `<file>` 标签也是这套规矩）——
           只有当 CWD 恰好是 KiraAI 根目录、且数据目录就是 `<root>/data`
           时，它才等于 `<CWD>/data/files`。

        白名单要是按 CWD 解释，就会**静默失效**（两处口径对不上）：

        * 用户配了 `data/temp` 当本机文件白名单，而截图其实落在
          `<框架数据目录>/temp` ⇒ **自己刚截的图自己打不开**；
        * 反过来，CWD 下恰好存在同名目录时，白名单会意外放行它 ——
          一个安全开关名不副实。

        取不到框架（单测/桩环境）时退回插件数据目录的上两级，与
        `_framework_data_path` 的兜底一致。
        """
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            from .backends.headless_backend import _resolve_user_dir
            base = Path(self.ctx.get_plugin_data_dir())
            return _resolve_user_dir(raw, raw, base)
        except Exception as e:                       # noqa: BLE001
            # ⚠️ 这里**不能**静默返回原字符串 —— 那等于悄悄退回"按 CWD 解释"
            #    这条已知会失效的路径。退回绝对化至少让行为可预测，并留下日志。
            logger.warning(f"目录「{raw}」无法按框架语义解析（{e}），按绝对路径处理")
            return os.path.abspath(raw)

    def _apply_config(self, cfg: dict) -> None:
        """把配置摊平到实例属性。initialize 会重入，必须幂等。

        ⚠️ **侧边栏 WebUI 的改动也要能生效**：WebUI 写下来的覆盖值存在
           `<插件数据目录>/webui_config.json`，这里把它们**叠在框架配置之上**
           （覆盖优先）—— 于是 `_apply_config` 一跑，热更新就完成了。
           不这么做的话，WebUI 改完得重启 KiraAI 才生效 ✗
        """
        cfg = dict(cfg or {})
        try:
            cfg.update(self._cfg_overrides or {})
        except Exception as e:                     # 覆盖值坏了不该拖垮初始化
            logger.warning(f"WebUI 覆盖配置读取失败（忽略）：{e}")
        self.enabled = _b(cfg.get("enabled", True))
        # —— 后端策略 ——
        self.backend_strategy = (cfg.get("backend_strategy", "auto") or "auto").lower()
        self.extension_enabled = _b(cfg.get("extension_enabled", True))
        self.headless_enabled = _b(cfg.get("headless_enabled", True))

        # —— 安全策略（沿用桥接插件那套，读写分离）——
        # 默认 false：让 bot 拥有完整的读写能力（点击/输入/跳转）。
        # 想收紧的话在配置里打开；打开后写工具会从模型可见的工具表里整个摘掉。
        self.read_only = _b(cfg.get("read_only", False))
        # ⚠️ 必须防"存回来的是**字符串**"：面板字段类型一旦与框架认得的
        #    类型对不上（schema 里曾写成 `array`，而框架只认 `list`），
        #    控件会退化成文本框、把整个列表存成一串文本 ——
        #    这时 `list("*.bank*")` 得到的是 `['*','.','b',...]` **逐字符**
        #    的列表，黑名单**静默失效**（看着配了，实际每条规则只剩一个字符）。
        # 扩展「自动接入」的跨机开关（配对端点用）
        self.allow_remote_pairing = _b(cfg.get("allow_remote_pairing"))
        self.allowed_domains = _as_list(cfg.get("allowed_domains"))
        self.blocked_domains = _as_list(cfg.get("blocked_domains"))
        # —— 截图 → VLM 描述（让 bot 能"看到"页面）——
        # ⚠️ 这个能力在原版 headless_browser 里是有的，合并时**被整体弄丢**过。
        #    它很重要：插件能给**用户**发图，但 bot 自己看不到图 ——
        #    工具结果是以 role:"tool" 的**文本**进模型的。
        #    bot 想"看到"页面只能靠 VLM 把图转成描述。
        #    两个后端都适用（VLM 调用在插件进程里，跟谁拍的图无关）。
        self.vlm_model = str(cfg.get("vlm_model") or "").strip()
        self.vlm_describe_prompt = str(cfg.get("vlm_describe_prompt") or "").strip()
        # ⚠️ 默认 **60 秒**。原来 10 → 30 还是偏紧：一张大截图的编码 + 推理
        #    经常十几秒，网络慢或模型忙就更久，超时后描述被丢掉，
        #    用户看到的是"没拿到描述"。
        #    现在已经**默认先压缩再发**（见 vlm_compress），正常几秒就回来了；
        #    60 秒是留给"模型确实慢"的余量 —— 超时只是不附描述，
        #    截图本身照常返回、照常发给用户，所以放宽不增加风险。
        self.vlm_timeout = float(cfg.get("vlm_timeout", 60) or 60)
        # VLM 前压缩（默认开）。三个值都能在面板上调。
        self.vlm_compress = _b(cfg.get("vlm_compress", True))
        self.vlm_compress_max_size = int(cfg.get("vlm_compress_max_size", 1280) or 1280)
        self.vlm_compress_quality = int(cfg.get("vlm_compress_quality", 85) or 85)
        # 写操作后是否顺手带回页面状态（默认开）。
        # 省工具调用次数：框架每轮上限默认 5，"点一下+看一眼"要两次就太快用光。
        self.return_page_after_write = _b(cfg.get("return_page_after_write", True))
        # ⚠️ **默认关**：浏览历史是**用户没主动交出来**的隐私数据 ——
        #    它会把"你最近看过什么"整段交给模型。要开的人自己去面板上开，
        #    而且开了之后 `browser_diag` 会一直显示这个状态（看得见）。
        self.allow_history = _b(cfg.get("allow_history", False))
        #: 默认是否描述。**每次截图时模型也可以自己用 describe 参数覆盖** ——
        # 「要不要看图」应该由模型按当前任务决定（有时它只想把图发给用户）。
        self.auto_describe_screenshot = _b(cfg.get("auto_describe_screenshot", True))
        #: 截图时窗口最小化/被完全遮挡 → 让扩展"借窗口一瞬"：恢复窗口 → 截 → 还原。
        #: 默认开（bot 的常见用法就是"浏览器丢后台自己截图看"）；不想被弹窗的人可关，
        #: 关了之后最小化状态下截图就直接如实失败。
        self.screenshot_restore_window = _b(cfg.get("screenshot_restore_window", True))
        #: **运行时**显式切换的后端（`browser_backend` 工具写的）。
        #: ⚠️ 只在「后端策略」= auto 时有效；且只在内存里 —— 插件重载后回到配置值。
        #:    （不要让 bot 一次调用就永久改掉用户的配置 ✗）
        self._backend_override = None
        #: 降级提示是否已经把"两套浏览器"那句说全过（避免每次调用都刷一大段）
        self._degrade_announced = False

        # ⚠️ 本机 / 内网默认**允许**访问：本插件就是给 AI 当浏览器用的，
        #    localhost:3000 这类开发服务器和 KiraAI 自己的面板都是正常工作目标。
        #    想收紧的人在配置里关掉，那时本机与内网一律拒绝。
        self.local_access = _b(cfg.get("local_access", True))
        # 本机**文件**（file://）单独一条开关。
        # ⚠️ 默认开，理由与 local_access 完全一致：bot 看不到本地文件，
        #    "帮我看看这张图 / 这份 PDF / 这个视频"就全不可用 ——
        #    而这正是浏览器最自然的用法之一。
        #    历史上 file 被硬编码进 BLOCKED_SCHEMES（理由写着"扩展没权限"），
        #    那句话只对了一半：扩展在用户打开「允许访问文件网址」后就能读，
        #    无头浏览器更是从来没有这条限制 ⇒ 那一条硬编码把两个后端同时钉死。
        self.local_file_access = _b(cfg.get("local_file_access", True))
        # 本地文件路径白名单（与 upload_allow_any_path 同一套语义）
        self.file_allow_any_path = _b(cfg.get("file_allow_any_path", True))
        self.file_allowed_dirs = _as_list(
            cfg.get("file_allowed_dirs")
            or list(security.DEFAULT_FILE_DIRS))
        # ⚠️ 白名单里的相对目录必须按**框架语义**展开成绝对路径。
        #    `data/files` 在 KiraAI 里指的是 `<框架数据目录>/files`
        #    （见 `_resolve_user_dir`），**不是** `<CWD>/data/files`。
        #    不展开的话，这两组开关会**静默失效**：
        #      · 关掉 `file_allow_any_path` 后，用户填的 `data/temp` 被按 CWD
        #        解释，而插件产出的截图/下载其实在框架数据目录里 ⇒
        #        用户看着自己配的白名单，**自己刚下载的文件却打不开**；
        #      · 更糟的是反向：CWD 下恰好存在 `data/files` 时，
        #        白名单会意外放行那个目录 —— 安全开关名不副实。
        #    与 `upload_allowed_dirs` 用同一套语义，两处口径必须一致。
        # ⚠️ 必须**丢掉解析后为空**的条目。
        #    空串经 realpath 之后会变成 **CWD**，于是白名单会意外放行
        #    启动目录下的一切 —— 一个空配置项把安全开关打开，很难发现。
        self.file_allowed_dirs = [
            d for d in (self._resolve_data_dir(x)
                        for x in self.file_allowed_dirs) if d]
        self.require_confirm = _b(cfg.get("require_confirm", False))
        # ⚠️ 默认**关**。理由（按分量）：
        #    ① 隐私：开着的话，**每一轮请求**都会把用户正在浏览的标题+网址
        #       发给模型服务商 —— 哪怕这轮聊的根本不是浏览器的事。
        #       工具方式是**按需**取，取的动作还留在对话记录里。
        #    ② 冗余：模型真要用浏览器时，工具返回里本来就有标题/网址/标签数。
        #    ③ 噪音：每轮都挂着"可读可写（无白名单限制）"这类提示。
        #    ④ token：约 60~120 token/轮，每轮都算。
        #    附带：开着时 _collect_state() 每 120 秒会去戳一次用户的浏览器。
        self.inject_page_state = _b(cfg.get("inject_page_state", False))
        self.panel_auth_required = _b(cfg.get("panel_auth_required", True))
        self.max_content_chars = max(500, int(cfg.get("max_content_chars", 8000) or 8000))
        # 上传/发送文件的**路径白名单**。
        # 默认放行任意路径（方便），但可以收紧到指定目录 ——
        # 否则模型可以借"上传"把本机任意文件外传。
        # ⚠️ 默认值必须与 schema.json 一致（两处写同一个值）。
        #    这里**有意选 true**：本插件的定位是"完全全能的浏览器操作"，
        #    上传任何本机文件是预期能力（比如把本地 PDF 传到网盘）。
        #    想收紧的人把这项关掉即可，白名单在 upload_allowed_dirs。
        self.upload_allow_any_path = _b(cfg.get("upload_allow_any_path", True))
        _dirs = cfg.get("upload_allowed_dirs") or ["data/files", "data/temp"]
        if isinstance(_dirs, str):
            _dirs = _dirs.splitlines()
        # ⚠️ 同样按框架语义展开（见下面 _resolve_data_dir 的说明）——
        #    原来这里只是 `str(d).strip()`，于是 `data/files` 被按 **CWD**
        #    解释，而这个插件真正落盘的地方是**框架数据目录**。
        #    结果：关掉 `upload_allow_any_path` 后，白名单**静默失效** ——
        #    用户配了白名单，自己刚下载到 `<data>/files` 的文件却传不上去
        #    （报错还说"只允许上传下列目录"，列出的正是那个目录，非常迷惑）。
        # ⚠️ 同样丢掉解析后为空的条目（空串 realpath 之后 = CWD，
        #    会让白名单意外放行启动目录下的一切）。
        self.upload_allowed_dirs = [
            d for d in (self._resolve_data_dir(x)
                        for x in _as_list(_dirs)) if d]

        try:
            ct = float(cfg.get("command_timeout"))
        except (TypeError, ValueError):
            ct = 20.0
        if self.require_confirm:
            ct = max(ct, CONFIRM_WAIT_SECONDS + 5)
        self.bridge.command_timeout = max(3.0, min(ct, 300.0))

        # —— 无头后端参数 ——
        # 页面操作超时是否与框架的 tool_call_timeout 挂钩：
        #   默认 False = **完全脱钩**。框架那个超时（默认 60s）是"到点直接
        #   cancel 我们的协程"，中途取消会让 Playwright 留下状态不明的页面。
        #   脱钩后由插件自己决定何时收手，行为可预测。
        #   如果你希望插件永远不超过框架上限，把它设为 true 再配合
        #   op_timeout_ratio 使用。
        # 扩展桥的大小限制（走 WebSocket 传输，需要单独钳制）
        # ⚠️ 兜底值必须与 schema.json 一致（32MB）。
        #    另：在扩展后端改成"分多条消息流式传输"之前，配置值会被
        #    ExtensionBackend.MAX_UPLOAD_BYTES 钳住 —— 否则用户把配置调到
        #    200MB 会重新引入"单条消息 >500MB 峰值 + 267MB 单帧被拒"。
        _umb = int(cfg.get("upload_max_bytes", 256 * 1024 * 1024) or 0)
        try:
            # ⚠️ 用**已导入的** `ExtensionBackend`（见文件头 `from .backends import ...`）。
            #    写 `from backends.extension_backend import ...` 是**绝对导入** ——
            #    插件是以包的形式加载的（`<pkg>.main`），此时 `backends` 并不是
            #    顶层模块，这条 import 会失败 → 静默落到 except → **钳制失效**。
            _ceil = getattr(ExtensionBackend, "MAX_UPLOAD_BYTES", 0)
            if _ceil and _umb > _ceil:
                logger.warning(
                    f"upload_max_bytes={_umb} 超过单条消息能承载的上限，"
                    f"已钳制到 {_ceil}（需多消息流式传输才能再调大）")
                _umb = _ceil
        except Exception:
            pass
        self.upload_max_bytes = _umb
        self.download_timeout = float(cfg.get("download_timeout", 600) or 600)

        self.op_timeout_follows_framework = _b(cfg.get("op_timeout_follows_framework", False))
        # ⚠️ 在这里就**钳住**合法区间 (0,1)，不要留到使用时才判 ——
        #    留到使用点的话，只有"跟随框架"那条分支会纠正它，
        #    其它路径（含 browser_diag 的展示）看到的仍是非法原值，
        #    "显示 5.0、实际用 0.8"这种对不上的情况就会一直存在。
        #    ⚠️ schema 里**不能**用 minimum/maximum 表达这个约束：
        #       框架的 create_field_from_schema 只读 type/name/hint/default/
        #       options/locales，不认这两个键 —— 写进去只是空头承诺，
        #       面板照样允许填非法值。所以必须在这里兜住。
        try:
            _ratio = float(cfg.get("op_timeout_ratio", 0.8) or 0.8)
        except (TypeError, ValueError):
            _ratio = 0.8
        if not (0.0 < _ratio < 1.0):
            logger.warning(
                f"op_timeout_ratio={_ratio} 不在 (0,1) 内，已改回 0.8"
                f"（0 或负数会算出无意义的超时；>=1 会让插件超时越过框架自己的）")
            _ratio = 0.8
        self.op_timeout_ratio = _ratio

        self._headless_cfg = {
            "headless": cfg.get("headless", True),
            "browser_channel": cfg.get("browser_channel", "auto"),
            "timeout": cfg.get("timeout", 45),
            "default_viewport": cfg.get("default_viewport", "1920x1080"),
            "user_agent": cfg.get("user_agent"),
            # 兜底值必须与 schema.json 的默认一致（inherit）——
            # 写成 persistent 的话，配置文件缺这一项时会静默退回
            # "插件自己的 profile"，用户以为继承了登录态其实没有。
            "headless_profile_mode": cfg.get("headless_profile_mode", "inherit"),
            "custom_user_data_dir": cfg.get("custom_user_data_dir"),
            "screenshot_dir": cfg.get("screenshot_dir") or str(Path("data/temp")),
            "download_dir": cfg.get("download_dir"),
            # cookie 自动加载（原版能力，重写时丢过一次）
            "cookies_dir": cfg.get("cookies_dir") or str(Path("data/files/cookie")),
            "load_cookies_on_start": cfg.get("load_cookies_on_start", True),
            # 所有浏览器来源都失败时，自动下载内置 Chromium（README 承诺过）
            "auto_download_browser": cfg.get("auto_download_browser", True),
            "auto_download_timeout": cfg.get("auto_download_timeout", 600),
            "screenshot_max_count": cfg.get("screenshot_max_count", 50),
            "screenshot_auto_clean": cfg.get("screenshot_auto_clean", True),
            "download_auto_clean": cfg.get("download_auto_clean", True),
            "download_max_count": cfg.get("download_max_count", 100),
            "download_max_bytes": cfg.get("download_max_bytes", 2 * 1024 ** 3),
            "content_page_size": cfg.get("content_page_size", 8000),
            "idle_close_seconds": cfg.get("idle_close_seconds", 300),
            # 默认值必须与 schema.json 一致（120）—— 不一致时，
            # 配置文件缺这一项就会用 40s，而面板显示 120s。
            "op_timeout": cfg.get("op_timeout", 120),
            "action_timeout": cfg.get("action_timeout", 20),
            "default_wait_until": cfg.get("default_wait_until", "domcontentloaded"),
        }

    # ══════════════════════════════════════════════════════════════════
    #  生命周期
    # ══════════════════════════════════════════════════════════════════

    async def initialize(self):
        self._apply_config(self.plugin_cfg)

        if not self.enabled:
            logger.info("浏览器插件已禁用，跳过初始化")
            await self.bridge.close()
            return

        # 事件回调（先清再注册，热重载不会重复累积）
        self.bridge.clear_event_listeners()
        self.bridge.on_event(P.EVT_PAGE_LOADED, self._on_page_event)
        self.bridge.on_event(P.EVT_TAB_ACTIVATED, self._on_page_event)
        self.bridge.on_event(P.EVT_USER_CONFIRMED, self._on_user_confirmed)

        if self.extension_enabled:
            try:
                self._token = ensure_token()
                logger.info("扩展接入令牌已就绪（重新生成会另打日志）")
            except Exception as e:
                logger.error(f"生成扩展令牌失败: {e}")

        data_dir = Path(self.ctx.get_plugin_data_dir())
        self._headless = HeadlessBackend(data_dir, self._headless_cfg)

        # op_timeout 脱钩：读一次框架的 tool_call_timeout，仅用于"要不要挂钩"
        if self.op_timeout_follows_framework:
            # ratio 的合法性已在**解析配置时**钳好（见 __init__），
            # 这里直接用即可 —— 不要再留一份"使用时才纠正"的判断，
            # 那样两处口径容易分叉。
            try:
                fw = float(self.ctx.config.get_config(
                    "bot_config.agent.tool_call_timeout", 60.0) or 60.0)
                if fw > 0:
                    r = self.op_timeout_ratio
                    tuned = fw * r
                    # 下限取 min(5.0, 目标值)，**绝不能**被 5 秒顶到框架超时
                    # 之上：fw 很小时（如 6s），max(5, 4.8) 会变成 5，仍可能
                    # 撞上框架取消；这里保证 tuned 始终 < fw。
                    tuned = max(min(5.0, tuned), tuned)
                    tuned = min(tuned, fw * 0.95)
                    self._headless_cfg["op_timeout"] = round(tuned, 1)
                    self._headless_cfg["action_timeout"] = round(min(tuned, fw * 0.5), 1)
                    logger.info(
                        f"op_timeout 已跟随框架（{fw}s × {r}）= {round(tuned, 1)}s")
            except Exception as e:
                logger.debug(f"读取框架 tool_call_timeout 失败，保持插件默认: {e}")
        else:
            logger.info(
                "op_timeout 与框架工具超时**脱钩**"
                f"（插件自己管：{self._headless_cfg.get('op_timeout')}s）")

        self.router = BackendRouter(self.backend_strategy)
        if self.extension_enabled:
            self.router.register(ExtensionBackend(
                self.bridge, P,
                max_upload_bytes=self.upload_max_bytes or None,
                max_download_bytes=int(self._headless_cfg.get("download_max_bytes") or 0) or None,
                download_timeout=self.download_timeout,
                content_page_size=self._headless_cfg.get("content_page_size", 8000),
                require_confirm=self.require_confirm,
                confirm_timeout=CONFIRM_WAIT_SECONDS,
                screenshot_restore_window=self.screenshot_restore_window,
            ))
        if self.headless_enabled:
            self.router.register(self._headless)

        logger.info(f"浏览器插件已就绪：{self.router.describe()}")
        logger.info(
            f"安全策略：只读={self.read_only}，白名单 {len(self.allowed_domains)} 条，"
            f"黑名单 {len(self.blocked_domains)} 条"
        )
        if self._headless_cfg.get("idle_close_seconds"):
            logger.info(f"无头浏览器空闲 {self._headless_cfg['idle_close_seconds']}s 后自动关闭")

        # —— 首次运行引导 ——
        # 扩展还没连上时，把「扩展在哪、怎么装、装完怎么连」准备好，
        # 等模型第一次用到浏览器工具时顺手带给用户。
        plugin_dir = Path(__file__).resolve().parent
        self._setup_notice = setup_guide.first_run_notice(
            plugin_dir, connected=self.bridge.connected,
            profile_mode=self._headless_cfg.get("headless_profile_mode", "inherit"))
        if self._setup_notice:
            logger.info(
                "扩展尚未连接。已准备好安装引导；扩展包位置：%s",
                setup_guide.extension_dir(plugin_dir),
            )
        for line in setup_guide.compatibility_report().splitlines():
            logger.info(line)

    async def terminate(self):
        if self.router:
            for b in self.router.candidates():
                try:
                    await b.close()
                except Exception as e:
                    logger.debug(f"关闭后端失败: {e}")
        await self.bridge.close()
        logger.info("浏览器插件已停止")

    # ══════════════════════════════════════════════════════════════════
    #  后端路由 —— 所有工具都走这里
    # ══════════════════════════════════════════════════════════════════

    async def _with_page_after(self, result: str, *, chars: int = 800,
                               tab_id=None) -> str:
        """把「动作结果」和「动作之后的页面状态」拼成**一次**返回。

        ⚠️ 为什么必须合起来：框架有**每轮工具调用上限**
           （`bot_config.agent.max_tool_calls_per_turn`，默认 **5**）。
           "点一下 → 再看一眼"如果各占一次调用，5 次只够两轮半 ——
           bot 还没干完就被限流，日志里表现为满屏
           `Tool call limit exceeded ... skipping tool 'browser_page'`。

        ⚠️ 而**扩展内部命令不计次**（计的是 LLM 发起的工具调用）。所以在工具
           内部顺手把页面取回来是**白赚的** —— 同样的预算能干两倍的事，
           还少一次模型往返，更快。

        ⚠️ 取不到就只回动作结果 —— 不能让"顺手多取"把动作本身搞成失败。
        """
        try:
            info = await self._call("get_info", tab_id=tab_id)
        except Exception:
            info = ""
        try:
            body = await self._call("get_page", detail="text", tab_id=tab_id,
                                    max_chars=int(chars or 800))
        except Exception:
            body = ""
        if not info and not body:
            return result
        parts = [result] if result else []
        if info:
            parts.append(f"📍 现在的页面：\n{info}")
        if body:
            parts.append(f"📄 页面内容（截断）：\n{body}")
        return "\n\n".join(parts)

    #: 失败之后要不要接着试下一个后端。
    #: ⚠️ **产品里永远是 False**：用户明确要求"操作进行中不许自动切换后端"。
    #:    中途换 = 换了操作对象，前面那步的结果就此断掉；读/截图更糟 ——
    #:    会拿到**另一套浏览器**的画面却报成功（假成功）。
    #: 之所以留成类属性，是为了让**反向自检**能把它翻成 True，
    #: 证明"不换后端"这条判据真的会响（而不是摆着好看）。
    allow_failover = False

    def _candidates(self):
        """本次实际可用的后端顺序。

        - 用户把「后端策略」固定成某一类 → **只有一个候选**（bot 也改不了，
          见 `browser_backend` 工具：那是用户的决定）
        - `auto` + bot 显式切换过 → 只留它点名的那个（**不保留**"失败再试另一个"）
        - `auto` → 扩展优先；无头只作为"首选从一开始就不可用"时的落点
        """
        if self.router is None:
            return []
        if self.backend_strategy != "auto":
            return self.router.candidates()
        if self._backend_override:
            b = self.router.by_name(self._backend_override)
            return [b] if b is not None else self.router.candidates()
        return self.router.candidates()

    async def _call(self, method: str, *, for_write: bool = False, **kw):
        """调用某个能力：**一个后端，一次机会**。

        用哪个由「后端策略」决定（`auto` = 扩展优先，其次无头）。
        bot 想换，只能**显式**调 `browser_backend`（且仅当策略是 `auto`）。

        ⚠️ **中途绝不自动换后端**（用户明确要求，2026-09-22）：
           首选可用、但这次调用失败 → **如实失败**，绝不接着试下一个。
           理由：换后端 = 换了操作对象，前面那步的结果就此断掉；
           读/截图更糟 —— 会拿到**另一套浏览器**的画面却报"成功"，
           模型会把别人的图当成用户看到的页面（真正的假成功）。
        ⚠️ 唯一例外：首选**从一开始就不可用**（没连上 / 没启动）→ 用下一个，
           但必须在结果里**明说**（bot 得知道自己看的是另一套浏览器）。
        """
        if self.router is None:
            return "❌ 插件尚未初始化完成，请稍后重试。"

        candidates = self._candidates()
        if not candidates:
            return f"❌ {self.router.hint()}"

        tried = []
        for idx, backend in enumerate(candidates):
            if not backend.available and not await self._probe(backend):
                tried.append(f"{backend.display}（不可用）")
                continue
            # ⚠️ 走到这里 = 这次就用它了。**后面无论成败都不再换后端**（见 docstring）
            if idx == 0:
                self._degrade_announced = False          # 首选回来了 → 重新允许提示
                degrade = ""
            else:
                degrade = self._degrade_notice(method, candidates[0], backend, tried)
            if for_write:
                # 写操作前校验目标页面（扩展后端能拿到 URL，无头后端用当前页）
                err = await self._check_write(backend, kw.get("url"))
                if err:
                    return err
            fn = getattr(backend, method, None)
            if fn is None:
                return (f"❌ {backend.display} 不支持「{method}」。\n"
                        f"{self._switch_hint()}")
            res = await fn(**kw)
            if res.ok:
                out = self._render(method, res, backend)
                if degrade:
                    out = degrade + out
                # ⚠️ **动作与结果一体返回**。
                #    框架有每轮工具调用上限（max_tool_calls_per_turn，
                #    默认 5），"点一下 → 再看一眼"如果各占一次调用，5 次只够
                #    两轮半 —— 日志里满屏 "Tool call limit exceeded ...
                #    skipping tool 'browser_page'" 就是这么来的。
                #    而**扩展/后端的内部命令不计次**，所以在 `_call` 这一层
                #    顺手把页面状态带上，是**白赚**的：一处改动覆盖所有写操作
                #    （点/填/导航/滚动…），以后加新工具也自动生效，
                #    还省掉一次模型往返。
                #    ⚠️ 只对**写**操作做（for_write）—— 读操作本身就在取页面；
                #       `_with_page_after` 内部的读是 for_write=False，
                #       所以不会递归。
                if for_write and self.return_page_after_write:
                    out = await self._with_page_after(out, chars=800)
                # 首次成功调用：如果扩展没连上，顺手把安装引导捎给用户
                # （只带一次，不刷屏）
                return self._attach_setup_notice(out)
            if getattr(res, "indeterminate", False):
                # ⚠️ 命令**可能已经在浏览器里生效**，只是没等到回执。
                #    此时换后端重试 = 同一个点击/输入做两次。
                #    宁可如实告诉模型"不确定"，也不要重复执行。
                logger.info(f"[{method}] 结果不确定（可能已执行），不再换后端重试")
                return (f"⚠️ {res.error}\n"
                        f"这条操作**可能已经在浏览器里生效了**，所以没有自动重试"
                        f"（避免重复执行）。请先查看页面当前状态，再决定要不要重做。")
            if getattr(res, "declined", False):
                # ⚠️ 用户明确拒绝了，**立刻停手**，绝不换后端重试。
                #    否则会出现「我点了拒绝，结果插件换条路把事情做了」——
                #    这比没有确认机制更糟，因为它让人以为自己拦住了。
                logger.info(f"[{method}] 用户拒绝了本次操作，已终止（不再尝试其它后端）")
                return f"🚫 {res.error}。已按你的决定终止，没有改用其它方式执行。"

            # ── 失败：**不换后端**（用户明确要求）─────────────────────────
            logger.warning(f"[{method}] {backend.display} 失败：{res.error}")
            if self.allow_failover:
                # ⚠️ 这条分支是**故意留着的反向自检通道**：它正是"中途自动换后端"
                #    的老行为，产品里永远走不到（allow_failover 恒为 False）。
                #    守卫会把它翻成 True，验证"不许换"这条判据真的能抓到回退。
                tried.append(f"{backend.display}: {res.error}")
                continue
            return self._no_switch_failure(method, backend, res)

        # 所有候选都不可用
        detail = "；".join(tried)
        return self._attach_setup_notice(
            f"❌ 这次没有可用的浏览器后端：{detail}\n{self._switch_hint()}")

    def _degrade_notice(self, method: str, preferred, backend, tried) -> str:
        """首选后端**从一开始就不可用**、这次用了别的 → 必须让 bot 知道。

        ⚠️ 这是唯一允许"落到下一个后端"的情形（用户规则），而且**必须说出来**：
           不说的话，模型会以为它操作的是用户自己的浏览器。
        ⚠️ 只有状态**刚变化**时把话说全（"两套浏览器"），之后每次只留一行 ——
           每次调用都刷一大段就成了新的噪音。
        """
        why = "；".join(tried)
        line = f"ℹ️ 本次用的是「{backend.display}」" + (f"（{why}）" if why else "") + "\n"
        if getattr(self, "_degrade_announced", False):
            return line
        self._degrade_announced = True
        if method == "screenshot":
            extra = "⚠️ 那是另一套浏览器：这张图不是用户浏览器的当前画面。\n"
        else:
            extra = "⚠️ 那是另一套浏览器：它的页面不等于用户浏览器的当前页面。\n"
        return line + extra + "\n"

    def _no_switch_failure(self, method: str, backend, res) -> str:
        """失败了就是失败了：**不换后端**，并告诉对方"想换该怎么换"。"""
        msg = (f"❌ {backend.display} 执行「{method}」失败：{res.error}\n"
               f"（没有自动换后端：中途换会换掉操作对象。）")
        hint = self._switch_hint()
        if hint:
            msg += "\n" + hint
        return self._attach_setup_notice(msg)

    def _switch_hint(self) -> str:
        """告诉 bot「想换后端该怎么换」；用户把策略固定时，明确说"不许换"。"""
        if self.backend_strategy != "auto":
            label = {"extension": "只用扩展桥", "headless": "只用无头浏览器"}.get(
                self.backend_strategy, self.backend_strategy)
            return f"「后端策略」被用户固定为「{label}」，不换后端；要改请让用户改配置。"
        cur = self._backend_override or "auto"
        other = "extension" if cur == "headless" else "headless"
        return (f"要换请显式说：browser_backend(action=\"use\", use=\"{other}\") "
                f"—— 那是另一个浏览器，页面不是这个。")

    async def _probe(self, backend) -> bool:
        """懒启动：无头后端第一次被用到时才拉起，不拖慢插件加载。"""
        if backend.name != "headless":
            return backend.available
        if self.backend_strategy == "extension":
            return False
        err = await backend.start()
        if err:
            logger.warning(f"无头后端启动失败: {err}")
            return False
        logger.info("扩展桥不可用，已自动切换到无头浏览器")
        return True

    async def _check_write(self, backend, url=None) -> Optional[str]:
        if self.read_only:
            return ("当前处于「只读模式」，无法执行点击/输入/跳转等写操作。"
                    "如确实需要，请在插件配置里关闭只读模式。")
        if url:
            ok, reason = await self._check_url_async(url, for_write=True)
            return None if ok else reason
        # 没给 URL：拿当前页面地址来判
        cur = await self._current_url(backend)
        if not cur:
            return ("无法确认当前页面地址，出于安全考虑已拒绝本次写操作。"
                    "请确认扩展已连接，或先让无头后端打开一个页面。")
        ok, reason = await self._check_url_async(cur, for_write=True)
        return None if ok else reason

    async def _check_url_async(self, url: str, for_write: bool = False):
        """URL 校验的**异步**入口。

        ⚠️ 为什么要单独一个：`security.check_url` 在 `local_access=False`
        时会调用同步的 `socket.getaddrinfo` 去解析主机名
        （判断 `internal.corp` 这类名字是不是指向内网）。
        在事件循环里直接调同步 DNS，遇到慢解析器/断网/黑洞路由会
        **卡住整个循环** —— 所有并发任务一起停摆，不只是这次调用变慢。

        这里把"解析主机名"那一步换成异步版本（`loop.getaddrinfo` + 超时），
        其余判定逻辑完全复用 `check_url`：
        先用同步版判**字符串层面**的规则（scheme/黑名单/白名单/本机写法），
        只有在它因"本机开关关闭"而需要真解析时才走异步那条。
        """
        # 先按"不解析 DNS"跑一遍：这一步涵盖 scheme、黑名单、
        # 白名单、字面量本机判定 —— 绝大多数情况在这里就有结论。
        ok, reason = security.check_url(
            url, allowed=self.allowed_domains, blocked=self.blocked_domains,
            for_write=for_write, local_access=True,
            local_file_access=self.local_file_access,
            file_allow_any_path=self.file_allow_any_path,
            file_allowed_dirs=self.file_allowed_dirs)
        if not ok:
            return ok, reason

        # ⚠️ 本机文件在这里就到底了 —— 它没有域名，不存在"解析到内网"的问题。
        #    不早退的话，下面的 `is_local_host` / `resolved_url_is_internal_async`
        #    会拿空 host 去查 DNS，白等一次超时。
        if security.parse_scheme(url) in security.FILE_SCHEMES:
            return True, ""

        # 允许本机时，前面那步已是最终答案
        if self.local_access:
            return True, ""

        # local_access=False：需要知道主机名**真正解析**到哪里
        host = security.parse_host(url)
        if host and security.is_local_host(host):
            return False, (f"域名 {host} 指向本机地址，已按配置拒绝"
                           f"（「允许访问本机/内网」已关闭）")
        if host:
            try:
                internal, ip = await security.resolved_url_is_internal_async(url)
            except Exception:
                internal, ip = False, ""
            if internal:
                return False, (f"域名 {host} 解析到内网地址 {ip}，已按配置拒绝"
                               f"（「允许访问本机/内网」已关闭）")
        # 解析不出内网：再看白名单等规则（这些不依赖 DNS）。
        # check_url 在 local_access=False 路径上可能已把本机情况拒掉，
        # 这里用 local_access=True 的结论即可。
        return True, ""

    async def _current_url(self, backend) -> Optional[str]:
        try:
            r = await backend.list_tabs()
            if not r.ok:
                return None
            tabs = (r.data or {}).get("tabs") or []
            active = next((t for t in tabs if t.get("active")), None)
            return (active or {}).get("url")
        except Exception:
            return None

    # ══════════════════════════════════════════════════════════════════
    #  发送图片 / 文件到会话
    #
    #  注意：event.session 是 Session **对象**，不是字符串 ——
    #  直接 str() 它拿到的是 repr（不是 "adapter:type:id"），
    #  适配器会解析失败。正确做法是用 event.sid（框架提供的属性）。
    # ══════════════════════════════════════════════════════════════════

    def _sid_of(self, event) -> str:
        """取会话字符串 "adapter:sessiotype:id"。

        优先用框架的 ``event.sid``；拿不到再退回 ``str(event.session)``
        （Session 有 __str__，正常情况下等价）。
        """
        sid = getattr(event, "sid", None)
        if isinstance(sid, str) and sid.count(":") == 2:
            return sid
        sess = getattr(event, "session", None)
        if sess is None:
            return ""
        s = str(sess)
        return s if s.count(":") == 2 else ""

    async def _adapter_for(self, event):
        """解析出 (adapter, chat_type, target_id)。"""
        sid = self._sid_of(event)
        parts = sid.split(":")
        if len(parts) != 3:
            logger.error(f"无法解析会话标识：{sid!r}")
            return None
        adapter = self.ctx.adapter_mgr.get_adapter(parts[0])
        if not adapter:
            logger.error(f"未找到适配器: {parts[0]}")
            return None
        return adapter, parts[1], parts[2]

    async def _send_chain(self, event, elements) -> bool:
        got = await self._adapter_for(event)
        if not got:
            return False
        adapter, chat_type, target = got
        try:
            chain = MessageChain(elements)
            if chat_type == "gm":
                r = await adapter.send_group_message(target, chain)
            else:
                r = await adapter.send_direct_message(target, chain)
            ok = bool(r and getattr(r, "ok", False))
            if not ok:
                logger.error(f"发送失败: {r}")
            return ok
        except Exception as e:
            logger.error(f"发送异常: {e}")
            return False

    async def _send_image(self, event, path: str) -> bool:
        return await self._send_chain(event, [Image(image=path)])

    async def _send_file(self, event, path: str, name: str = "") -> bool:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        fname = name or os.path.basename(path)
        return await self._send_chain(event, [File(file=path, name=fname, size=str(size))])

    def _path_allowed(self, resolved: str) -> bool:
        """上传/发送文件前的路径校验。

        默认 ``upload_allow_any_path=True`` 直接放行；关掉后只允许
        ``upload_allowed_dirs`` 里的目录（用 realpath 归一，防 `../` 穿越）。
        """
        if self.upload_allow_any_path:
            return True
        for d in self.upload_allowed_dirs:
            root = os.path.realpath(d)
            try:
                if os.path.commonpath((root, resolved)) == root:
                    return True
            except ValueError:
                continue
        return False

    def _attach_setup_notice(self, text: str) -> str:
        """首次成功调用时，把「装扩展」的引导捎带一次。

        这里是**工具返回值**，不是发给用户的聊天消息：它进的是模型的上下文，
        和 browser_navigate 返回"✅ 已打开页面"走同一条路。插件不会主动往
        聊天窗口发消息 —— 用户能否看到，取决于模型有没有转述。

        为了让转述率尽量高，下面把引导包在明确的「请转述给用户」指令里。
        """
        if self._setup_notified or not self._setup_notice:
            return text
        if self.bridge.connected:
            return text
        self._setup_notified = True

        return (f"{text}\n\n---\n"
                f"【系统提示：以下内容请**原样转述给用户**，不要省略】\n"
                f"{self._setup_notice}\n\n"
                f"（这段提示只会出现一次。装了扩展之后，AI 就能直接操作你正在用的浏览器；"
                f"不装也不影响使用，会继续用插件自带的无头浏览器。）")

    def _render(self, method: str, res, backend) -> str:
        """把后端返回渲染成给模型看的文本（含来源标注）。

        末尾**可能**追加一句"另一个实例刚动过页面"的提醒 ——
        见 :meth:`_cross_actor_note`。正常情况一个字都不多。
        """
        text = self._render_base(method, res, backend)
        note = self._cross_actor_note(res)
        return f"{text}{note}" if note else text

    def _cross_actor_note(self, res) -> str:
        """别的 KiraAI 实例在我上次收到结果之后写过页面 → 提醒一句。

        为什么需要：这个插件现在允许**一个浏览器被多个实例同时操作**
        （用户有两个 bot，都该能看到同一个页面）。不做仲裁 —— 谁都能动，
        会抢鼠标 —— 但必须让 bot **自己知道**页面可能已经不是我记忆里的
        样子了，否则它会拿旧的 selector 去点一个早就被换掉的页面。

        ⚠️ 只在真的发生时才返回非空：平时这条提示**一个 token 都不花**。
        """
        try:
            who = (res.data or {}).get("other_writer")
        except (AttributeError, TypeError):
            return ""
        if not who:
            return ""
        return (f"\n\n⚠️ 另一个实例（{who}）在你上次操作之后动过这个页面，"
                f"内容可能已经变了 —— 建议重新读一次再继续。")

    def _render_base(self, method: str, res, backend) -> str:
        """真正的渲染（按 method 分支）。"""
        d = res.data or {}
        tag = f"（来源：{backend.display}）"

        if method in ("navigate",):
            return f"✅ 已打开 {d.get('url', '')}\n📄 标题: {d.get('title', '')} {tag}"
        if method == "list_tabs":
            tabs = d.get("tabs") or []
            if not tabs:
                return f"当前没有打开的标签页 {tag}"
            lines = [f"共 {len(tabs)} 个标签页 {tag}"]
            for t in tabs:
                mark = " ← 当前" if t.get("active") else ""
                lines.append(f"- [id={t.get('id')}] {t.get('title') or '(无标题)'}{mark}")
                lines.append(f"  {t.get('url')}")
            return "\n".join(lines)
        if method == "get_page":
            content = d.get("content") or ""
            total = d.get("total_chars")
            head = f"# {d.get('title') or '(无标题)'}\n{d.get('url', '')}\n"
            out = f"{head}\n{content}\n{tag}"
            # 分页信息：让 bot 知道"还有多少没读、怎么接着读"，
            # 而不是被一个硬上限卡住 —— 它需要更多内容时自己带 offset 再取即可。
            if d.get("has_more"):
                _read = (d.get('offset') or 0) + (d.get('returned') or 0)
                out += (f"\n\n📄 {d.get('offset')}–{_read} / 共 {total}，还有 {total - _read} 未读。"
                        f"续读 browser_page(offset={d.get('next_offset')})。")
            return out
        if method == "extract":
            import json as _json
            items = d.get("items") or []
            if not items:
                return f"没有匹配到任何元素 {tag}"
            return f"{_json.dumps(items, ensure_ascii=False, indent=1)}\n{tag}"
        if method == "screenshot":
            return f"✅ 截图已保存: {d.get('path')} {tag}"
        if method == "download":
            return f"✅ 文件已下载: {d.get('path')}（{d.get('size')} 字节）{tag}"
        if method == "wait_for":
            if d.get("found"):
                return f"✅ 已出现（耗时 {d.get('elapsed', '?')}s）{tag}"
            return f"⏱️ 等待超时，元素未出现 {tag}"
        if method == "execute_js":
            return f"✅ JavaScript 执行结果:\n{d.get('result')} {tag}"
        # ── 以下这些如果落到默认分支，模型就看不到结果了 ──
        # 尤其 cookie_get：导出的是**数据**，必须回传内容，
        # 否则 browser_cookie(action="export") 等于白跑一趟。
        if method == "cookie_get":
            cookies = d.get("cookies") or []
            if not cookies:
                return f"没有可导出的 cookie（{d.get('url', '')}）{tag}"
            import json as _json
            return (f"🍪 已导出 {len(cookies)} 条 cookie（{d.get('url', '')}）{tag}\n"
                    f"{_json.dumps(cookies, ensure_ascii=False)}\n\n"
                    f"提示：可用 browser_cookie(action=\"import\", cookies=[...]) "
                    f"写入另一个后端，这样降级到无头时不用重新登录。")
        if method == "cookie_set":
            return (f"🍪 已写入 {d.get('written', 0)} 条 cookie"
                    + (f"，跳过 {d['skipped']} 条（缺字段）" if d.get("skipped") else "")
                    + f" {tag}")
        if method == "get_info":
            return f"📄 标题: {d.get('title', '')}\n🔗 URL: {d.get('url', '')} {tag}"
        if method == "get_selection":
            t = (d.get("content") or "").strip()
            if not t:
                return f"✂️ 页面上没有选中的文字{tag}"
            return (f"✂️ 选中的文字（{len(t)} 字符，来自 {d.get('title') or d.get('url')}）："
                    f"\n{t}")
        if method == "clipboard":
            if d.get("mode") == "write":
                return f"📋 已写入剪贴板（{d.get('length', len(d.get('text') or ''))} 字符）{tag}"
            t = d.get("text") or ""
            return (f"📋 剪贴板内容（{len(t)} 字符）：\n{t}" if t
                    else "📋 剪贴板是空的" + tag)
        if method == "history":
            # ⚠️ 没这个分支数据会被默认分支丢掉（守卫 A1 盯的就是这个）
            its = d.get("items") or []
            if not its:
                return (f"🕘 没找到历史记录"
                        + (f"（关键词：{d.get('query')}）" if d.get("query") else "")
                        + f"{tag}")
            lines = [f"🕘 历史 {len(its)} 条"
                     + (f"（关键词：{d.get('query')}）" if d.get("query") else "") + f"{tag}"]
            for h in its[:60]:
                lines.append(f"- {h.get('title')}  {h.get('url')}"
                             + (f"  （访问 {h.get('visits')} 次）" if h.get("visits") else ""))
            return "\n".join(lines)
        if method == "close_tab":
            tid = d.get("tab_id")
            ok = d.get("closed", True)
            return (f"🗑️ 已关闭标签 {tid}{tag}" if ok
                    else f"❌ 没能关闭标签 {tid}{tag}")
        if method == "activate_tab":
            return f"🔀 已切到标签 {d.get('tab_id')}{tag}"
        if method == "mute_tab":
            return (f"{'🔇 已静音' if d.get('muted') else '🔊 已取消静音'}"
                    f"标签 {d.get('tab_id')}{tag}")
        if method == "pin_tab":
            return (f"{'📌 已固定' if d.get('pinned') else '📍 已取消固定'}"
                    f"标签 {d.get('tab_id')}{tag}")
        if method == "bookmarks":
            # ⚠️ 没有这个分支的话数据会被**默认分支丢掉**（守卫 A1 专门盯这个）：
            #    模型只会看到一句"操作成功"，书签却一条都没拿到。
            bms = d.get("bookmarks") or []
            if not bms:
                return (f"🔖 没找到书签"
                        + (f"（关键词：{d.get('query')}）" if d.get("query") else "")
                        + f"{tag}")
            head = (f"🔖 书签 {len(bms)} 条"
                    + (f"（筛选自 {d.get('total_bookmarks')} 条）"
                       if d.get("total_bookmarks") else "")
                    + ("，已达上限被截断" if d.get("truncated") else "")
                    + f"{tag}")
            lines = [head]
            for b in bms[:80]:
                if b.get("is_folder"):
                    lines.append(f"- 📁 {b.get('title')}  [{b.get('folder', '')}]")
                else:
                    lines.append(f"- {b.get('title')}  {b.get('url')}"
                                 + (f"  （{b.get('folder')}）" if b.get("folder") else ""))
            return "\n".join(lines)
        if method == "list_files":
            files = d.get("files") or []
            if not files:
                return f"目录里没有文件（{d.get('dir', '')}）{tag}"
            lines = [f"📁 {d.get('dir', '')}（共 {len(files)} 个）{tag}"]
            for f_ in files:
                lines.append(f"- {f_.get('name')}  {f_.get('size', 0)} 字节")
            return "\n".join(lines)
        if method in ("go_back", "refresh"):
            what = "返回上一页" if method == "go_back" else "刷新页面"
            return f"✅ 已{what}\n📄 当前页面: {d.get('url', '')} {tag}"
        if method == "hover":
            return f"✅ 已悬停 {tag}"
        if method == "upload_file":
            return (f"✅ 已上传文件到页面: {os.path.basename(d.get('path', ''))} {tag}")
        if method == "click":
            extra = ""
            if d.get("navigated"):
                extra = f"，页面已跳转到 {d.get('url')}"
            elif d.get("changed"):
                extra = "，页面内容已变化"
            return f"✅ 已点击{extra} {tag}"
        if method == "type_text":
            tail = "，并已提交" if d.get("submitted") else ""
            return f"✅ 已输入内容{tail} {tag}"
        if method == "scroll":
            return f"✅ 已滚动 {tag}"
        if method == "keyboard_press":
            return f"✅ 已按键 {tag}"
        if method == "keyboard_down_up":
            return f"✅ 键盘操作完成 {tag}"
        if method == "keyboard_type":
            return f"✅ 已用键盘输入文本 {tag}"
        if method == "mouse_move":
            return f"✅ 鼠标已移动到 ({d.get('x')}, {d.get('y')}) {tag}"
        if method == "mouse_click":
            extra = f"，页面已跳转到 {d.get('url')}" if d.get("navigated") else ""
            return f"✅ 已在坐标处点击{extra} {tag}"
        if method == "mouse_down_up":
            return f"✅ 鼠标按键操作完成 {tag}"
        if method == "mouse_wheel":
            return f"✅ 已滚动滚轮 {tag}"
        if method == "mouse_drag":
            return f"✅ 已完成拖拽 {tag}"
        return f"✅ 完成 {tag}"

    # ══════════════════════════════════════════════════════════════════
    #  WebSocket 端点（扩展接入）
    # ══════════════════════════════════════════════════════════════════

    @register.ws("/bridge", auth=True)
    async def bridge_endpoint(self, ws):
        if await self._reject_superseded_token(ws):
            return
        await self.bridge.handle_connection(ws)

    async def _reject_superseded_token(self, ws) -> bool:
        incoming = ws.query_params.get("token")
        if is_current_token(incoming):
            return False
        logger.warning("拒绝了使用过期令牌的扩展连接（请到面板复制新令牌）")
        try:
            await ws.accept()
            await ws.close(code=4003, reason="Token superseded, please re-pair")
        except Exception:
            pass
        return True

    # ══════════════════════════════════════════════════════════════════
    #  Hook
    # ══════════════════════════════════════════════════════════════════

    @on.llm_request(priority=Priority.HIGH)
    async def drop_write_tools_in_read_only(self, event, req: LLMRequest, *_):
        if not self.enabled or not self.read_only:
            return
        ts = getattr(req, "tool_set", None)
        if ts is not None:
            ts.remove(*WRITE_TOOL_NAMES)

    @on.llm_request(priority=Priority.MEDIUM)
    async def inject_browser_state(self, event, req: LLMRequest, *_):
        """注入当前可用后端和用户正在看的页面，让模型知道"我在操作谁"。"""
        if not self.enabled or not self.inject_page_state or self.router is None:
            return
        act = self.router.active
        lines = ["[浏览器状态]"]
        lines.append(f"可用后端：{self.router.describe()}")
        if act and act.is_user_browser:
            state = await self._collect_state()
            if state.get("tab_url"):
                lines.append(f"用户正在浏览：{state.get('tab_title') or '(无标题)'}")
                lines.append(f"网址：{state['tab_url']}")
                if state.get("tab_count"):
                    lines.append(f"打开的标签页数量：{state['tab_count']}")
        lines.append(f"能力：{self._capability_summary()}")
        block = "\n".join(lines)

        # ⚠️ 注入位置：**动态段 `chat_env`**，不是随便一个 system 段。
        #
        #    为什么：这个块里有"当前网址 / 标题 / 标签页数"，**每轮都可能变**。
        #    而提示词缓存按**前缀**命中 —— 把易变内容留在 system prompt 前缀里，
        #    等于每次一变就把**后面整段对话**的缓存全部作废（对话越长亏得越多）。
        #
        #    框架为此提供了"动态段重定位"：`sessions` / `chat_env` / `time`
        #    （v2.33.1 起 `memory` 也是）在 assemble 时会被标 `persist=False`、
        #    包上 `<system_reminder>`、**挪到最新 user 消息最前** ——
        #    system prompt 因此跨轮稳定，前缀缓存能覆盖整段记忆。
        #
        #    时机上这样是对的：本钩子（ON_LLM_REQUEST）在 message_manager 里
        #    **先于** `assemble_prompt()` 执行，所以往 `chat_env` 里加的内容
        #    会被那次重定位一并带走。
        from core.provider.llm_model import Prompt as _Prompt
        for _p in req.system_prompt:
            if getattr(_p, "name", None) == "chat_env":
                _p.content += f"\n{block}"
                break
        else:
            # 没有 chat_env 段（部署差异）→ 退化成"自己放进最新用户轮"，
            # 同样带 persist=False（不进记忆/日志）
            req.user_prompt.insert(
                0, _Prompt(content=block, name="browser_state",
                           source=PLUGIN_ID, persist=False))

    def _capability_summary(self) -> str:
        if self.read_only:
            return "只读（可查看页面内容，不能点击或输入）"
        if self.allowed_domains:
            return f"可读可写（写操作仅限白名单 {len(self.allowed_domains)} 条规则内的域名）"
        return "可读可写（无白名单限制，请注意风险）"

    async def _collect_state(self) -> dict:
        if self._last_state and time.time() - self._last_state.get("_ts", 0) < 120:
            return self._last_state
        act = self.router.active if self.router else None
        if act is None:
            return {}
        try:
            r = await act.list_tabs()
            tabs = (r.data or {}).get("tabs") or []
            a = next((t for t in tabs if t.get("active")), None)
            if a:
                self._last_state = {"tab_title": a.get("title"), "tab_url": a.get("url"),
                                    "tab_count": len(tabs), "_ts": time.time()}
        except Exception as e:
            logger.debug(f"获取浏览状态失败: {e}")
        return self._last_state

    async def _on_page_event(self, data: dict) -> None:
        self._last_state = {
            "tab_title": data.get("title"),
            "tab_url": data.get("url"),
            "tab_count": data.get("tab_count") or self._last_state.get("tab_count"),
            "_ts": time.time(),
        }

    async def _on_user_confirmed(self, data: dict) -> None:
        self._confirm_log.append({**data, "ts": time.time()})
        del self._confirm_log[:-50]

    # ══════════════════════════════════════════════════════════════════
    #  Tool —— 动作式接口
    #
    #  原版是 31 个平铺工具名。这里按「同类动作」合并成 12 个：
    #  模型只要记住「要干什么」+「对谁干」，不用记十几个近义名字。
    #  能力一个都没少（合并后用 verify_tools 逐条核对）。
    # ══════════════════════════════════════════════════════════════════

    # ── 1. 看：拿页面内容 ────────────────────────────────────────────

    @register.tool(
        name="browser_page",
        description=(
            "读页面。mode: info=标题+网址 / text=正文(默认) / outline=标题+可交互元素+链接"
            "/ html=原始HTML(很长) / selector=取选择器内文本 / extract=抽多条数据(配 attr/limit)。"
            "长页用 offset 续读。"
        ),
        params={"type": "object", "properties": {
            "mode": {"type": "string",
                     "enum": ["info", "text", "outline", "html", "selector", "extract", "selection"]},
            "selector": {"type": "string"},
            "attr": {"type": "string", "description": "extract 取该属性(如 href)，省略取文本"},
            "limit": {"type": "integer", "description": "extract 最多几条，默认 50"},
            "offset": {"type": "integer", "description": "正文起始字符位置"},
            "max_chars": {"type": "integer"},
            "tab_id": {"type": "integer"}},
            "required": []},
    )
    async def tool_page(self, event, mode: str = "text", selector: str = "",
                        attr: str = "", limit: int = 50, offset: int = 0,
                        max_chars: int = 0, tab_id=None, **_):
        if not self.enabled:
            return "浏览器插件未启用"
        m = (mode or "text").lower()
        if m == "info":
            return await self._call("get_info")
        if m == "selection":
            # 读用户**选中的文字**（扩展侧一直有 get_selection，只是没接出来）
            return await self._call("get_selection", for_write=False,
                                    tab_id=tab_id)
        if m == "extract":
            if not selector:
                return "mode=extract 需要提供 selector"
            return await self._call("extract", selector=selector,
                                    attr=(attr or None), limit=limit, tab_id=tab_id)
        if m == "selector":
            if not selector:
                return "mode=selector 需要提供 selector"
            return await self._call("get_page", detail="text", selector=selector,
                                    tab_id=tab_id)
        detail = m if m in ("text", "outline", "html") else "text"
        return await self._call("get_page", detail=detail, tab_id=tab_id,
                                offset=offset, max_chars=(max_chars or None))

    @register.tool(
        name="browser_tabs",
        description=(
            "标签页管理：列出 / 切换 / 关闭 / 静音 / 固定。"
            "关标签页**只能用这里的 action=close** —— Ctrl+W、window.close() "
            "对扩展注入的脚本无效（浏览器不允许），别再去试那些。"
        ),
        params={"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["list", "search", "activate", "close", "mute", "pin"],
                       "description": "默认 list（列出）"},
            "tab_id": {"type": "integer", "description": "目标标签（activate/close/mute/pin 用）"},
            "query": {"type": "string", "description": "action=search 用它筛标签；mute/pin/close 带 query 时**批量**作用于所有匹配的标签（按标题或网址匹配）"},
            "muted": {"type": "boolean", "description": "action=mute 时：true 静音 / false 取消"},
            "pinned": {"type": "boolean", "description": "action=pin 时：true 固定 / false 取消"},
        }, "required": []},
    )
    async def tool_tabs(self, event, action: str = "list", **_kw):
        if not self.enabled:
            return "浏览器插件未启用"
        a = (action or "list").lower()
        q = (_kw.get("query") or "").strip().lower()
        tid = _kw.get("tab_id")

        if a in ("list", ""):
            return await self._call("list_tabs", for_write=False)

        # 搜索 / 批量操作：先拿列表，在插件侧筛（扩展内部命令不计次，
        # 所以"筛完再逐个操作"完全可行 —— 不用给扩展加批量命令）。
        if a == "search" or ((a in ("mute", "pin", "close")) and q):
            r = await self._call("list_tabs", for_write=False)
            tabs = (r or {}).get("data", {}).get("tabs") if isinstance(r, dict) \
                else getattr(r, "data", {}).get("tabs", [])
            tabs = tabs or []
            hit = [t for t in tabs
                   if not q or q in (t.get("title", "") + " " + t.get("url", "")).lower()]
            if a == "search":
                if not hit:
                    return f"🔍 没有匹配「{q}」的标签（共 {len(tabs)} 个）"
                lines = [f"🔍 匹配「{q}」的标签 {len(hit)} 个："]
                for t in hit[:30]:
                    lines.append(f"- [{t.get('id')}] {t.get('title')}  {t.get('url')}"
                                 + ("  📌" if t.get("pinned") else "")
                                 + ("  🔇" if t.get("muted") else ""))
                return "\n".join(lines)
            # 批量：逐个调用（内部命令不计次）
            ok = 0
            for t in hit[:50]:
                try:
                    if a == "mute":
                        await self._call("mute_tab", for_write=True, tab_id=t.get("id"),
                                         muted=bool(_kw.get("muted", True)))
                    elif a == "pin":
                        await self._call("pin_tab", for_write=True, tab_id=t.get("id"),
                                         pinned=bool(_kw.get("pinned", True)))
                    else:
                        await self._call("close_tab", for_write=True, tab_id=t.get("id"))
                    ok += 1
                except Exception:
                    pass
            verb = {"mute": "静音", "pin": "固定", "close": "关闭"}[a]
            return f"✅ 已{verb} {ok} 个匹配「{q}」的标签（共匹配 {len(hit)} 个）"

        # ⚠️ 这些能力**扩展早就实现了**（`chrome.tabs.remove` /
        #    `chrome.tabs.update`），但插件侧一直只调了 `list_tabs` ——
        #    于是 bot 根本够不着，只能去试 Ctrl+W / window.close()，
        #    那些对注入脚本是无效的（浏览器不允许），结论就成了
        #    "浏览器桥没有关标签的 API"。其实是**没接出来**。
        if a == "close":
            return await self._call("close_tab", for_write=True, tab_id=tid)
        if a in ("activate", "switch"):
            return await self._call("activate_tab", for_write=True, tab_id=tid)
        if a == "mute":
            return await self._call("mute_tab", for_write=True, tab_id=tid,
                                    muted=bool(_kw.get("muted", True)))
        if a in ("pin", "unpin"):
            return await self._call("pin_tab", for_write=True, tab_id=tid,
                                    pinned=(a == "pin") if _kw.get("pinned") is None
                                    else bool(_kw.get("pinned")))
        return f"❌ 不认识的 action：{action}（可用：list/search/activate/close/mute/pin）"

    @register.tool(
        name="browser_screenshot",
        description=(
            "截图，并用视觉模型描述给你（工具结果是文本，图片不进你的上下文）。"
            "selector=只截元素；full_page=整页；describe=false 不要描述；send=false 不发用户。"
        ),
        params={"type": "object", "properties": {
            "full_page": {"type": "boolean"},
            "selector": {"type": "string"},
            "send": {"type": "boolean"},
            "describe": {"type": "boolean",
                         "description": (
                             "要不要让视觉模型也描述这张图（默认取插件配置）。"
                             "页面上有很多文字/表单时，browser_page 拿到的 DOM 文本"
                             "通常比图更快更准 —— 那类场景传 false 可以省掉几秒到几十秒；"
                             "但传了 false 你就**看不到画面本身**（布局、图片、验证码、"
                             "渲染异常这类只有图里才有的信息）。拿不准就别传。")}},
            "required": []},
    )
    async def tool_screenshot(self, event: KiraMessageBatchEvent, full_page: bool = False,
                              selector: str = "", send: bool = True,
                              describe=None, **_):
        if not self.enabled:
            return "浏览器插件未启用"
        prefix = "element" if selector else "screenshot"
        if self._headless is not None:
            path = os.path.join(self._headless.screenshot_dir,
                                self._headless.new_filename(prefix))
        else:
            # ⚠️ 同样不能写相对路径（`data/temp`）—— CWD 一变就落到别处。
            #    这里没有 headless 后端可问，就用框架数据目录推。
            # ⚠️ 必须是**相对导入**（`from .backends...`）。
            #    写 `from backends.headless_backend import ...` 是绝对导入 ——
            #    插件以包的形式加载（`<pkg>.main`）时 `backends` 不是顶层模块，
            #    这条会抛 ImportError: attempted relative import beyond top-level
            #    package。而它只在"headless 后端没注册"这一条分支里，
            #    平时走不到 ⇒ **静默**：真走到时整个 browser_diag(action="visible")
            #    直接崩。同文件里已经因为同样的坑栽过一次（见上面
            #    `_umb = ... ExtensionBackend.MAX_UPLOAD_BYTES` 那段注释）。
            from .backends.headless_backend import _framework_data_path
            _base = _framework_data_path(Path(self.ctx.get_plugin_data_dir()))
            _d = _base / "temp"
            os.makedirs(_d, exist_ok=True)
            path = os.path.join(str(_d), f"{prefix}_{int(time.time())}.png")
        # ⚠️ 这里**不再**有"可视区域截图不许回退"的特例参数 —— 因为从 2026-09-22 起
        #    `_call` 对**所有**操作都禁止中途换后端（用户要求）。扩展做不到整页/元素时
        #    就如实失败，并给出"想用无头请显式切换"的提示。
        r = await self._call("screenshot", path=path, full_page=full_page,
                             selector=selector or None)

        # 截图失败：直接回错，不要再去发图/描述
        if not (isinstance(r, str) and r.startswith("✅")):
            return r
        if not os.path.isfile(path):
            return r + "\n⚠️ 截图文件不在预期路径上，已跳过发送/描述"

        parts = [r]

        if send:
            sent = await self._send_image(event, path)
            parts.append("📤 图片已发送给用户" if sent else "⚠️ 图片发送失败")

        # —— VLM 描述：让 bot 也能"看到" ——
        # 模型每次可以自己决定要不要（describe 参数），默认取插件配置。
        want = self.auto_describe_screenshot if describe is None else bool(describe)
        if want:
            desc = await vlm.describe_image(
                self.ctx, path,
                configured_model=self.vlm_model,
                prompt=self.vlm_describe_prompt,
                timeout=self.vlm_timeout,
                # ⚠️ 默认**开**：不压的话 1920×1080 的截图会变成好几 MB 的
                #    data URL，配上框架写死的 detail:"high"，又慢又贵还容易超时。
                compress=self.vlm_compress,
                compress_max_size=self.vlm_compress_max_size,
                compress_quality=self.vlm_compress_quality,
            )
            if desc:
                parts.append(f"🖼️ 图片描述（VLM）：\n{desc}")
            else:
                # 这里**不要**展开讲原因 —— 一段六行的排查说明会挤进每次
                # 失败的返回里，既占 token 又干扰模型。细节都在
                # `browser_diag(action="vlm")`，要查的人自然会去查。
                parts.append("ℹ️ 这次没拿到图片描述（图已保存）。"
                             "排查：browser_diag action=\"vlm\"")
        return "\n".join(parts)

    # ── 2. 等 ────────────────────────────────────────────────────────

    @register.tool(
        name="browser_wait",
        description=(
            "等待。给 selector/text 就等它们出现（更准）；都没给则等 seconds 秒。"
        ),
        params={"type": "object", "properties": {
            "selector": {"type": "string"},
            "text": {"type": "string"},
            "timeout": {"type": "integer", "description": "最长等待秒数，默认 10"},
            "seconds": {"type": "number", "description": "单纯等待的秒数"}},
            "required": []},
    )
    async def tool_wait(self, event, selector=None, text=None, timeout: int = 10,
                        seconds: float = 0, **_):
        if not self.enabled:
            return "浏览器插件未启用"
        if selector or text:
            return await self._call("wait_for", selector=selector, text=text, timeout=timeout)
        sec = max(0.0, min(float(seconds or 0), 300.0))
        await asyncio.sleep(sec)
        return f"⏱️ 已等待 {sec} 秒"

    # ── 3. 动：所有交互合并成一个 ────────────────────────────────────

    @register.tool(
        name="browser_interact",
        description=(
            "操作页面。action→参数：\n"
            "click/hover: selector|text|index\n"
            "fill/type: selector+value（submit=true 回车；clear_first 默认 true）\n"
            "scroll: direction+amount\n"
            "upload: selector+file_path\n"
            "go_back/refresh: 无\n"
            "key_press: key（Enter / Control+a）；key_type: text\n"
            "低层鼠标（CSS 定位不到时用）: mouse_click/move(x,y) "
            "mouse_wheel(delta_x/y) mouse_drag(start_x/y,end_x/y) mouse_down/up(button)"
        ),
        params={"type": "object", "properties": {
            "action": {"type": "string", "enum": [
                "click", "fill", "type", "hover", "scroll", "upload",
                "go_back", "refresh", "key_press", "key_down", "key_up", "key_type",
                "mouse_click", "mouse_move", "mouse_down", "mouse_up",
                "mouse_wheel", "mouse_drag", "bookmarks", "history",
                "clipboard_get", "clipboard_set"]},
            "selector": {"type": "string", "description": "CSS 选择器"},
            "text": {"type": "string", "description": "可见文字 / key_type 的文本"},
            "index": {"type": "integer", "description": "第几个可点击元素，从 0 开始"},
            "value": {"type": "string", "description": "填入的文本"},
            "file_path": {"type": "string", "description": "上传文件绝对路径"},
            "key": {"type": "string", "description": "Enter / Tab / Control+a"},
            "direction": {"type": "string", "enum": ["up", "down", "top", "bottom"]},
            "amount": {"type": "integer", "description": "滚动像素"},
            "timeout": {"type": "integer", "description": "等待超时秒数"},
            "x": {"type": "integer"}, "y": {"type": "integer"},
            "delta_x": {"type": "integer"}, "delta_y": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "steps": {"type": "integer"}, "click_count": {"type": "integer"},
            "start_x": {"type": "integer"}, "start_y": {"type": "integer"},
            "end_x": {"type": "integer"}, "end_y": {"type": "integer"},
            "submit": {"type": "boolean"}, "clear_first": {"type": "boolean"},
            "query": {"type": "string",
                      "description": "只在 action=bookmarks 时用：按关键词过滤书签（匹配标题或网址）"},
            "tab_id": {"type": "integer"}},
            "required": ["action"]},
    )
    async def tool_interact(self, event, action: str, **kw):
        if not self.enabled:
            return "浏览器插件未启用"
        a = (action or "").lower()
        w = True          # 默认按写操作处理

        if a in ("clipboard_get", "clipboard_read", "clipboard_set", "clipboard_write"):
            # 剪贴板读写。⚠️ **读**要求页面在前台聚焦（浏览器隐私限制），
            #    失败时会说清原因，而不是笼统报错。
            mode = "write" if a.endswith(("set", "write")) else "read"
            return await self._call("clipboard", for_write=(mode == "write"),
                                    mode=mode, text=kw.get("text") or "",
                                    tab_id=kw.get("tab_id"))

        if a == "history":
            # 看过的网页（chrome.history）—— 和书签同理，是**数据**不是页面
            if not self.allow_history:
                return ("🔒 浏览历史读取**未开启**（默认关，属于隐私数据）。"
                        "需要的话请在插件配置里打开「允许读取浏览历史」。"
                        "书签（action=\"bookmarks\"）不受这个开关限制。")
            return await self._call("history", for_write=False,
                                    query=kw.get("query"),
                                    limit=kw.get("amount") or 100,
                                    days=int(kw.get("days") or 0))

        if a in ("bookmarks", "bookmark"):
            # 读书签**数据**（不是那个页面）。
            # ⚠️ 为什么需要：`edge://bookmarks` 是浏览器内部页，任何扩展都注入
            #    不进去（硬边界），"打开书签页去读"这条路是死的。但书签数据本身
            #    可以走 chrome.bookmarks 拿 —— 用户要的是书签，不是那个页面。
            #    这是**读**操作（w=False），不需要回带页面。
            return await self._call("bookmarks", for_write=False,
                                    query=kw.get("query"),
                                    max=kw.get("amount") or 200,
                                    folders_only=bool(kw.get("folders_only")))

        if a == "click":
            if not any([kw.get("selector"), kw.get("text"), kw.get("index") is not None]):
                return "action=click 需要 selector、text 或 index 之一"
            return await self._call("click", for_write=w, selector=kw.get("selector"),
                                    text=kw.get("text"), index=kw.get("index"))
        if a == "fill":
            if not kw.get("selector"):
                return "action=fill 需要 selector"
            return await self._call("type_text", for_write=w,
                                    selector=kw["selector"], text=kw.get("value", ""),
                                    clear_first=kw.get("clear_first", True))
        if a == "type":
            if not kw.get("selector"):
                return "action=type 需要 selector"
            return await self._call("type_text", for_write=w,
                                    selector=kw["selector"], text=kw.get("value", ""),
                                    submit=bool(kw.get("submit")),
                                    clear_first=kw.get("clear_first", True))
        if a == "hover":
            if not kw.get("selector"):
                return "action=hover 需要 selector"
            return await self._call("hover", for_write=w, selector=kw["selector"])
        if a == "scroll":
            d = kw.get("direction")
            if d not in ("up", "down", "top", "bottom"):
                return "action=scroll 需要 direction（up/down/top/bottom）"
            return await self._call("scroll", for_write=w, direction=d,
                                    amount=kw.get("amount"))
        if a == "upload":
            fp = kw.get("file_path")
            if not kw.get("selector") or not fp:
                return "action=upload 需要 selector 和 file_path"
            # ⚠️ 路径白名单必须在**读文件之前**判 ——
            #    否则模型可以借"上传"把本机任意文件送到远端页面。
            resolved = os.path.realpath(str(fp))
            if not os.path.isfile(resolved):
                return f"❌ 文件不存在或不是常规文件: {fp}"
            if not self._path_allowed(resolved):
                return (f"❌ 出于安全考虑，只允许上传以下目录中的文件："
                        f"{', '.join(self.upload_allowed_dirs)}"
                        f"（或把配置 upload_allow_any_path 打开）")
            return await self._call("upload_file", for_write=w,
                                    selector=kw["selector"], file_path=resolved)
        if a == "go_back":
            return await self._call("go_back", for_write=w)
        if a == "refresh":
            return await self._call("refresh", for_write=w)

        if a in ("key_press", "key_down", "key_up", "key_type"):
            if a == "key_type":
                if not kw.get("text"):
                    return "action=key_type 需要 text"
                return await self._call("keyboard_type", for_write=w, text=kw["text"])
            k = kw.get("key")
            if not k:
                return f"action={a} 需要 key"
            if a == "key_press":
                return await self._call("keyboard_press", for_write=w, key=k)
            return await self._call("keyboard_down_up", for_write=w,
                                    action=("down" if a == "key_down" else "up"), key=k)

        if a in ("mouse_click", "mouse_move", "mouse_down", "mouse_up",
                 "mouse_wheel", "mouse_drag"):
            if a == "mouse_move":
                if kw.get("x") is None or kw.get("y") is None:
                    return "action=mouse_move 需要 x 和 y"
                return await self._call("mouse_move", for_write=w,
                                        x=kw["x"], y=kw["y"], steps=kw.get("steps", 1))
            if a == "mouse_click":
                return await self._call("mouse_click", for_write=w,
                                        x=kw.get("x"), y=kw.get("y"),
                                        button=kw.get("button", "left"),
                                        click_count=kw.get("click_count", 1))
            if a in ("mouse_down", "mouse_up"):
                return await self._call("mouse_down_up", for_write=w,
                                        action=("down" if a == "mouse_down" else "up"),
                                        button=kw.get("button", "left"))
            if a == "mouse_wheel":
                return await self._call("mouse_wheel", for_write=w,
                                        delta_x=kw.get("delta_x", 0),
                                        delta_y=kw.get("delta_y", 0))
            need = ("start_x", "start_y", "end_x", "end_y")
            if any(kw.get(k) is None for k in need):
                return "action=mouse_drag 需要 start_x/start_y/end_x/end_y"
            return await self._call("mouse_drag", for_write=w,
                                    start_x=kw["start_x"], start_y=kw["start_y"],
                                    end_x=kw["end_x"], end_y=kw["end_y"],
                                    button=kw.get("button", "left"),
                                    steps=kw.get("steps", 10))

        return (f"未知 action「{action}」。可用：click / fill / type / hover / scroll / "
                f"upload / go_back / refresh / key_press / key_down / key_up / key_type / "
                f"mouse_click / mouse_move / mouse_down / mouse_up / mouse_wheel / mouse_drag")

    # ── 4. 去 ────────────────────────────────────────────────────────

    @register.tool(
        name="browser_navigate",
        description=(
            "打开网址，**也可以打开本机文件**（图片 / PDF / 文本 / 视频等）。"
            "url 直接写完整路径即可，如 /data/temp/a.png 或 "
            "C:\\Users\\me\\Desktop\\a.pdf，插件会自动转成能打开的地址。"
        ),
        params={"type": "object", "properties": {
            "url": {"type": "string",
                    "description": "完整网址，或本机文件路径"},
            "new_tab": {"type": "boolean"}},
            "required": ["url"]},
    )
    async def tool_navigate(self, event, url: str, new_tab: bool = False, **_):
        if not self.enabled:
            return "浏览器插件未启用"
        url = (url or "").strip()
        if not url:
            return "❌ 没给网址"
        # ⚠️ **先判本地路径**，再判 scheme。
        #    顺序反过来的话，`C:\Users\me\a.png` 会被当成 scheme "c:" 直接放行，
        #    最后报一个谁也看不懂的 URL 错误 —— 这正是用户遇到的形态之一。
        if security.looks_like_local_path(url):
            # ⚠️ 记下"用户给的是相对路径"这件事 —— 转成 file:// 之后就看不出来了
            #    （`definitely_not_here\x.png` → `file:///definitely_not_here/x.png`，
            #    看着就是个绝对路径）。报错时要用这个标记告诉用户
            #    "请给完整路径"，否则他会去反复检查一个其实写对了的文件名。
            _was_relative = not security.is_absolute_local_path(url)
            url = security.path_to_file_url(url)
        else:
            _was_relative = False
        # ⚠️ 只在"**完全没有 scheme**"时才补前缀。
        #    原来是 `if not url.startswith(("http://", "https://")): url = "https://" + url`
        #    —— 于是 `about:blank` 变成 `https://about:blank`、`edge://settings`
        #    变成 `https://edge://settings`，全都变成非法 URL。
        #    日志里那句 `[navigate] 失败：Invalid url: "https://about:blank"`
        #    就是这么来的。
        #
        #    判据不能只看"有没有冒号" —— `localhost:3000/p` 也长成 `x:y`，
        #    但它是**主机:端口**、不是 scheme。所以三条一起看：
        #      ① 形如 `scheme:`（字母开头）
        #      ② 冒号前**不含点**（含点的多半是域名，如 example.com:8080）
        #      ③ 冒号后**不以数字开头**（`localhost:3000` 的 3 是端口号）
        #    三条都成立才当 scheme（about: / edge: / chrome: / file: /
        #    data: / view-source: / mailto: …）。
        import re as _re
        _m = _re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):(.*)$", url, _re.S)
        _is_scheme = bool(_m) and "." not in _m.group(1) \
            and not _m.group(2)[:1].isdigit()
        if not _is_scheme:
            # 本机地址用 http（https 在 127.0.0.1/localhost 上基本连不上）
            _host = url.split("/")[0].split(":")[0].lower()
            _scheme = "http" if (_host in ("localhost", "127.0.0.1", "::1")
                                 or _host.endswith(".local")) else "https"
            url = f"{_scheme}://" + url.lstrip("/")
        # ⚠️ 本地文件先查一遍"在不在"。
        #    不然这条会一路走到浏览器里，报一句
        #   `net::ERR_FILE_NOT_FOUND`（或扩展的 "Invalid url"），
        #    模型不知道是路径写错了还是权限没开。这里直接说清楚。
        if security.parse_scheme(url) in security.FILE_SCHEMES:
            # ⚠️ **先判策略，再判文件在不在**。顺序反过来的话：
            #    · 用户把「允许打开本机文件」关掉后，仍然能从返回的
            #      "文件不存在/存在"反推出磁盘上的情况 ——
            #      一个已经关掉的开关不该还能被用来探测文件系统；
            #    · 报错也会指向错误的方向（用户以为路径写错了，
            #      其实是策略拦的）。
            if not self.local_file_access:
                return ("打开本机文件已按配置关闭（「允许打开本机文件」）。"
                        "如确实需要，请在插件配置里打开它。")
            _ok, _why = security.check_url(
                url, local_file_access=True,
                file_allow_any_path=self.file_allow_any_path,
                file_allowed_dirs=self.file_allowed_dirs)
            if not _ok:
                return f"❌ {_why}"
            _p = security.file_url_to_path(url)
            if not _p or not os.path.isfile(_p):
                return (f"❌ 本机不存在这个文件：{_p or url}\n"
                        f"（路径要写全：Windows 形如 C:\\Users\\me\\a.png，"
                        f"Linux/macOS 形如 /home/me/a.png）"
                        + ("\n⚠️ 你给的是**相对路径**，它的基准取决于"
                           "KiraAI 的启动目录，插件没法可靠地猜 —— "
                           "请换成**完整路径**再试。"
                           if _was_relative else ""))
        # ⚠️ 导航完**顺手把新页面带回来** —— "导航 → 再看一眼"是浏览器里
        #    最常见的两次调用，合起来才够用（框架默认每轮只有 5 次）。
        r = await self._call("navigate", for_write=True, url=url, new_tab=new_tab)
        # ⚠️ 本地文件**不要**顺手回正文：
        #    · HTML → 回一大堆标签源码，对模型没用、纯烧 token；
        #    · 图片 / 视频 / PDF → 根本没有可读文本，回了也是空；
        #    而"看画面"本来就该走 browser_screenshot（截渲染后的画面）。
        if security.parse_scheme(url) in security.FILE_SCHEMES:
            return (f"{r}\n\n📂 这是本机文件（不是网页）。\n"
                    f"· 要看**画面**（图片 / 视频 / PDF / 渲染出的效果）"
                    f"→ 用 browser_screenshot；\n"
                    f"· 要看**纯文本内容**（txt / md / 代码等）"
                    f"→ 用 browser_page。")
        return await self._with_page_after(r, chars=800)

    # ── 5. 脚本 ──────────────────────────────────────────────────────

    @register.tool(
        name="browser_script",
        description="在页面执行 JavaScript 并返回结果。",
        params={"type": "object", "properties": {
            "script": {"type": "string",
                       "description": "JS 表达式，如 document.title"}},
            "required": ["script"]},
    )
    async def tool_script(self, event, script: str, **_):
        if not self.enabled:
            return "浏览器插件未启用"
        # ⚠️ 必须标成写操作：执行任意 JS 能干任何事，
        #    不标的话**只读模式对它完全无效**（也不走域名白名单校验）——
        #    那等于只读模式形同虚设。
        return await self._call("execute_js", for_write=True, script=script)

    # ── 6. 文件 ──────────────────────────────────────────────────────

    @register.tool(
        name="browser_file",
        description=(
            "文件操作。mode=download 下载 URL 到本地并发给用户（带登录态）；"
            "mode=list 列已下载/截图文件。上传用 browser_interact(upload)。"
        ),
        params={"type": "object", "properties": {
            "mode": {"type": "string", "enum": ["download", "list"]},
            "url": {"type": "string"},
            "filename": {"type": "string"},
            "dir_type": {"type": "string", "enum": ["downloads", "screenshots"]},
            "limit": {"type": "integer"}},
            "required": []},
    )
    async def tool_file(self, event: KiraMessageBatchEvent, mode: str = "download",
                        url: str = "", filename: str = "", dir_type: str = "downloads",
                        limit: int = 20, **_):
        if not self.enabled:
            return "浏览器插件未启用"
        m = (mode or "download").lower()
        if m == "list":
            return await self._call("list_files", dir_type=dir_type, limit=limit)
        if not url:
            return "mode=download 需要提供 url"
        if self._headless is None:
            return "❌ 下载需要无头后端做落盘"
        name = filename or (os.path.basename(url.split("?")[0]) or f"download_{int(time.time())}")
        name = os.path.basename(name.replace("\\", "/"))
        err = await self._headless.start()
        if err:
            return err
        path = os.path.join(self._headless.download_dir, name)
        # 优先让扩展桥去下（带用户的登录态）；失败或没连上再回退无头自己下
        r = await self._call("download", for_write=True, url=url, path=path)
        if isinstance(r, str) and r.startswith("❌") and self._headless is not None:
            hr = await self._headless.download(url, path)
            if not hr.ok:
                return f"❌ {hr.error}"
            r = f"✅ 文件已下载: {path}（{hr.data.get('size')} 字节）"
        # ⚠️ 发送前确认文件真的落盘了。
        #    下载成功之后文件仍可能不在（路径被改、磁盘问题、上面的分支没走到），
        #    这时还去 _send_file 并回一句"已发送给用户"，就是**假成功** ——
        #    用户会一直等一个永远不会到的文件。
        import os as _os
        if not _os.path.isfile(path):
            return (f"⚠️ 文件不在路径上（{path}），**没有发送**。"
                    f"请检查下载是否真的成功。")
        # ⚠️ 还要看发送本身成没成 —— `_send_file` 返回 False 时
        #    文件仍在本地，但用户没收到。这里若照旧拼一句"已发送给用户"，
        #    模型就会对用户说"文件发你了"，而用户那边什么都没有。
        if not await self._send_file(event, path, name):
            return (f"{r}\n⚠️ 文件已下载到 {path}，但**发送给用户失败**。"
                    f"请告知用户文件没能发出。")
        return r + f"\n📤 已发送给用户: {name}"

    # ── 7. Cookie（打通两个后端的登录态）──────────────────────────────

    @register.tool(
        name="browser_cookie",
        description=(
            "导出/写入 cookie，把「你浏览器里的登录态」带到另一个后端。"
            "action=export 导出（当前页或指定 url）；action=import 写入。"
        ),
        params={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["export", "import"]},
            "url": {"type": "string", "description": "export 目标，省略用当前页"},
            "cookies": {"type": "array",
                        # ⚠️ `items` **必须写**：Gemini 的函数声明 schema 比
                        #    JSON Schema 严 —— 数组没有 items 直接 400：
                        #      tools[0].function_declarations[..].properties
                        #      [cookies].items: missing field.
                        #    OpenAI 宽松所以没事，换 Gemini 就整个模型组失败 ✗
                        "items": {"type": "object",
                                  "properties": {
                                      "name": {"type": "string"},
                                      "value": {"type": "string"},
                                      "domain": {"type": "string"},
                                      "path": {"type": "string"},
                                      "secure": {"type": "boolean"},
                                      "httpOnly": {"type": "boolean"},
                                      "expires": {"type": "number"}}},
                        "description": "import 要写入的 cookie 数组"
                                       "（每项至少有 name + value；"
                                       "export 出来的可以原样传回来）"}},
            "required": ["action"]},
    )
    async def tool_cookie(self, event, action: str, url: str = "", cookies=None, **_):
        if not self.enabled:
            return "浏览器插件未启用"
        a = (action or "").lower()
        if a == "export":
            return await self._call("cookie_get", url=url)
        if a == "import":
            if not cookies:
                return "action=import 需要提供 cookies"
            return await self._call("cookie_set", for_write=True, cookies=cookies)
        return "action 只能是 export 或 import"

    # ── 8. 排障 / 帮助 ───────────────────────────────────────────────

    async def _diag_vlm(self):
        """检查 VLM 配置。

        ⚠️ 这个工具原版有，v2.1.0 重写时被整段丢掉。
        它正好是恢复 VLM 描述功能之后最需要的自查入口 ——
        没有它，用户遇到"没描述"只能翻日志。
        """
        if not self.enabled:
            return "浏览器插件未启用"

        info = ["🔍 截图分析（VLM）配置检查", ""]

        # ── 插件侧配置 ────────────────────────────────────────────────
        if self.vlm_model:
            info.append(f"· 插件配置指定的模型：{self.vlm_model}")
        else:
            info.append("· 插件未指定模型 → **使用框架设置里的默认 VLM**（推荐）")
        info.append(f"· 自动描述截图：{'开' if self.auto_describe_screenshot else '关'}"
                    f"（模型每次可以自己用 describe 参数覆盖）")
        info.append(f"· 超时：{self.vlm_timeout} 秒")
        info.append(f"· 提示词：{'自定义' if self.vlm_describe_prompt else '内置（网页分析用）'}")

        # ── 实际会用的模型 ────────────────────────────────────────────
        info.extend(["", "📷 实际会使用的模型："])
        try:
            client = await vlm.get_vlm_client(self.ctx, self.vlm_model)
        except Exception as e:
            client = None
            info.append(f"  ❌ 取 VLM 客户端时异常：{e}")

        if client is None:
            info.extend([
                "  ❌ **没有可用的 VLM 模型** —— 截图能拍、能发给用户，"
                "但 bot 看不到内容。",
                "  常见原因：",
                "    · 没配任何视觉模型；",
                "    · **模型配错了组**：用于描述的模型必须是「大语言模型」组里的"
                "（不能放「图像」组），即使它本身支持视觉。",
            ])
        else:
            m = getattr(client, "model", None)
            mid = getattr(m, "model_id", "?")
            pid = getattr(m, "provider_id", "?")
            info.append(f"  ✅ {pid}:{mid}")
            type_ok = vlm.is_vision_model(client)
            info.append(f"  视觉能力：{'✅ 看起来支持' if type_ok else '❌ 看起来不支持'}")
            if not type_ok:
                info.append("  （模型名像 embedding/tts 之类，描述会失败）")

        # ── 系统里有哪些可选的视觉模型 ────────────────────────────────
        info.extend(["", "📋 系统里可用的 LLM 模型："])
        try:
            vision, others = [], []
            mgr = self.ctx.provider_mgr
            providers = mgr.get_all_providers()
            for pid, _prov in providers.items():
                try:
                    infos = mgr.get_model_infos(pid)
                except Exception:
                    continue
                for mi in infos:
                    try:
                        mt = getattr(mi.model_type, "value", str(mi.model_type))
                    except Exception:
                        mt = ""
                    if mt != "llm":
                        continue
                    uuid = f"{pid}:{mi.model_id}"
                    lower = str(mi.model_id).lower()
                    if any(x in lower for x in
                           ("embedding", "rerank", "tts", "stt", "davinci",
                            "babbage", "whisper")):
                        others.append(f"    {uuid}")
                    else:
                        vision.append(f"  👁️ {uuid}")
            if vision:
                info.append("  可能支持视觉（选其中一个填到「VLM 模型」）：")
                info.extend(vision[:10])
            if others:
                info.append("  其它（看起来不支持视觉）：")
                info.extend(others[:10])
            if not vision and not others:
                info.append("  ⚠️ 没有找到任何 LLM 模型")
        except Exception as e:
            info.append(f"  ⚠️ 取模型列表失败：{e}")

        # ── 系统默认 VLM ──────────────────────────────────────────────
        info.extend(["", "🔧 框架默认 VLM："])
        try:
            dv = self.ctx.provider_mgr.get_default_vlm()
            if dv and getattr(dv, "model", None):
                info.append(f"  ✅ {dv.model.provider_id}:{dv.model.model_id}"
                            f"（{type(dv).__name__}）")
            else:
                info.append("  ⚠️ 没有配置框架默认 VLM")
                info.append("     可在 KiraAI 的模型设置里指定「默认 VLM」，"
                            "或在本插件配置里选「VLM 模型」")
        except TypeError as e:
            info.append(f"  ❌ 框架默认 VLM 的类型不对：{e}")
            info.append("     默认 VLM 必须是**大语言模型**组里的模型")
        except Exception as e:
            info.append(f"  ⚠️ 取默认 VLM 失败（可能没配）：{e}")

        info.extend([
            "",
            "💡 怎么配：",
            "  1) 推荐：在 KiraAI 的模型设置里指定默认 VLM，本插件留空即可；",
            "  2) 或：在本插件配置的「VLM 模型」里选一个视觉模型；",
            "  3) ⚠️ 无论哪种，用来描述的模型都必须放在**大语言模型**组，"
            "不能放「图像」组。",
        ])
        return "\n".join(info)

    @register.tool(
        name="browser_backend",
        description=(
            "查看/切换用哪个浏览器后端。\n"
            "action=status 看当前用哪个；action=use 显式切换"
            "（extension=自己的浏览器 / headless=无头浏览器 / auto=回到配置策略）。\n"
            "两者是两套独立浏览器：切到 headless 后，你看的是它自己打开的那个页面。\n"
            "只有「后端策略」= auto 时才切得动（用户固定成某一类时本工具会拒绝）。"
            "插件不会自动换后端。"
        ),
        params={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["status", "use"]},
            "use": {"type": "string", "enum": ["extension", "headless", "auto"]},
        }, "required": ["action"]},
    )
    async def tool_backend(self, event, action: str = "status", use: str = "", **_):
        if not self.enabled:
            return "浏览器插件未启用"
        a = (action or "status").lower()
        if a == "status":
            return self._describe_backend_choice()
        if a != "use":
            return "action 只能是 status / use"
        # ⚠️ 用户把策略固定成某一类 = 用户的决定，**谁也别改**（用户明确要求）
        if self.backend_strategy != "auto":
            label = {"extension": "只用扩展桥", "headless": "只用无头浏览器"}.get(
                self.backend_strategy, self.backend_strategy)
            return f"🚫 不改：「后端策略」被用户固定成「{label}」。要换请让用户改插件配置。"
        want = (use or "").lower()
        if want == "auto":
            self._backend_override = None
            self._degrade_announced = False
            return "✅ 已回到配置策略（auto：扩展优先）。\n" + self._describe_backend_choice()
        if want not in ("extension", "headless"):
            return "use 只能是 extension / headless / auto"
        b = self.router.by_name(want) if self.router else None
        if b is None:
            return f"❌ 这个后端没启用（配置里关掉了？）：{want}"
        if not b.available:
            if not await self._probe(b):
                if want == "extension":
                    return ("❌ 切不过去：扩展没连上。打开一次你的 KiraAI 页面"
                            "（或点扩展图标确认已连接）再试。")
                return ("❌ 切不过去：无头浏览器起不来。"
                        "可用 browser_diag(action=\"status\") 看具体原因。")
        self._backend_override = want
        self._degrade_announced = False
        what = "另一套浏览器，页面不是用户那个" if want == "headless" else "用户自己的浏览器"
        return (f"✅ 已切到「{b.display}」（{what}）。运行时生效，插件重载后回配置值。\n"
                + self._describe_backend_choice())

    def _describe_backend_choice(self) -> str:
        """把"现在到底用哪一个、还能不能换"讲清楚（给 bot 和用户都看得懂）。"""
        cands = self._candidates()
        cur = cands[0] if cands else None
        switchable = self.backend_strategy == "auto"
        head = f"🔍 后端：{cur.display if cur else '没有可用的后端'}"
        if self._backend_override:
            head += f"（运行时切换：{self._backend_override}）"
        return "\n".join([
            head,
            f"策略：{self.backend_strategy}｜可切换：{'是' if switchable else '否（用户固定了策略）'}",
            ("切换：browser_backend(action=\"use\", use=\"extension|headless|auto\")"
             if switchable else "切换：无 —— 要改请让用户改插件配置"),
        ])

    @register.tool(
        name="browser_diag",
        description=(
            "查状态 / 排障。action：\n"
            "status=后端状态（用哪个后端、profile 模式、超时、空闲多久）\n"
            "vlm=截图分析实际用哪个视觉模型（browser_screenshot 返回「未能生成图片描述」时查）\n"
            "visible=打开测试页，确认可视模式窗口是否真的显示出来了\n"
            "extension=扩展装在哪、怎么装、接入令牌（用户问「怎么让你看我的浏览器」时用）"
        ),
        params={"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["status", "vlm", "visible", "extension"]}},
            "required": ["action"]},
    )
    async def tool_diag(self, event, action: str, **_):
        if not self.enabled:
            return "浏览器插件未启用"
        a = (action or "").lower()
        if a == "status":
            return await self._diag_status()
        if a == "vlm":
            return await self._diag_vlm()
        if a == "visible":
            return await self._diag_visible()
        if a == "extension":
            return await self._diag_extension()
        return "action 只能是 status / vlm / visible / extension"

    async def _diag_status(self):
        if not self.enabled:
            return "浏览器插件未启用"
        parts = ["🔍 浏览器插件状态", "",
                 f"后端策略: {self.backend_strategy}",
                 f"路由: {self.router.describe() if self.router else '未初始化'}",
                 f"op_timeout 跟随框架: {self.op_timeout_follows_framework}"]
        if self._headless is not None:
            r = await self._headless.debug_state()
            d = r.data or {}
            parts += ["", "无头后端:"]
            for k in ("backend", "available", "headless", "profile_mode",
                      "profile_dir", "wait_until", "op_timeout", "action_timeout",
                      "idle_close_seconds", "idle_for", "pages_open",
                      "launch_args_count"):
                parts.append(f"  {k}: {d.get(k)}")
        return "\n".join(parts)

    async def _diag_visible(self):
        if not self.enabled:
            return "浏览器插件未启用"
        html = ("<!doctype html><meta charset='utf-8'><title>可视模式测试</title>"
                "<body style='font-family:sans-serif;text-align:center;padding:60px'>"
                "<h1>🎉 如果你能看到这个窗口，说明可视模式正常</h1>"
                "<p>当前时间：<span id=t></span></p>"
                "<script>document.getElementById('t').textContent=new Date().toLocaleString()</script>")
        import tempfile as _tf
        p = os.path.join(_tf.gettempdir(), "kira_visible_test.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(html)
        r = await self._call("navigate", for_write=True, url=f"file://{p}")
        if self._headless is not None and self._headless.headless:
            return r + ("\n\n⚠️ 当前是无头模式，窗口不可见。"
                        "把配置里的「无头模式」关掉并重载插件就能看到窗口。")
        return r + "\n\n👀 去屏幕上找一下这个测试页面；看不到就用 browser_diag(action=\"status\") 看状态。"

    async def _diag_extension(self):
        plugin_dir = Path(__file__).resolve().parent
        parts = [setup_guide.compatibility_report(), ""]
        notice = setup_guide.first_run_notice(
            plugin_dir, self.bridge.connected,
            profile_mode=self._headless_cfg.get("headless_profile_mode", "inherit"))
        parts.append(notice if notice
                     else "✅ 扩展已连接，AI 现在可以直接操作你正在用的浏览器。")
        d = setup_guide.extension_dir(plugin_dir)
        parts += ["", f"📁 扩展文件夹（可直接复制这个路径）：\n     {d}"]
        if self._token:
            parts.append(f"\n🔑 接入令牌（粘到扩展里）：\n     {self._token}")
        return "\n".join(parts)


    @register.api("GET", "/extension", auth=True)
    async def api_extension(self):
        """面板用：扩展位置、安装步骤、令牌、是否已连接。"""
        plugin_dir = Path(__file__).resolve().parent
        d = setup_guide.extension_dir(plugin_dir)
        browsers = setup_guide.known_chromium_browsers()
        primary = browsers[0]["name"] if browsers else "chrome"
        return {
            "packaged": setup_guide.extension_exists(plugin_dir),
            "path": str(d),
            "connected": self.bridge.connected,
            "browsers_found": browsers,
            "steps": setup_guide.steps_for(primary, str(d)),
            "extensions_url": setup_guide.EXTENSIONS_URL.get(primary, "chrome://extensions"),
            "token": self._token,
            "compatibility": setup_guide.compatibility_report(),
        }

    @register.api("GET", "/status", auth=True)
    async def api_status(self):
        # 扩展"该不该更新"：**后端算一次**，面板只渲染 state。
        # 版本号来自两处真源：插件自带的 browser-bridge/manifest.json，
        # 以及扩展握手时上报的 chrome.runtime.getManifest().version。
        # ⇒ 以后插件把扩展升到 1.6.0，用户那边还是 1.5.0，提示会自动出现，
        #   前端一行都不用改（"未来都可以检测"）。
        try:
            _bundled = setup_guide.bundled_extension_version(
                Path(__file__).resolve().parent)
            _hello = getattr(self.bridge, "_hello", None)
            _ext_state = setup_guide.extension_update_state(
                bundled=_bundled,
                connected=getattr(_hello, "extension_version", None),
                is_connected=self.bridge.connected,
                protocol_ok=(getattr(_hello, "protocol", None) in (None, P.PROTOCOL_VERSION)),
            )
        except Exception as e:                     # 提示功能不能拖垮 /status
            logger.warning(f"计算扩展更新状态失败：{type(e).__name__}: {e}")
            _ext_state = setup_guide.extension_update_state(None, None, False)
        return {
            "enabled": self.enabled,
            "plugin_version": getattr(self, "PLUGIN_VERSION", "") or "",
            "connected": self.bridge.connected,
            "bridge": self.bridge.info,
            "extension": _ext_state,
            "router": {
                "strategy": self.backend_strategy,
                "active": self.router.active.display if (self.router and self.router.active) else None,
                "describe": self.router.describe() if self.router else "",
            },
            "policy": {
                "read_only": self.read_only,
                "require_confirm": self.require_confirm,
                "allowed_domains": self.allowed_domains,
                "blocked_domains": self.blocked_domains,
                # 面板要据此显示"本机/内网：允许 / 已拒绝"
                "local_access": self.local_access,
                "max_content_chars": self.max_content_chars,
            },
            "last_state": {k: v for k, v in self._last_state.items() if k != "_ts"},
            "confirm_log": list(reversed(self._confirm_log[-20:])),
        }

    @register.api("POST", "/token", auth=True)
    async def api_issue_token(self, force: bool = True):
        if not self.panel_auth_required:
            logger.warning("「配置面板需要登录」已关闭：令牌端点仍保持登录校验")
        try:
            before = self._token
            self._token = ensure_token(force=bool(force))
            if force:
                logger.info("面板请求重新生成令牌：旧令牌已全部作废")
        except Exception as e:
            logger.error(f"签发扩展令牌失败: {e}")
            return {"ok": False, "error": str(e)}
        return {"ok": True, "token": self._token, "expires": token_expiry(),
                "never_expires": token_expiry() is None,
                "changed": self._token != before,
                # 路径里的插件 id 必须与 manifest.plugin_id 一致，
                # 否则扩展会连到不存在的路由
                "ws_path": f"/ws/plugin/{PLUGIN_ID}/bridge"}

    @register.page(
        "/panel",
        auth=True,
        menu=PageMenu(label={"zh": "全能浏览器", "en": "All-in-One Browser"}, icon="Monitor", order=60),
    )
    def page_panel(self):
        return PluginPage.from_folder("./web")

    # ── 浏览器扩展的「零配置接入」端点 ───────────────────────────────
    #  为什么需要：扩展要填 host / 端口 / 令牌三样，而**端口默认写死 5267** ——
    #  用户只要改过 KiraAI 的端口，扩展就连不上，且报错只说"连不上"，
    #  小白用户根本不知道该改哪里。
    # ── 侧边栏 WebUI：配置读写（热更新）────────────────────────────
    def _overrides_path(self):
        return Path(self.ctx.get_plugin_data_dir()) / "webui_config.json"

    def _load_overrides(self) -> dict:
        """读 WebUI 写下来的覆盖值。任何异常都当"没有覆盖"，不拖垮初始化。"""
        try:
            p = self._overrides_path()
            if p.is_file():
                d = json.loads(p.read_text(encoding="utf-8"))
                return d if isinstance(d, dict) else {}
        except Exception as e:
            logger.warning(f"读取 WebUI 配置失败（按无覆盖处理）：{e}")
        return {}

    def _schema_fields(self) -> dict:
        """**界面直接从 schema.json 长出来** —— 一处真源。

        ⚠️ 这比在 HTML 里手写一遍表单强得多：以后加一个配置项，
           只要写进 schema.json，侧边栏就自动出现，不用改前端 ✗✓
        """
        try:
            p = Path(__file__).with_name("schema.json")
            d = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                return {}
            # ⚠️ `info` / `section` 是**版面元素**（说明块、分组），不是配置项 ——
            #    混进来会让 POST 校验把"info_intro"当成一个可以写入的键 ✗
            return {k: v for k, v in d.items()
                    if isinstance(v, dict)
                    and v.get("type") not in ("info", "section")}
        except Exception as e:
            logger.warning(f"读取 schema.json 失败：{e}")
            return {}

    def _config_snapshot(self) -> dict:
        """当前**生效**的值（含 WebUI 覆盖），给界面回显用。

        ⚠️ 这里必须**每个字段都有值** —— 否则面板上就是一个空框，
        用户会以为"没设置"，而不是"在用默认值"（用户明确提过这个问题：
        命令超时 / 页面加载超时 / 交互操作超时 / 浏览器来源 / profile 模式
        这些框全是空的）。

        为什么会空：这些键（timeout、op_timeout、browser_channel、
        headless_profile_mode …）根本不在插件实例上，它们是**传给后端**的，
        由 `backends/headless_backend.py` 自己 `cfg.get(key, 默认值)` 读。
        所以回退顺序是：

          实例属性 → 框架配置里写过的 → 面板覆盖过的 → schema 里的 default

        最后那一步是安全的：这些键的**代码默认值与 schema 默认值一致**
        （有检查盯着，见回归里的"schema 默认值 = 代码默认值"）。
        """
        fields = self._schema_fields()
        cfg = getattr(self, "plugin_cfg", None) or {}
        overrides = getattr(self, "_cfg_overrides", None) or {}
        out = {}
        for k, meta in sorted(fields.items()):
            v = getattr(self, k, None)
            if v is None:
                v = cfg.get(k)
            if v is None:
                v = overrides.get(k)
            if v is None:
                v = (meta or {}).get("default")
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[k] = v
            elif isinstance(v, (list, tuple)):
                out[k] = list(v)
        return out

    @register.api("GET", "/config", auth=True)
    async def api_get_config(self):
        """侧边栏读取：**当前生效值** + schema（界面照着它渲染表单）。"""
        return {"ok": True, "values": self._config_snapshot(),
                "fields": self._schema_fields(),
                "overrides": sorted((self._cfg_overrides or {}).keys())}

    @register.api("POST", "/config", auth=True)
    async def api_set_config(self, request: Request):
        """侧边栏写入：**存下来 + 立刻生效**（不用重启）✓

        ⚠️ 只接受 schema 里声明过的键 —— 免得前端拼错一个字就悄悄写入
           一个没人读的字段（那种 bug 最难查）。
        """
        # ⚠️ 用 `await request.json()` 读 body（照 Z 插件的写法）——
        #    之前写成 `values: dict = None`，FastAPI 会把**整个 body** 当成
        #    `values` ✗ → 面板发 `{"values": {...}}` 就变成
        #    `values = {"values": {...}}` → 报"未知配置项：['values']" ✓
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        # 两种形状都认：`{"values": {...}}` 和直接摊平的 `{...}`
        values = body.get("values") if isinstance(body.get("values"), dict) else body
        values = values or {}
        known = set(self._schema_fields().keys())
        bad = [k for k in values if k not in known]
        if bad:
            return {"ok": False, "error": f"未知配置项：{bad}"}

        cur = dict(self._cfg_overrides or {})
        for k, v in values.items():
            if v is None or v == "":
                cur.pop(k, None)       # 空 = 回到框架配置的默认值
            else:
                cur[k] = v
        try:
            p = self._overrides_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(cur, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        except Exception as e:
            logger.error(f"保存 WebUI 配置失败：{e}")
            return {"ok": False, "error": str(e)}

        self._cfg_overrides = cur
        # ⚠️ **热更新**：重跑一次 _apply_config，立刻生效
        self._apply_config(getattr(self, "plugin_cfg", {}) or {})
        logger.info(f"侧边栏改配置：{list(values.keys())}（已热生效）")
        return {"ok": True, "values": self._config_snapshot(),
                "overrides": sorted(cur.keys()),
                "applied": list(values.keys())}

    @register.api("GET", "/models", auth=True)
    async def api_models(self):
        """给面板的 model_select 用：列出可选的模型。

        照 Z 插件的做法 —— **由插件后端去框架里读**，而不是让面板直接
        打框架的 /api/providers ✗（那样既绕、又容易因为字段名不同而显示成 id）。

        - 只取 `model_config.llm` 组：视觉模型也必须配在 LLM 组里才选得到
          （框架只把 LLM 组的模型交给模型用）
        - `id` 用 `provider_id:model_id`（配置里填的就是这个格式）
        - `name` 是 `模型名 (提供商名)` —— 下拉里给人看的是**提供商的名字**，
          不是那串 id ✓
        """
        models = []
        try:
            pm = getattr(self.ctx, "provider_mgr", None)
            if pm is not None and hasattr(pm, "kira_config"):
                providers = pm.kira_config.get("providers", {}) or {}
                for pid, pcfg in providers.items():
                    if not isinstance(pcfg, dict):
                        continue
                    mc = (pcfg.get("model_config") or {})
                    llm = (mc.get("llm") or {})
                    pname = pcfg.get("name") or pid
                    for mid in llm:
                        models.append({"id": f"{pid}:{mid}",
                                       "name": f"{mid} ({pname})"})
        except Exception as e:
            logger.warning(f"列模型失败：{type(e).__name__}: {e}")
        return {"models": models}

    @register.api("GET", "/pair", auth=False)
    async def api_pair(self, request: Request):
        """返回本实例的接入信息（端口 + 令牌），供扩展自动填充。

        ⚠️ **为什么可以免登录**：来调它的人正是"还没配好、连不上"的扩展。
        要求登录就还是要用户先去面板里找令牌 —— 那就没解决问题。
        所以这里用**回环限制**代替登录：只回答来自本机（127.0.0.1 / ::1）
        的请求。确实需要"浏览器在另一台机器"的用户，可以打开
        `allow_remote_pairing` 显式放行（那时请自行确保网络可信）。
        """
        if not self.enabled:
            raise HTTPException(status_code=404, detail="插件未启用")
        if not _is_loopback(request) and not self.allow_remote_pairing:
            raise HTTPException(
                status_code=403,
                detail="只允许本机配对。要在另一台机器上用浏览器，"
                       "请打开「允许跨机配对」配置。")
        return {
            "ok": True,
            "plugin": PLUGIN_ID,
            "host": "127.0.0.1",
            "port": _server_port(),
            "token": self._token,
            "ws_path": f"/ws/plugin/{PLUGIN_ID}/bridge",
            # ⚠️ 「这台机器上还有别的 KiraAI」时的区分依据：
            #    扩展会把所有探测到的实例列出来让用户选，
            #    所以每个实例必须能被**认出来**，不能只给一个端口号
            #    （端口对小白没有意义，他们分不清 5267 和 8080 哪个是自己的）。
            **_instance_label(),
        }


def _instance_label() -> dict:
    """本实例的标识：数据目录 + 它的上一级目录名。

    一台机器上可能部署了多个 KiraAI（不同端口、不同数据目录），
    它们都装了本插件。扩展自动探测时必须能分辨，否则会**连错实例** ——
    用户会发现自己对着 A 说话，B 却动了他的浏览器。
    """
    out = {"instance": "", "data_dir": ""}
    try:
        from core.utils.path_utils import get_data_path
        d = Path(get_data_path()).resolve()
        out["data_dir"] = str(d)
        # 数据目录的上一级目录名通常是部署目录名（如 `kira-a`），
        # 比完整路径短，面板上列出来看得清
        out["instance"] = d.parent.name or d.name
    except Exception:
        pass
    return out


def _is_loopback(request) -> bool:
    """请求是否来自本机。"""
    try:
        host = (request.client.host or "").strip()
    except Exception:
        return False
    return host in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1")


def _server_port() -> int:
    """KiraAI 实际监听的端口。

    优先读框架自己的 `webui.json`（`<data>/webui.json` 的 `port`）——
    用户改过端口就按改后的来。读不到再回落到框架默认值。
    """
    try:
        from core.utils.path_utils import get_data_path
        conf = Path(get_data_path()) / "webui.json"
        if conf.is_file():
            import json as _json
            port = int(_json.loads(conf.read_text(encoding="utf-8")).get("port") or 0)
            if 1 <= port <= 65535:
                return port
    except Exception:
        pass
    return 5267


def _b(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    return bool(v)


def _as_list(v):
    """把配置值统一成字符串列表。

    ⚠️ 为什么要防：这套配置由面板按 `schema.json` 渲染。如果 schema 里写了
    一个框架**不认得**的 type（例如 `array` —— 框架只认 `list`），控件会
    **退化成文本框**，于是整个列表被存成一串文本。这时
    `list("*.bank*")` 会得到 `['*','.','b','a','n','k','*']` 这样**逐字符**
    的列表：看着配了黑名单，实际每条规则都只剩一个字符，拦截**静默失效**
    —— 是最难发现的那种坏法。

    实测后果：`blocked_domains` 从"拦 *.bank*"变成"拦单个字符"；
    `upload_allowed_dirs` 会变成 `['d','a','t','a',...]`。
    """
    if v is None:
        return []
    if isinstance(v, str):
        # 换行 / 逗号都当分隔符（textarea 与单行文本框两种形态都能收）
        parts = re.split(r"[\n,]+", v)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(v, (list, tuple, set)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v).strip()] if str(v).strip() else []
