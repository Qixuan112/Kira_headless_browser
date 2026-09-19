"""一步到位：写操作要**连页面结果一起**返回；无头后端要有安全 UA。

两件事放一起，是因为它们回答的是同一类问题 —— "bot 用起来顺不顺"：
  · 调用次数：框架每轮只给 5 次工具调用，"点一下 → 再看一眼"各占一次就太快用光
  · 环境可信度：无头浏览器默认 UA 带 Headless，B站这类站点会直接拦
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..harness import PLUGIN_DIR, section, src_safe

TITLE = "一步到位（动作带结果 / 安全 UA）"

sys.path.insert(0, str(PLUGIN_DIR.parent))


def run(r) -> None:
    section("一步到位")
    main = src_safe("main.py")
    head = src_safe("backends/headless_backend.py")

    # ── S1：写操作后必须把页面内容一起带回来 ──────────────────────────
    # ⚠️ 用户明确要求："尽量大部分都一步到位，动作结构和页面结果这种一起返回"。
    #    框架有 `bot_config.agent.max_tool_calls_per_turn`（默认 **5**），
    #    "点一下 → 再看一眼"各占一次的话 5 次只够两轮半，bot 还没干完就被
    #    限流（日志里满屏 Tool call limit exceeded ... 'browser_page'）。
    #    ⚠️ 而**扩展内部命令不计次**（计的是 LLM 发起的工具调用），
    #       所以在 `_call` 里顺手取页面是白赚的 —— 必须落在那里，
    #       才能一处覆盖所有写操作（也才不会"新加个工具就忘了带结果"）。
    _bad1 = []
    if "_with_page_after" not in main:
        _bad1.append("没有'带页面一起返回'的实现")
    if "for_write and self.return_page_after_write" not in main:
        _bad1.append("没有挂在 for_write 上（新加的写工具会漏掉）")
    if 'cfg.get("return_page_after_write"' not in main:
        _bad1.append("没有开关（用户想省 token 时关不掉）")
    if '"return_page_after_write"' not in src_safe("schema.json"):
        _bad1.append("schema 里没有这一项")
    r.ok("S1 写操作后一并返回页面（挂在 _call 上，覆盖所有写工具）", not _bad1,
         f"问题={_bad1 or '无'}")

    # ── S2：无头后端必须有**不带 Headless**的安全 UA ───────────────────
    #    Playwright 自带浏览器的默认 UA 里带 `HeadlessChrome`，
    #    B站/知乎这类站点会据此直接拦（表现为"页面能开但内容空/弹验证"）。
    _bad2 = []
    if "_safe_default_ua" not in head:
        _bad2.append("没有默认 UA")
    if "Headless" not in head:
        _bad2.append("没说清为什么要去掉 Headless")
    r.ok("S2 无头后端默认给安全 UA（不含 Headless，能正常上 B站）", not _bad2,
         f"问题={_bad2 or '无'}")

    # ── S3：行为验证 —— 真造一个无头后端，看 UA 到底是什么 ─────────────
    #    只查"代码里有没有"会被自己骗；这里直接把对象建出来看值。
    try:
        from . import runtime_behavior
        hb = runtime_behavior._load_plugin()
        b = hb.HeadlessBackend(Path("/tmp/_probe/plugin_data/hb"), {})
        ua = b.user_agent or ""
        _ok3 = ua and "Headless" not in ua and "Mozilla/" in ua
        r.ok("S3 实测默认 UA 不含 Headless、且像真实浏览器", bool(_ok3), f"UA={ua!r}")
        # 用户自己配了就听他的
        b2 = hb.HeadlessBackend(Path("/tmp/_probe/plugin_data/hb"),
                                {"user_agent": "Mozilla/5.0 (custom)"})
        r.ok("S4 用户填了 user_agent 就优先用他的",
             b2.user_agent == "Mozilla/5.0 (custom)", f"实际={b2.user_agent!r}")

    except Exception as e:
        r.warn("S3/S4 真造无头后端看 UA（需要桩环境）", f"{type(e).__name__}: {e}")

    # ── S5 内部页（edge://）的报错必须**可照做** ────────────────────────
    #    ⚠️ 原来只说"不允许注入脚本，请先切换到普通网页" —— 模型只能放弃，
    #       然后回用户一句"扩展没权限访问"，看着像缺陷。
    #       真实情况是**硬边界**（`<all_urls>` 也不含 chrome://），开不了；
    #       但有两条能走通的路必须写出来：截图（不需要注入）+ 书签数据接口。
    _sh = src_safe("browser-bridge/shared.js")
    _bad5 = []
    if "硬边界" not in _sh:
        _bad5.append("没说清这是浏览器的硬边界（不是权限没开）")
    if "browser_screenshot" not in _sh:
        _bad5.append("没告诉模型'截图对内部页照样有效'")
    if "bookmarks" not in _sh:
        _bad5.append("没告诉模型'书签数据有接口'")
    r.ok("S5 内部页报错可照做（硬边界 + 截图 + 书签接口）", not _bad5,
         f"问题={_bad5 or '无'}")

    # ── S6 书签能力与权限 ───────────────────────────────────────────────
    import json as _json
    _mf = _json.loads(src_safe("browser-bridge/manifest.json"))
    _bad6 = []
    if "bookmarks" not in (_mf.get("permissions") or []):
        _bad6.append("manifest 没申请 bookmarks 权限")
    if "async function bookmarks" not in src_safe("browser-bridge/capabilities.js"):
        _bad6.append("capabilities.js 里没有 bookmarks 实现")
    if '"bookmarks"' not in src_safe("main.py"):
        _bad6.append("browser_interact 里没接这个 action")
    r.ok("S6 书签数据能力可用（权限 + 实现 + action 都齐）", not _bad6,
         f"问题={_bad6 or '无'}")

    # ── S7 扩展能执行的命令，插件必须**够得着** ────────────────────────
    #    ⚠️ 这一类 bug 用户抓到过两次：
    #       · close_tab / activate_tab —— 扩展实现了 31 个命令，插件只调了 12 个
    #       · get_selection —— 扩展一直有，插件从没调用
    #       从 bot 的视角看就是"这个能力不存在"，它只能去试 Ctrl+W 这种歪招。
    #    判据：协议里的每个命令，要么 main.py 里调得到，要么在下面的
    #    **内部子步骤**白名单里（那些是别的命令内部用的，不该单独暴露）。
    import re as _re7
    _INTERNAL = {
        # 只有**真正内部**的才在白名单里 —— 别的都该在 main.py 或后端方法里找得到。
        # 白名单放宽 = 这个检查就没牙齿了（第一版把所有东西都列进去，等于白写）。
        "upload_chunk", "upload_finish", "upload_abort",   # upload 的内部步骤
        "exec_js",        # 后端方法叫 execute_js（方法名 ≠ 命令名），下面单独认
        "key_up", "mouse_up",   # 动作走的是 key_down_up / mouse_down_up 组合
    }
    _proto = src_safe("protocol.py")
    _names = set(_re7.findall(r'CMD_\w+ = "([a-z_]+)"', _proto))
    _main = src_safe("main.py")
    _backend = {}
    for _f in ("backends/extension_backend.py", "backends/headless_backend.py"):
        _backend[_f] = src_safe(_f)
    _unreachable = []
    for _n in sorted(_names - _INTERNAL):
        # ⚠️ 判据必须是 **`_call("xxx")`**，不能只查 `"xxx"` 这个字符串 ——
        #    渲染分支里也会出现 `method == "get_selection"`，
        #    只查字符串的话"删掉调用、留下渲染"照样绿（反向验证时抓到的）。
        if f'_call("{_n}"' in _main:
            continue
        # ⚠️ 不看"后端有没有这个方法" —— 方法存在**不等于**插件会调它。
        #    get_selection 就是活例子：后端方法一直有，main.py 从没调过 ✗
        #    （反向验证时正是靠删掉调用才暴露出这一点）。
        # 方法名和命令名不同的（exec_js ↔ execute_js），用"哪个后端方法
        # 发这条命令"反查。
        if any(f'CMD_{_n.upper()} ' in _v or f'CMD_{_n.upper()},' in _v
               or f'CMD_{_n.upper()})' in _v for _v in _backend.values()):
            continue
        _unreachable.append(_n)
    r.ok("S7 扩展能执行的命令，插件都够得着（不会再出现'实现了却没接出来'）",
         not _unreachable, f"够不着的={_unreachable or '无'}")

    # ── S8 工具 schema 里**数组必须带 items**（否则 Gemini 直接 400）──────
    #    ⚠️ 真实事故：browser_cookie 的 `cookies` 只写了
    #       {"type": "array", "description": ...} —— **没有 items**。
    #       OpenAI 宽松没事，换 Gemini 整个模型组失败：
    #         tools[0].function_declarations[12].***.properties[cookies]
    #         .items: missing field.
    #       （用户的模型组里有 Gemini，于是一条 400 把整组拖垮。）
    #    ⚠️ 扫描要用 ast（文本 regex 分不清层级）—— 且注意
    #       **`async def` 是 AsyncFunctionDef**，只认 FunctionDef 会扫出 0 个工具
    #       （我第一次就是这么写的，白跑三轮）。
    import ast as _ast8
    _tree = _ast8.parse(src_safe("main.py"))
    _bad8, _arrays = [], 0

    def _scan8(node, tool):
        nonlocal _arrays
        if isinstance(node, _ast8.Dict):
            _kv = {}
            for _k, _v in zip(node.keys, node.values):
                if isinstance(_k, _ast8.Constant):
                    _kv[_k.value] = _v
            if getattr(_kv.get("type"), "value", None) == "array":
                _arrays += 1
                if "items" not in _kv:
                    _bad8.append(f"{tool}(行 {node.lineno})")
            for _v in node.values:
                _scan8(_v, tool)
        elif isinstance(node, (_ast8.List, _ast8.Tuple)):
            for _v in (getattr(node, "elts", None) or getattr(node, "values", []) or []):
                _scan8(_v, tool)

    for _n in _ast8.walk(_tree):
        if isinstance(_n, (_ast8.FunctionDef, _ast8.AsyncFunctionDef)):
            for _d in _n.decorator_list:
                if isinstance(_d, _ast8.Call) and getattr(_d.func, "attr", "") == "tool":
                    for _kw in _d.keywords:
                        if _kw.arg == "params":
                            _scan8(_kw.value, _n.name)
    r.ok("S8 工具 schema 的数组都带 items（否则 Gemini 直接 400）",
         not _bad8, f"缺 items={_bad8 or '无'}（扫到 {_arrays} 个数组）")

    # ── S9 浏览历史默认关（隐私），且开了才放行 ──────────────────────
    #    历史是**用户没主动交出来**的数据，不能默认就交给模型 ——
    #    和 inject_page_state / 下载清理一个道理：默认取向要是保守的那边。
    #    书签不受此限（书签是用户主动收藏的，性质不同）。
    import json as _json9
    _sch9 = _json9.loads(src_safe("schema.json"))

    def _find9(o, key):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == key: return v
                got = _find9(v, key)
                if got is not None: return got
        elif isinstance(o, list):
            for v in o:
                got = _find9(v, key)
                if got is not None: return got
        return None
    _m9 = src_safe("main.py")
    _bad9 = []
    if (_find9(_sch9, "allow_history") or {}).get("default") is not False:
        _bad9.append("schema 里不是默认关")
    if 'cfg.get("allow_history", False)' not in _m9:
        _bad9.append("代码回落值不是 False")
    if "if not self.allow_history" not in _m9:
        _bad9.append("没有真的拦住（开关没接进动作里）")
    r.ok("S9 浏览历史默认关，且开关真的拦得住", not _bad9,
         f"问题={_bad9 or '无'}")

    # ── S10 侧边栏能配**全部**项，且改完立刻生效 ──────────────────────
    #    用户要的是"完全由侧边栏可配置和热更改"。三条都要在：
    #      ① 有读/写配置的端点
    #      ② _apply_config 会把侧边栏的覆盖值叠在框架配置之上（不叠 = 光存不生效）
    #      ③ 界面**从 schema.json 生成**（照着一处真源长出来，加新项自动出现）
    _m10 = src_safe("main.py")
    _ui = src_safe("web/app.js")
    _bad10 = []
    if 'register.api("GET", "/config"' not in _m10:
        _bad10.append("没有 GET /config")
    if 'register.api("POST", "/config"' not in _m10:
        _bad10.append("没有 POST /config")
    if "cfg.update(self._cfg_overrides or {})" not in _m10:
        _bad10.append("覆盖值没叠进 _apply_config（那样就像'存了不生效'）")
    if "self._apply_config(getattr(self, \"plugin_cfg\", {}) or {})" not in _m10:
        _bad10.append("保存后没有热应用")
    if "schema.json" not in _m10 or '"fields": self._schema_fields()' not in _m10:
        _bad10.append("端点没把 schema 交出去")
    if "r.fields" not in _ui or "loadConfig" not in _ui:
        _bad10.append("界面没有按 schema 生成")
    if "保存并立刻生效" not in _ui:
        _bad10.append("界面上没说清'立刻生效'")
    r.ok("S10 侧边栏可配置全部项并热生效（读/写端点 + 叠覆盖 + schema 生成）",
         not _bad10, f"问题={_bad10 or '无'}")

    # ── S11 README 里要写明"一切都可以在侧边栏配置" ────────────────────
    _rd = src_safe("README.md")
    r.ok("S11 README 的配置章节写明'侧边栏可配置、改完即生效'",
         "侧边栏 WebUI" in _rd and "不用重启" in _rd,
         "用户找不到入口的话，再好的面板也白搭")

    # ── S12 配置区开头要有说明块（照 KiraAI 官方搜索插件的 info 写法）────
    #    官方那套是 `"type": "info"` + `level` + `locales.zh.hint` ——
    #    在设置页里渲染成一段纯说明（不是输入框）。用户要求：
    #    告诉用户"一切都可以在侧边栏 WebUI 配置更快捷"，
    #    并提示"装完扩展后重开浏览器 + 重新打开侧边栏页面更容易连上"。
    import json as _json12
    _raw12 = _json12.loads(src_safe("schema.json"))
    _first12 = list(_raw12.keys())[0] if _raw12 else ""
    _info12 = _raw12.get("info_intro") or {}
    _zh12 = ((_info12.get("locales") or {}).get("zh") or {})
    _txt12 = str(_zh12.get("hint") or "")
    _bad12 = []
    if _first12 != "info_intro":
        _bad12.append(f"说明块不在最前面（第一项是 {_first12}）")
    if _info12.get("type") != "info" or _info12.get("level") != "info":
        _bad12.append("没有按官方写法（type/level 都该是 info）")
    if "侧边栏" not in _txt12:
        _bad12.append("没提侧边栏 WebUI")
    if "重新打开一次" not in _txt12:
        _bad12.append("没提'装完扩展后重开一次更容易连上'")
    r.ok("S12 配置开头有说明块（照官方 info 写法，含两个关键提示）",
         not _bad12, f"问题={_bad12 or '无'}")

    # ── S13 令牌的 force 必须走 query（塞 body 会变成"每次面板都重生成"）──
    #    ⚠️ 真事故：FastAPI 对**简单类型**默认按 query 绑定，塞进 JSON body
    #       根本不生效 → 端点走自己的默认 `force=True` → **每次打开面板
    #       都会重新生成令牌**，旧令牌当场作废 → 扩展刚配对好就又连不上 ✗
    _ui13 = src_safe("web/app.js")
    _bad13 = []
    if "token?force=" not in _ui13:
        _bad13.append("令牌调用没把 force 放进 query")
    # ⚠️ **还要是 POST** —— 这就是"旧版能用、重写后不能用"的真正差别：
    #    旧版是 `api("/token?force=...", { method: "POST" })`，
    #    我重写面板时把 `{ method: "POST" }` 弄丢了 ✗ → 变成 GET →
    #    端点只注册了 POST → 404 → 界面"读取失败"。
    #    只查 query 会漏掉这一半，所以两半都要查。
    if "token?force=true" not in _ui13 or _ui13.count('method: "POST"') < 2:
        _bad13.append("令牌调用缺 POST（只有 query 不够 —— 端点只注册了 POST）")
    if 'api("/token", {' in _ui13:
        _bad13.append("还有地方按旧写法调 /token")
    # model_select 必须是下拉（框架的客户端缓存类字段都这么给）
    if "model_select" not in _ui13 or "<select" not in _ui13:
        _bad13.append("model_select 没渲染成下拉")
    # 拉不到模型列表时要能退回文本框（不能给个空下拉）
    if "没能取到模型列表" not in _ui13:
        _bad13.append("拉不到模型列表时没有退回方案")
    r.ok("S13 令牌 force 走 query + model_select 渲染成下拉（且能降级）",
         not _bad13, f"问题={_bad13 or '无'}")

    # ── S14 静态资源里不能混进"工具的输出"（这次的坑）──────────────────
    #    ⚠️ 真事故：`file_write` 追加内容太大时会被**换成一句提示文字**
    #       （"CONTEXT OFFLOADED … saved to …"），而那句话**被当成文件内容
    #       写进了 style.css** ✗ → CSS 从此坏掉，启动动画样式整段失效
    #       （用户报"启动动画没出现"，查了半天才发现是这行垃圾）。
    #    判据：前端资源里不许出现这类提示文字。
    _bad14 = []
    for _f in ("web/style.css", "web/app.js", "web/index.html"):
        _t = src_safe(_f)
        for _mark in ("CONTEXT OFFLOADED", "offloads/tools/"):
            if _mark in _t:
                _bad14.append(f"{_f} 含 {_mark!r}")
    r.ok("S14 前端资源里没有混进工具输出（offload 提示等）", not _bad14,
         f"问题={_bad14 or '无'} —— 混进去会让整个样式/脚本失效")

    # ── S15 前端 CSS 必须结构完整（注释/括号配平）──────────────────────
    #    ⚠️ 真事故：我早先"清理" style.css 时，把某段注释的**开头和它所属的
    #       规则一起删了**，只剩尾巴浮在文件里 ✗ → 解析器从那里开始错乱 →
    #       **后面的动画规则全部失效** → 用户看到"动画完全不动"。
    #       这类损坏肉眼很难发现（文件看着挺正常），但后果是整段失效。
    _css = src_safe("web/style.css")
    _bad15 = []
    if _css.count("{") != _css.count("}"):
        _bad15.append(f"花括号不配平（{{={_css.count('{')} }}={_css.count('}')}）")
    _i, _depth, _opens, _orphan = 0, 0, 0, []
    while _i < len(_css) - 1:
        if _css[_i:_i + 2] == "/*":
            if _depth == 0:
                _opens += 1
            _depth += 1
            _i += 2
            continue
        if _css[_i:_i + 2] == "*/":
            if _depth == 0:
                _orphan.append(_css[:_i].count("\n") + 1)
            _depth = max(0, _depth - 1)
            _i += 2
            continue
        _i += 1
    if _depth:
        _bad15.append("有注释没闭合（会吞掉它之后的全部规则）")
    if _orphan:
        _bad15.append(f"有游离的注释尾巴（第 {_orphan} 行）")
    r.ok("S15 前端 CSS 结构完整（注释闭合 / 括号配平）", not _bad15,
         f"问题={_bad15 or '无'} —— 这类损坏会让后面的样式整段失效")
