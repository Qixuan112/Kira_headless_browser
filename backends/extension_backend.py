"""扩展桥后端 —— 直接驱动**用户自己的浏览器**（零冲突）。

这是合并方案里解决"真实浏览器不能共用"的关键：扩展作为 WebSocket 客户端
主动连出，插件不需要启动任何浏览器，因此**不存在 profile 抢占**。

与无头后端的区别：
  * 用的就是用户眼前那个浏览器（`is_user_browser = True`）
  * 拿得到真实的登录态、Cookie、已打开的标签页
  * 但能力受扩展限制（不能执行任意 JS、不能上传文件）
"""

from __future__ import annotations

from typing import Optional

from core.logging_manager import get_logger

from .. import protocol as _P_MOD
from .base import OpResult
from .router import Backend

logger = get_logger("browser_merged", "cyan")


class ExtensionBackend(Backend):
    """包装与浏览器扩展之间的 BrowserBridge。"""

    name = "extension"
    is_user_browser = True

    #: 上传大小上限（默认 **256MB**）。
    #
    #  **帧尺寸**：不是约束。上传走**分块流式**，单帧恒定 ~340KB。
    #  **SW 内存**：也不是约束。分块的累积发生在**页面侧**（content.js），
    #  Service Worker 只做转发、峰值恒定为一块（~0.3MB）——
    #  这一点很重要，因为 MV3 的 SW 恰恰是最容易被系统回收的。
    #
    #  实测（Node 基线，RSS）：
    #     文件 64MB → 页面峰值 +70MB (1.10×)
    #     文件 200MB → +200MB (1.00×)
    #     文件 256MB → +261MB (1.02×)
    #  也就是说峰值 ≈ 1.0× 文件大小，不再有 2.67× 的放大。
    #  吞吐实测 ≈19 MB/s（256MB 约 13s），内容 SHA-256 全部校验一致。
    #
    #  取 256MB 为默认上限；要更大可调 upload_max_bytes。
    MAX_UPLOAD_BYTES = 256 * 1024 * 1024

    def __init__(self, bridge, protocol, max_upload_bytes=None,
                 max_download_bytes=None, download_timeout=None,
                 content_page_size=8000,
                 require_confirm=False, confirm_timeout=45,
                 screenshot_restore_window=True):
        self._bridge = bridge
        self._P = protocol
        self.max_upload_bytes = int(max_upload_bytes or self.MAX_UPLOAD_BYTES)
        self.max_download_bytes = max_download_bytes or 2 * 1024 ** 3
        self.download_timeout = download_timeout or 600.0
        self.content_page_size = int(content_page_size or 8000)
        # 二次确认：由插件把这两个值随命令下发，扩展侧才弹通知。
        # （配置项存在、扩展也实现了，但如果不在这里传下去，整套确认就是死的）
        self.require_confirm = bool(require_confirm)
        self.confirm_timeout = int(confirm_timeout or 45)
        #: 截图时窗口最小化 → 让扩展"借窗口一瞬"（截完还原）。同 require_confirm，
        #: 必须随命令下发，否则配置项等于不存在。
        self.screenshot_restore_window = bool(screenshot_restore_window)

    # ─── Backend 接口 ────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        try:
            return bool(self._bridge.connected)
        except Exception:
            return False

    @property
    def display(self) -> str:
        # ⚠️ 这里要**取一次公开的 info**（BrowserBridge.info 是 @property），
        #    不要直接摸 _bridge._hello 之类的内部字段；也不要把 info 当成
        #    可调用对象。取不到就退回占位符，绝不因为桥未连接而抛异常。
        try:
            info = self._bridge.info or {}
        except Exception:
            info = {}
        ver = info.get("extension_version") or "?"
        br = info.get("browser") or "?"
        return f"用户浏览器（{br} · 扩展 v{ver}）"

    async def close(self) -> None:
        # ⚠️ **不要**在这里关 bridge：bridge 的生命周期归主插件
        #    （main.terminate 里 `await self.bridge.close()` 兜底）。
        #    这里也关一次的话 terminate 会关两遍 —— 幂等不出错，
        #    但"backend 是否拥有 bridge"的语义会糊掉。
        return None

    #: **只读但敏感**、必须经用户确认的命令。
    #  cookie_get 会把 chrome.cookies.getAll 的**实际取值**回传给插件，
    #  虽然它不改状态（因此不属写操作、不受只读模式与域名白名单约束），
    #  但导出会话 Cookie 等同于交出登录态 —— 开了「写操作需确认」时，
    #  用户理应看到"要导出 Cookie"这一条并亲自批准，而不是被静默放行。
    CONFIRM_ONLY_CMDS = {"cookie_get"}

    #: 需要用户确认的命令（与扩展侧 shared.js 的 PRIVILEGED_COMMANDS 对齐）
    # ⚠️ **从 protocol 派生**，不要在这里再抄一份字面量 ——
    #    这里原本抄了一份，而 protocol.py 里早就有权威的
    #    `WRITE_COMMANDS`（用 CMD_* 常量拼的）。两份定义迟早漂移：
    #    protocol 加了新写命令，这份字面量不会自动跟上 →
    #    那条命令**静默绕过确认框**。
    #    派生之后"新增命令自动纳入确认"，不再需要人工同步。
    #    （用类定义处的模块级导入 `_P_MOD`，不用构造函数的 `self._P` ——
    #      类属性在类定义时求值，那时还没有实例。）
    WRITE_CMDS = set(_P_MOD.WRITE_COMMANDS)

    async def _send(self, cmd: str, params: Optional[dict] = None, timeout=None,
                    cmd_id: str = None) -> OpResult:
        p = dict(params or {})
        # ⚠️ 二次确认必须在这里统一下发。
        #    之前插件侧从不传 require_confirm，导致「写操作需用户确认」这个
        #    配置项**完全不生效** —— 扩展那边实现好了却永远收不到开关。
        if self.require_confirm and cmd in (self.WRITE_CMDS | self.CONFIRM_ONLY_CMDS):
            p.setdefault("require_confirm", True)
            p.setdefault("confirm_timeout", self.confirm_timeout)
        # 截图：窗口最小化/被遮挡时要不要"借窗口一瞬"（截完还原）。
        # 同 require_confirm —— 不下发的话，扩展那边永远拿默认值，配置项形同虚设。
        if cmd == self._P.CMD_SCREENSHOT:
            p.setdefault("restore_window", self.screenshot_restore_window)
        try:
            data = await self._bridge.send_command(cmd, p,
                                                   timeout=timeout, cmd_id=cmd_id)
            if isinstance(data, dict) and data.get("declined"):
                # 用 declined 而不是普通 fail —— 调用方据此**禁止**换后端重试
                return OpResult.declined_by_user(self.name)
            return OpResult(data=data, backend=self.name)
        except Exception as e:
            msg = str(e)
            # ⚠️ 超时类错误标成**不确定**：命令可能已经在页面里执行了，
            #    只是回执没回来。若当成普通失败，上层会换（无头）后端重试，
            #    同一个点击/输入就被做了两次。
            #
            # ⚠️ 优先看**显式错误类别**（扩展上报的 error_code）。
            #    以前只靠 `"超时" in msg` 判定 —— 那是文案匹配，
            #    改个提示文字（或换语言）这条安全逻辑就**静默失效**，
            #    退化成"同一个操作被执行两次"。文案匹配保留为兜底
            #    （兼容还没上报 error_code 的旧版扩展）。
            if getattr(e, "err_code", None) == self._P.ERR_TIMEOUT:
                return OpResult.indeterminate_result(msg, self.name)
            if "超时" in msg or "timeout" in msg.lower():
                return OpResult.indeterminate_result(msg, self.name)
            return OpResult.fail(msg, self.name)

    # ══════════════════════════════════════════════════════════════════
    #  能力实现（与无头后端同一套签名，便于路由互换）
    # ══════════════════════════════════════════════════════════════════

    async def list_tabs(self) -> OpResult:
        r = await self._send(self._P.CMD_LIST_TABS)
        return r

    async def get_page(self, detail: str = "text", tab_id=None,
                       offset: int = 0, max_chars=None, selector: str = "",
                       **kw) -> OpResult:
        """读页面。**必须和 HeadlessBackend 返回同样形状** ——
        路由可能在两者间切换，若只有一边分页，模型拿到的字段会随后端而变。

        selector 走 CMD_EXTRACT 取单个元素的文本（扩展侧不做 selector 读）。
        """
        if selector:
            r = await self._send(self._P.CMD_EXTRACT,
                                 {"selector": selector, "limit": 1, "tab_id": tab_id})
            if not r.ok:
                return r
            items = (r.data or {}).get("items") or []
            content = items[0] if items else ""
            return OpResult(data={"title": "", "url": (r.data or {}).get("url", ""),
                                  "content": content, "total_chars": len(content),
                                  "offset": 0, "returned": len(content),
                                  "has_more": False, "next_offset": None},
                            backend=self.name)

        r = await self._send(self._P.CMD_GET_PAGE,
                             {"detail": detail or "text", "tab_id": tab_id})
        if not r.ok:
            return r
        # 在这里补上分页（扩展侧一次性回全量，分页放到插件侧做）
        d = dict(r.data or {})
        full = d.get("content") or ""
        total = len(full)
        limit = int(max_chars) if max_chars else self.content_page_size
        start = max(0, int(offset or 0))
        chunk = full[start:start + limit] if limit and limit > 0 else full[start:]
        end = start + len(chunk)
        d.update({"content": chunk, "total_chars": total, "offset": start,
                  "returned": len(chunk), "has_more": end < total,
                  "next_offset": end if end < total else None})
        return OpResult(data=d, backend=self.name)

    async def extract(self, selector: str, attr=None, limit: int = 50, tab_id=None) -> OpResult:
        return await self._send(self._P.CMD_EXTRACT,
                                {"selector": selector, "attr": attr,
                                 "limit": int(limit or 50), "tab_id": tab_id})

    async def navigate(self, url: str, new_tab: bool = False, tab_id=None) -> OpResult:
        r = await self._send(self._P.CMD_NAVIGATE,
                             {"url": url, "tab_id": tab_id, "new_tab": bool(new_tab)})
        if not r.ok:
            return r
        # 与无头后端保持同样的字段（无头侧会回 title，这边也补上，
        # 否则模型拿到的信息随路由而变）
        d = dict(r.data or {}) if isinstance(r.data, dict) else {}
        if "title" not in d:
            try:
                info = await self._send(self._P.CMD_GET_INFO, {"tab_id": d.get("tab_id")})
                if info.ok and isinstance(info.data, dict):
                    d["title"] = info.data.get("title", "")
            except Exception:
                pass
            # ⚠️ 兜底必须放在 try 之外 ——
            #    `_send` 会把失败**转成 OpResult** 而不是抛异常，
            #    所以 except 分支根本不会走，title 就漏了，
            #    两后端的返回契约随之被破坏。
            d.setdefault("title", "")
        return OpResult(data=d, backend=self.name)

    async def click(self, selector=None, text=None, index=None, **kw) -> OpResult:
        return await self._send(self._P.CMD_CLICK,
                                {"selector": selector, "text": text, "index": index})

    async def type_text(self, selector: str, text: str, submit: bool = False,
                        clear_first: bool = True, **kw) -> OpResult:
        return await self._send(self._P.CMD_TYPE,
                                {"selector": selector, "text": text,
                                 "submit": bool(submit), "clear_first": bool(clear_first)})

    async def scroll(self, direction: str, amount=None, **kw) -> OpResult:
        return await self._send(self._P.CMD_SCROLL,
                                {"direction": direction, "amount": amount})

    async def wait_for(self, selector=None, text=None, timeout: int = 10, **kw) -> OpResult:
        limit = max(1, min(int(timeout or 10), 60))
        return await self._send(self._P.CMD_WAIT_FOR,
                                {"selector": selector, "text": text, "timeout": limit},
                                timeout=limit + 5)

    async def screenshot(self, path: str, full_page: bool = False, selector=None) -> OpResult:
        """扩展截图，返回 base64；这里落盘。

        两条路线：
          · 可视区域 —— `captureVisibleTab`（老能力，不需要调试器权限）；
          · 整页 / 元素 —— 扩展 v1.6.0 起走 **CDP**
            （`Page.captureScreenshot` + `captureBeyondViewport` / clip）。
            旧版扩展没有这条路：事前按握手版本拦住，明说怎么更新 ——
            而不是**默默忽略**整页参数、照样截一张视口图报成功（假成功）。
        """
        if full_page or selector:
            if not self._ext_version_ok(self.CDP_MIN_EXT_VERSION):
                return OpResult.fail(
                    f"整页/元素截图需要扩展 v{self.CDP_MIN_EXT_VERSION}+"
                    f"（走 CDP；当前扩展版本过低或未连接）。"
                    f"请用插件目录里的 browser-bridge/ 重新加载扩展；"
                    f"或显式切到无头后端（browser_backend use=headless，"
                    f"那是另一个浏览器）。",
                    self.name)
        r = await self._send(self._P.CMD_SCREENSHOT,
                             {"full_page": bool(full_page),
                              "selector": selector or ""})
        if not r.ok:
            return r
        data = r.data or {}
        img = data.get("image") or ""
        if not img.startswith("data:image"):
            return OpResult.fail("扩展没有返回截图数据", self.name)
        try:
            import base64
            payload = img.split(",", 1)[1]
            with open(path, "wb") as f:
                f.write(base64.b64decode(payload))
            out = {"path": path, "url": data.get("url")}
            # ⚠️ 整页被高度上限截断时**必须让调用方知道** ——
            #    否则模型会以为"页面就这么长"，漏掉下面的内容。
            if data.get("truncated"):
                out["truncated"] = True
            return OpResult(data=out, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"保存截图失败: {e}", self.name)

    async def get_selection(self, tab_id: int = 0) -> OpResult:
        """读页面上**用户选中的文字**。

        ⚠️ 这个能力扩展早就实现了（content script 的 get_selection），
           但插件侧一直没接 —— 于是 bot 够不着，只能去读整页文本再自己找。
        """
        return await self._send(self._P.CMD_GET_SELECTION, {"tab_id": tab_id})

    async def execute_js(self, script: str) -> OpResult:
        """执行任意 JS。

        MV3 下 `chrome.scripting.executeScript` 的 eval 会被页面 CSP 挡掉，
        所以扩展走 `chrome.userScripts`（官方为运行任意代码字符串设计）。
        代价：Chrome 138+ 需要用户手动打开「Allow User Scripts」开关 ——
        扩展会把这种情况翻译成一句用户能照做的话，而不是一个裸错误。
        """
        return await self._send(self._P.CMD_EXEC_JS, {"script": script})

    #: 扩展从哪个版本起带 CDP（chrome.debugger）能力。
    #: 低于它的扩展收到 cdp 命令会报"未知命令"，整页/元素截图会被静默降级
    #: 成可视区截图 —— 所以这里**事前**按握手版本拦住，给能照做的话。
    CDP_MIN_EXT_VERSION = "1.6.0"

    def _ext_version_ok(self, minimum: str) -> bool:
        """当前连着的扩展版本 >= minimum 吗（连不上/没报版本都按不满足）。

        ⚠️ 用本模块内置的 `_cmp_semver`，**不要**去借 setup_guide 的
           compare_versions —— 那是面板模块，后端不该反向依赖它
           （某些加载顺序下它根本不在 sys.modules 里，版本闸门会静默全拒）。
        """
        try:
            hello = getattr(self._bridge, "_hello", None)
            cur = getattr(hello, "extension_version", None)
            if not cur:
                return False
            return _cmp_semver(str(cur), minimum) >= 0
        except Exception:
            return False

    async def cdp(self, method: str, params: Optional[dict] = None,
                  tab_id=None) -> OpResult:
        """CDP 透传（chrome.debugger）：trusted 输入 / 整页截图 / 协议层数据。

        ⚠️ 权限等级与 exec_js 同级：都是"写"，走同一套只读/白名单/确认约束，
           这里不另设门槛（同样的能力两个标准反而不可预期）。
        """
        method = str(method or "").strip()
        if not method:
            return OpResult.fail("缺少 method（如 Page.captureScreenshot）",
                                 self.name)
        if not self._ext_version_ok(self.CDP_MIN_EXT_VERSION):
            return OpResult.fail(
                f"当前扩展不支持 CDP（需要扩展 v{self.CDP_MIN_EXT_VERSION}+）。"
                f"请用插件目录里的 browser-bridge/ 重新加载一次扩展"
                f"（chrome://extensions → 开发者模式 → 加载已解压的扩展）。"
                f"注意：新版本新增了「调试器」权限，浏览器会要求你确认一次。",
                self.name)
        return await self._send(self._P.CMD_CDP,
                                {"method": method, "params": params or {},
                                 "tab_id": tab_id})

    async def upload_file(self, selector: str, file_path: str) -> OpResult:
        """上传本地文件。

        扩展读不到本地磁盘路径，所以插件把文件内容分块送过去，
        扩展在页面里用 DataTransfer 构造 FileList 塞进 input[type=file]。
        路径白名单由插件侧负责（和原版无头插件一致）。
        """
        import base64
        import os
        resolved = os.path.realpath(file_path)
        if not os.path.isfile(resolved):
            return OpResult.fail(f"文件不存在或不是常规文件: {file_path}", self.name)
        try:
            size = os.path.getsize(resolved)
            if self.max_upload_bytes > 0 and size > self.max_upload_bytes:
                return OpResult.fail(
                    f"文件过大（{size} > {self.max_upload_bytes} 字节），已拒绝上传。"
                    f"如需放开请调整插件配置里的 upload_max_bytes。", self.name)
            # 逐块读、逐块编码，避免把整份文件同时拿在内存里
            name = os.path.basename(resolved)
            # ⚠️ 分块大小必须是 **3 的倍数**。
            #    base64 每 3 字节编成 4 字符；块长不是 3 的倍数时，
            #    每块末尾都会带 padding（=），独立编码的块直接拼接后
            #    整体不再是合法 base64，`atob` 会抛 InvalidCharacterError。
            #    256*1024 % 3 = 1 → 必须改。
            step = 255 * 1024          # 261120 % 3 == 0

            # ⚠️⚠️ 这里过去是"把整个文件编成 chunks、塞进**一条** WebSocket
            #       消息发出去"。那是错的，而且后果比"上传失败"严重得多：
            #
            #   uvicorn 的 ws_max_size 默认 **16 MiB**，KiraAI 没有覆盖它。
            #   实测：整条帧超过 16 MiB → 对端直接 1009 (message too big)
            #   并**关闭整个 WebSocket 连接**。也就是说一次超大上传会把
            #   连接打断，连带后面所有命令一起崩，而不只是这一次失败。
            #
            #   而且 base64 要放大 4/3，所以"文件大小"的上限其实只有
            #   ~12 MiB —— 之前配的 32MB 默认值根本发不出去。
            #
            # → 改成**按分块逐条消息发**（和下载的 MSG_CHUNK 对称）：
            #   每块单独一个 upload_chunk 消息，扩展侧边收边拼。
            #   这样单帧大小恒定（~340KB），内存和帧尺寸都与文件大小无关。
            r = await self._send(self._P.CMD_UPLOAD, {
                "selector": selector, "name": name,
                "mime": _guess_mime(name),
                # ⚠️ **不发绝对路径**：扩展侧只是把它当显示名回显
                #    （capabilities.js 里 `path: params.path || res.name`），
                #    并没有真拿它去读文件 —— 内容是由插件侧分块推过去的。
                #    让它白白经过 WS 桥（还带用户主目录结构）没有收益。
                #    返回给调用方的 path 由下面用本地的 resolved 权威填入。
                "size": size, "chunk_size": step,
                "limit": self.max_upload_bytes,
            }, timeout=max(60.0, size / (1024 * 1024) * 3))
            if not r.ok:
                return r
            d = dict(r.data or {}) if isinstance(r.data, dict) else {}
            uid = str(d.get("upload_id") or "")
            if not uid:
                return OpResult.fail(
                    "扩展没有返回 upload_id（版本不匹配？请更新扩展后重试）",
                    self.name)
            # 逐块推送。任一块失败就立刻中止，并把已收的部分丢掉。
            try:
                with open(resolved, "rb") as f:
                    idx = 0
                    while True:
                        block = f.read(step)
                        if not block:
                            break
                        chunk_b64 = base64.b64encode(block).decode()
                        cr = await self._send(self._P.CMD_UPLOAD_CHUNK, {
                            "upload_id": uid, "index": idx, "data": chunk_b64,
                        }, timeout=max(30.0, len(chunk_b64) / (256 * 1024) * 5))
                        if not cr.ok:
                            await self._send(self._P.CMD_UPLOAD_ABORT,
                                             {"upload_id": uid}, timeout=10.0)
                            return cr
                        idx += 1
            except Exception as e:
                try:
                    await self._send(self._P.CMD_UPLOAD_ABORT,
                                     {"upload_id": uid}, timeout=10.0)
                except Exception:
                    pass
                return OpResult.fail(f"上传分块发送失败: {e}", self.name)
            # 收尾：扩展侧此时才构造 File 并塞进 input[type=file]
            fr = await self._send(self._P.CMD_UPLOAD_FINISH,
                                  {"upload_id": uid}, timeout=120.0)
            if not fr.ok:
                return fr
            d2 = dict(fr.data or {}) if isinstance(fr.data, dict) else {}
            # ⚠️ 用**赋值**而不是 setdefault：上面已经不把 resolved 发给
            #    扩展了，扩展回显的是文件名（`params.path || res.name`），
            #    setdefault 会保留那个文件名 → 两个后端的返回结构不一致
            #    （headless 返回的是绝对路径）。这里以插件侧为准。
            d2["path"] = resolved
            d2.setdefault("size", size)
            return OpResult(data=d2, backend=self.name)
        except Exception as e:
            return OpResult.fail(f"上传失败: {e}", self.name)

    async def download(self, url: str, path: str) -> OpResult:
        """下载文件。

        让**扩展用用户浏览器的会话**去抓（带上已登录的 Cookie），
        分块回传给插件。

        内存行为：分块**边收边写盘**（由 BrowserBridge 的 sink 负责），
        调用方拿到的只是「写了多少字节」。所以多大的文件内存都是平的 ——
        旧实现把所有分块攒成列表再一次性返回，大文件会占住与整个文件
        （base64 后还 ×1.33）相当的内存。
        """
        import os
        import uuid as _uuid

        cmd_id = _uuid.uuid4().hex
        try:
            self._bridge.open_download_sink(cmd_id, path, limit=self.max_download_bytes)
        except Exception as e:
            return OpResult.fail(f"无法创建下载文件 {path}: {e}", self.name)
        r = await self._send(self._P.CMD_DOWNLOAD,
                             {"url": url, "max_bytes": self.max_download_bytes},
                             timeout=self.download_timeout,
                             cmd_id=cmd_id)
        if not r.ok:
            # ⚠️ 命令可能**根本没到 bridge**（扩展未连接 / 未知命令），
            #    那条路径不会走到 send_command 的 try 里，sink 就没人收 ——
            #    文件句柄留到进程退出，磁盘上多一个 0 字节文件，重试还会叠加。
            self._bridge.abort_download_sink(cmd_id)
            return r
        size = (r.data or {}).get("bytes")
        if size is None:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
        return OpResult(data={"path": path, "size": size,
                              "url": url,
                              "mime": (r.data or {}).get("mime")},
                        backend=self.name)

    async def get_info(self) -> OpResult:
        return await self._send(self._P.CMD_GET_INFO)

    async def go_back(self) -> OpResult:
        return await self._send(self._P.CMD_GO_BACK)

    async def refresh(self) -> OpResult:
        return await self._send(self._P.CMD_REFRESH)

    async def hover(self, selector: str) -> OpResult:
        return await self._send(self._P.CMD_HOVER, {"selector": selector})

    async def keyboard_type(self, text: str, delay: int = 0) -> OpResult:
        # 扩展侧没有真正的"逐字输入"，退化为 type 到当前聚焦元素：
        # 用 type 命令 + 当前焦点。这里直接走 key 系列更稳。
        return await self._send(self._P.CMD_TYPE, {"selector": ":focus", "text": text,
                                                   "clear_first": False})

    async def keyboard_press(self, key: str) -> OpResult:
        return await self._send(self._P.CMD_KEY_PRESS, {"key": key})

    async def keyboard_down_up(self, action: str, key: str) -> OpResult:
        cmd = self._P.CMD_KEY_DOWN if action == "down" else self._P.CMD_KEY_UP
        return await self._send(cmd, {"key": key})

    async def mouse_move(self, x: int, y: int, steps: int = 1) -> OpResult:
        return await self._send(self._P.CMD_MOUSE_MOVE, {"x": x, "y": y, "steps": steps})

    async def mouse_click(self, x=None, y=None, button: str = "left",
                          click_count: int = 1) -> OpResult:
        return await self._send(self._P.CMD_MOUSE_CLICK, {
            "x": x, "y": y, "button": button, "click_count": click_count})

    async def mouse_down_up(self, action: str, button: str = "left") -> OpResult:
        cmd = self._P.CMD_MOUSE_DOWN if action == "down" else self._P.CMD_MOUSE_UP
        return await self._send(cmd, {"button": button})

    async def mouse_wheel(self, delta_x: int = 0, delta_y: int = 0) -> OpResult:
        # 滚轮不改变 URL —— 与无头后端保持同样的返回形状
        r = await self._send(self._P.CMD_MOUSE_WHEEL,
                             {"delta_x": delta_x, "delta_y": delta_y})
        if not r.ok:
            return r
        d = dict(r.data or {}) if isinstance(r.data, dict) else {}
        d.pop("url", None)
        return OpResult(data=d, backend=self.name)

    async def mouse_drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
                         button: str = "left", steps: int = 10) -> OpResult:
        return await self._send(self._P.CMD_MOUSE_DRAG, {
            "start_x": start_x, "start_y": start_y, "end_x": end_x, "end_y": end_y,
            "button": button, "steps": steps}, timeout=60.0)

    async def list_files(self, dir_type: str = "downloads", limit: int = 20) -> OpResult:
        return await self._send(self._P.CMD_LIST_FILES,
                                {"dir_type": dir_type, "limit": limit})

    async def close_tab(self, tab_id: int = 0) -> OpResult:
        """关掉一个标签（chrome.tabs.remove）。

        ⚠️ 这是**唯一**能关标签的路 —— Ctrl+W / window.close() 对扩展注入的
           脚本无效（浏览器不允许）。所以别让模型去试那些。
        """
        return await self._send(self._P.CMD_CLOSE_TAB, {"tab_id": tab_id})

    async def activate_tab(self, tab_id: int = 0) -> OpResult:
        """切到某个标签（chrome.tabs.update(active)）。"""
        return await self._send(self._P.CMD_ACTIVATE_TAB, {"tab_id": tab_id})

    async def mute_tab(self, tab_id: int = 0, muted: bool = True) -> OpResult:
        """静音/取消静音某个标签（chrome.tabs.update({muted})）。"""
        return await self._send(self._P.CMD_MUTE_TAB,
                                {"tab_id": tab_id, "muted": bool(muted)})

    async def pin_tab(self, tab_id: int = 0, pinned: bool = True) -> OpResult:
        """固定/取消固定某个标签（chrome.tabs.update({pinned})）。"""
        return await self._send(self._P.CMD_PIN_TAB,
                                {"tab_id": tab_id, "pinned": bool(pinned)})

    async def clipboard(self, mode: str = "read", text: str = "",
                        tab_id: int = 0) -> OpResult:
        """剪贴板读写。⚠️ **读**要求页面在前台聚焦（浏览器隐私限制）。"""
        return await self._send(self._P.CMD_CLIPBOARD,
                                {"mode": mode, "text": text or "", "tab_id": tab_id})

    async def history(self, query: str = "", limit: int = 100,
                      days: int = 0) -> OpResult:
        """读浏览历史（chrome.history）。和书签同理：要数据，不要页面。"""
        return await self._send(self._P.CMD_HISTORY,
                                {"query": query or "", "max": limit, "days": days})

    async def bookmarks(self, query: str = "", limit: int = 200,
                        folders_only: bool = False) -> OpResult:
        """读书签**数据**（不是 edge://bookmarks 那个页面）。

        ⚠️ 为什么必须走数据接口：`edge://bookmarks` 是浏览器内部页，
           任何扩展都注入不进去（硬边界），"打开书签页去读"这条路是死的。
           用户要的是书签本身，不是那个页面 —— chrome.bookmarks 能给。
        """
        return await self._send(self._P.CMD_BOOKMARKS,
                                {"query": query or "", "max": limit,
                                 "folders_only": bool(folders_only)})

    async def debug_state(self) -> OpResult:
        return await self._send(self._P.CMD_DEBUG)

    async def start(self):
        """扩展后端不需要"启动" —— 连上了就能用。"""
        return None if self.available else "扩展未连接"

    async def cookie_get(self, url: str = "", tab_id=None) -> OpResult:
        """导出当前站点的 cookie（用于打通到无头后端的登录态）。"""
        return await self._send(self._P.CMD_COOKIE_GET, {"url": url, "tab_id": tab_id})

    async def cookie_set(self, cookies: list) -> OpResult:
        """把 cookie 写进用户浏览器。"""
        return await self._send(self._P.CMD_COOKIE_SET, {"cookies": cookies})


_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
    ".csv": "text/csv", ".json": "application/json", ".xml": "application/xml",
    ".zip": "application/zip", ".gz": "application/gzip", ".7z": "application/x-7z-compressed",
    ".doc": "application/msword", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".mp4": "video/mp4",
    ".webm": "video/webm", ".html": "text/html",
}


def _guess_mime(name: str) -> str:
    import os
    return _MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream")
def _cmp_semver(a: str, b: str) -> int:
    """简化版 semver 比较：按点分数字逐段比，非数字段按 0 算。

    返回 >0 / 0 / <0。解析不了就按"不比对方新"（保守，宁可提示更新）。
    """
    def _v(x):
        out = []
        for part in str(x).split("."):
            digits = "".join(ch for ch in part if ch.isdigit())
            out.append(int(digits) if digits else 0)
        return out
    try:
        va, vb = _v(a), _v(b)
        n = max(len(va), len(vb))
        va += [0] * (n - len(va))
        vb += [0] * (n - len(vb))
        return (va > vb) - (va < vb)
    except Exception:
        return -1
