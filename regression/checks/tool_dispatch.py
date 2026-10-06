"""工具分发的参数传递 —— kw 不许撞名、CDP 通道端到端。

## 为什么单独一个检查（2026-10-07 线上 bug）

用户日志：

    browser_script args: {'cdp_method': 'Input.dispatchMouseEvent', ...}
    ERROR Failed to call tool 'browser_script':
          BrowserPlugin._call() got multiple values for argument 'method'

根因：`_call(op, *, for_write=False, **kw)` 的 kw 会**原样转发**给后端方法
（`fn(**kw)`）—— 后端 `cdp(method=...)` 也要一个叫 `method` 的参数，两边
撞名，Python 直接抛 TypeError。（修复：`_call` 的首参改名 `op`。）

顺着这条线扫全仓，**同类问题还有两处**（都是"写了但运行时静默失效/直接报错"）：

1. `_call("get_info", tab_id=...)`：两个后端的 `get_info()` 都不收 `tab_id` ——
   每次写操作后"顺手回带页面状态"的那次调用抛 TypeError，又被调用方的
   `try/except` 吞掉 → **"📍 现在的页面"一栏永远是空的**（静默失效）。
2. `_call("bookmarks", max=...)`：后端签名是 `bookmarks(query, limit, ...)` ——
   `max=` 是 TypeError → 书签工具**一调就失败**。

所以本检查有两层：
  · **T 组（静态）**：扫描 main.py 所有 `_call("x", ..., kw=...)` 调用点，
    kw 键必须要么被 `_call` 自己消费（for_write），要么被**两个后端**的
    目标方法签名接受。附反向自检（注入三个历史 bug，判据必须全抓到）。
  · **E 组（运行时）**：真插件实例 + 假后端（签名与真实后端逐字对齐），
    把 `browser_script`（cdp / js 两条通道）、`browser_interact(bookmarks)`、
    写操作回带页面 完整跑一遍 —— 参数名错一个字段这里就会炸。

  为什么假后端要"逐字对齐签名"：只记调用的宽松假后端（`**kw`）测不出
  参数名错配 —— 真实后端就会炸的地方它照单全收。签名对齐之后，
  "曾经 TypeError 的调用"在这层就会被复现。
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys

from ..harness import JS_DIR, PLUGIN_DIR, section, src_safe

TITLE = "工具分发参数传递（kw 撞名 / CDP 通道）"


# ══════════════════════════════════════════════════════════════════
# T 组：静态扫描
# ══════════════════════════════════════════════════════════════════

def _backend_signatures(src_text: str) -> dict:
    """{方法名: 参数名集合}；带 *args/**kwargs 的记为含 "*"。

    ⚠️ 收**文本**不收路径：调用方用 `src_safe` 读（缺文件不中断整组）。
    """
    tree = ast.parse(src_text)
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for fn in node.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
                    names.discard("self")
                    if fn.args.vararg or fn.args.kwarg:
                        names.add("*")
                    out[fn.name] = names
    return out


def _call_own_params(main_src: str) -> set:
    """从 main.py 里解析 `_call` **自己**的形参名（动态，不写死）。

    ⚠️ 动态解析很重要：历史 bug 正是"`_call` 的首参叫 method、kw 也叫
       method"。首参哪天再改名，这里必须跟着变，否则判据失准。
    """
    tree = ast.parse(main_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_call":
            names = {a.arg for a in node.args.args + node.args.kwonlyargs}
            names.discard("self")
            return names
    return set()


def _scan_call_sites(main_src: str, eb_sig: dict, hb_sig: dict) -> list:
    """扫描 `self._call("x", ..., kw=...)`：返回 [(op, kw, 说明, 行号)]。

    判定：
      · kw 撞 `_call` 的**首参**（永远按位置传入）→ 必然 "multiple values" 报错；
      · kw 是 `_call` 的其它形参（for_write）→ 它本就被 _call 消费，合法；
      · 其余 kw → 必须被**两个后端**的目标方法签名接受。
    """
    own = _call_own_params(main_src)
    tree = ast.parse(main_src)
    # 首参：按定义顺序取第一个（op），永远以位置参数传入
    first = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_call" and node.args.args:
            first = node.args.args[0].arg if node.args.args[0].arg != "self" else (
                node.args.args[1].arg if len(node.args.args) > 1 else None)
            break

    problems = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_call" and node.args
                and isinstance(node.args[0], ast.Constant)):
            continue
        op = node.args[0].value
        if not isinstance(op, str):
            continue
        for kw in node.keywords:
            if kw.arg is None:
                continue  # ** 展开交给运行时
            if kw.arg == first:
                problems.append((op, kw.arg, "撞 _call 首参（必然 TypeError）",
                                 node.lineno))
                continue
            if kw.arg in own:
                continue  # for_write 等：_call 自己消费，不转发
            for name, sig in (("extension", eb_sig), ("headless", hb_sig)):
                params = sig.get(op)
                if params is None or ("*" not in params and kw.arg not in params):
                    problems.append((op, kw.arg, f"{name} 签名不接受", node.lineno))
    return problems


def _scan_checks(r) -> None:
    section("T. 静态：_call 的 kw 与后端签名（防再犯同类撞名/错名）")
    eb_sig = _backend_signatures(src_safe("backends/extension_backend.py"))
    hb_sig = _backend_signatures(src_safe("backends/headless_backend.py"))
    main_src = src_safe("main.py")
    if not (eb_sig and hb_sig and main_src):
        r.ok("T0 关键文件可读（extension/headless/main）", False,
             "读到空内容 —— 文件缺失或改名，本组无法继续")
        return

    problems = _scan_call_sites(main_src, eb_sig, hb_sig)
    detail = "; ".join(f'_call("{p[0]}", {p[1]}=...) [{p[2]}] 行{p[3]}'
                       for p in problems[:5])
    r.ok("T1 所有 _call 的 kw 都被两个后端签名接受（且不撞 _call 形参）",
         not problems, f"问题={detail or '无'}")

    # 反向自检：注入四种形态，判据必须**全部**抓到。
    # ⚠️ 判据写瞎了（比如永远返回空）时，真 bug 会静默漏过 ——
    #    所以必须用"已知会犯的错"验证它真的会响。
    #    ⚠️ "历史形态"那条要把 _call 的首参名**也改回去**（改回 method）——
    #       真实 bug 就是这样成对的（首参叫 method + kw 也叫 method）；
    #       只注入一半的话模拟不出撞名。
    _hist = main_src.replace(
        "async def _call(self, op: str, *, for_write: bool = False, **kw):",
        "async def _call(self, method: str, *, for_write: bool = False, **kw):"
    ).replace(
        'await self._call("cdp", for_write=True',
        'await self._call("cdp", method="X", for_write=True')
    _mutants = {
        "历史形态：method 撞 _call 首参": _hist,
        "首参撞名（op=）": main_src.replace(
            'await self._call("cdp", for_write=True',
            'await self._call("cdp", op="X", for_write=True'),
        "bookmarks 传 max 而非 limit": main_src.replace(
            'limit=kw.get("amount") or 200',
            'max=kw.get("amount") or 200'),
        "get_info 传未知 kw": main_src.replace(
            'await self._call("get_info", tab_id=tab_id)',
            'await self._call("get_info", tabidx=tab_id)'),
    }
    caught = {label: bool(_scan_call_sites(src, eb_sig, hb_sig))
              for label, src in _mutants.items()}
    r.ok("T2 反向自检：四种历史/同类 bug 注入后判据都会翻红",
         all(caught.values()),
         "; ".join(f"{k}={'抓到' if v else '漏过'}" for k, v in caught.items()))


# ══════════════════════════════════════════════════════════════════
# E 组：真插件实例 + 签名对齐的假后端，端到端跑工具
# ══════════════════════════════════════════════════════════════════

_PROBE = r'''
import asyncio, json, os, sys, tempfile, types
from pathlib import Path

ROOT = os.environ["KIRA_PLUGIN_DIR"]
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "regression", "stubs"))
import regression.harness as h
h.install_stubs()

pkg = types.ModuleType("hb_tool_dispatch")
pkg.__path__ = [ROOT]
sys.modules["hb_tool_dispatch"] = pkg

from hb_tool_dispatch.backends.base import OpResult
import hb_tool_dispatch.main as M

OUT = {}


class FakeBackend:
    """签名与真实后端**逐字对齐** —— 参数名错一个这里就会炸（这正是目的）。

    ⚠️ 不要图省事写 `**kw` 收一切：那会让本组探针"永远绿"，
       而真实后端照样在用户那里 TypeError（这条检查的缘起就是它）。
    """
    name = "extension"
    display = "用户浏览器(假)"
    is_user_browser = True

    def __init__(self):
        self.calls = []

    @property
    def available(self):
        return True

    async def close(self):
        return None

    async def list_tabs(self):
        self.calls.append(("list_tabs", None))
        return OpResult(data={"tabs": [{"id": 1, "url": "https://a/",
                                        "active": True}], "tab_count": 1},
                        backend="extension")

    async def get_info(self, tab_id=None):
        self.calls.append(("get_info", tab_id))
        return OpResult(data={"title": "T", "url": "https://a/"},
                        backend="extension")

    async def get_page(self, **kw):
        self.calls.append(("get_page", None))
        return OpResult(data={"title": "T", "url": "https://a/",
                              "content": "body", "total_chars": 4, "offset": 0,
                              "returned": 4, "has_more": False,
                              "next_offset": None}, backend="extension")

    async def bookmarks(self, query="", limit=200, folders_only=False):
        self.calls.append(("bookmarks", {"limit": limit, "query": query}))
        return OpResult(data={"count": 1, "total_bookmarks": 1, "query": "",
                              "truncated": False,
                              "bookmarks": [{"title": "B站", "url": "https://b/",
                                             "folder": ""}]},
                        backend="extension")

    async def cdp(self, method, params=None, tab_id=None):
        self.calls.append(("cdp", {"method": method, "params": params}))
        return OpResult(data={"method": method, "result": {"ok": 1},
                              "url": "https://a/", "title": "T"},
                        backend="extension")

    async def execute_js(self, script):
        self.calls.append(("execute_js", script))
        return OpResult(data={"result": "2", "url": "https://a/"},
                        backend="extension")

    async def refresh(self, tab_id=None):
        self.calls.append(("refresh", {"tab_id": tab_id}))
        return OpResult(data={"url": "https://a/"}, backend="extension")

    async def click(self, selector=None, text=None, index=None, tab_id=None):
        # 签名与真实 extension_backend.click 对齐（含 tab_id）——
        # main 侧丢了 tab_id 的话这里收不到，E5 会翻红。
        self.calls.append(("click", {"selector": selector, "text": text,
                                     "index": index, "tab_id": tab_id}))
        return OpResult(data={"ok": True, "navigated": False, "url": "https://a/"},
                        backend="extension")


class FakeConfig:
    def get_config(self, key, default=None):
        return {"bot_config.agent.tool_call_timeout": 60.0}.get(key, default)


class FakeCtx:
    def __init__(self, d):
        self._d = d
        self.config = FakeConfig()

    def get_plugin_data_dir(self):
        return Path(self._d)


class Ev:
    pass


async def main():
    tmp = tempfile.mkdtemp(prefix="tool_dispatch_")
    p = M.BrowserPlugin(FakeCtx(tmp), {"enabled": True})
    be = FakeBackend()

    class R:
        def candidates(self):
            return [be]

        def by_name(self, n):
            return be

        @property
        def active(self):
            return be

        def describe(self):
            return "fake"

    p.router = R()
    p._setup_notice = ""
    p._attach_setup_notice = lambda t: t
    p.return_page_after_write = True

    OUT["cdp"] = await p.tool_script(
        Ev(), cdp_method="Input.dispatchMouseEvent",
        cdp_params={"type": "mouseMoved", "x": 640, "y": 400})
    OUT["cdp_calls"] = [list(c) for c in be.calls if c[0] == "cdp"]
    be.calls.clear()

    OUT["js"] = await p.tool_script(Ev(), script="1+1")
    OUT["js_calls"] = [list(c) for c in be.calls if c[0] == "execute_js"]
    be.calls.clear()

    OUT["bookmarks"] = await p.tool_interact(Ev(), action="bookmarks")
    OUT["bookmarks_calls"] = [list(c) for c in be.calls if c[0] == "bookmarks"]
    be.calls.clear()

    OUT["refresh"] = await p.tool_interact(Ev(), action="refresh")
    OUT["refresh_calls"] = [c[0] for c in be.calls]
    be.calls.clear()

    OUT["click"] = await p.tool_interact(
        Ev(), action="click", selector="#x", tab_id=7)
    OUT["click_calls"] = [list(c) for c in be.calls if c[0] == "click"]
    be.calls.clear()


try:
    asyncio.run(main())
except Exception as e:
    import traceback
    OUT["error"] = traceback.format_exc()[-1200:]

print("RESULT:" + json.dumps(OUT, ensure_ascii=False))
'''


def _run_probe() -> dict:
    env = dict(os.environ)
    env["KIRA_PLUGIN_DIR"] = str(PLUGIN_DIR)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True,
                       text=True, env=env, timeout=240)
    for line in (p.stdout or "").splitlines():
        if line.startswith("RESULT:"):
            return json.loads(line[len("RESULT:"):])
    return {"error": ((p.stdout or "")[-600:] + (p.stderr or "")[-600:])}


def _run_e2e(r) -> None:
    section("E. 运行时：真插件 + 签名对齐假后端，跑工具全链路")
    out = _run_probe()
    if out.get("error"):
        r.ok("E0 探针能跑起来（不抛异常）", False, out["error"][-500:])
        return
    r.ok("E0 探针能跑起来（不抛异常）", True)

    # ① CDP 通道：参数原样抵达后端、结果渲染出来
    cdp_calls = out.get("cdp_calls") or []
    cdp_ok = (bool(cdp_calls)
              and cdp_calls[0][1].get("method") == "Input.dispatchMouseEvent"
              and (cdp_calls[0][1].get("params") or {}).get("x") == 640)
    r.ok("E1 browser_script(cdp)：method/params 原样抵达后端（不再 TypeError）",
         cdp_ok and "CDP" in (out.get("cdp") or ""),
         f"后端收到={cdp_calls}；回话={(out.get('cdp') or '')[:90]!r}")

    # ② JS 通道不受影响
    js_calls = out.get("js_calls") or []
    r.ok("E2 browser_script(script)：JS 通道不受影响",
         bool(js_calls) and js_calls[0][1] == "1+1" and "2" in (out.get("js") or ""),
         f"后端收到={js_calls}")

    # ③ bookmarks：limit 参数名正确、工具真的可用
    bm_calls = out.get("bookmarks_calls") or []
    bm_ok = bool(bm_calls) and bm_calls[0][1].get("limit") == 200
    r.ok("E3 browser_interact(bookmarks)：kw 名与后端签名一致（一调就炸的 bug 不再）",
         bm_ok and "B站" in (out.get("bookmarks") or ""),
         f"后端收到={bm_calls}；回话={(out.get('bookmarks') or '')[:90]!r}")

    # ④ 写操作回带页面：get_info 真被调、标题真出现
    ref_calls = out.get("refresh_calls") or []
    ref = out.get("refresh") or ""
    r.ok("E4 写操作回带页面状态（get_info 的 tab_id 不再被吞）",
         "get_info" in ref_calls and "现在的页面" in ref,
         f"调用序列={ref_calls}；回话={(ref or '')[:110]!r}")

    # ⑤ tab_id 全链路：工具收 → _call 传 → 后端转 → 命令带（2026-10-07 补齐）
    ck_calls = out.get("click_calls") or []
    ck_ok = (bool(ck_calls) and ck_calls[0][1].get("tab_id") == 7
             and ck_calls[0][1].get("selector") == "#x")
    r.ok("E5 browser_interact(click, tab_id=7)：tab_id 一路到后端（不再落在活动标签）",
         ck_ok, f"后端收到={ck_calls}")




# ══════════════════════════════════════════════════════════════════
# F 组：CDP 扩展侧真跑探针（chrome.debugger 桩）
# ══════════════════════════════════════════════════════════════════

def _run_cdp_probe(r) -> None:
    section("F. CDP 扩展侧：attach→send→detach 纪律 / 整页与元素截图")
    probe = JS_DIR / "cdp_flow.mjs"
    node = shutil.which("node")
    if not probe.is_file():
        r.ok("F0 CDP 探针存在", False, f"缺少 {probe}")
        return
    if not node:
        r.warn("没有 node，跳过 CDP 行为验证", "安装 Node.js 后可启用")
        return
    try:
        cp = subprocess.run(
            [node, str(probe)], cwd=str(JS_DIR), capture_output=True,
            text=True, timeout=60,
            env={"PATH": os.environ.get("PATH", "") + ":/usr/bin:/bin",
                 "KIRA_PLUGIN_DIR": str(PLUGIN_DIR)})
        items = json.loads((cp.stdout or "[]").strip().splitlines()[-1])
    except Exception as e:
        r.ok("F0 CDP 探针能跑起来", False, f"{type(e).__name__}: {e}"[:160])
        return
    for it in items:
        r.ok(f"F {it.get('name', '?')}", bool(it.get("ok")),
             str(it.get("detail", ""))[:150])


def run(r) -> None:
    # 各组互不依赖：一组失败不拦其它组
    for _label, _fn in (("T", _scan_checks), ("E", _run_e2e), ("F", _run_cdp_probe)):
        try:
            _fn(r)
        except Exception as e:
            r.ok(f"{_label} 组可运行", False, f"{type(e).__name__}: {e}"[:160])
