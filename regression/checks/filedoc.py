#!/usr/bin/env python3
"""本机文件（``file://``）能被浏览器打开 —— 两个后端都要能，且都能说清"为什么不行"。

## 为什么单独一组检查（真事故）

用户报：无论走扩展还是无头，bot 都打不开本地文件。日志原文：

    [tool_use] browser_navigate args: {'url': 'file:///C:/Users/.../xxx.jpg'}
    [tool_use] tool_result: 不支持的页面类型（file://），扩展无权访问

根因是 `security.py` 里 ``file`` 被硬编码进了 `BLOCKED_SCHEMES`，
注释写着"扩展也拿不到权限"。**那句话只对了一半**：

* 扩展默认确实读不了本地文件 —— 但用户在扩展详情页打开
  「允许访问文件网址」之后就能了；
* 无头浏览器（浏览器自己启动的那个）**从来没有这条限制**。

于是那一条硬编码把**两个后端同时**钉死，而"帮我看看这张图 / 这份 PDF"
恰恰是浏览器最自然的用法。这类缺陷的坏处是**静默**：不是报错崩溃，
而是功能根本不存在，测试也不会红（原来那条 C4 断言的是"file:// 被拒"，
它**把 bug 当成预期**钉住了）。

## 这组检查盯什么

1. **放行**：默认能打开本机文件（两个后端都要有这条路径）；
2. **可收紧**：开关关掉后必须真拒绝（"默认开"不等于"关不掉"）；
3. **路径白名单**：关掉"任意路径"后 ``../`` 穿越必须被拦；
4. **网络共享**：``file://server/share`` 一律拒绝（那不是本机文件）；
5. **路径归一**：中文/空格的 percent-encoding 要能解回来（否则必然找不到文件）；
6. **模型够得着**：给一个本机路径（不是 URL）也能打开 —— 这是用户实际会说的形态；
7. **报错可照做**：扩展侧没开那个开关时，报错必须包含"去哪开"；
8. **headless shell 的 PDF 限制**：要能翻译成"换哪条路"，而不是透传 ERR_ABORTED。

## 反向验证

每条判据都要求它在**改回旧行为**时报红 —— 见 ``run`` 末尾的 M 段：
直接构造"旧代码"（把 file 塞回 BLOCKED_SCHEMES）跑同一批断言，
必须当场失败。否则这些检查只是"永远成立"的装饰。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from ..harness import PLUGIN_DIR, section, src_safe, install_stubs

TITLE = "本机文件（file://）能打开"


def _run_file_access_probe(r):
    """真跑扩展的 shared.js（mock chrome API）。返回 None = 没有 node。"""
    import shutil
    import subprocess
    node_bin = shutil.which("node")
    if not node_bin:
        return None
    script = PLUGIN_DIR / "regression" / "js" / "file_access.mjs"
    if not script.is_file():
        return {"error": f"探针脚本不存在：{script}"}
    import os as _os
    env = dict(_os.environ)
    env["KIRA_SHARED_JS"] = str(PLUGIN_DIR / "browser-bridge" / "shared.js")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        p = subprocess.run([node_bin, str(script)], capture_output=True,
                           text=True, env=env, timeout=90,
                           cwd=str(script.parent))
    except Exception as e:                                    # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    for line in (p.stdout or "").splitlines():
        if line.startswith("RESULT:"):
            try:
                return json.loads(line[len("RESULT:"):])
            except json.JSONDecodeError as e:
                return {"error": f"探针输出不是 JSON: {e}"}
    return {"error": ((p.stdout or "")[-300:] + (p.stderr or "")[-300:])}


def _load_security():
    """加载被检查的 security.py（用仓库里那份，不是安装过的）。

    ⚠️ 文件缺失时必须**返回 None 而不是抛异常**。抛出去的话，
    `run()` 开头那一行就会崩 —— **整组检查一条都不跑**，
    报告上只剩一句笼统的"未抛异常"，连"少了 50 多条覆盖"都看不出来。
    删文件矩阵专门抓这种"整段中断"。
    （同项目的 security_rules.py 早就为同一个文件做了这个兜底，
      新写的模块漏了 —— 这类一致性缺失最容易发生在"照着别人写但少抄一段"时。）
    """
    install_stubs()
    import importlib.util
    p = PLUGIN_DIR / "security.py"
    if not p.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_hb_security_check", p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                        # noqa: BLE001
        return None


def run(r) -> None:
    sec = _load_security()
    if sec is None:
        # ⚠️ 这里**不能直接 return** —— 后面几段（D2~D4 导航入口、E 扩展侧、
        #    F 无头侧、G 配置接线）都只读**源码文本**，不依赖 security 模块，
        #    照样能给出结论。提前退出等于把它们一起抹掉，
        #    报告上就只剩"少了一大片覆盖"而看不出少了什么。
        r.ok("A0 security.py 可加载（否则 A/B/C/M 三段无从谈起）",
             False, "security.py 缺失或加载失败 —— 只跑不依赖它的段落")
    else:
        _run_behavior_checks(r, sec)
    _run_source_checks(r)


def _run_behavior_checks(r, sec) -> None:
    """A/B/C/M 四段：需要真的 import security 模块才能跑。"""

    # ══════════════════════════════════════════════════════════════════
    section("A. 默认能打开本机文件（这是本次要修的主诉求）")
    # ══════════════════════════════════════════════════════════════════
    _cases = [
        "file:///C:/Users/me/Desktop/a.png",
        "file:///home/me/a.pdf",
        "file:///tmp/a.txt",
        "file:///data/temp/clip.mp4",
        "file://localhost/tmp/a.html",
    ]
    _blocked = [u for u in _cases if not sec.check_url(u)[0]]
    r.ok("A1 默认放行本机文件（图片 / PDF / 文本 / 视频 / HTML）",
         not _blocked, f"被误拦={_blocked or '无'}")

    # 关掉开关必须真拦 —— "默认开"不等于"关不掉"
    _leak = [u for u in _cases if sec.check_url(u, local_file_access=False)[0]]
    r.ok("A2 关掉「允许打开本机文件」后一律拒绝",
         not _leak, f"漏放={_leak or '无'}")

    # ⚠️ 这条最容易漏：`local_access`（本机网页）和 `local_file_access`（本机文件）
    #    是两个正交开关。判据必须验"它们确实互不影响"——
    #    否则实现里很容易把 file 挂到 local_access 上，
    #    于是"只想禁 localhost 网页"的用户把本地文件也一起禁了（反之亦然）。
    _cross = sec.check_url("file:///tmp/a.png", local_access=False)[0]
    r.ok("A3 关「允许访问本机/内网」不影响本地文件（两个开关正交）",
         _cross, "本机网页与本机文件必须是两件事")
    _cross2 = sec.check_url("http://localhost:3000/", local_file_access=False)[0]
    r.ok("A4 关「允许打开本机文件」不影响 localhost 网页（两个开关正交）",
         _cross2, "反向也要正交，否则开关名字与实际行为对不上")

    # 浏览器内部页仍然是硬边界 —— 别把 file 的放行误扩到它们身上
    _hard = [u for u, want in (("chrome://settings", False),
                               ("edge://settings", False),
                               ("about:blank", False),
                               ("javascript:alert(1)", False),
                               ("view-source:http://x/", False))
             if sec.check_url(u)[0] != want]
    r.ok("A5 放行 file 没有顺手放过浏览器内部页（硬边界仍在）",
         not _hard, f"误放={_hard or '无'}")

    # ══════════════════════════════════════════════════════════════════
    section("B. 路径解析（URL ↔ 路径，含 percent-encoding 与 UNC）")
    # ══════════════════════════════════════════════════════════════════
    _parse = [
        ("file:///C:/Users/me/a.png", "C:/Users/me/a.png"),
        ("file:///home/me/a.pdf", "/home/me/a.pdf"),
        ("file://localhost/tmp/a.txt", "/tmp/a.txt"),
        ("file:///tmp/%E4%B8%AD%E6%96%87.png", "/tmp/中文.png"),
        ("file:///tmp/a%20b.png", "/tmp/a b.png"),
    ]
    _bad = []
    for u, want in _parse:
        got = sec.file_url_to_path(u)
        if got != want:
            _bad.append(f"{u} → {got!r}（应为 {want!r}）")
    r.ok("B1 file:// → 路径（Windows 盘符 / percent-encoding 都要对）",
         not _bad, f"不符={_bad or '无'}")

    # 逆变换：路径 → URL。中文必须编码，否则路径里的 # / ? 会截断
    _u = sec.path_to_file_url("/tmp/中文 图.png")
    r.ok("B2 路径 → file:// 会对中文与空格编码",
         "%E4%B8%AD" in _u and "%20" in _u and " " not in _u, f"得到={_u}")
    _u2 = sec.path_to_file_url("C:\\Users\\me\\a.png")
    r.ok("B3 Windows 反斜杠路径能转成 file:///C:/...",
         _u2.lower().startswith("file:///c:"), f"得到={_u2}")

    # ⚠️ B3b：相对路径**绝不能**让第一段变成"主机名"。
    #    直接拼 `file://data/temp/a.png` 时，urlparse 会把 `data` 当 netloc
    #    ⇒ 被判成**网络共享**而拒绝，用户看到的是一句莫名其妙的
    #    "这不是本机文件"。必须补前导斜杠（file:///data/...），
    #    netloc 保持为空 —— 这样它仍是"本机文件"这条通道，
    #    找不到就是"文件不存在"，报错诚实且可照做。
    _u3 = sec.path_to_file_url("data\\temp\\a.png")
    _u3_ok = _u3 == "file:///data/temp/a.png" and sec.check_url(_u3)[0]
    r.ok("B3b 相对路径不会让首段变成主机名（否则会被误判成网络共享）",
         _u3_ok, f"得到={_u3}；check_url={sec.check_url(_u3)}")
    r.ok("B3c 相对路径能原样还原（往返无损，只是基准未知）",
         sec.file_url_to_path(_u3) == "/data/temp/a.png",
         f"还原={sec.file_url_to_path(_u3)}")

    r.ok("B3d is_absolute_local_path 判得对（这是「请给完整路径」提示的依据）",
         sec.is_absolute_local_path("/tmp/a")
         and sec.is_absolute_local_path("C:/a")
         and sec.is_absolute_local_path("C:\\a")
         and not sec.is_absolute_local_path("data\\temp\\a.png")
         and not sec.is_absolute_local_path("data/a"))

    # 往返回路（encode 之后必须还能 decode 回来）
    _rt = []
    for p in ("/tmp/中文 图.png", "C:/Users/me/我的 文档.pdf", "/tmp/a#b.png"):
        back = sec.file_url_to_path(sec.path_to_file_url(p))
        if back != p:
            _rt.append(f"{p} → {back}")
    r.ok("B4 路径→URL→路径 往返无损（含 # 这种会被当 fragment 的字符）",
         not _rt, f"不符={_rt or '无'}")

    # UNC：网络共享**不是**本机文件
    _unc = [u for u in ("file://server/share/a.png",
                        "file://192.168.1.9/share/a.png")
            if sec.check_url(u)[0]]
    r.ok("B5 网络共享（file://server/...）一律拒绝 —— 那不是本机文件",
         not _unc, f"漏放={_unc or '无'}")

    # ══════════════════════════════════════════════════════════════════
    section("C. 路径白名单（关掉「任意路径」后必须真拦得住 ../ 穿越）")
    # ══════════════════════════════════════════════════════════════════
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "allowed"
        root.mkdir()
        inside = root / "ok.png"
        inside.write_bytes(b"x")
        secret = Path(td) / "secret.txt"
        secret.write_text("s", encoding="utf-8")

        ok_in, _ = sec.file_path_allowed(str(inside), allow_any=False,
                                         allowed_dirs=[str(root)])
        r.ok("C1 白名单内的文件放行", ok_in, f"路径={inside}")

        ok_out, _ = sec.file_path_allowed(str(secret), allow_any=False,
                                          allowed_dirs=[str(root)])
        r.ok("C2 白名单外的文件拒绝", not ok_out)

        # ⚠️ 核心：`..` 穿越必须靠 realpath 拦住。
        #    只做字符串前缀比较的实现会在这里**错误放行**。
        trav = str(root) + "/../secret.txt"
        ok_tr, _ = sec.file_path_allowed(trav, allow_any=False,
                                         allowed_dirs=[str(root)])
        r.ok("C3 ../ 穿越被 realpath 归一后拦住（关键安全项）",
             not ok_tr, f"穿越路径={trav}")

        # 开关打开时任何路径都放行（与 upload_allow_any_path 同语义）
        ok_any, _ = sec.file_path_allowed(str(secret), allow_any=True)
        r.ok("C4 「允许任意路径」打开时不受目录限制", ok_any)

    # 穿越也必须能从 URL 那条路拦（不能只在直接调用 helper 时成立）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "sub"
        root.mkdir()
        secret = Path(td) / "secret.txt"
        secret.write_text("s", encoding="utf-8")
        url = sec.path_to_file_url(str(secret))
        ok, _ = sec.check_url(url, file_allow_any_path=False,
                              file_allowed_dirs=[str(root)])
        r.ok("C5 穿越检查在 check_url 这条**实际入口**上也生效",
             not ok, f"URL={url}")


    # ══════════════════════════════════════════════════════════════════
    section("M. 反向验证：把旧行为装回去，上面的判据必须报红")
    # ══════════════════════════════════════════════════════════════════
    #  ⚠️ 这一段是整组检查里**最值钱**的部分。
    #     前 40 条断言如果在旧代码上也全部通过，那它们什么都没验证 ——
    #     而旧代码恰恰是这条 bug 的现场（file 在 BLOCKED_SCHEMES 里），
    #     所以反向验证在这里是**真的能跑**的，不是摆设。
    #
    #     做法：把 file 塞回 BLOCKED_SCHEMES（= 改动前的状态），
    #     再调**真实的 check_url** 跑同一批用例 —— 必须全部被拒。
    _real_blocked = frozenset(sec.BLOCKED_SCHEMES)
    _saved_bs = sec.BLOCKED_SCHEMES
    try:
        sec.BLOCKED_SCHEMES = _real_blocked | {"file"}
        _old_blocked = [u for u in _cases if not sec.check_url(u)[0]]
    finally:
        sec.BLOCKED_SCHEMES = _saved_bs

    r.ok("M1 反向自检：把 file 装回 BLOCKED_SCHEMES 后，A1 的 5 条**全部**被拒（bug 复现）",
         len(_old_blocked) == len(_cases),
         f"旧行为拒绝 {len(_old_blocked)}/{len(_cases)} 条"
         f"（若这里不为 5，说明这些断言在旧代码上也通过 —— 那就是摆设）")
    r.ok("M2 反向自检：恢复后 A1 重新全部放行（证明上面的报红真的是开关引起的）",
         all(sec.check_url(u)[0] for u in _cases))

    # 穿越那条：把 realpath 归一换成朴素字符串前缀比较（常见的错实现），
    # C3 必须报红 —— 否则说明 C3 根本抓不到这个洞。
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "allowed"
        root.mkdir()
        secret = Path(td) / "secret.txt"
        secret.write_text("s", encoding="utf-8")
        trav = str(root) + "/../secret.txt"
        naive_allow = trav.startswith(str(root))          # 朴素实现 → True（放行）
        real_allow, _ = sec.file_path_allowed(
            trav, allow_any=False, allowed_dirs=[str(root)])
        r.ok("M3 反向自检：朴素前缀比较会放行穿越，而真实现拦住",
             naive_allow and not real_allow,
             "若这条不成立，说明 C3 拦的是别的东西，不是穿越")

    # E8（await 漏检）也必须真能抓到：造一个漏 await 的样本
    _sample = "a();\n  assertInjectable(tab);\n  b();"
    _hit = bool(re.search(r"(?<!await )\bassertInjectable\(tab\)", _sample))
    r.ok("M4 反向自检：漏 await 的样本能被 E8 的正则抓到", _hit)

    _should = {
        "/home/me/a.png": True,
        r"C:\Users\me\Desktop\a.pdf": True,
        "C:/Users/me/a.pdf": True,
        r"data\temp\a.png": True,
        r"\\server\share\a.png": True,
        # ↓ 这些**不是**路径（认错会把域名当路径，很糟）
        "example.com/a.png": False,
        "https://example.com/a": False,
        "localhost:3000/x": False,
        "about:blank": False,
    }
    _mis = [v for v, want in _should.items()
            if sec.looks_like_local_path(v) != want]
    r.ok("D1 本机路径识别正确（且不把域名/网址误判成路径）",
         not _mis, f"判错={_mis or '无'}")


    _run_source_checks(r)


def _run_source_checks(r) -> None:
    # ══════════════════════════════════════════════════════════════════
    section("D. 模型给的本机路径要能被认出来（用户实际会说的形态）")
    # ══════════════════════════════════════════════════════════════════

    # ⚠️ D2：光有识别函数没用，**导航入口必须真的调用它** ——
    #    用户/模型给的是 `C:\Users\me\a.png`（不是 file:// URL），
    #    这条路径如果不转换，会被补成 `https://C:\Users\...` 然后报一个
    #    谁也看不懂的 URL 错误。这正是用户遇到的形态之一。
    _main = src_safe("main.py")
    _nav = ""
    _m = re.search(r"async def tool_navigate\(.*?\n(?=    @register\.tool)",
                   _main, re.S)
    if _m:
        _nav = _m.group(0)
    r.ok("D2 browser_navigate 真的把本机路径转成 file://（不是只写了个助手没人用）",
         bool(_nav) and "looks_like_local_path" in _nav
         and "path_to_file_url" in _nav,
         "导航入口必须调用识别 + 转换")

    # 文件不存在时要说清楚，别让浏览器去报 ERR_FILE_NOT_FOUND
    r.ok("D3 文件不存在时给出可照做的提示（而不是透传浏览器的 ERR_FILE_NOT_FOUND）",
         bool(_nav) and "不存在这个文件" in _nav)

    # 本地文件不该顺手回正文（图片/视频没有正文，HTML 回源码纯烧 token）
    r.ok("D4 打开本机文件后不硬塞正文，改为指引 screenshot / page",
         bool(_nav) and "browser_screenshot" in _nav and "browser_page" in _nav)

    # ══════════════════════════════════════════════════════════════════
    section("E. 扩展侧：能不能访问本地文件要**真去问**，报错要能照做")
    # ══════════════════════════════════════════════════════════════════
    _shared = src_safe("browser-bridge/shared.js")
    r.ok("E1 扩展用 chrome.extension.isAllowedFileSchemeAccess 真问一次",
         "isAllowedFileSchemeAccess" in _shared,
         "这是用户级开关，只能问，猜不出来")
    r.ok("E2 探测失败的结论**不缓存**（否则一次偶发异常会永久钉住）",
         "invalidateFileAccessCache" in _shared)
    r.ok("E3 file:// 与 chrome:// 分开处理（前者有开关可开，后者是硬边界）",
         "FILE_URL" in _shared and "INJECTABLE" in _shared)

    # ── E·BEH：**真跑** shared.js（mock chrome API）────────────────────
    #  ⚠️ E1~E3 只证明"代码里写了"，证明不了"开关关着时真的会抛那句
    #     可照做的错、开着时真的放行"。这里用 node + 一个最小 chrome 桩
    #     直接 import 真文件跑用例。
    _beh = _run_file_access_probe(r)
    if _beh is None:
        r.warn("E·BEH 扩展 file:// 行为探针", "没有 node，跳过真跑验证")
    elif _beh.get("error"):
        r.ok("E·BEH 扩展 file:// 行为探针能跑起来", False, _beh["error"][:300])
    else:
        _by = {c["label"]: c for c in (_beh.get("cases") or [])}
        r.ok("E·BEH·1 开关打开时 file:// 放行（不抛错）",
             _by.get("file+allowed", {}).get("threw") is None,
             f"实际={_by.get('file+allowed')}")
        _den = (_by.get("file+denied", {}) or {}).get("threw") or ""
        r.ok("E·BEH·2 开关关着时抛出**可照做**的错（不是一句「没有权限」）",
             all(k in _den for k in ("chrome://extensions", "详情",
                                     "允许访问文件网址")),
             f"实际={_den[:100]!r}")
        r.ok("E·BEH·2b 同一句话里给出替代路径（换无头）",
             "browser_backend" in _den or "无头" in _den)
        r.ok("E·BEH·3 探测 API 自己抛异常时**不把用户拦死**（按允许处理，"
             "让真实错误浮现）",
             _by.get("file+probe-error", {}).get("threw") is None,
             f"实际={_by.get('file+probe-error')}")
        _ch = (_by.get("chrome+allowed", {}) or {}).get("threw") or ""
        r.ok("E·BEH·4 chrome:// 仍然是硬边界（file 放行没有顺带放过它）",
             "浏览器内部页" in _ch, f"实际={_ch[:80]!r}")
        r.ok("E·BEH·5 普通 https 页面不受影响",
             _by.get("https", {}).get("threw") is None)
        _cache = _beh.get("cache") or {}
        r.ok("E·BEH·6 探测失败时的结论没被缓存（去打开开关后下次就能生效）",
             _cache.get("afterProbeError") is True
             and _cache.get("freshDenied") is False,
             f"实际={_cache}")

    _bg = src_safe("browser-bridge/background.js")
    r.ok("E4 导航到 file:// 前先检查开关（否则报的是 Cannot navigate to a file URL）",
         bool(re.search(r"isFileAccessAllowed\(\)", _bg)))
    r.ok("E5 即使探测说行、真导航被拒也要翻译成可照做的说明（兜底）",
         "invalidateFileAccessCache" in _bg)

    # 报错必须包含"去哪开"—— 只说"没权限"等于把问题丢回给用户
    _help = _shared[_shared.find("function fileAccessHelp"):]
    _help = _help[: _help.find("\n}\n") + 3] if "\n}\n" in _help else _help
    # ⚠️ 源码里那段用的是模板插值 `${EXTENSIONS_URL}`，字面量不在函数体里。
    #    直接把常量定义替换进来再查 —— 否则这条会**误报**
    #    （函数明明写对了，只是引用了常量）。而"把常量内联两份"是更差的实现。
    _url_const = re.search(r'EXTENSIONS_URL\s*=\s*"([^"]+)"', _shared)
    if _url_const:
        _help = _help.replace("${EXTENSIONS_URL}", _url_const.group(1))
    _need = ["chrome://extensions", "详情", "允许访问文件网址"]
    _miss = [k for k in _need if k not in _help]
    r.ok("E6 没开开关时的报错含「去哪开、点什么」（三个要素齐）",
         not _miss, f"缺={_miss or '无'}")
    r.ok("E7 报错里给出替代路径（换无头后端），别让模型只能放弃",
         "browser_backend" in _help or "无头" in _help)

    # await 化：assertInjectable 改成异步了，**每个调用点**都必须 await，
    # 否则拿到的是 Promise（真值为真）→ 校验被完全跳过。
    # 这是"改了函数形状却没改调用点"的经典事故。
    # ⚠️ 必须**排除定义处**（`export async function assertInjectable(tab) {`）——
    #    把它也算成"没 await 的调用"就是纯误报。
    _call_re = re.compile(
        r"(?<!await )(?<!function )\bassertInjectable\(tab\)")
    _noawait = []
    for fn in ("browser-bridge/shared.js", "browser-bridge/background.js",
               "browser-bridge/capabilities.js", "browser-bridge/commands.js"):
        t = src_safe(fn)
        for m in _call_re.finditer(t):
            line = t[:m.start()].count("\n") + 1
            _noawait.append(f"{fn}:{line}")
    r.ok("E8 assertInjectable 改异步后，所有调用点都 await 了（漏一个=校验静默失效）",
         not _noawait, f"未 await={_noawait or '无'}")

    # ══════════════════════════════════════════════════════════════════
    section("F. 无头侧：headless shell 打不开 PDF / 音视频，要说清换哪条路")
    # ══════════════════════════════════════════════════════════════════
    _hb = src_safe("backends/headless_backend.py")
    r.ok("F1 认得出必须有渲染器才能看的那几类（PDF / 音视频）",
         "PDF_EXTS" in _hb and "MEDIA_EXTS" in _hb and "_is_viewable_media" in _hb)
    r.ok("F2 导航被中止（ERR_ABORTED）时翻译成人话，而不是透传错误码",
         "_nav_aborted" in _hb and "_file_render_hint" in _hb
         and "ERR_ABORTED" in _hb)
    _hint_i = _hb.find("_file_render_hint")
    _hint_body = _hb[_hint_i:_hint_i + 3000] if _hint_i >= 0 else ""
    r.ok("F3 提示里给出三条能走通的路（换扩展 / 换新版无头 / 只读文本）",
         all(k in _hint_body for k in ("extension", "chromium", "browser_file"))
         or all(k in _hint_body for k in ("extension", "chromium", "browser_file")),
         "必须能照做，不能只说'渲染不了'")
    r.ok("F4 图片**不**走这条（headless shell 有完整图片解码，file:// 图片正常）",
         "IMAGE_EXTS" in _hb
         and re.search(r"PDF_EXTS\s*=\s*frozenset\(\{[\"']\.pdf[\"']\}\)", _hb)
         is not None,
         "把图片也当成'渲染不了'是误报")

    # ══════════════════════════════════════════════════════════════════
    section("G. 配置接线（schema ↔ 代码 ↔ 文档三处一致）")
    # ══════════════════════════════════════════════════════════════════
    try:
        _sch = json.loads(src_safe("schema.json"))
    except json.JSONDecodeError:
        _sch = {}
    for key, typ in (("local_file_access", "switch"),
                     ("file_allow_any_path", "switch"),
                     ("file_allowed_dirs", "list")):
        node = _sch.get(key) or {}
        r.ok(f"G·{key} 在 schema 里存在且类型正确（{typ}）",
             node.get("type") == typ,
             f"实际={node.get('type')!r}；面板靠 type 选控件，写错会退化成文本框")

    _main_src = src_safe("main.py")
    r.ok("G4 三个开关都在代码里被读出来（schema 有、代码不读 = 配置形同虚设）",
         all(k in _main_src for k in ("local_file_access",
                                      "file_allow_any_path", "file_allowed_dirs")))
    r.ok("G5 开关真的转发到 check_url（只读进成员变量、不往下传 = 无效）",
         "local_file_access=self.local_file_access" in _main_src)

    # schema 默认值必须与代码兜底值一致 —— 不一致的话"配置文件缺这项"时
    # 行为与面板显示的对不上，而且极难发现。
    _def_any = ((_sch.get("file_allow_any_path") or {}).get("default"))
    r.ok("G6 file_allow_any_path 的 schema 默认与代码兜底一致（都是 true）",
         _def_any is True and 'cfg.get("file_allow_any_path", True)' in _main_src,
         f"schema={_def_any}")

    _def_lfa = ((_sch.get("local_file_access") or {}).get("default"))
    r.ok("G7 local_file_access 的 schema 默认与代码兜底一致（都是 true）",
         _def_lfa is True and 'cfg.get("local_file_access", True)' in _main_src,
         f"schema={_def_lfa}")

    # README 要说清"怎么开、怎么关"—— 用户找不到开关等于没做
    _readme = src_safe("README.md")
    r.ok("G8 README 写明了本机文件这组开关（含默认值与收紧方式）",
         "local_file_access" in _readme and "file_allow_any_path" in _readme)
    _sec_doc = src_safe("SECURITY_DESIGN.md")
    r.ok("G9 SECURITY_DESIGN 交代了本机文件开关的取舍（安全文档不能漏）",
         "local_file_access" in _sec_doc or "本机文件" in _sec_doc)