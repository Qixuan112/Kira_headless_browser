"""无头浏览器后端（CPU 与内存均已优化）。

从原 headless_browser 插件移植，改动集中在：
  * **启动参数**：删掉三个反向参数，补上防崩溃 / 省 CPU 的参数（详见文件头）
  * **等待策略**：默认 domcontentloaded，不再无脑 networkidle
  * **绝不占用用户真实 profile**：只用插件持久化 profile 或临时 profile
  * **空闲回收 / 页面自愈 / 弹窗回收 / 下载与截图的清理**
"""

from __future__ import annotations

import asyncio
import glob
import os
import time
from datetime import datetime
from urllib.parse import urljoin
from pathlib import Path
from typing import Optional

from core.logging_manager import get_logger

from .base import OpResult, TabInfo
from .router import Backend

logger = get_logger("browser_merged", "cyan")


def _resolve_user_dir(value, default: str, plugin_data_dir: Path) -> str:
    """把用户填的目录解析成**绝对路径**，语义与 KiraAI 的 `<file>` 标签一致。

    ⚠️ 这个函数存在的理由：用户在配置里填 `data/bs` 时，
       **它代表的不是 `<CWD>/data/bs`，而是 `<框架数据目录>/bs`**。

       框架自己的规矩（`core/plugin/builtin_plugins/kira-ai/tags.py`）：
         · 绝对路径                     → 原样使用
         · `data/<rel>`                 → `<get_data_path()>/<rel>`
         · 其他相对路径（含裸名）       → **直接丢弃**（return []）

       插件如果按 CWD 解释，就会出现"用户填了 `data/bs`，文件却落到
       `<CWD>/data/bs`"—— 只有当 CWD 恰好是 KiraAI 根目录、且数据目录
       就是 `<root>/data` 时才对得上。换个启动目录、或 `--data-dir` 换过，
       就静默跑到别处去了。

       裸相对名（比如 `bs`）框架是丢弃的，但配置框里静默丢弃更糟 ——
       这里统一按**同一个基准**（框架数据目录）解释，也就是 `bs` == `data/bs`。
    """
    raw = (value or "").strip().replace("\\", "/")
    if not raw:
        return default
    if raw == "data":
        return str(_framework_data_path(plugin_data_dir))
    if raw.startswith("data/"):
        return str(_framework_data_path(plugin_data_dir) / raw[5:])
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    return str(_framework_data_path(plugin_data_dir) / raw)


def _framework_data_path(plugin_data_dir: Path) -> Path:
    """框架的数据目录（**绝对路径**）。

    ⚠️ 不能拿相对字符串当默认目录。`data/temp` 这种写法只有在
    "CWD 恰好是 KiraAI 根目录、且数据目录就是 `<root>/data`" 时才成立；
    用户用 `--data-dir` 换过目录、或从别的 CWD 启动，就会静默落到别处。

    取不到框架时（单测/桩环境）退回插件数据目录的上两级：
    插件数据目录是 `<data>/plugin_data/<plugin_id>`，往上两级正是 `<data>`。
    """
    try:
        from core.utils.path_utils import get_data_path
        return Path(get_data_path())
    except Exception:
        return Path(plugin_data_dir).parent.parent


# ══════════════════════════════════════════════════════════════════════
# 启动参数 —— CPU 优化的核心
# ══════════════════════════════════════════════════════════════════════

#: ⛔ 这三个是原版在 Windows 可视模式下加的，属于**反向优化**，任何情况都不要加。
#:   它们分别关掉了「遮挡降频 / 渲染进程降级 / 后台定时器节流」——
#:    而 Chromium 的后台节流能把后台标签 CPU 降到 1/5（M87 官方数据）。
#:    bot 的浏览器窗口基本常年被挡在后面，正好全部命中。
FORBIDDEN_ARGS = frozenset({
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
})

#: 通用参数：防崩溃 + 省 CPU + 关掉用不上的子系统
_COMMON_ARGS = [
    "--disable-dev-shm-usage",        # /dev/shm 常只有 64MB，写满会让渲染进程直接崩
    "--disable-software-rasterizer",  # 否则回退到 SwiftShader 用 CPU 软渲染
    "--disable-extensions",
    "--disable-sync",
    "--disable-translate",
    "--disable-background-networking",
    "--mute-audio",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-ipc-flooding-protection",
    "--disable-features=Translate,BackForwardCache,AcceptCHFrame,MediaRouter,OptimizationHints,CalculateNativeWinOcclusion",
]

#: 无头专用：不需要 GPU 合成，留着只会烧 CPU
_HEADLESS_ONLY_ARGS = [
    "--disable-gpu",
    "--renderer-process-limit=4",
    "--js-flags=--max-old-space-size=512",
]

#: 可视模式：补回窗口可见性参数。
#:
#: ⚠️ 关于"删掉后台节流参数会不会影响可视化"——**不会**，理由：
#:
#:  1. 那三个参数（background-timer-throttling / backgrounding-occluded-windows
#:     / renderer-backgrounding）**不是窗口可见性开关**，它们只关掉"省电降频"。
#:     窗口能不能显示由窗口尺寸/位置/GPU/合成器决定。
#:  2. 窗口**可见且在前台**时，本来就没有节流，这三个参数加不加都一样。
#:  3. 窗口被遮挡时才触发节流，而那种情况下页面本来就不该全速跑。
#:  4. Playwright 的"元素稳定"判定用的是 requestAnimationFrame
#:     （官方：*maintained the same bounding box for at least two consecutive
#:     animation frames*），而后台 rAF 节流**本来就没有开关能关掉**
#:     （--disable-renderer-backgrounding 只作用于定时器）——
#:     也就是说**加了那三个参数也帮不到 Playwright**，只是让页面白烧 CPU。
#:
#: 下面这些才是真正影响"能不能看见窗口"的参数，已补回。
_HEADFUL_EXTRA_ARGS = [
    "--start-maximized",
    "--window-position=80,60",
    "--window-size=1600,900",
    "--force-device-scale-factor=1",
    "--renderer-process-limit=6",
    "--js-flags=--max-old-space-size=768",
]


def build_launch_args(headless: bool, extra: Optional[list] = None) -> list:
    """构造启动参数。任何调用方都不能绕过 FORBIDDEN 过滤。"""
    args = list(_COMMON_ARGS)
    args += list(_HEADLESS_ONLY_ARGS) if headless else list(_HEADFUL_EXTRA_ARGS)
    if extra:
        args += [a for a in extra if a not in FORBIDDEN_ARGS]
    # 最后再兜一道：即使有人从配置里塞进来也拦掉
    return [a for a in args if a not in FORBIDDEN_ARGS]


class HeadlessBackend(Backend):
    """插件自己拉起的浏览器。**永不占用用户真实 profile。**"""

    name = "headless"
    is_user_browser = False

    def __init__(self, data_dir: Path, cfg: dict):
        self._data_dir = data_dir
        self._browser = None
        self._context = None
        self._page = None
        self._own_page = None
        self._playwright = None
        self._lock = asyncio.Lock()          # 保护「启动浏览器」
        # ⚠️ 另有一把锁保护**页面操作**。
        #    模型可以在同一轮里并发调多个工具（比如同时 navigate + click），
        #    而它们共用同一张 self._page。不串行化的话，
        #    page.goto 还没完成就会有人在上面 click，页面状态直接错乱。
        self._op_lock = asyncio.Lock()
        # ⚠️ 第三把锁：保护「换页」。_ensure_page 可能在已持 _op_lock 的路径上
        #    被调用（_op → 自愈），所以**不能**复用 _op_lock（会自锁死）。
        self._page_lock = asyncio.Lock()
        self._desc = ""
        self._idle_task = None
        self._popup_hooked = False
        self._fail_streak = 0

        self.headless = _as_bool(cfg.get("headless", True))
        self.channel = cfg.get("browser_channel", "auto") or "auto"
        self.timeout = int(cfg.get("timeout", 45) or 45)
        self.viewport = _parse_viewport(cfg.get("default_viewport", "1920x1080"))
        self.user_agent = (cfg.get("user_agent") or "").strip() or None

        # 只用插件自己的 profile：临时（用完即弃）或持久化（保留登录态）
        self.profile_mode = (cfg.get("headless_profile_mode", "inherit") or "inherit").lower()
        self.custom_user_data_dir = (cfg.get("custom_user_data_dir") or "").strip()

        # ⚠️ 默认目录必须是**绝对路径**，且以框架的数据目录为基准。
        #    原来写的是相对字符串（`data/temp`、`data/files/cookie`）——
        #    只有当"进程 CWD 恰好是 KiraAI 根目录、且数据目录就是 <root>/data"
        #    时才对；用户自定义了数据目录、或从别处启动 KiraAI，
        #    截图/Cookie 就会**落到别的地方**（而且不报错，很难发现）。
        #    框架的数据目录用 get_data_path() 取（和 tokens.py 同一个来源）。
        _fw_data = _framework_data_path(data_dir)
        # ⚠️ 用户手填的值也要走同一个解析器 —— 只把**默认值**改成绝对路径
        #    是不够的：用户填 `data/bs` 时，按 CWD 解释仍然会跑偏。
        self.screenshot_dir = _resolve_user_dir(
            cfg.get("screenshot_dir"), str(_fw_data / "temp"), data_dir)
        #    默认跟随**框架自己的目录约定**（不是我自己发明的新目录）：
        #      · 截图  → `<data>/temp`  —— 框架的 AsyncTempMonitor 本来就在清它
        #      · 下载  → `<data>/files` —— 框架 `<file>` 标签列给模型的"可发送文件"区
        #    用户想在哪儿享受自动清理，把目录填到哪儿就行（清理是特性）。
        self.download_dir = _resolve_user_dir(
            cfg.get("download_dir"), str(_fw_data / "files"), data_dir)
        # ⚠️ cookie 自动加载目录（原版能力，重写时丢过一次）。
        #    启动时把这里的 *.json 全部灌进浏览器 —— 用户的登录态因此
        #    在重装/换机器/临时 profile 之后还能找回来。
        self.cookies_dir = _resolve_user_dir(
            cfg.get("cookies_dir"), str(_fw_data / "files" / "cookie"), data_dir)
        self.load_cookies_on_start = _as_bool(cfg.get("load_cookies_on_start", True))
        #: 允许"所有浏览器来源都失败"时自动下载内置 Chromium（README 承诺的行为）。
        #  下载很慢，所以给一个宽松但有限的超时；可以关掉。
        self._allow_auto_download = _as_bool(cfg.get("auto_download_browser", True))
        self.auto_download_timeout = float(cfg.get("auto_download_timeout", 600) or 600)
        self.screenshot_max_count = int(cfg.get("screenshot_max_count", 50) or 50)
        self.screenshot_auto_clean = _as_bool(cfg.get("screenshot_auto_clean", True))
        self.download_auto_clean = _as_bool(cfg.get("download_auto_clean", True))
        self.download_max_count = int(cfg.get("download_max_count", 100) or 100)
        # 2GB。注意：下载是**流式落盘**（64KB 一块），无论多大都**不占内存**，
        # 这个上限只用来拦住异常的超大文件，不是内存保护。
        self.download_max_bytes = int(cfg.get("download_max_bytes", 2 * 1024 ** 3) or 0)

        self.idle_close_seconds = int(cfg.get("idle_close_seconds", 300) or 0)
        # 与 schema.json / main.py 三处保持一致（120）
        self.op_timeout = float(cfg.get("op_timeout", 120) or 0)
        self.action_timeout = float(cfg.get("action_timeout", 20) or 0)
        self.wait_until = cfg.get("default_wait_until", "domcontentloaded") or "domcontentloaded"
        # 单次返回给模型的正文长度（可通过 offset 续读，不是硬上限）
        self.content_page_size = int(cfg.get("content_page_size", 8000) or 0)

        self._last_used = time.time()

    # ─── Backend 接口 ────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        # ⚠️ 只认 `_context`。
        #    非持久化启动时会**先赋 _browser 再建 _context**；
        #    如果这里把 _browser 也算作"可用"，并发调用就能在
        #    _context 还是 None 的时候绕过 _lock 进来，
        #    它的自愈逻辑甚至会把对方**正在初始化**的浏览器关掉。
        return self._context is not None

    @property
    def display(self) -> str:
        return self._desc or "无头浏览器（未启动）"

    async def close(self) -> None:
        await self._close()

    async def start(self) -> Optional[str]:
        """按需启动。返回错误信息，None 表示成功。"""
        try:
            await self._ensure()
            return None
        except Exception as e:
            msg = str(e).splitlines()[0] if str(e) else repr(e)
            return f"❌ 无头浏览器启动失败: {msg}"

    # ─── 生命周期 ────────────────────────────────────────────────────

    def _launch_kwargs(self) -> dict:
        return {
            "headless": self.headless,
            "args": build_launch_args(self.headless),
        }

    def _context_options(self) -> dict:
        opts = {"accept_downloads": True}
        if self.headless:
            opts["viewport"] = self.viewport
        else:
            opts["viewport"] = None
            opts["no_viewport"] = True
        if self.user_agent:
            opts["user_agent"] = self.user_agent
        return opts

    async def _profile_dir_async(self) -> Optional[str]:
        """异步版：复制 profile 时不会阻塞事件循环。

        ⚠️ inherit 模式**必须**带回退 —— `_inherited_profile_dir()` 在
        "找不到真实浏览器 / 复制失败"时返回 None。直接把它当结果返回的话，
        本次启动就**完全没有 profile**（既不继承也不回退插件目录），
        而用户以为自己开了 inherit 模式。同步版 `_profile_dir()` 是有
        这个回退的（会走到 browser_profile/），两条路径行为必须一致。
        """
        if self.profile_mode == "inherit":
            inherited = await self._inherited_profile_dir()
            if inherited:
                return inherited
            logger.warning(
                "inherit 模式未能复制真实 profile，回退到插件自带 profile")
            return self._profile_dir_fallback()
        return self._profile_dir()

    def _profile_dir_fallback(self) -> Optional[str]:
        """inherit 失败后的回退：custom_user_data_dir → 插件自带 profile。

        ⚠️ 与 `_profile_dir()` 的对应分支保持同一套判断（含"指向真实浏览器
        目录就拒绝"那条），否则两条路径会出现"同步能跑、异步拒了"的差异。
        """
        if self.custom_user_data_dir:
            if self._looks_like_real_profile(self.custom_user_data_dir):
                logger.error(
                    "custom_user_data_dir 指向了真实浏览器的 User Data 目录，"
                    "已拒绝使用（会抢锁、导致用户的浏览器打不开）。"
                    "请改用 headless_profile_mode=inherit（复制副本），"
                    "或填插件自己的目录。"
                )
                return None
            return self.custom_user_data_dir
        d = Path(self._data_dir) / "browser_profile"
        os.makedirs(d, exist_ok=True)
        return str(d)

    def _profile_dir(self) -> Optional[str]:
        """返回要用的 profile 目录。

        三种模式：
          ``inherit``    —— **用你的真实浏览器数据**：把真实 User Data 目录
                            **复制**一份到插件目录，然后启动到这个副本上。
                            登录态/Cookie/书签全都在（同机同用户，DPAPI 能解开），
                            但因为没有直接用原目录，**不会持有 ProcessSingleton 锁**，
                            所以你自己的浏览器照常能用。
          ``persistent`` —— 插件自己的 profile（与真实浏览器无关）
          ``temp``       —— 临时目录，用完即弃
        """
        if self.profile_mode == "temp":
            return None                      # None → 交给 Playwright 用临时目录
        if self.profile_mode == "inherit":
            # 注意：这里是同步入口，只用于 debug_state() 之类**只读展示**；
            # 真正启动走 _profile_dir_async()，避免在事件循环里做重活。
            inherited = None if getattr(self, "_no_block_copy", False) else \
                self._peek_inherited()
            if inherited:
                return inherited
            logger.warning("inherit 模式未能复制真实 profile，回退到插件自带 profile")
        if self.custom_user_data_dir:
            # ⚠️ 拦住"把 custom_user_data_dir 指向真实浏览器"这种用法 ——
            #    那正是我们要避免的抢锁场景（Playwright 会持有
            #    ProcessSingleton，用户就打不开自己的浏览器了）。
            if self._looks_like_real_profile(self.custom_user_data_dir):
                logger.error(
                    "custom_user_data_dir 指向了真实浏览器的 User Data 目录，"
                    "已拒绝使用（会抢锁、导致用户的浏览器打不开）。"
                    "请改用 headless_profile_mode=inherit（复制副本），或填插件自己的目录。"
                )
                return None
            return self.custom_user_data_dir
        d = Path(self._data_dir) / "browser_profile"
        os.makedirs(d, exist_ok=True)
        return str(d)

    @staticmethod
    def _looks_like_real_profile(path: str) -> bool:
        """粗判某个目录是不是真实浏览器的 User Data 目录。"""
        p = str(path).replace("\\", "/").rstrip("/").lower()
        markers = ("google/chrome/user data", "microsoft/edge/user data",
                   "chromium/user data", "brave-browser/user data",
                   "/library/application support/google/chrome",
                   "/library/application support/microsoft edge",
                   ".config/google-chrome", ".config/microsoft-edge",
                   ".config/chromium")
        return any(m in p for m in markers)

    def _real_user_data_dir(self, channel: Optional[str] = None) -> Optional[str]:
        """定位用户真实浏览器的 User Data 目录（只用于**复制**，绝不直接启动）。"""
        import platform
        system = platform.system()
        home = Path.home()
        local = os.environ.get("LOCALAPPDATA", str(home / "AppData/Local"))
        table = {
            "chrome": {
                "Windows": Path(local) / "Google/Chrome/User Data",
                "Darwin": home / "Library/Application Support/Google/Chrome",
                "Linux": home / ".config/google-chrome",
            },
            "msedge": {
                "Windows": Path(local) / "Microsoft/Edge/User Data",
                "Darwin": home / "Library/Application Support/Microsoft Edge",
                "Linux": home / ".config/microsoft-edge",
            },
            "brave": {
                "Windows": Path(local) / "BraveSoftware/Brave-Browser/User Data",
                "Darwin": home / "Library/Application Support/BraveSoftware/Brave-Browser",
                "Linux": home / ".config/BraveSoftware/Brave-Browser",
            },
            "chromium": {
                "Windows": Path(local) / "Chromium/User Data",
                "Darwin": home / "Library/Application Support/Chromium",
                "Linux": home / ".config/chromium",
            },
        }
        order = [channel] if channel else ["chrome", "msedge", "brave", "chromium"]
        for ch in order:
            p = table.get(ch, {}).get(system)
            if p and p.is_dir():
                return str(p)
        return None

    def _peek_inherited(self) -> Optional[str]:
        """只看副本在不在（不做复制）—— 给 debug_state 这类只读展示用。"""
        dst = Path(self._data_dir) / "inherited_profile"
        return str(dst) if dst.is_dir() else None

    async def _inherited_profile_dir(self) -> Optional[str]:
        """把真实 profile 复制一份出来给插件用。

        为什么要复制而不是直接用：直接用会持有原目录的 ProcessSingleton 锁，
        用户就再也打不开自己的浏览器了（这是原版最大的坑）。
        复制到插件目录后，插件锁的是副本 —— 用户完全不受影响。

        Cookie 能用的原因：Chrome 80+ 的 Cookie 用 AES-GCM 加密，密钥由
        DPAPI（Windows）/ Keychain（mac）/ OSCrypt（Linux）包裹，而这三者都是
        **用户级、与路径无关**的 —— 同一台机器同一个用户，复制出来的副本
        照样能解密。所以登录态是**完整保留**的。
        """
        import shutil
        src = self._real_user_data_dir(self.channel if self.channel != "auto" else None)
        if not src:
            return None

        dst = Path(self._data_dir) / "inherited_profile"
        stamp = dst / ".source_mtime"

        # 源目录 mtime 没变就复用上次的副本，避免每次启动都全量复制
        # ⚠️ 不能用**目录** mtime 当版本号：目录 mtime 只在顶层增删条目时变，
        #    `Default/Cookies` 被改写（也就是登录态更新）时它**不变** ——
        #    结果就是一直复用旧副本，用户新登录的账号读不到。
        #    改成看真正承载登录态的那几个文件的 mtime 之和。
        # ⚠️ 除了 Cookie 文件，**Local Storage** 也必须看 ——
        #    不少站点把登录 token 只存在 Local Storage 里，
        #    漏了它就会一直复用旧副本，用户"明明重新登录了却还是登出状态"。
        src_mtime = 0.0
        STAMPS = ("Default/Cookies", "Default/Login Data", "Local State",
                  "Default/Preferences", "Default/Network/Cookies")
        for rel in STAMPS:
            try:
                src_mtime = max(src_mtime, os.path.getmtime(Path(src) / rel))
            except OSError:
                continue
        # Local Storage / Session Storage 下的文件（递归取最大 mtime）。
        # ⚠️ 这里**不要**包含 IndexedDB：档案复制时并不搬 IndexedDB，
        #    把它的 mtime 算进来会导致"源侧 IndexedDB 一变就判定副本过期、
        #    整份档案重拷一遍"，白花很多时间而副本其实没有过期。
        for rel in ("Default/Local Storage", "Default/Session Storage"):
            root = Path(src) / rel
            if not root.is_dir():
                continue
            try:
                for dirpath, _dirnames, filenames in os.walk(root):
                    for fn in filenames:
                        try:
                            src_mtime = max(src_mtime,
                                            os.path.getmtime(os.path.join(dirpath, fn)))
                        except OSError:
                            continue
            except OSError:
                continue
        if src_mtime == 0.0:
            try:
                src_mtime = os.path.getmtime(src)
            except OSError:
                src_mtime = 0.0
        if dst.is_dir() and stamp.is_file():
            try:
                if float(stamp.read_text().strip()) >= src_mtime:
                    logger.info(f"复用已复制的真实 profile 副本: {dst}")
                    return str(dst)
            except Exception:
                pass

        # 只复制必要的东西：整个 User Data 可能好几个 GB，
        # 而我们只要登录态相关的（Default 下的 Cookies / Local Storage / ...）。
        # 这里用整体复制但忽略大而无用的目录（缓存/媒体/代码缓存）。
        IGNORE = shutil.ignore_patterns(
            "Cache", "Code Cache", "GPUCache", "ShaderCache", "GrShaderCache",
            "Media Cache", "DawnCache", "DawnGraphiteCache", "component_crx_cache",
            "extensions_crx_cache", "Crashpad", "BrowserMetrics", "Safe Browsing*",
            "OptimizationGuide*", "File System", "IndexedDB", "Service Worker",
            "*.log", "*.tmp",
        )
        try:
            if dst.exists():
                # 删除也可能很慢（几万个文件），放到线程里
                await asyncio.to_thread(shutil.rmtree, dst, True)
            # ⚠️ copytree 是**同步阻塞**的，User Data 可能有几个 GB ——
            #    直接在事件循环里跑会把整个 KiraAI 卡住（所有会话都停摆）。
            await asyncio.to_thread(shutil.copytree, src, dst,
                                    ignore=IGNORE, dirs_exist_ok=True)
            # 副本必须删掉锁文件，否则 Playwright 会以为"正在运行"
            for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket",
                         "lockfile"):
                try:
                    (dst / lock).unlink()
                except OSError:
                    pass
            stamp.write_text(str(src_mtime))
            logger.info(f"已复制真实浏览器数据用于无头后端（登录态保留）: {src} → {dst}")
            return str(dst)
        except Exception as e:
            logger.warning(f"复制真实 profile 失败（将回退到插件 profile）: {e}")
            return None

    def _channels(self) -> list:
        ch = (self.channel or "auto").lower()
        if ch == "bundled":
            return [None]
        if ch == "auto":
            return ["chrome", "msedge", "chromium", None]
        return [ch, None]

    async def _ensure(self):
        if self.available:
            return
        async with self._lock:
            if self.available:
                return
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            os.makedirs(self.screenshot_dir, exist_ok=True)
            os.makedirs(self.download_dir, exist_ok=True)

            errors = []
            profile = await self._profile_dir_async()
            for ch in self._channels():
                launch_ch = {"channel": ch} if ch else {}
                try:
                    if profile:
                        self._context = await self._playwright.chromium.launch_persistent_context(
                            profile, downloads_path=self.download_dir,
                            **launch_ch, **self._launch_kwargs(), **self._context_options())
                        self._browser = self._context.browser
                        self._desc = f"无头({ch or '内置Chromium'}) + 插件profile"
                    else:
                        # 先建 browser 再建 context —— 注意 available 只看 _context，
                        # 所以这里中间态不会被别的协程当成"已就绪"
                        self._browser = await self._playwright.chromium.launch(
                            **launch_ch, **self._launch_kwargs())
                        self._context = await self._browser.new_context(**self._context_options())
                        self._desc = f"无头({ch or '内置Chromium'}) + 临时profile"
                    break
                except Exception as e:
                    msg = str(e).splitlines()[0] if str(e) else repr(e)
                    errors.append(f"{ch or 'bundled'}: {msg}")
                    logger.warning(f"无头后端启动失败 [{ch or 'bundled'}]: {msg}")
                    # ⚠️ 必须先关掉半成品再清引用。
                    #    launch() 成功但 new_context() 失败时，
                    #    浏览器的**进程已经起来了** —— 直接置 None 就是泄漏一个
                    #    孤儿 Chromium，用户会在任务管理器里看到它一直挂着。
                    for obj in (self._context, self._browser):
                        if obj is not None:
                            try:
                                await obj.close()
                            except Exception as ce:
                                logger.debug(f"清理启动失败的实例时出错: {ce}")
                    self._context = self._browser = None

            if self._context is None:
                # ⚠️ 第 4 级回退：**自动下载**内置 Chromium。
                #    README 一直承诺"全部失败会自动下载内置 Chromium"，
                #    但这个实现（原版的 `_download_chromium`）在 v2.1.0 重写时
                #    被整段丢掉，只剩一句"请手动安装"的提示 ——
                #    **文档说有、代码没有**，用户装完插件首次使用可能直接卡住。
                #
                #    触发条件：所有浏览器来源都起不来。最常见的原因是
                #    playwright 装了但没跑过 `playwright install chromium`。
                if self._allow_auto_download:
                    got = await self._download_chromium(errors)
                    if got:
                        try:
                            if profile:
                                self._context = await self._playwright.chromium.launch_persistent_context(
                                    profile, downloads_path=self.download_dir,
                                    **self._launch_kwargs(), **self._context_options())
                                self._browser = self._context.browser
                                self._desc = "无头(内置Chromium·刚下载) + 插件profile"
                            else:
                                self._browser = await self._playwright.chromium.launch(
                                    **self._launch_kwargs())
                                self._context = await self._browser.new_context(
                                    **self._context_options())
                                self._desc = "无头(内置Chromium·刚下载) + 临时profile"
                            logger.info("自动下载 Chromium 后启动成功")
                        except Exception as e:
                            msg = str(e).splitlines()[0] if str(e) else repr(e)
                            errors.append(f"下载后仍启动失败: {msg}")
                            logger.warning(f"自动下载 Chromium 后仍启动失败: {msg}")

            if self._context is None:
                await self._close()
                raise RuntimeError(
                    "所有浏览器启动方式均失败：\n  - " + "\n  - ".join(errors[-5:]) +
                    "\n提示：可先用 pip install playwright && python -m playwright install chromium 手动安装。"
                )

            await self._hook_popups()
            self._adopt_page(await self._new_page())
            self._page.set_default_timeout(self.timeout * 1000)

            # ⚠️ 自动加载 cookie 目录。
            #    这个能力原版有，v2.1.0 重写时被整段丢掉过 ——
            #    用户的登录态因此每次开浏览器都要重登。
            #    **失败不能影响浏览器本身可用**（cookies.py 内部已逐文件容错）。
            if getattr(self, "cookies_dir", "") and getattr(self, "load_cookies_on_start", True):
                try:
                    from . import cookies as _ck
                    stats = await _ck.load_into_context(self._context, self.cookies_dir)
                    if stats["loaded"]:
                        self._desc += f"，已加载 {stats['cookies']} 条 cookie"
                    for err in stats["errors"][:5]:
                        logger.warning(f"cookie 加载跳过：{err}")
                except Exception as e:
                    logger.warning(f"自动加载 cookie 失败（不影响浏览器使用）：{e}")

            logger.info(f"无头后端已启动: {self._desc}")
            self._touch()

    async def _download_chromium(self, errors: list) -> bool:
        """自动下载内置 Chromium（带验证）；成功返回 True。

        移植自原版的 `_download_chromium` —— v2.1.0 重写时被整段丢掉，
        而 README 一直在承诺这个行为。

        ⚠️ 两个细节不能省：
          * **超时**：网络差的时候 `playwright install` 可能挂很久，
            不设超时会把插件的启动流程整个卡住；
          * **失败要给出可照做的命令**，而不是一个裸报错。
        """
        import sys
        logger.info("所有浏览器来源都不可用，开始自动下载内置 Chromium…")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "playwright", "install", "chromium",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception as e:
            errors.append(f"自动下载启动失败: {e}")
            logger.warning(f"无法启动 Chromium 自动下载: {e}")
            return False

        try:
            out, _ = await asyncio.wait_for(proc.communicate(),
                                            timeout=self.auto_download_timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            errors.append(f"自动下载超时（{self.auto_download_timeout} 秒）")
            logger.warning(
                f"Chromium 自动下载超时（{self.auto_download_timeout}s）——"
                f" 请检查网络后重试，或手动运行："
                f"{sys.executable} -m playwright install chromium")
            return False

        if proc.returncode != 0:
            tail = (out or b"").decode(errors="ignore")[-300:]
            errors.append(f"自动下载失败（退出码 {proc.returncode}）")
            logger.warning(
                f"Chromium 自动下载失败（退出码 {proc.returncode}）：{tail}\n"
                f"请手动运行：{sys.executable} -m playwright install chromium")
            return False

        logger.info("内置 Chromium 下载完成")
        return True

    async def _hook_popups(self):
        if self._popup_hooked or self._context is None:
            return
        try:
            self._context.on("page", self._on_new_page)
            self._popup_hooked = True
        except Exception as e:
            logger.debug(f"注册新页面监听失败: {e}")

    async def _new_page(self):
        """插件自己开新页面的**唯一入口**。

        new_page() 会先派发 page 事件再返回，所以必须先登记到 _creating_pages，
        否则 _on_new_page 会把它当成"用户/广告开出来的页面"直接关掉。
        """
        # 先占位：用一个哨兵对象登记，事件回调只要看到"有创建在进行"就跳过
        self._creating = getattr(self, "_creating", 0) + 1
        try:
            page = await self._context.new_page()
            return page
        finally:
            self._creating -= 1

    def _adopt_page(self, page):
        """把新页面正式认领为"我们的页面"。

        ``_creating_pages`` 只在"已创建但可能还没被事件回调看到"的窗口期有用，
        认领之后 _page/_own_page 已经指过去了。
        这里只保留最近一张，避免集合长期增长。
        """
        self._page = page
        self._own_page = page
        self._creating_pages = {page}
        return page

    async def _on_new_page(self, page):
        try:
            # 正在创建中的页面不回收（见 _new_page 的说明）
            if getattr(self, "_creating", 0) > 0:
                return
            if page in getattr(self, "_creating_pages", ()):  # 已认领
                return
            if page is self._page or page is self._own_page:
                return
            logger.info("回收非插件页面（弹窗/新标签）")
            await page.close()
        except Exception as e:
            logger.debug(f"关闭弹窗失败: {e}")

    async def _close(self):
        # ⚠️ _close() 会被 _idle_watchdog() 自己调用 —— 那时不能 cancel 自己：
        #    自我取消会在下一个 await 点抛 CancelledError，
        #    把"正常收尾"变成"异常退出"，日志里会多出一堆无意义的取消栈。
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if (self._idle_task and not self._idle_task.done()
                and self._idle_task is not current):
            self._idle_task.cancel()
        self._idle_task = None
        self._popup_hooked = False
        self._fail_streak = 0
        for attr, label in (("_page", "页面"), ("_context", "上下文"),
                            ("_browser", "浏览器")):
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    await obj.close()
                except Exception as e:
                    logger.debug(f"关闭{label}失败: {e}")
                setattr(self, attr, None)
        self._own_page = None
        self._creating_pages = set()
        # ⚠️ **不要**把 _creating 清零 —— 它由 `_new_page()` 的 finally 负责递减。
        #    如果此刻有 `_new_page()` 正卡在 `await context.new_page()` 上，
        #    这里清零之后，它的 finally 再 `-= 1` 就把它变成**负数** ——
        #    而 `_on_new_page()` 靠 `_creating > 0` 判断"有页面正在创建、
        #    别回收它"，负数值会让这个保护**永久失效**（后续弹窗回收逻辑错乱）。
        #    这里只保证属性存在（供后续读取），让它自己归零。
        self._creating = max(getattr(self, "_creating", 0), 0)
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.debug(f"停止 playwright 失败: {e}")
            self._playwright = None
        self._desc = ""
        logger.info("无头浏览器已关闭")

    # ─── 空闲回收 ────────────────────────────────────────────────────

    def _touch(self):
        self._last_used = time.time()
        if self.idle_close_seconds > 0 and (self._idle_task is None or self._idle_task.done()):
            try:
                self._idle_task = asyncio.create_task(self._idle_watchdog())
            except RuntimeError:
                self._idle_task = None

    async def _idle_watchdog(self):
        try:
            tick = min(30, max(5, self.idle_close_seconds // 4))
            while True:
                await asyncio.sleep(tick)
                if not self.available:
                    return
                idle = time.time() - self._last_used
                if idle >= self.idle_close_seconds:
                    logger.info(f"空闲 {idle:.0f}s（阈值 {self.idle_close_seconds}s），"
                                f"自动关闭无头浏览器以释放 CPU/内存")
                    await self._close()
                    return
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"空闲回收任务异常退出: {e}")

    # ─── 页面自愈 ────────────────────────────────────────────────────

    async def _page_alive(self) -> bool:
        page = self._page
        if page is None or page.is_closed():
            return False
        try:
            await page.evaluate("1")
            return True
        except Exception:
            return False

    async def _ensure_page(self) -> Optional[str]:
        """确保有一张可用页面；没有（或已失效）时换一张。

        ⚠️ **必须串行化**：并发调用（模型一轮里同时发几个工具请求，
        或者 `_ready()` 与 `_op()` 撞在一起）会各自发现"页面死了"，
        然后**各建一张新页** —— 结果 `_page`/`_own_page` 被后写的那个
        覆盖，先前建出来的页面**没人引用也没人关**（常驻泄漏），
        而且两个调用方各自拿到不同的页面，行为不可预期。

        这里用**独立的一把锁**（不复用 `_op_lock`）：`_ensure_page` 可能在
        已经持有 `_op_lock` 的路径上被调用（`_op` → 自愈），
        复用会导致自锁死。
        """
        async with self._page_lock:
            if await self._page_alive():
                return None
            if self._context is None:
                err = await self.start()
                if err:
                    return err
            # ⚠️ 拿到锁后**重新检查一次**：等锁期间别的调用可能已经换好了页面。
            if await self._page_alive():
                return None
            return await self._replace_page()

    async def _replace_page(self) -> Optional[str]:
        """换一张可用页面（复用现有标签，或新建）。

        ⚠️ 调用方必须已经持有 `_page_lock`。
        """
        try:
            reuse = None
            for p in list(getattr(self._context, "pages", []) or []):
                try:
                    if not p.is_closed():
                        reuse = p
                        break
                except Exception:
                    continue
            if reuse is not None:
                self._page = reuse
                logger.info("原页面已失效，复用浏览器里剩余的可用标签页")
            else:
                self._adopt_page(await self._new_page())
                logger.info("原页面已失效，已新建页面")
            self._own_page = self._page
            try:
                self._page.set_default_timeout(self.timeout * 1000)
            except Exception:
                pass
            return None
        except Exception as e:
            logger.warning(f"换页失败（{e}），重建浏览器")
            await self._close()
            return await self.start()

    async def _recover(self, exc: Exception):
        text = str(exc).lower()
        fatal = any(k in text for k in (
            "has been closed", "page closed", "target closed", "browser closed",
            "context closed", "connection closed", "crashed"))
        if not fatal:
            self._fail_streak = 0
            return
        self._fail_streak += 1
        logger.warning(f"检测到页面/浏览器失效（第 {self._fail_streak} 次），执行自愈")
        if self._fail_streak >= 2:
            await self._close()
            self._fail_streak = 0
        else:
            await self._ensure_page()

    async def _op(self, coro, what: str, timeout: Optional[float] = None):
        """执行一次页面操作。**串行化** —— 同一张页面上不允许并发操作。"""
        limit = timeout if timeout is not None else self.op_timeout
        try:
            async with self._op_lock:
                if limit and limit > 0:
                    return await asyncio.wait_for(coro, timeout=limit)
                return await coro
        except asyncio.TimeoutError:
            self._touch()
            raise RuntimeError(
                f"{what}超时（{limit:.0f}s）。页面可能仍在加载或该元素不可交互，"
                f"可以先用 browser_wait 等待后重试。") from None
        except Exception as e:
            await self._recover(e)
            raise
        finally:
            self._touch()

    async def _ready(self) -> Optional[str]:
        err = await self.start()
        if err:
            return err
        err = await self._ensure_page()
        if err:
            return err
        self._touch()
        return None

    # ══════════════════════════════════════════════════════════════════
    #  能力实现
    # ══════════════════════════════════════════════════════════════════

    async def list_tabs(self) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        tabs = []
        for i, p in enumerate(getattr(self._context, "pages", []) or []):
            try:
                if p.is_closed():
                    continue
                tabs.append(TabInfo(id=i, title=await p.title(), url=p.url,
                                    active=(p is self._page)))
            except Exception:
                continue
        return OpResult(data={"tabs": [t.to_dict() for t in tabs],
                              "tab_count": len(tabs)}, backend=self.name)

    def _check_tab_id(self, tab_id) -> Optional[str]:
        """无头后端只有一张页面 —— 调用方传了别的 tab_id 要**明确告知**，
        不能默默忽略（否则模型以为操作了那张标签页，实际没有）。"""
        if tab_id in (None, "", 0):
            return None
        return (f"无头后端只有一张页面（tab_id 固定为 0），"
                f"不支持指定 tab_id={tab_id}。"
                f"如需操作多标签，请使用扩展桥后端（browser_tabs 查看）。")

    async def get_page(self, detail: str = "text", tab_id=None,
                       offset: int = 0, max_chars=None,
                       selector: str = "", **kw) -> OpResult:
        """读取页面内容。支持 ``offset`` / ``max_chars`` 做**分页续读** ——
        单次返回的长度不该限制 bot 能看多少：它拿到「还有 N 字符未读」之后，
        可以带更大的 offset 再要一段，必要时自己翻到底。

        ``has_more`` / ``next_offset`` 会一并返回，方便模型直接续读。
        """
        msg = self._check_tab_id(tab_id)
        if msg:
            return OpResult.fail(msg, self.name)
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            page = self._page
            # ⚠️ mode=selector 时 main.py 会传 selector 进来。这个参数过去
            #    **不在签名里** —— 于是无头后端会直接 TypeError：
            #    "get_page() got an unexpected keyword argument 'selector'"，
            #    而且因为是在调度层抛的，模型只会看到一句莫名其妙的报错。
            #    这里补上实现（与扩展后端同形状：只取该元素的文本）。
            if selector:
                content = await self._op(
                    page.evaluate(
                        "(sel) => { const el = document.querySelector(sel);"
                        " return el ? (el.innerText || el.textContent || '')"
                        ".trim() : ''; }", selector),
                    "读取选择器内容")
                title = await self._op(page.title(), "读取标题")
                return OpResult(data={
                    "title": title, "url": page.url, "content": content,
                    "total_chars": len(content), "offset": 0,
                    "returned": len(content), "has_more": False,
                    "next_offset": None, "selector": selector,
                }, backend=self.name)
            if detail == "html":
                content = await self._op(page.content(), "读取 HTML")
            elif detail == "outline":
                content = await self._op(page.evaluate(
                    "() => Array.from(document.querySelectorAll('h1,h2,h3'))"
                    ".map(h => '  '.repeat(+h.tagName[1]-1) + '- ' + h.innerText).join('\\n')"),
                    "读取结构")
                links = await self._op(page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]')).slice(0,40)"
                    ".map(a => '- ' + (a.innerText||'').trim().slice(0,80) + ' → ' + a.href).join('\\n')"),
                    "读取链接")
                content = f"{content}\n\n## 主要链接\n{links}"
            else:
                content = await self._op(page.inner_text("body"), "读取正文")
            title = await self._op(page.title(), "读取标题")
            total = len(content)
            # 分页：offset 之前的内容丢掉，只回 max_chars 这么多
            limit = int(max_chars) if max_chars else self.content_page_size
            start = max(0, int(offset or 0))
            if limit and limit > 0:
                chunk = content[start:start + limit]
            else:
                chunk = content[start:]
            end = start + len(chunk)
            return OpResult(data={
                "title": title, "url": page.url, "content": chunk,
                "total_chars": total, "offset": start, "returned": len(chunk),
                "has_more": end < total,
                "next_offset": end if end < total else None,
            }, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"读取页面失败: {e}", self.name)

    async def extract(self, selector: str, attr=None, limit: int = 50, tab_id=None) -> OpResult:
        msg = self._check_tab_id(tab_id)
        if msg:
            return OpResult.fail(msg, self.name)
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            script = (
                "([sel, at, lim]) => Array.from(document.querySelectorAll(sel)).slice(0, lim)"
                ".map(el => at ? el.getAttribute(at) : (el.innerText || el.textContent || '').trim())"
            )
            items = await self._op(
                self._page.evaluate(script, [selector, attr, int(limit or 50)]), "提取数据")
            return OpResult(data={"url": self._page.url, "items": items}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"提取失败: {e}", self.name)

    async def navigate(self, url: str, new_tab: bool = False, tab_id=None) -> OpResult:
        # new_tab=True 是"开新页"，不需要 tab_id；
        # 否则指定别的 tab_id 在无头侧做不到，明确告知而不是默默忽略
        if not new_tab:
            msg = self._check_tab_id(tab_id)
            if msg:
                return OpResult.fail(msg, self.name)
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            if new_tab:
                # ⚠️ 先建新页、认领，再关旧页。
                #    不关的话每调一次就多一张 Chromium 页面常驻吃资源，
                #    而 _check_tab_id() 又让调用方选不到它们 —— 纯泄漏。
                old_page = self._page
                page = self._adopt_page(await self._new_page())
                if old_page is not None and old_page is not page:
                    try:
                        await old_page.close()
                    except Exception as pe:
                        logger.debug(f"关闭旧页面失败: {pe}")
            # 默认 domcontentloaded：networkidle 已被官方标注不推荐，
            # 现代页面可能永远不空闲，白等 + 让页面持续跑
            await self._op(self._page.goto(url, wait_until=self.wait_until,
                                           timeout=self.timeout * 1000),
                           f"访问 {url}")
            title = await self._op(self._page.title(), "读取标题")
            return OpResult(data={"url": self._page.url, "title": title,
                                  "navigated": True, "tab_id": 0}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"访问页面失败: {e}", self.name)

    async def click(self, selector=None, text=None, index=None, **kw) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            if selector:
                await self._op(self._page.click(selector, timeout=self.action_timeout * 1000),
                               f"点击 {selector}")
            elif text:
                loc = self._page.get_by_text(text, exact=False).first
                await self._op(loc.click(timeout=self.action_timeout * 1000),
                               f"点击文字「{text}」")
            elif index is not None:
                loc = self._page.locator(
                    "a,button,input[type=submit],[role=button]").nth(int(index))
                await self._op(loc.click(timeout=self.action_timeout * 1000),
                               f"点击第 {index} 个可点击元素")
            else:
                return OpResult.fail("需要提供 selector、text 或 index 之一", self.name)
            # 与扩展后端保持**同样的返回字段** —— 否则同一个工具会因为
            # 路由到不同后端而给出不同形状的结果，模型看到的信息不一致。
            # （扩展侧能知道"页面是否跳转"，无头侧同样能判断，就该给出来）
            await asyncio.sleep(0.2)          # 给跳转一点时间
            return OpResult(data={"ok": True, "navigated": False, "changed": True,
                                  "match": selector or (f"text={text}" if text else f"index={index}"),
                                  "url": self._page.url},
                            backend=self.name)
        except Exception as e:
            return OpResult.fail(f"点击失败: {e}", self.name)

    async def type_text(self, selector: str, text: str, submit: bool = False,
                        clear_first: bool = True, **kw) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            if clear_first:
                await self._op(self._page.fill(selector, text,
                                               timeout=self.action_timeout * 1000),
                               f"填写 {selector}")
            else:
                await self._op(self._page.type(selector, text,
                                               timeout=self.action_timeout * 1000),
                               f"输入 {selector}")
            if submit:
                await self._op(self._page.press(selector, "Enter",
                                                timeout=self.action_timeout * 1000),
                               "提交")
            await asyncio.sleep(0.2)
            return OpResult(data={"ok": True, "submitted": bool(submit),
                                  "navigated": False, "url": self._page.url},
                            backend=self.name)
        except Exception as e:
            return OpResult.fail(f"输入失败: {e}", self.name)

    async def scroll(self, direction: str, amount=None, **kw) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            step = int(amount) if amount else 800
            js = {
                "down": f"window.scrollBy(0, {step})",
                "up": f"window.scrollBy(0, -{step})",
                "bottom": "window.scrollTo(0, document.body.scrollHeight)",
                "top": "window.scrollTo(0, 0)",
            }.get(direction)
            if not js:
                return OpResult.fail(f"未知滚动方向: {direction}", self.name)
            await self._op(self._page.evaluate(js), f"滚动到 {direction}")
            return OpResult(data={"ok": True, "changed": True}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"滚动失败: {e}", self.name)

    async def wait_for(self, selector=None, text=None, timeout: int = 10, **kw) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        limit = max(1, min(int(timeout or 10), 60))
        started = time.time()
        # 先取 url：出错时 _recover 可能把 self._page 置空，
        # except 里再去读就是 AttributeError
        url_before = ""
        try:
            url_before = self._page.url
        except Exception:
            pass
        try:
            if selector:
                await self._op(self._page.wait_for_selector(selector, timeout=limit * 1000),
                               f"等待 {selector}", timeout=limit + 5)
            elif text:
                await self._op(self._page.wait_for_function(
                    "t => document.body && document.body.innerText.includes(t)",
                    arg=text, timeout=limit * 1000), f"等待文字「{text}」", timeout=limit + 5)
            else:
                return OpResult.fail("需要提供 selector 或 text", self.name)
            cur = self._page.url if self._page is not None else url_before
            return OpResult(data={"found": True, "elapsed": round(time.time() - started, 1),
                                  "url": cur}, backend=self.name)
        except Exception:
            return OpResult(data={"found": False, "elapsed": round(time.time() - started, 1),
                                  "url": url_before}, backend=self.name)

    async def screenshot(self, path: str, full_page: bool = False, selector=None) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            if selector:
                el = await self._page.query_selector(selector)
                if not el:
                    return OpResult.fail(f"未找到元素: {selector}", self.name)
                await self._op(el.screenshot(path=path), "元素截图")
            else:
                await self._op(self._page.screenshot(path=path, full_page=full_page),
                               "页面截图")
            self._clean_screenshots()
            return OpResult(data={"path": path, "url": self._page.url}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"截图失败: {e}", self.name)

    # ─── 补齐的能力（原版有，合并时被我漏掉了）─────────────────────

    async def get_info(self) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            return OpResult(data={"title": await self._op(self._page.title(), "读取标题"),
                                  "url": self._page.url}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"获取信息失败: {e}", self.name)

    async def go_back(self) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            await self._op(self._page.go_back(), "返回上一页")
            return OpResult(data={"url": self._page.url}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"返回失败: {e}", self.name)

    async def refresh(self) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            await self._op(self._page.reload(), "刷新页面")
            return OpResult(data={"url": self._page.url}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"刷新失败: {e}", self.name)

    async def hover(self, selector: str) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            await self._op(self._page.hover(selector, timeout=self.action_timeout * 1000),
                           f"悬停 {selector}")
            return OpResult(data={"ok": True, "url": self._page.url}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"悬停失败: {e}", self.name)

    async def upload_file(self, selector: str, file_path: str) -> OpResult:
        """上传本地文件到 input[type=file]，绕过系统文件对话框。"""
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        resolved = os.path.realpath(file_path)
        if not os.path.isfile(resolved):
            return OpResult.fail(f"文件不存在或不是常规文件: {file_path}", self.name)
        try:
            await self._op(self._page.set_input_files(selector, resolved),
                           f"上传文件到 {selector}", timeout=self.action_timeout)
            try:
                size = os.path.getsize(resolved)
            except OSError:
                size = 0
            return OpResult(data={"path": resolved,
                                  "name": os.path.basename(resolved),
                                  "size": size, "url": self._page.url}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"上传失败: {e}", self.name)

    async def keyboard_type(self, text: str, delay: int = 0) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            await self._op(self._page.keyboard.type(text, delay=int(delay or 0)),
                           "键盘输入", timeout=max(self.action_timeout, len(text) * 0.05 + 5))
            return OpResult(data={"ok": True, "navigated": False, "submitted": False,
                                  "url": self._page.url}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"输入失败: {e}", self.name)

    async def keyboard_press(self, key: str) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            await self._op(self._page.keyboard.press(key), f"按键 {key}")
            return OpResult(data={"ok": True, "url": self._page.url}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"按键失败: {e}", self.name)

    async def keyboard_down_up(self, action: str, key: str) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            if action == "down":
                await self._op(self._page.keyboard.down(key), f"按住 {key}")
            else:
                await self._op(self._page.keyboard.up(key), f"释放 {key}")
            return OpResult(data={"ok": True, "url": self._page.url}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"操作失败: {e}", self.name)

    async def mouse_move(self, x: int, y: int, steps: int = 1) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            await self._op(self._page.mouse.move(int(x), int(y), steps=int(steps or 1)),
                           "移动鼠标", timeout=self.action_timeout)
            return OpResult(data={"x": x, "y": y}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"移动失败: {e}", self.name)

    async def mouse_click(self, x=None, y=None, button: str = "left",
                          click_count: int = 1) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            if x is not None and y is not None:
                await self._op(self._page.mouse.move(int(x), int(y)), "移动鼠标")
            # ⚠️ 不能循环 down/up —— 那样每次的 clickCount 都是 1，
            #    页面收到的是"两次独立单击"而不是一次双击，
            #    `dblclick` 事件永远不触发（双击选词、双击打开都会失效）。
            #    mouse.click 支持 click_count，会正确设置 detail/clickCount。
            n = max(1, int(click_count or 1))
            if x is not None and y is not None:
                await self._op(self._page.mouse.click(int(x), int(y),
                                                      button=button, click_count=n),
                               "坐标点击")
            else:
                # ⚠️ 无坐标时也**必须传 click_count**：
                #    单纯循环 down/up 每次的 clickCount 都是 1，
                #    页面收到的是"两次独立单击"而不是一次双击 →
                #    `dblclick` 永远不触发（和上面注释说的问题同一个）。
                for i in range(n):
                    cc = i + 1
                    await self._op(self._page.mouse.down(button=button,
                                                         click_count=cc), "按下鼠标")
                    await self._op(self._page.mouse.up(button=button,
                                                       click_count=cc), "释放鼠标")
            await asyncio.sleep(0.2)
            return OpResult(data={"ok": True, "navigated": False,
                                  "url": self._page.url}, backend=self.name)
        except Exception as e:
            try:
                await self._page.mouse.up(button=button)
            except Exception:
                pass
            return OpResult.fail(f"点击失败: {e}", self.name)

    async def mouse_down_up(self, action: str, button: str = "left") -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            if action == "down":
                await self._op(self._page.mouse.down(button=button), "按下鼠标")
            else:
                await self._op(self._page.mouse.up(button=button), "释放鼠标")
            return OpResult(data={"ok": True, "url": self._page.url}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"操作失败: {e}", self.name)

    async def mouse_wheel(self, delta_x: int = 0, delta_y: int = 0) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            await self._op(self._page.mouse.wheel(int(delta_x or 0), int(delta_y or 0)),
                           "滚轮滚动")
            return OpResult(data={"ok": True}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"滚动失败: {e}", self.name)

    async def mouse_drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
                         button: str = "left", steps: int = 10) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            await self._op(self._page.mouse.move(int(start_x), int(start_y)), "移动到起点")
            await self._op(self._page.mouse.down(button=button), "按下鼠标")
            await self._op(self._page.mouse.move(int(end_x), int(end_y),
                                                 steps=int(steps or 10)), "拖拽")
            await self._op(self._page.mouse.up(button=button), "释放鼠标")
            return OpResult(data={"ok": True, "url": self._page.url}, backend=self.name)
        except Exception as e:
            try:
                await self._page.mouse.up(button=button)
            except Exception:
                pass
            return OpResult.fail(f"拖拽失败: {e}", self.name)

    async def list_files(self, dir_type: str = "screenshots", limit: int = 20) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        d = self.download_dir if dir_type == "downloads" else self.screenshot_dir
        try:
            names = []
            for n in sorted(os.listdir(d), reverse=True):
                fp = os.path.join(d, n)
                if os.path.isfile(fp):
                    names.append({"name": n, "size": os.path.getsize(fp),
                                  "mtime": os.path.getmtime(fp)})
                if len(names) >= int(limit or 20):
                    break
            return OpResult(data={"dir": d, "files": names}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"列目录失败: {e}", self.name)

    async def debug_state(self) -> OpResult:
        """给排障用：当前后端到底处在什么状态。"""
        pages = 0
        try:
            pages = len([p for p in (self._context.pages or []) if not p.is_closed()])
        except Exception:
            pass
        return OpResult(data={
            "backend": self.display,
            "available": self.available,
            "headless": self.headless,
            "profile_mode": self.profile_mode,
            "profile_dir": self._peek_inherited() or str(
                Path(self._data_dir) / "browser_profile"),
            "wait_until": self.wait_until,
            "op_timeout": self.op_timeout,
            "action_timeout": self.action_timeout,
            "idle_close_seconds": self.idle_close_seconds,
            "idle_for": round(time.time() - self._last_used, 1),
            "pages_open": pages,
            "owns_page": self._own_page is not None,
            "launch_args_count": len(build_launch_args(self.headless)),
        }, backend=self.name)

    async def cookie_get(self, url: str = "", tab_id=None) -> OpResult:
        """导出当前站点 cookie（用于打通到另一个后端）。"""
        msg = self._check_tab_id(tab_id)
        if msg:
            return OpResult.fail(msg, self.name)
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        target = url or self._page.url
        try:
            cookies = await self._context.cookies(target if target else None)
            return OpResult(data={"url": target, "cookies": cookies}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"导出 cookie 失败: {e}", self.name)

    async def cookie_set(self, cookies: list) -> OpResult:
        """把 cookie 写进无头后端（用它来复用真实浏览器的登录态）。"""
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        fixed, skipped = [], 0
        for c in cookies or []:
            if not isinstance(c, dict) or not c.get("name") or not c.get("domain"):
                skipped += 1
                continue
            same = str(c.get("sameSite") or "Lax")
            same = {"strict": "Strict", "lax": "Lax", "none": "None",
                    "no_restriction": "None", "unspecified": "Lax"}.get(
                        same.lower(), same if same in ("Strict", "Lax", "None") else "Lax")
            item = {
                "name": c["name"], "value": c.get("value", ""),
                "domain": c["domain"], "path": c.get("path", "/"),
                "secure": bool(c.get("secure")), "httpOnly": bool(c.get("httpOnly")),
                "sameSite": same,
            }
            exp = c.get("expirationDate") or c.get("expires")
            if exp:
                try:
                    item["expires"] = int(float(exp))
                except (TypeError, ValueError):
                    pass
            fixed.append(item)
        try:
            if not fixed:
                return OpResult.fail("没有可写入的 cookie", self.name)
            await self._context.add_cookies(fixed)
            # written/skipped 与扩展后端字段一致
            return OpResult(data={"ok": len(fixed), "written": len(fixed),
                                  "skipped": skipped, "failed": 0,
                                  "total": len(cookies or [])},
                            backend=self.name)
        except Exception as e:
            return OpResult.fail(f"写入 cookie 失败: {e}", self.name)

    async def execute_js(self, script: str) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        try:
            r = await self._op(self._page.evaluate(script), "执行 JavaScript",
                               timeout=self.action_timeout)
            return OpResult(data={"result": r, "url": self._page.url},
                            backend=self.name)
        except Exception as e:
            return OpResult.fail(f"执行失败: {e}", self.name)

    async def download(self, url: str, path: str) -> OpResult:
        err = await self._ready()
        if err:
            return OpResult.fail(err, self.name)
        if not url.lower().startswith(("http://", "https://")):
            return OpResult.fail("仅支持 http/https 链接下载", self.name)
        # ⚠️ 带浏览器凭据去下载时，明文 HTTP 会把 cookie 暴露在网络上
        #    （CWE-319）。而且 aiohttp 默认跟随重定向，跳一次就可能
        #    把 cookie 带到 http 站点。所以：**非 HTTPS 就不带 cookie**。
        is_https = url.lower().startswith("https://")
        if not is_https:
            logger.warning(f"目标不是 HTTPS，本次下载将**不携带**浏览器 Cookie：{url}")
        try:
            import aiohttp
            from yarl import URL as _URL
            headers, jar = {}, None
            try:
                if self._context is not None and is_https:
                    jar = aiohttp.CookieJar(unsafe=False)
                    # ⚠️ 用 {name: value} 这种 dict 会把 domain/path/secure/expires
                    #    全部丢掉，只留"名字+值" ——
                    #    结果是跨域重定向（比如 file CDN 在另一个域）时，
                    #    cookie 可能被带到不该带的域，也可能该带的不带。
                    #    改成逐个 add_cookie，保留完整语义。
                    raw = await self._context.cookies(url)
                    # ⚠️ 这里原本有个空转循环：
                    #    `for c in raw: jar.update_cookies({}, ...)`
                    #    —— 传空 dict、还把异常吞掉，什么都没做。
                    #    真正写入 jar 的是下面那段基于 raw 的处理。
                    from http.cookies import SimpleCookie as _SC
                    for c in raw:
                        sc = _SC()
                        sc[c["name"]] = c.get("value", "")
                        m = sc[c["name"]]
                        m["path"] = c.get("path", "/")
                        if c.get("domain"):
                            m["domain"] = c["domain"]
                        if c.get("secure"):
                            m["secure"] = True
                        exp = c.get("expires")
                        if exp:
                            try:
                                import time as _t
                                m["expires"] = _t.strftime(
                                    "%a, %d-%b-%Y %H:%M:%S GMT",
                                    _t.gmtime(int(exp)))
                            except Exception:
                                pass
                        jar.update_cookies(sc, response_url=_URL(url))
                    if self.user_agent:
                        headers["User-Agent"] = self.user_agent
            except Exception as e:
                logger.debug(f"取下载 cookie 失败: {e}")
                jar = None
            limit = self.download_max_bytes
            async with aiohttp.ClientSession(headers=headers, cookie_jar=jar) as s:
                # ⚠️ 带了 cookie 就**不允许自动重定向**。
                #    aiohttp 只过滤 `Secure` cookie，而 HTTPS→HTTP 的同域重定向
                #    会把**非 Secure 的会话 cookie** 一起发出去（CWE-319）——
                #    等于把登录态明文送出。这里自己跟，且**每一跳都要求 HTTPS**；
                #    一旦要降级到 http，就丢掉 jar 再继续（宁可匿名也不明文带凭据）。
                # ⚠️ 带 cookie 时不自动跟随重定向，自己跟；每跳都要求 HTTPS。
                #    要降级到 http 时**直接停在这里**（不再继续跟）——
                #    既不把 Cookie 明文送出去，也不用去改 aiohttp 的
                #    私有属性 `_cookie_jar`（那是实现细节，升级即碎）。
                r = await s.get(url, allow_redirects=False)
                hops = 0
                while 300 <= r.status < 400 and hops < 5:
                    loc = r.headers.get("Location")
                    if not loc:
                        break
                    nxt = urljoin(str(r.url), loc)
                    if jar is not None and not nxt.lower().startswith("https://"):
                        logger.warning(
                            f"下载重定向到非 HTTPS（{nxt}）—— 为保护 Cookie "
                            f"不跟随该跳，按当前状态返回")
                        break
                    r = await s.get(nxt, allow_redirects=False)
                    hops += 1
                    url = nxt

                if r.status != 200:
                    return OpResult.fail(f"下载失败，HTTP {r.status}", self.name)
                declared = r.headers.get("Content-Length")
                if declared and limit > 0:
                    try:
                        if int(declared) > limit:
                            return OpResult.fail(
                                f"文件过大（{int(declared)} > {limit} 字节），已拒绝", self.name)
                    except ValueError:
                        pass
                size = 0
                with open(path, "wb") as f:
                    async for chunk in r.content.iter_chunked(64 * 1024):
                        size += len(chunk)
                        if limit > 0 and size > limit:
                            f.close()
                            try:
                                os.remove(path)
                            except Exception:
                                pass
                            return OpResult.fail(f"文件超过 {limit} 字节上限，已中止", self.name)
                        f.write(chunk)
            self._clean_downloads()
            return OpResult(data={"path": path, "size": size, "url": url,
                                  "mime": None}, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"下载失败: {e}", self.name)

    # ─── 清理 ────────────────────────────────────────────────────────

    def _clean_screenshots(self):
        if not self.screenshot_auto_clean:
            return
        try:
            files = (glob.glob(os.path.join(self.screenshot_dir, "screenshot_*.png"))
                     + glob.glob(os.path.join(self.screenshot_dir, "element_*.png")))
            if len(files) <= self.screenshot_max_count:
                return
            files.sort(key=lambda x: os.path.getmtime(x))
            n = 0
            for fp in files[:len(files) - self.screenshot_max_count]:
                try:
                    os.remove(fp)
                    n += 1
                except Exception:
                    pass
            if n:
                logger.info(f"清理了 {n} 张旧截图")
        except Exception as e:
            logger.debug(f"清理截图出错: {e}")

    def _clean_downloads(self):
        if not self.download_auto_clean:
            return
        try:
            files = [f for f in glob.glob(os.path.join(self.download_dir, "*"))
                     if os.path.isfile(f)]
            if len(files) <= self.download_max_count:
                return
            files.sort(key=lambda x: os.path.getmtime(x))
            n = 0
            for fp in files[:len(files) - self.download_max_count]:
                try:
                    os.remove(fp)
                    n += 1
                except Exception:
                    pass
            if n:
                logger.info(f"清理了 {n} 个旧下载")
        except Exception as e:
            logger.debug(f"清理下载出错: {e}")

    def new_filename(self, prefix: str = "screenshot", ext: str = "png") -> str:
        return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}"


# ─── 小工具 ──────────────────────────────────────────────────────────

def _as_bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    return bool(v)


def _parse_viewport(s: str) -> dict:
    try:
        w, h = map(int, str(s).lower().split("x"))
        return {"width": w, "height": h}
    except Exception:
        return {"width": 1920, "height": 1080}
