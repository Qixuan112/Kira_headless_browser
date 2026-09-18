"""默认目录（截图 / 下载 / cookie）必须是**绝对路径**，且跟着框架的 data 目录走。

## 抓这个的由来

`headless_backend` 里原来写的是**相对字符串**：

    screenshot_dir = cfg.get("screenshot_dir") or str(Path("data/temp"))
    cookies_dir    = cfg.get("cookies_dir")    or str(Path("data/files/cookie"))

只有当"进程 CWD 恰好是 KiraAI 根目录、**且**数据目录就是 `<root>/data`"时
才落到正确位置。用户用 `--data-dir` 换过数据目录、或从别的 CWD 启动 KiraAI，
截图 / Cookie 就会**静默落到别处**（不报错，极难发现）。

改成从框架的 `get_data_path()` 推导后：

* 默认情况（没改数据目录）→ `<CWD>/data/temp`，**和改之前完全一样** ✓
* 改过数据目录 → 跟着框架走 ✓（旧写法会跑偏）

这里把两种情形都钉住：既要证明"没改坏默认行为"，也要证明"改过的能跟上"。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from ..harness import PLUGIN_DIR, install_stubs, src_safe

TITLE = "默认目录基准（截图/下载/cookie）"


def _load_framework_path_utils():
    """单独加载框架的 path_utils（它只依赖标准库）。

    不能 `import core.utils.path_utils` —— 真实框架的包 `__init__` 会拉起
    fastapi/fastmcp 一大堆重依赖。直接按文件加载最省事，且用的是**真件**。
    """
    fw = os.environ.get("KIRA_FW_DIR")
    if not fw:
        return None
    p = Path(fw) / "core" / "utils" / "path_utils.py"
    if not p.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_fw_path_utils", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(r) -> None:
    # 走 src_safe：文件缺失时只让本组报失败，不会中断整组检查
    src = src_safe("backends/headless_backend.py")
    # HeadlessBackend 里 `from core.utils.path_utils import get_data_path`
    # 解析到的就是**桩**（测试环境把 stubs 放在 sys.path 最前）——
    # 基准必须用它，才能和被测代码看到同一个数据目录。
    from core.utils.path_utils import get_data_path

    # ── ① 不许再出现相对的目录默认值 ────────────────────────────────
    #    判据：三个目录的默认值必须来自绝对基准 —— 要么是 `_resolve_user_dir(...)`，
    #    要么直接是 `_fw_data / ...` / `Path(data_dir) / ...`；
    #    不能是 `str(Path("data/..."))` 这种字面量相对路径。
    #    ⚠️ 赋值写成多行了（解析器那版），所以要把**整条语句**拼起来看 ——
    #       只看单行会把正确写法误判成"不是从绝对基准推的"（首跑就误报了）。
    lines = src.splitlines()
    bad = []
    for name in ("screenshot_dir", "download_dir", "cookies_dir"):
        for i, line in enumerate(lines):
            if f"self.{name} = " not in line:
                continue
            # 往后拼到括号配平为止
            stmt, depth = line, line.count("(") - line.count(")")
            j = i + 1
            while depth > 0 and j < len(lines):
                stmt += " " + lines[j].strip()
                depth += lines[j].count("(") - lines[j].count(")")
                j += 1
            if 'Path("data/' in stmt or "Path('data/" in stmt:
                bad.append(f"{name} 用了相对字面量")
            elif not any(k in stmt for k in ("_resolve_user_dir", "_fw_data", "data_dir")):
                bad.append(f"{name} 的默认值不是从绝对基准推的")
    r.ok("C1 截图/下载/cookie 默认目录不含相对字面量", not bad, f"问题={bad or '无'}")

    # ── ② 兜底函数存在，且取不到框架时仍给绝对路径 ───────────────────
    has_helper = "def _framework_data_path" in src
    r.ok("C2 有 _framework_data_path()（取不到框架时退回插件数据目录的上两级）",
         has_helper, "" if has_helper else "找不到该函数，默认值可能又变回相对路径")

    # ── ③ 行为验证：用**真**框架 path_utils 跑两种情形 ────────────────
    pu = _load_framework_path_utils()
    if pu is None:
        r.warn("C3 行为验证（需要 KIRA_FW_DIR 指向真实 KiraAI 仓库）", "未设置 KIRA_FW_DIR")
        return

    cwd = os.getcwd()
    try:
        os.chdir("/tmp")
        # 情形①：默认 —— 新写法必须**等于**旧的相对写法（没改坏默认行为）
        pu._data_dir = None
        new = Path(pu.get_data_path()) / "temp"
        old = Path("data/temp").resolve()
        r.ok("C3 没改数据目录时，截图仍落在 <CWD>/data/temp（与改前一致）",
             str(new) == str(old), f"新={new} 旧={old}")

        # 情形②：换过数据目录 —— 必须跟着框架走（旧写法会跑偏）
        pu.init_paths(data_dir="/tmp/_kira_custom_data")
        new2 = Path(pu.get_data_path()) / "temp"
        old2 = Path("data/temp").resolve()
        r.ok("C4 换过 data-dir 时，截图跟着框架走（旧写法会跑到 CWD 下）",
             str(new2).startswith("/tmp/_kira_custom_data")
             and str(new2) != str(old2),
             f"新={new2} 旧={old2}")
    finally:
        os.chdir(cwd)

    # ── ④ 真构造对象，看三个目录到底是不是绝对路径 ────────────────────
    #    ⚠️ C3/C4 测的是**框架函数**的行为，抓不到"插件代码有没有用它" ——
    #       所以要真把 HeadlessBackend 建出来看结果。C1 只查字面量，
    #       如果哪天有人改成别的相对写法（比如 os.path.join("data","temp")），
    #       C1 会漏、这条不会。
    try:
        from . import runtime_behavior
        hb = runtime_behavior._load_plugin()
        b = hb.HeadlessBackend(Path("/tmp/_probe/plugin_data/headless_browser"), {})
        rel = [n for n in ("screenshot_dir", "download_dir", "cookies_dir")
               if not Path(getattr(b, n)).is_absolute()]
        vals = {n: getattr(b, n) for n in ("screenshot_dir", "download_dir", "cookies_dir")}
        r.ok("C5 真实例化后，三个目录都是绝对路径", not rel,
             f"相对的={rel} 实际={vals}")

        # ── C6：用户填 `data/bs` 必须解释成 <框架数据目录>/bs ──────────
        #    ⚠️ 这是本次的重点：框架自己的规矩（tags.py 的 `<file>` 标签）里
        #       `data/<rel>` == `<get_data_path()>/<rel>`，**不是** CWD 下的。
        #       插件按 CWD 解释 → 用户填 `data/bs` 会落到 `<CWD>/data/bs`。
        #
        #    ⚠️ 基准必须取**桩的** get_data_path —— 那才是 HeadlessBackend
        #       实际用的那个。用 `pu`（单独加载的真件）去比是错的：
        #       两个模块实例各有各的 _data_dir，首跑就是这么误报的。
        fw = Path(get_data_path())
        case = {
            "data/bs": str(fw / "bs"),          # 与框架一致
            "bs":      str(fw / "bs"),          # 同一基准（框架是丢弃，这里不丢）
            "/mnt/abs/x": "/mnt/abs/x",         # 绝对路径原样
            "data":    str(fw),                 # 就是数据目录本身
        }
        bad6 = []
        for filled, want in case.items():
            got = hb.HeadlessBackend(Path("/tmp/_probe/plugin_data/hb"),
                                     {"download_dir": filled}).download_dir
            if got != want:
                bad6.append(f"{filled!r}→{got}（应为 {want}）")
        r.ok("C6 用户填 data/xxx 解释为 <框架数据目录>/xxx（与 KiraAI 的 <file> 一致）",
             not bad6, f"不符={bad6 or '无'}")

        # ── C7：留空必须回落到**框架自己的目录**（不是插件私有目录、也不是自造目录）──
        #    ⚠️ 曾经的两次错法：
        #       ① `<data>/plugin_data/<id>/downloads` —— 插件内部状态目录，
        #          用户翻不到、模型也没法用 `data/...` 引用；
        #       ② 我自己发明的 `<data>/downloads` —— 框架里根本没这个约定。
        #    正确：下载 → `<data>/files`（框架 `<file>` 标签的文件区），
        #          截图 → `<data>/temp`（框架 AsyncTempMonitor 在清的临时区）。
        d7 = hb.HeadlessBackend(Path("/tmp/_probe/plugin_data/hb"), {}).download_dir
        r.ok("C7 留空时下载回落到 <数据目录>/files（框架的文件区）",
             d7 == str(fw / "files"), f"实际={d7} 应为={fw / 'files'}")
        s7 = hb.HeadlessBackend(Path("/tmp/_probe/plugin_data/hb"), {}).screenshot_dir
        r.ok("C7b 留空时截图回落到 <数据目录>/temp（框架临时区）",
             s7 == str(fw / "temp"), f"实际={s7} 应为={fw / 'temp'}")

        # ── C8：自动清理**不许**被代码偷偷关掉 ────────────────────────
        #    ⚠️ 我一度加过"下载目录是 data/files 就自动关掉清理"的所谓保护 ——
        #       但清理本身是**特性**，用户把目录填到哪儿就是想在那儿享受清理。
        #       这条判据盯着它别再回来。
        keep = []
        for filled in ("", "data/files", "data/bs"):
            bb = hb.HeadlessBackend(Path("/tmp/_probe/plugin_data/hb"),
                                    {"download_dir": filled} if filled else {})
            if not bb.download_auto_clean:
                keep.append(filled or "(留空)")
        r.ok("C8 自动清理不会被代码关掉（用户在哪儿填就在哪儿清理）", not keep,
             f"被关掉的情形={keep or '无'}")
        if "download_auto_clean = False" in src:
            r.ok("C9 源码里不再有「自动关闭清理」的写法", False,
                 "又出现了 download_auto_clean = False")
        else:
            r.ok("C9 源码里不再有「自动关闭清理」的写法", True, "")
    except Exception as e:
        r.warn("C5 真实例化 HeadlessBackend（需要桩环境）", f"{type(e).__name__}: {e}")
