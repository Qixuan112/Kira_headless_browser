"""A fake, semantics-faithful Playwright used to probe the plugin's lifecycle.

Models the parts that matter for leak analysis:
  * context.pages is a LIVE list of every page in the context
  * a popup (target=_blank / window.open) appends to it
  * page.close() removes that page; context.close() removes all
  * pages can die on their own (user closes the tab)

Everything is counted in STATS so the test can assert on it.
"""

from urllib.parse import urlsplit

STATS = {
    "pages_created": 0,
    "pages_closed": 0,
    "contexts_created": 0,
    "contexts_closed": 0,
    "browsers_launched": 0,
    "playwright_started": 0,
    "playwright_stopped": 0,
}

#: set to True to make every launch path fail, so we can exercise level-4 fallback
ALL_LAUNCHES_FAIL = False


class FakePage:
    def __init__(self, ctx, url="about:blank"):
        self._ctx = ctx
        self._url = url
        self._closed = False
        self._title = "fake"
        self._timeout = None
        STATS["pages_created"] += 1

    # --- plugin-facing surface -------------------------------------------
    @property
    def url(self):
        if self._closed:
            raise RuntimeError("Target page, context or browser has been closed")
        return self._url

    async def title(self):
        if self._closed:
            raise RuntimeError("Target page, context or browser has been closed")
        return self._title

    async def goto(self, url, **kw):
        if self._closed:
            raise RuntimeError("Target page, context or browser has been closed")
        self._url = url
        return None

    def set_default_timeout(self, ms):
        self._timeout = ms

    def is_closed(self):
        """真实 Playwright 的 Page.is_closed() 是同步方法"""
        return self._closed

    # ── 以下为契约校验需要的页面动作（保持"能做，但有真实语义"）──
    def _alive(self):
        if self._closed:
            raise RuntimeError("Target page, context or browser has been closed")

    async def click(self, selector=None, **kw):
        self._alive()
        return None

    async def fill(self, selector, value, **kw):
        self._alive()
        return None

    async def type(self, selector, text, **kw):
        self._alive()
        return None

    async def press(self, selector, key, **kw):
        self._alive()
        return None

    async def hover(self, selector, **kw):
        self._alive()
        return None

    async def wait_for_selector(self, selector, **kw):
        self._alive()
        return object()

    async def wait_for_function(self, expr, **kw):
        self._alive()
        return None

    async def inner_text(self, selector, **kw):
        self._alive()
        return "fake body text"

    async def content(self):
        self._alive()
        return "<html><body>fake</body></html>"

    async def screenshot(self, path=None, **kw):
        self._alive()
        if path:
            with open(path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")
        return b""

    async def go_back(self, **kw):
        self._alive()
        return None

    async def reload(self, **kw):
        self._alive()
        return None

    def locator(self, sel):
        page = self

        class _Loc:
            @property
            def first(self):
                return self

            def nth(self, i):
                return self

            async def click(self, **kw):
                page._alive()
                return None

        return _Loc()

    def get_by_text(self, text, exact=False):
        return self.locator(text)

    async def query_selector(self, selector):
        self._alive()

        class _El:
            async def screenshot(self, path=None, **kw):
                if path:
                    with open(path, "wb") as f:
                        f.write(b"\x89PNG\r\n\x1a\n")
                return b""

            async def inner_text(self):
                return "element text"

        return _El()

    async def set_input_files(self, selector, files, **kw):
        self._alive()
        return None

    @property
    def keyboard(self):
        page = self

        class _K:
            async def type(self, text, delay=0):
                page._alive()

            async def press(self, key):
                page._alive()

            async def down(self, key):
                page._alive()

            async def up(self, key):
                page._alive()

        return _K()

    @property
    def mouse(self):
        page = self

        class _M:
            async def move(self, x, y, steps=1):
                page._alive()

            # ⚠️ 必须和真实 Playwright 一样收 click_count：
            #    HeadlessBackend.mouse_click 会传它，桩不收就会 TypeError，
            #    把"双击"这条路完全挡住。
            async def down(self, button="left", click_count=1):
                page._alive()

            async def up(self, button="left", click_count=1):
                page._alive()

            async def wheel(self, dx, dy):
                page._alive()

            async def click(self, x, y, **kw):
                page._alive()

        return _M()

    async def evaluate(self, script, arg=None):
        """真实 Playwright 的 evaluate 支持传参（script, arg）"""
        if self._closed:
            raise RuntimeError("Target page, context or browser has been closed")
        # 针对几个常见脚本给出"像真的"返回值，方便上层组装 data
        if isinstance(script, str) and "querySelectorAll" in script:
            return ["item1", "item2"]
        # 取单个选择器文本（get_page(detail=..., selector=...) 用的脚本）
        if isinstance(script, str) and "querySelector(sel)" in script:
            return "selector-text"
        if isinstance(script, str) and "querySelectorAll" not in script and "scrollY" in script:
            return 100
        return 1

    async def close(self):
        if self._closed:
            return
        self._closed = True
        STATS["pages_closed"] += 1
        if self in self._ctx.pages:
            self._ctx.pages.remove(self)

    # --- events -----------------------------------------------------------
    def _die_by_itself(self):
        """Simulate the user closing this tab in a real browser window.

        这也是一次"页面关闭"，必须计入 STATS —— 契约是"每次关闭都计数"，
        漏了会让基于计数的断言失准。
        """
        if self._closed:
            return
        self._closed = True
        STATS["pages_closed"] += 1
        if self in self._ctx.pages:
            self._ctx.pages.remove(self)

    def _open_popup(self, url="https://popup.example"):
        """Simulate a target=_blank / window.open from this page.

        真实 Playwright 会在页面打开时触发 context 的 "page" 事件，
        插件正是靠它回收弹窗 —— 这里必须同样触发。
        """
        p = FakePage(self._ctx, url)
        self._ctx.pages.append(p)
        self._ctx._fire("page", p)
        return p


class FakeContext:
    def __init__(self, browser=None, **kw):
        self.pages = []
        self._browser = browser
        self._closed = False
        self._handlers = {}
        #: 存进来的 cookie（add_cookies 写、cookies() 读）。
        #  ⚠️ 必须真的存 —— 空实现会让"加 cookie 再读回来"的链路测不到。
        self._cookies = []
        #: 保住 _fire() 派发出去的异步回调，避免被 GC（见 _fire）
        self._bg_tasks = set()
        STATS["contexts_created"] += 1

    @property
    def browser(self):
        return self._browser

    def on(self, event, fn):
        self._handlers.setdefault(event, []).append(fn)

    def _fire(self, event, *args):
        """同步派发事件；回调是 async 就丢进事件循环。"""
        import asyncio
        for fn in self._handlers.get(event, []):
            r = fn(*args)
            if asyncio.iscoroutine(r):
                # ⚠️ 必须**留住 task 的强引用**：ensure_future 的返回值一旦
                #    无人引用，事件循环只持弱引用 → task 可能在异步处理器
                #    跑完前就被 GC 掉，让弹窗清理/生命周期检查变得不稳定。
                t = asyncio.ensure_future(r)
                self._bg_tasks.add(t)
                t.add_done_callback(self._bg_tasks.discard)

    async def new_page(self):
        p = FakePage(self)
        self.pages.append(p)
        return p

    async def add_cookies(self, cookies):
        """把 cookie 存进 context —— **要真的存**。

        ⚠️ 原来这里 `return None`、`cookies()` 永远返回 `[]`，
        于是"加了 cookie 再读回来"这条链路**测不到**：
        插件里任何依赖"读完确认写入成功"的逻辑（比如 cookie 导入、
        导出后再导入的往返）在测试里都是空转，全绿但没验证。
        这里存一份副本，`cookies()` 返回**副本**（不暴露内部列表）。
        """
        self._cookies.extend(list(cookies or []))
        return None

    async def new_cdp_session(self, page):
        """最小 CDP session stub：记录 send 调用，回一个可辨认的结果。"""
        ctx = self

        class _CDPSession:
            def __init__(self):
                self.calls = []
                self.detached = False

            async def send(self, method, params=None):
                self.calls.append((method, dict(params or {})))
                return {"stub": True, "method": method,
                        "echo": dict(params or {})}

            async def detach(self):
                self.detached = True

        ctx._last_cdp = _CDPSession()
        return ctx._last_cdp

    async def cookies(self, url=None):
        """返回已存 cookie 的**副本**（外部改动不影响内部状态）。

        `url` 参数按"同域或子域"过滤（够用的简化实现）：
        不传就返回全部。
        """
        if not url:
            return [dict(c) for c in self._cookies]
        # ⚠️ 不能手切：`http://[::1]:8080/` 按 `:` 切会得到 `[`，
        #    于是"[::1] 的 cookie"永远匹配不上，桩就悄悄返回了错的集合。
        #    ⚠️ 这里**不能**用 `except Exception` 兜底 —— 那样一来函数名写错
        #    （如 urlsplit 忘了导入）会伪装成"过滤失败 → 返回全部"，
        #    比不过滤更糟，而且套件照样绿。只认"根本不是字符串"这一种。
        try:
            host = urlsplit(url).hostname or ""
        except (TypeError, ValueError):
            return [dict(c) for c in self._cookies]
        out = []
        for c in self._cookies:
            dom = str(c.get("domain") or "").lstrip(".")
            if dom and (host == dom or host.endswith("." + dom)):
                out.append(dict(c))
        return out

    async def close(self):
        if self._closed:
            return
        self._closed = True
        STATS["contexts_closed"] += 1
        for p in list(self.pages):
            p._closed = True
            STATS["pages_closed"] += 1
        self.pages.clear()


class FakeBrowser:
    def __init__(self):
        STATS["browsers_launched"] += 1
        self._closed = False

    async def new_context(self, **kw):
        return FakeContext(browser=self)

    async def close(self):
        self._closed = True


class _Chromium:
    async def launch(self, **kw):
        if ALL_LAUNCHES_FAIL:
            raise RuntimeError("fake: launch failed")
        return FakeBrowser()

    async def launch_persistent_context(self, user_data_dir, **kw):
        if ALL_LAUNCHES_FAIL:
            raise RuntimeError("fake: persistent launch failed")
        # ⚠️ 真实的 `launch_persistent_context` 返回的上下文里**已经有一张
        #    页面**（初始 about:blank）。桩原来给的是空 pages，于是
        #    `_replace_page()` 在"复用现有标签"和"新建"之间走了**另一条分支**
        #    —— 生产上第一次是**复用初始页**，桩里却是新建，
        #    "页面复用/回收"相关的检查就在一个假世界里验。
        context = FakeContext(browser=None, **kw)
        context.pages.append(FakePage(context))
        return context


class _Playwright:
    def __init__(self):
        self.chromium = _Chromium()

    async def stop(self):
        STATS["playwright_stopped"] += 1


class _Starter:
    async def start(self):
        STATS["playwright_started"] += 1
        return _Playwright()


def async_playwright():
    return _Starter()
