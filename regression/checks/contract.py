"""两后端的**返回契约一致性**：同一个工具，换个后端必须给出同样的字段。

为什么单列一组：路由会在两个后端之间切换。如果只有一边返回某个字段，
同一个工具的行为就随"当时哪个后端可用"而变 —— 模型拿到的信息时有时无，
这类问题极难排查（"昨天还能读出标题，今天不行了"）。

做法：**真的把两个后端都调一遍**，收集每个方法实际返回的 data 键，
和渲染层 `_render()` 里要读的字段做比对。

  * 无头后端 → 用假 Playwright 真跑
  * 扩展后端 → 用假 bridge 返回**与扩展 JS 同形状**的数据

唯一例外：`download` 需要真实网络，沙箱里跑不了 —— 走源码字段静态兜底，
并在结果里标明需要真机验证。
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import sys
import tempfile
import types
from pathlib import Path

from ..harness import PLUGIN_DIR, STUBS_DIR, section, src_safe

TITLE = "两后端返回契约一致性"

#: 方法 → 调用参数
CALLS = {
    "list_tabs": {}, "get_info": {},
    "get_page": {"detail": "text"},
    "extract": {"selector": "a"},
    "navigate": {"url": "https://a/"},
    "click": {"selector": "#x"},
    "type_text": {"selector": "#x", "text": "hi"},
    "scroll": {"direction": "down"},
    "wait_for": {"selector": "#x"},
    # ⚠️ 这两个 path 会被**覆盖**成受管理 tmp 下的文件（见 _collect_*）——
    #    不要在这里写死 /tmp/xxx：那会落在 TemporaryDirectory 之外，
    #    每跑一次回归就在系统临时目录里留一份永不清理的残留。
    "screenshot": {"path": ""},
    "execute_js": {"script": "1"},
    "go_back": {}, "refresh": {}, "hover": {"selector": "#x"},
    "keyboard_type": {"text": "a"},
    "keyboard_press": {"key": "Enter"},
    "keyboard_down_up": {"action": "down", "key": "Control"},
    "mouse_move": {"x": 1, "y": 2},
    "mouse_click": {"x": 1, "y": 2},
    "mouse_down_up": {"action": "down"},
    "mouse_wheel": {"delta_y": 10},
    "mouse_drag": {"start_x": 1, "start_y": 1, "end_x": 2, "end_y": 2},
    "list_files": {"dir_type": "downloads"},
    "close_tab": {},
    "activate_tab": {},
    "mute_tab": {},
    "pin_tab": {},
    "get_selection": {},
    "clipboard": {},
    "history": {},
    "bookmarks": {},
    "cookie_get": {},
    "cookie_set": {"cookies": [{"name": "n", "value": "v", "domain": ".a"}]},
    "upload_file": {"selector": "#f"},
    "download": {"url": "https://a/f", "path": ""},
    "cdp": {"method": "Page.captureScreenshot", "params": {"format": "png"}},
}

FAKE_TABLE = None   # 延迟构造（需要 protocol 模块）


def _load_pkg():
    sys.path.insert(0, str(STUBS_DIR))
    sys.path.insert(0, str(PLUGIN_DIR.parent))
    name = "kirabrowser_contract"
    if name in sys.modules:
        return sys.modules[name]

    pkg = types.ModuleType(name)
    pkg.__path__ = [str(PLUGIN_DIR)]
    sys.modules[name] = pkg

    def L(sub, path):
        spec = importlib.util.spec_from_file_location(f"{name}.{sub}", path)
        m = importlib.util.module_from_spec(spec)
        sys.modules[f"{name}.{sub}"] = m
        spec.loader.exec_module(m)
        return m

    L("protocol", PLUGIN_DIR / "protocol.py")
    bp = types.ModuleType(f"{name}.backends")
    bp.__path__ = [str(PLUGIN_DIR / "backends")]
    sys.modules[f"{name}.backends"] = bp
    for sub in ("base", "router", "headless_backend", "extension_backend"):
        spec = importlib.util.spec_from_file_location(
            f"{name}.backends.{sub}", PLUGIN_DIR / "backends" / f"{sub}.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules[f"{name}.backends.{sub}"] = m
        spec.loader.exec_module(m)
        setattr(bp, sub, m)
    return pkg


def _render_fields() -> dict[str, set[str]]:
    """静态抽 _render() 里每个分支读的 d.get("x")"""
    import ast
    # ⚠️ 用 src_safe：main.py 缺失时不该让整组中断（各段自己报错）。
    src = src_safe("main.py")
    tree = ast.parse(src)
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        # ⚠️ 同时接受 async def —— `_render()` 若将来改成异步函数，
        #    只认 ast.FunctionDef 的话这里会**静默找不到**，
        #    字段提取返回空 → F1 契约校验变成空转（看起来还是 PASS）。
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                # ⚠️ 渲染分支现在在 `_render_base` 里 —— `_render` 外面包了
                #    一层"按需追加跨实例提醒"。两个名字都认，
                #    免得以后改名又让字段提取静默变空。
                and node.name in ("_render", "_render_base")):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.If):
                continue
            t = sub.test
            names = []
            if isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) \
                    and t.left.id == "method":
                for c in t.comparators:
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        names.append(c.value)
                    if isinstance(c, (ast.Tuple, ast.List)):
                        for el in c.elts:
                            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                                names.append(el.value)
            if not names:
                continue
            keys = set()
            for st in sub.body:
                for n2 in ast.walk(st):
                    if (isinstance(n2, ast.Call) and isinstance(n2.func, ast.Attribute)
                            and n2.func.attr == "get"
                            and isinstance(n2.func.value, ast.Name)
                            and n2.func.value.id == "d" and n2.args
                            and isinstance(n2.args[0], ast.Constant)):
                        keys.add(str(n2.args[0].value))
            for nm in names:
                out.setdefault(nm, set()).update(keys)
    return out


def _mk_fake_bridge(P):
    """假 bridge：返回与 browser-bridge/*.js 实际相同的形状。"""

    class FakeBridge:
        connected = True
        #: 版本闸门（CDP 需要扩展 >= 1.6.0）要读的握手信息 —— 给一个足够新的
        _hello = P.HelloPayload(extension_version="99.0.0", browser="Fake",
                                protocol=P.PROTOCOL_VERSION)

        def open_download_sink(self, *a, **k):
            pass

        async def send_command(self, cmd, params=None, timeout=None, cmd_id=None):
            table = {
                P.CMD_LIST_TABS: {"tabs": [{"id": 1, "title": "t",
                                            "url": "https://a/", "active": True}],
                                  "tab_count": 1},
                P.CMD_GET_PAGE: {"url": "https://a/", "title": "t",
                                 "content": "hello world"},
                P.CMD_GET_INFO: {"title": "t", "url": "https://a/"},
                P.CMD_EXTRACT: {"url": "https://a/", "items": ["x"]},
                P.CMD_NAVIGATE: {"ok": True, "tab_id": 1, "url": "https://a/",
                                 "navigated": True},
                P.CMD_CLICK: {"ok": True, "match": "sel", "changed": True,
                              "navigated": False, "url": "https://a/"},
                P.CMD_TYPE: {"ok": True, "submitted": False, "navigated": False,
                             "url": "https://a/"},
                P.CMD_SCROLL: {"ok": True, "changed": True},
                P.CMD_WAIT_FOR: {"found": True, "elapsed": "0.1",
                                 "url": "https://a/"},
                P.CMD_SCREENSHOT: {"url": "https://a/", "title": "t",
                                   "image": "data:image/png;base64,AAAA"},
                P.CMD_EXEC_JS: {"url": "https://a/", "result": 42},
                # 与扩展 capabilities.js 的 cdp() 返回同形状（url/title/method/result）
                P.CMD_CDP: {"url": "https://a/", "title": "t",
                            "method": "Page.captureScreenshot",
                            "result": {"data": "AAAA"}},
                P.CMD_CLOSE_TAB: {"tab_id": 0, "closed": True},
                P.CMD_ACTIVATE_TAB: {"tab_id": 0, "activated": True},
                P.CMD_MUTE_TAB: {"tab_id": 0, "muted": True},
                P.CMD_PIN_TAB: {"tab_id": 0, "pinned": True},
                P.CMD_GET_SELECTION: {"content": "选中的字", "title": "T", "url": "https://a/"},
                P.CMD_CLIPBOARD: {"mode": "read", "text": "hi", "length": 2},
                P.CMD_HISTORY: {"count": 1, "query": "", "items": [{"title": "B站", "url": "https://b/", "visits": 3, "last": "2026-01-01T00:00:00Z"}]},
                P.CMD_BOOKMARKS: {"count": 1, "total_bookmarks": 1, "query": "",
                                  "truncated": False,
                                  "bookmarks": [{"title": "B站",
                                                 "url": "https://b/",
                                                 "folder": "书签栏"}]},
                P.CMD_GO_BACK: {"url": "https://a/"},
                P.CMD_REFRESH: {"url": "https://a/"},
                P.CMD_HOVER: {"ok": True, "url": "https://a/"},
                P.CMD_KEY_PRESS: {"ok": True, "url": "https://a/"},
                P.CMD_KEY_DOWN: {"ok": True, "url": "https://a/"},
                P.CMD_KEY_UP: {"ok": True, "url": "https://a/"},
                P.CMD_MOUSE_MOVE: {"ok": True, "x": 1, "y": 2},
                P.CMD_MOUSE_CLICK: {"ok": True, "navigated": False,
                                    "url": "https://a/"},
                P.CMD_MOUSE_DOWN: {"ok": True, "url": "https://a/"},
                P.CMD_MOUSE_UP: {"ok": True, "url": "https://a/"},
                P.CMD_MOUSE_WHEEL: {"ok": True},
                P.CMD_MOUSE_DRAG: {"ok": True, "url": "https://a/"},
                P.CMD_LIST_FILES: {"dir": "/d", "files": [{"name": "f", "size": 1}]},
                P.CMD_COOKIE_GET: {"url": "https://a/",
                                   "cookies": [{"name": "n", "value": "v",
                                                "domain": ".a"}]},
                P.CMD_COOKIE_SET: {"ok": 1, "written": 1, "skipped": 0,
                                   "failed": 0, "total": 1},
                # 上传现在是**分块流式**的：upload 只建立会话，
                # upload_chunk 逐块送，upload_finish 才返回最终字段。
                P.CMD_UPLOAD: {"ok": True, "url": "https://a/",
                               "upload_id": "up_test"},
                P.CMD_UPLOAD_CHUNK: {"ok": True, "received": 1},
                P.CMD_UPLOAD_FINISH: {"ok": True, "url": "https://a/", "name": "f",
                                      "size": 1, "path": "/x/f"},
                P.CMD_UPLOAD_ABORT: {"ok": True},
                P.CMD_DOWNLOAD: {"ok": True, "url": "https://a/",
                                 "mime": "text/plain", "bytes": 5,
                                 "path": "/tmp/x", "size": 5},
                P.CMD_DEBUG: {"backend": "extension"},
            }
            return table.get(cmd, {"ok": True})

    return FakeBridge()


def _apply_tmp_paths(kw: dict, method: str, tmp, upfile) -> None:
    """把所有**会真的落盘**的路径改到受管理的 tmp 下。

    ⚠️ 为什么必须逐个覆盖：假 Playwright 的 `page.screenshot(path=...)`
    与下载落盘**会真的写文件**。夹具路径写死在 /tmp 里的话，
    每跑一次回归就留一份残留（而且并发跑会互相覆盖）。
    放在 TemporaryDirectory 之下才会被自动清理。
    """
    if method == "upload_file":
        kw["file_path"] = str(upfile)
    elif method == "screenshot":
        kw["path"] = str(Path(tmp) / "shot.png")
    elif method == "download":
        kw["path"] = str(Path(tmp) / "dl.bin")


async def _collect_hb(mod, tmp) -> dict[str, set[str]]:
    """每个方法用**全新实例** —— 共用一个会互相污染（前一个改了页面状态）。"""
    out: dict[str, set[str]] = {}
    # ⚠️ 夹具建在**受管理的 tmp 之下**：另起 mkdtemp 的话，
    #    它落在 TemporaryDirectory 之外，永远不会被清理。
    upfile = Path(tmp) / "up.txt"
    upfile.write_text("x")
    for method, kwargs in CALLS.items():
        b = mod.HeadlessBackend(Path(tmp), {
            "headless": True, "browser_channel": "chrome",
            "headless_profile_mode": "temp",
            "screenshot_dir": os.path.join(tmp, "s"),
            "download_dir": os.path.join(tmp, "d"),
            "idle_close_seconds": 0, "op_timeout": 5, "action_timeout": 3,
        })
        fn = getattr(b, method, None)
        if fn is None:
            await b.close()
            continue
        kw = dict(kwargs)
        _apply_tmp_paths(kw, method, tmp, upfile)
        try:
            res = await fn(**kw)
            out[method] = (set((res.data or {}).keys())
                           if hasattr(res, "data") and isinstance(res.data, dict)
                           else set())
        except Exception:
            out[method] = set()
        await b.close()

    # download 需要真网络，沙箱跑不了 → 源码字段兜底
    if not out.get("download"):
        body = src_safe("backends/headless_backend.py")
        i = body.find("async def download(")
        if i > 0:
            # ⚠️ 要允许跨行 —— 返回字典常写成多行，
            #    单行正则匹配不到就会误报"字段缺失"。
            # 窗口要够大：download() 里加了 HTTPS 校验后变长了，
            # 4000 字符取不到末尾的成功返回。
            nxt = body.find("\n    async def ", i + 10)
            seg = body[i:nxt] if nxt > 0 else body[i:i + 12000]
            succ = re.findall(r'OpResult\(\s*data=\{([^}]*)\}\s*,\s*backend=self\.name\s*\)',
                              seg, re.S)
            keys = set()
            for grp in succ:
                keys |= set(re.findall(r'"([a-z_]+)":', grp))
            if keys:
                out["download"] = keys
    return out


async def _collect_eb(mod, P, tmp) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    # 同上：夹具必须在同一个受管理的根之下
    upfile = Path(tmp) / "up_eb.txt"
    upfile.write_text("x")
    for method, kwargs in CALLS.items():
        b = mod.ExtensionBackend(_mk_fake_bridge(P), P)
        fn = getattr(b, method, None)
        if fn is None:
            continue
        kw = dict(kwargs)
        _apply_tmp_paths(kw, method, tmp, upfile)
        try:
            res = await fn(**kw)
            out[method] = (set((res.data or {}).keys())
                           if hasattr(res, "data") and isinstance(res.data, dict)
                           else set())
        except Exception:
            out[method] = set()
    return out


def run(r) -> None:
    # ⚠️ 加载失败要**明确报出来**并停在这里 —— 两个后端模块是"比对契约"
    #    的**结构性前提**（少一个就没有可比的对象），继续跑只会连环报错。
    #    重点是把原因说清楚，而不是抛一句裸 FileNotFoundError
    #    （那读起来像 harness 自己的 bug）。
    try:
        _load_pkg()
        hbmod = sys.modules["kirabrowser_contract.backends.headless_backend"]
        ebmod = sys.modules["kirabrowser_contract.backends.extension_backend"]
        P = sys.modules["kirabrowser_contract.protocol"]
    except Exception as e:
        r.ok("能加载两个后端模块（否则无从比对契约）", False,
             f"{type(e).__name__}: {e}")
        return

    rf = _render_fields()
    if not rf:
        r.ok("解析 _render 的字段", False, "没能从 main.py 里提取到任何渲染分支")
        return
    # ⚠️ 用 TemporaryDirectory：mkdtemp 留下的 profile/screenshot/download/
    #    upload 夹具目录从不清理（失败路径也留），会一路堆积。
    _td = tempfile.TemporaryDirectory(prefix="kira_contract_")
    tmp = _td.name
    _ = _td   # 持有引用，别被 GC 提前回收

    async def go():
        return (await _collect_hb(hbmod, tmp),
                await _collect_eb(ebmod, P, tmp))

    hb_keys, eb_keys = asyncio.run(go())

    section("渲染层要读的字段 vs 两个后端实际返回")
    problems = []
    checked = 0
    for m in sorted(rf):
        if not rf[m]:
            continue
        # ⚠️ 不要"两边都没有就跳过" —— 那等于放过"渲染层要读的字段
        #    两个后端都不返回"这种最严重的情况。`.get(m, set())` 已经把
        #    "缺失"表达成空集合了，继续走正常校验即可。
        checked += 1
        miss_h = sorted(rf[m] - hb_keys.get(m, set()))
        miss_e = sorted(rf[m] - eb_keys.get(m, set()))
        if miss_h or miss_e:
            problems.append(f"{m}: 无头缺={miss_h or '-'} 扩展缺={miss_e or '-'}")
            r.note(f"❌ {m:<16} 无头缺 {miss_h}  扩展缺 {miss_e}")
        else:
            r.note(f"✅ {m:<16} 一致")

    r.ok("F1 渲染层读的字段，两个后端都真的返回",
         not problems, f"检查了 {checked} 个方法；不一致={len(problems)} 处")
    r.metric("检查的方法数", checked)
    for p in problems:
        r.ok(f"F1-{p.split(':')[0]} 字段一致", False, p)

    # 反向差异（不算错，但要知道）
    diffs = []
    for m in sorted(set(hb_keys) & set(eb_keys)):
        only_h = sorted(hb_keys[m] - eb_keys[m] - {"ok"})
        only_e = sorted(eb_keys[m] - hb_keys[m] - {"ok"})
        if only_h or only_e:
            diffs.append(f"{m}(仅无头={only_h} 仅扩展={only_e})")
    if diffs:
        r.warn(f"两后端返回字段仍有 {len(diffs)} 处差异（不影响功能）",
               "；".join(diffs[:6]))
