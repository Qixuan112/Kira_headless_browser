#!/usr/bin/env python3
"""真跑一遍 browser_navigate 打开本机文件 —— 端到端行为验证（不只是静态扫描）。

## 为什么还要这一段

`filedoc` 那组是静态 + 单元层：它证明 `check_url` 放行、路径转得对、
导航入口**写了**这几行代码。但它证明不了"这些行**真的会被执行到**"。

历史教训（本项目多次）：静态检查说"代码里有"，而运行时因为分支顺序、
早退、异常吞掉等原因**根本没走到**。所以这里用**真插件实例 + 假后端**
把 `tool_navigate` 完整跑一遍，断言：

  1. 给一个本机**路径**（不是 URL），最终交给后端的 url 是规范化的 `file://`；
  2. 给 `file://` URL 时原样通过；
  3. **写操作校验真的放行**（`_check_write` 不拦）—— 这是本次 bug 的现场；
  4. 文件不存在时**不调后端**就返回可照做的错误；
  5. 打开本地文件后**不**去取正文（省 token、也没正文可取）；
  6. 关掉开关后**在到达后端之前**就被拒绝。

⚠️ 假后端只记录"收到了什么 url"，不做真实导航 —— 我们要验的是**插件侧**的
   行为（转换 / 校验 / 分支），不是浏览器。真浏览器的行为由 filedoc 的
   E/F 段和人工验证覆盖。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from ..harness import PLUGIN_DIR, section

TITLE = "打开本机文件（端到端跑一遍）"

#: 在子进程里跑：真加载插件、真调工具函数、假后端记录调用。
_PROBE = r'''
import asyncio, json, os, sys, types, tempfile
from pathlib import Path

ROOT = os.environ["KIRA_PLUGIN_DIR"]
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "regression", "stubs"))
import regression.harness as h
h.install_stubs()

pkg = types.ModuleType("hb_filedoc_e2e")
pkg.__path__ = [ROOT]
sys.modules["hb_filedoc_e2e"] = pkg

OUT = {}

# ⚠️ 顺序很关键：**先**把这个插件目录注册成一个包再导入它的子模块。
#    如果提前 `from backends.base import ...` / `import security`，
#    就会在 sys.modules 里注册**顶层**的 `backends` / `security` ——
#    之后 main.py 里的相对导入（`from .backends import ...`）解析到的是
#    **另一个**模块对象，既会抛 "relative import beyond top-level package"，
#    更隐蔽的是"改了一个、其实验的是另一个"（反向验证就成了假绿）。
#    所以下面所有内部引用一律走 `hb_filedoc_e2e.` 前缀。
import hb_filedoc_e2e.security as _sec
if os.environ.get("BLOCK_FILE") == "1":
    _sec.BLOCKED_SCHEMES = frozenset(_sec.BLOCKED_SCHEMES | {"file"})

from hb_filedoc_e2e.backends.base import OpResult


class FakeBackend:
    """假后端：只记下被要求打开的 url，不真的开浏览器。"""
    name = "headless"
    display = "无头(假)"
    is_user_browser = False

    def __init__(self):
        self.calls = []

    @property
    def available(self):
        return True

    async def close(self):
        return None

    async def start(self):
        return None

    async def navigate(self, url="", new_tab=False, tab_id=None):
        self.calls.append(("navigate", url))
        return OpResult(data={"url": url, "title": "T", "navigated": True,
                              "tab_id": 0}, backend="headless")

    async def get_info(self, tab_id=None):
        self.calls.append(("get_info", None))
        return OpResult(data={"title": "T", "url": "u"}, backend="headless")

    async def get_page(self, **kw):
        self.calls.append(("get_page", None))
        return OpResult(data={"title": "T", "url": "u", "content": "body"},
                        backend="headless")

    async def list_tabs(self):
        return OpResult(data={"tabs": [{"id": 0, "url": "about:blank",
                                        "active": True}]}, backend="headless")


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
    import hb_filedoc_e2e.main as M

    tmp = tempfile.mkdtemp(prefix="filedoc_")
    cfg = {"enabled": True, "headless": True, "headless_profile_mode": "temp",
           "browser_channel": "chrome",
           "screenshot_dir": os.path.join(tmp, "shots"),
           "download_dir": os.path.join(tmp, "dl"),
           "timeout": 30, "op_timeout": 5, "action_timeout": 3,
           "idle_close_seconds": 0}
    p = M.BrowserPlugin(FakeCtx(tmp), cfg)
    inst = p
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

    inst.router = R()
    inst._setup_notice = ""
    inst._setup_notice_done = True
    inst._attach_setup_notice = lambda t: t
    inst.return_page_after_write = False
    inst._degrade_announced = False
    inst._backend_override = None
    inst.backend_strategy = "headless"

    _tmp = Path(tmp) / "files"
    _tmp.mkdir(parents=True, exist_ok=True)
    real = _tmp / "a.png"
    real.write_bytes(b"\x89PNG\r\n\x1a\n")
    missing = str(_tmp / "nope.png")

    OUT["path_input"] = await inst.tool_navigate(Ev(), url=str(real))
    OUT["path_calls"] = [list(c) for c in be.calls]
    be.calls.clear()

    OUT["url_input"] = await inst.tool_navigate(Ev(), url="file://" + str(real))
    OUT["url_calls"] = [list(c) for c in be.calls]
    be.calls.clear()

    OUT["missing"] = await inst.tool_navigate(Ev(), url=missing)
    OUT["missing_calls"] = [list(c) for c in be.calls]
    be.calls.clear()

    inst.local_file_access = False
    OUT["off"] = await inst.tool_navigate(Ev(), url="file://" + str(real))
    OUT["off_calls"] = [list(c) for c in be.calls]
    be.calls.clear()
    inst.local_file_access = True

    OUT["web"] = await inst.tool_navigate(Ev(), url="example.com")
    OUT["web_calls"] = [list(c) for c in be.calls]
    be.calls.clear()

    # ── 相对路径：不能"文件不存在"就完事，要指出是相对路径的锅 ──────
    OUT["rel"] = await inst.tool_navigate(Ev(), url=r"definitely_not_here\x.png")
    OUT["rel_calls"] = [list(c) for c in be.calls]
    be.calls.clear()

    # ── 白名单：关掉"任意路径"后，白名单外必须被拦住，且**在到后端之前** ──
    inst.file_allow_any_path = False
    inst.file_allowed_dirs = [str(_tmp / "allowed")]
    (_tmp / "allowed").mkdir(exist_ok=True)
    allowed = _tmp / "allowed" / "ok.png"
    allowed.write_bytes(b"\x89PNG\r\n\x1a\n")
    OUT["wl_in"] = await inst.tool_navigate(Ev(), url=str(allowed))
    OUT["wl_in_calls"] = [list(c) for c in be.calls]
    be.calls.clear()
    OUT["wl_out"] = await inst.tool_navigate(Ev(), url=str(real))
    OUT["wl_out_calls"] = [list(c) for c in be.calls]
    be.calls.clear()
    inst.file_allow_any_path = True

    # ── 关掉开关时，**不得**泄漏"文件到底在不在" ────────────────────
    inst.local_file_access = False
    OUT["off_existing"] = await inst.tool_navigate(Ev(), url="file://" + str(real))
    OUT["off_missing"] = await inst.tool_navigate(Ev(), url="file://" + str(missing))
    be.calls.clear()
    inst.local_file_access = True


try:
    asyncio.run(main())
except Exception as e:
    import traceback
    OUT["error"] = traceback.format_exc()[-1200:]

print("RESULT:" + json.dumps(OUT, ensure_ascii=False))
'''


def _run_probe(block_file: bool = False) -> dict:
    env = dict(os.environ)
    env["KIRA_PLUGIN_DIR"] = str(PLUGIN_DIR)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if block_file:
        env["BLOCK_FILE"] = "1"
    p = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True,
                       text=True, env=env, timeout=240)
    for line in (p.stdout or "").splitlines():
        if line.startswith("RESULT:"):
            return json.loads(line[len("RESULT:"):])
    return {"error": ((p.stdout or "")[-600:] + (p.stderr or "")[-600:])}


def run(r) -> None:
    out = _run_probe()

    section("端到端：真插件实例 + 假后端，跑 tool_navigate")
    if out.get("error"):
        r.ok("E2E 探针能跑起来（不抛异常）", False, out["error"][-500:])
        return
    r.ok("E2E 探针能跑起来（不抛异常）", True)

    # ① 给**路径**（不是 URL）—— 这是用户/模型实际会给的形态
    _nav = [c for c in (out.get("path_calls") or []) if c[0] == "navigate"]
    r.ok("E2E·1 给本机路径时，后端收到的 url 是规范化的 file://",
         bool(_nav) and str(_nav[0][1]).startswith("file://"),
         f"后端收到={_nav[0][1] if _nav else '（没调 navigate）'}")

    # ⚠️ 这条是本次 bug 的现场：改动前 `_check_write` 会因为
    #    "不支持的页面类型（file://）" 直接返回，**后端根本收不到调用**。
    r.ok("E2E·2 写操作校验放行（后端真的被调到了 —— 改动前后端收不到）",
         bool(_nav), f"调用序列={out.get('path_calls')}")

    # ② 已经是 file:// URL
    _nav2 = [c for c in (out.get("url_calls") or []) if c[0] == "navigate"]
    r.ok("E2E·3 直接给 file:// URL 也放行", bool(_nav2),
         f"调用序列={out.get('url_calls')}")

    # ③ 文件不存在：不调后端，且错误可照做
    _miss = out.get("missing") or ""
    _miss_calls = [c for c in (out.get("missing_calls") or [])
                   if c[0] == "navigate"]
    r.ok("E2E·4 文件不存在时**不**去调浏览器，直接回一句可照做的错误",
         ("不存在" in _miss) and not _miss_calls,
         f"回话={_miss[:80]!r}；后端调用={_miss_calls}")

    # ④ 本地文件不顺手取正文（图片/视频没有正文；HTML 回源码纯烧 token）
    _p_calls = [c[0] for c in (out.get("path_calls") or [])]
    r.ok("E2E·5 打开本地文件后不调 get_page（省 token，也没正文可取）",
         "get_page" not in _p_calls, f"调用序列={_p_calls}")
    r.ok("E2E·6 但给了「要看画面用 screenshot」的指引",
         "browser_screenshot" in (out.get("path_input") or ""),
         f"回话={(out.get('path_input') or '')[:120]!r}")

    # ⑤ 开关关掉后必须在到达后端之前就被拒
    _off_calls = [c for c in (out.get("off_calls") or []) if c[0] == "navigate"]
    r.ok("E2E·7 关掉「允许打开本机文件」后，后端**完全没被调到**（拒绝在前）",
         not _off_calls, f"后端调用={_off_calls}")
    r.ok("E2E·8 拒绝的话说明了是哪个开关",
         "本机文件" in (out.get("off") or ""),
         f"回话={(out.get('off') or '')[:80]!r}")

    # ⑥ 普通网页不受影响
    _web = [c for c in (out.get("web_calls") or []) if c[0] == "navigate"]
    r.ok("E2E·9 普通网页导航不受影响（补齐 scheme 后照常打开）",
         bool(_web) and str(_web[0][1]).startswith("https://"),
         f"后端收到={_web[0][1] if _web else '（没调）'}")

    # ⑦ 相对路径：必须是"指出是相对路径"，不是笼统的"文件不存在"
    #    ⚠️ 相对路径在这里推不出正确基准（取决于 KiraAI 的启动目录），
    #       所以插件该说的是"请给完整路径"——否则用户会去反复检查一个
    #       其实写对了的文件名。
    _rel = out.get("rel") or ""
    r.ok("E2E·10 相对路径的报错点明「请给完整路径」（而不是只说文件不存在）",
         "相对路径" in _rel and "完整路径" in _rel,
         f"回话={_rel[:110]!r}")

    # ⑧ 白名单：关掉"允许任意路径"后，白名单外必须在到达后端前被拒
    _wl_in = [c for c in (out.get("wl_in_calls") or []) if c[0] == "navigate"]
    _wl_out = [c for c in (out.get("wl_out_calls") or []) if c[0] == "navigate"]
    r.ok("E2E·11 白名单内的文件放行（后端真的被调到）", bool(_wl_in),
         f"调用={out.get('wl_in_calls')}")
    r.ok("E2E·12 白名单外的文件被拒，且**在到达后端之前**",
         not _wl_out, f"调用={out.get('wl_out_calls')}")
    r.ok("E2E·13 白名单外的拒绝说明了是哪个开关（可照做）",
         "白名单" in (out.get("wl_out") or "") or "目录" in (out.get("wl_out") or ""),
         f"回话={(out.get('wl_out') or '')[:90]!r}")

    # ⑨ 关掉开关时**不得**泄漏"文件到底在不在"
    #    ⚠️ 顺序反了（先查在不在、再判策略）的话，用户关掉开关后
    #       仍然能从返回文案区分"存在"与"不存在" —— 一个已关掉的开关
    #       不该还能用来探测文件系统。
    _oe, _om = out.get("off_existing") or "", out.get("off_missing") or ""
    r.ok("E2E·14 关掉开关后，存在与不存在的文件返回**同一句话**（不泄漏磁盘信息）",
         bool(_oe) and _oe == _om,
         f"存在={_oe[:60]!r} / 不存在={_om[:60]!r}")
    r.ok("E2E·15 且那句话指向的是开关本身，不是文件不存在（否则会误导排查方向）",
         ("开关" in _oe or "配置" in _oe) and "不存在" not in _oe,
         f"回话={_oe[:80]!r}")

    # ── 反向验证 ────────────────────────────────────────────────────
    #  ⚠️ 把 file 塞回 BLOCKED_SCHEMES（= 改动前的状态）再跑同一个探针，
    #     关键在于：**这次是在真实运行路径上复现**，不是模拟。
    #     改动前用户看到的就是"后端收不到调用 + 一句不支持的页面类型"。
    section("反向验证：把 file 重新拒掉，关键断言必须翻红")
    out2 = _run_probe(block_file=True)
    if out2.get("error"):
        r.ok("M·E2E 反向探针能跑起来", False, out2["error"][-400:])
        return
    _nav_old = [c for c in (out2.get("path_calls") or []) if c[0] == "navigate"]
    r.ok("M·E2E·1 反向自检：file 被拒时后端**收不到调用**（用户报的 bug 复现）",
         not _nav_old,
         f"旧行为下后端调用={_nav_old}；回话="
         f"{(out2.get('path_input') or '')[:100]!r}")
    r.ok("M·E2E·2 反向自检：旧行为的错误文案正是用户日志里那句",
         "不支持的页面类型" in (out2.get("path_input") or ""),
         f"回话={(out2.get('path_input') or '')[:100]!r}")
    # 恢复后必须重新放行 —— 证明上面翻红真的是那个开关造成的
    r.ok("M·E2E·3 恢复 file 后重新放行（证明翻红是它引起的，不是别的因素）",
         bool(_nav), f"后端调用={_nav}")
