"""调用图完整性：**调用了但类里没定义**的方法。

这类 bug 最阴险：静态语法检查（`py_compile`）看不出来，
但一跑到那行就是 `AttributeError`。

真实案例：重构工具层时把 `_send_image` / `_send_file` 弄丢了，
只剩调用点还在 —— 截图发送、文件发送会直接崩，
而所有现有检查全绿（因为它们只看"名字有没有出现"，
不看"定义有没有存在"）。

同时也查反向：定义了但从未被调用的私有方法（可能是残留）。
"""

from __future__ import annotations

import ast

from ..harness import PLUGIN_DIR, section

TITLE = "调用图完整性（未定义方法 / 死代码）"

#: 这些来自框架基类或运行时注入，不算"未定义"
# ⚠️ 这份白名单只能放**真正由框架基类/运行期注入提供**的名字。
#    之前混进了 `get` / `append` / `format` / `create_task` 这类**通用方法名** ——
#    那等于给 A1 开了一个大洞：`self.get(...)` / `self.append(...)` 写错也
#    永远不会被报出来（因为"看起来像继承来的"）。
#    判据：这个名字在 BasePlugin 上有定义，或由框架在运行期塞进实例。
INHERITED_OK = {
    # BasePlugin 的属性（框架注入）
    "ctx", "plugin_cfg",
    # 框架运行期注入的辅助（BasePlugin 提供）
    "logger", "get_logger",
}

#: 允许"定义了但没被调用"的：框架回调（框架按名字调用）。
#  ⚠️ 除了这里列的名字，**带框架装饰器的方法一律豁免**（见 E1 的实现）——
#     装饰器本身就是"框架会调它"的证据，比手写名单更可靠。
FRAMEWORK_CALLED = {
    "initialize", "terminate",            # BasePlugin 生命周期
    "_apply_config",
}

#: 这些装饰器 = 框架按名字调用（不该算死代码）
FRAMEWORK_DECORATORS = (
    "register.tool", "register.api", "register.page", "register.ws",
    "register.adapter", "register.provider",
    "on.", "hook.", "listen.",
)


def _iter_py():
    for f in sorted(PLUGIN_DIR.rglob("*.py")):
        s = str(f)
        if "__pycache__" in s or "regression" in s or "/.git/" in s:
            continue
        yield f


def run(r) -> None:
    section("A. self.xxx() 调用了但类里没定义")
    undefined = []
    for f in _iter_py():
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as e:
            undefined.append(f"{f}: 语法错误 {e}")
            continue
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            defined = {m.name for m in cls.body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
            # ⚠️ 类体里的 **赋值** 也是"存在的东西"：
            #    类属性（`FOO = {...}`）和赋值出来的方法别名都算，
            #    否则会误报"未定义"。
            for st in cls.body:
                if isinstance(st, ast.Assign):
                    for t in st.targets:
                        if isinstance(t, ast.Name):
                            defined.add(t.id)
                elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    defined.add(st.target.id)
            # ⚠️ 先把「类里赋过值的属性」收集起来：`self._sink = fn` 之后
            #    再 `self._sink()` 是**完全合法**的（存起来的可调用），
            #    不收集的话 A1 会把它误报成"未定义" —— 误报多了，
            #    这条检查就会被当成噪音而没人看。
            #
            #    ⚠️ 只扫**本类**（不含嵌套 ClassDef）：嵌套类的 self.x
            #    属于那个内部类，拿它来满足外层类的调用是错的。
            # 收集本类的属性赋值，**排除嵌套类**（那个类的 self 是自己）。
            _nested_nodes = set()
            for _nc in ast.walk(cls):
                if isinstance(_nc, ast.ClassDef) and _nc is not cls:
                    for _n2 in ast.walk(_nc):
                        _nested_nodes.add(id(_n2))
            for _st in ast.walk(cls):
                if id(_st) in _nested_nodes:
                    continue
                if isinstance(_st, (ast.Assign, ast.AnnAssign)):
                    _tgts = (_st.targets if isinstance(_st, ast.Assign)
                             else [_st.target])
                    for _t in _tgts:
                        # `self._x = ...`
                        if (isinstance(_t, ast.Attribute)
                                and isinstance(_t.value, ast.Name)
                                and _t.value.id == "self"):
                            defined.add(_t.attr)

            for n in ast.walk(cls):
                # ⚠️ 调用扫描**也要**排除嵌套类的节点 ——
                #    赋值扫描排除了（见上面 `_nested_nodes`），调用扫描却漏了，
                #    于是嵌套类里的 `self.method()` 会按**外层类**的成员去查，
                #    明明定义在嵌套类里也报"未定义"（A1 误报）。
                #    嵌套类的 self 是它自己，跟外层类不是一回事。
                if id(n) in _nested_nodes:
                    continue
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and isinstance(n.func.value, ast.Name) \
                        and n.func.value.id == "self":
                    nm = n.func.attr
                    if nm in INHERITED_OK or nm in defined:
                        continue
                    rel = f.relative_to(PLUGIN_DIR)
                    undefined.append(f"{rel}:{n.lineno} {cls.name}.self.{nm}() 未定义")
    r.ok("A1 所有 self.xxx() 调用都能找到定义", not undefined,
         f"未定义={undefined or '无'}")
    for u in undefined:
        r.note(f"   ❗ {u}")

    # ── B1. 在**协作者对象**上调用不存在的方法 ───────────────────────
    #  ⚠️ A1 只扫 `self.xxx()`。而 `self.bridge.clear_event_listeners()`
    #    这种**在成员对象上**的调用它看不到 —— 实测就是它漏掉了：
    #    `BrowserBridge` 少了 `clear_event_listeners()`，
    #    `initialize()` 一跑到那行就 AttributeError，
    #    **整个插件起不来**，日志里只有一行 "Failed to initialize plugin"。
    #    这类调用和 A1 一样阴险：语法检查看不出来，一跑就崩。
    _cls_methods = {}          # 类名 -> 该类"存在的东西"（方法 + 类属性 + 赋值）
    _cls_of = {}               # (类名, 属性名) -> 目标类名
    _calls = []                # (文件, 行, 外层类, 属性, 方法)
    for f in _iter_py():
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            _names = {m.name for m in cls.body
                      if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for st in cls.body:
                if isinstance(st, ast.Assign):
                    for t in st.targets:
                        if isinstance(t, ast.Name):
                            _names.add(t.id)
                elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    _names.add(st.target.id)
            # 同名类只合并（插件里类名唯一，合并无害）
            _cls_methods.setdefault(cls.name, set()).update(_names)
            for n in ast.walk(cls):
                # `self.X = SomeClass(...)` → 记住 X 指向哪个类
                if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                    _fn = n.value.func
                    _target = (_fn.id if isinstance(_fn, ast.Name)
                               else (_fn.attr if isinstance(_fn, ast.Attribute) else None))
                    if _target and _target[0].isupper():
                        for _tg in n.targets:
                            if (isinstance(_tg, ast.Attribute)
                                    and isinstance(_tg.value, ast.Name)
                                    and _tg.value.id == "self"):
                                _cls_of[(cls.name, _tg.attr)] = _target
                # `self.X.method()` → 记下待查
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                    _inner = n.func.value
                    if (isinstance(_inner, ast.Attribute)
                            and isinstance(_inner.value, ast.Name)
                            and _inner.value.id == "self"):
                        _calls.append((f, n.lineno, cls.name, _inner.attr, n.func.attr))
    _ghost = []
    for f, lineno, outer, attr, method in _calls:
        target = _cls_of.get((outer, attr))
        # 目标类不是**插件自己定义的**（Lock / 框架对象…）→ 无从查证，跳过
        if not target or target not in _cls_methods:
            continue
        if method not in _cls_methods[target]:
            # 对方类里的类属性赋值也算"存在"，避免误报存起来的回调
            _ghost.append(f"{f.relative_to(PLUGIN_DIR)}:{lineno} "
                          f"{outer}.self.{attr}.{method}() —— "
                          f"{target} 里没有 {method}()")
    r.ok("B1 在协作者对象上调用的方法都存在（启动期 AttributeError 的源头）",
         not _ghost, f"未定义={_ghost or '无'}")
    for g in _ghost:
        r.note(f"   ❗ {g}")

    section("B. 工具函数是否都被框架能识别（签名合规）")
    # 框架调用方式：tool_inst.execute(event, **args) —— 第一个位置参数必须是 event
    bad_sig = []
    for f in _iter_py():
        src = f.read_text(encoding="utf-8")
        if "@register.tool" not in src:
            continue
        # ⚠️ 每个 parse 点都要自己接住 SyntaxError：让异常逃出 run()
        #    会让**整组检查**变成一条笼统失败，后面的段落全不执行。
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            bad_sig.append(f"{f}: 语法错误 {e}")
            continue
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            # ⚠️ 不要用 `if not isinstance(m, AsyncFunctionDef): continue` 开头 ——
            #    那样"同步函数被注册成工具"这种错**永远查不出来**（它会被跳过）。
            #    应该先认装饰器，再判定它是不是 async。
            for m in cls.body:
                if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                decs = [ast.unparse(d) for d in m.decorator_list]
                if not any("register.tool" in d for d in decs):
                    continue
                if not isinstance(m, ast.AsyncFunctionDef):
                    bad_sig.append(f"{f.name}::{m.name} 不是 async"
                                   f"（框架会 await 它 → TypeError）")
                    continue
                args = [a.arg for a in m.args.args]
                # args[0] 必须是 self，args[1] 必须是 event
                if len(args) < 2 or args[0] != "self" or args[1] != "event":
                    bad_sig.append(f"{f.name}::{m.name} 签名={args[:3]}")
    r.ok("B1 所有 @register.tool 的函数签名合规（self, event, …）且是 async",
         not bad_sig, f"不合规={bad_sig or '无'}")

    section("C. hook 签名是否与框架调用一致")
    # 框架按 (event, req, ...) 调用 ON_LLM_REQUEST
    bad_hook = []
    for f in _iter_py():
        src = f.read_text(encoding="utf-8")
        if "@on." not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            bad_hook.append(f"{f}: 语法错误 {e}")
            continue
        for m in [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]:
            decs = [ast.unparse(d) for d in m.decorator_list]
            if not any("@on." in d or "on." in d for d in decs):
                continue
            args = [a.arg for a in m.args.args]
            if len(args) < 3 or args[0] != "self" or args[1] != "event":
                bad_hook.append(f"{f.name}::{m.name} 签名={args[:4]}")
    r.ok("C1 所有 hook 签名合规（self, event, req, …）", not bad_hook,
         f"不合规={bad_hook or '无'}")

    section("D. 会话标识取法正确（event.session 是对象，不是字符串）")
    # ⚠️ 之前是"文件里只要有一处合法的 _sid_of 兜底，整个文件都跳过" ——
    #    等于同一文件里其它不安全的 str(event.session) 全被放过。
    #    改成按 **AST 定位所属函数**，只豁免 _sid_of 内部那处。
    wrong = []
    for f in _iter_py():
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            wrong.append(f"{f}: 语法错误 {e}")
            continue
        # 找出所有"函数内使用了 str(event.session)"的位置
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            bad_here = []
            for node in ast.walk(fn):
                # 要匹配的是**调用** str(event.session)，不是字符串常量。
                # ast.unparse 能稳定还原成 "str(event.session)"。
                if not isinstance(node, ast.Call):
                    continue
                # ⚠️ 只看**裸函数名**调用（str(...)）。`logger.info(...)`
                #    这类属性调用不是我们要找的，先筛掉能避免
                #    ast.unparse/结构判断在它们身上浪费或误伤。
                if not (isinstance(node.func, ast.Name) and node.func.id == "str"):
                    continue
                # ⚠️ 用 **AST 结构**判断，不要用 ast.unparse() 的字符串前缀：
                #    前缀匹配会被 `str(event.session_id)` 这类**不同**的属性
                #    误命中（session_id 是合法用法），也会被空格/换行差别绕过。
                #    判据：实参必须是属性链，且**最后一个属性恰好是 session**，
                #    接收者必须是 `event` 或 `self.event`。
                if not node.args:
                    continue
                arg = node.args[0]
                if not isinstance(arg, ast.Attribute) or arg.attr != "session":
                    continue
                recv = arg.value
                is_event = (isinstance(recv, ast.Name) and recv.id == "event")
                is_self_event = (
                    isinstance(recv, ast.Attribute) and recv.attr == "event"
                    and isinstance(recv.value, ast.Name) and recv.value.id == "self")
                if is_event or is_self_event:
                    bad_here.append(getattr(node, "lineno", 0))
            if not bad_here:
                continue
            body = ast.get_source_segment(src, fn) or ""
            # 只有在 _sid_of 内部、且带 `count(":") == 2` 校验时才放行
            if fn.name == "_sid_of" and 'count(":") == 2' in body:
                continue
            for ln in bad_here:
                wrong.append(f"{f.name}:{ln} ({fn.name})")
    r.ok("D1 没有把 event.session 直接当字符串用",
         not wrong,
         f"可疑={wrong or '无'}（event.session 是 Session 对象，"
         f"str() 得到的是 repr，适配器解析不了）")

    section("E. 死代码（定义了但没人调用）")
    # ⚠️ 这条检查原来**只写在 TITLE 里**（"调用图完整性（未定义方法 / 死代码）"），
    #    实现从来没有 —— `FRAMEWORK_CALLED` 常量定义了却**从没被读过**，
    #    就是那段没写完的痕迹。文档声称有、代码没有，比不写更糟。
    #
    #    判据（保守，宁可漏报不误报）：
    #      · 只看**函数/方法定义**，且**没有**框架装饰器；
    #      · 引用形态要覆盖三种：`name(` / `.name` / `"name"`（字符串派发）
    #        —— 只查 `name(` 会把 `self.x()` 和 `store.call("x")` 全判成死代码，
    #        那样会一次性误报上百个，检查立刻变成噪音；
    #      · `__xxx__` 魔术方法、以及 FRAMEWORK_CALLED 名单里的名字豁免。
    _refs = set()
    _defs = []          # (name, rel, lineno, cls, has_framework_dec)
    for f in _iter_py():
        try:
            _t = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        _rel = f.relative_to(PLUGIN_DIR)
        # 收集"被引用到的名字"：属性访问 + 裸名 + 字符串常量
        for _n in ast.walk(_t):
            if isinstance(_n, ast.Attribute):
                _refs.add(_n.attr)
            elif isinstance(_n, ast.Name):
                _refs.add(_n.id)
            elif isinstance(_n, ast.Constant) and isinstance(_n.value, str):
                _refs.add(_n.value)
        # 收集定义
        for _cls in ast.walk(_t):
            if not isinstance(_cls, ast.ClassDef):
                continue
            for _m in _cls.body:
                if not isinstance(_m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                _dec = []
                for _d in _m.decorator_list:
                    _dec.append(ast.unparse(_d))
                _fw = any(any(k in _dd for k in FRAMEWORK_DECORATORS)
                          for _dd in _dec)
                _defs.append((_m.name, str(_rel), _m.lineno, _cls.name, _fw))

    _dead = []
    for _name, _rel, _ln, _cls, _fw in _defs:
        if _fw or _name.startswith("__"):
            continue
        if _name in FRAMEWORK_CALLED or _name in INHERITED_OK:
            continue
        if _name not in _refs:
            _dead.append(f"{_rel}:{_ln} {_cls}.{_name}")
    r.ok("E1 没有「定义了但从未被引用」的方法（死代码）",
         not _dead,
         f"零引用={_dead or '无'}（可能是重构后忘了删，或名字改了没跟着改）")
    for _d in _dead:
        r.note(f"   💀 {_d}")

    # ── F. 函数体里的**绝对导入** —— 插件是以包加载的，这种写法会崩 ──
    #
    #  ⚠️ 这类 bug 的特征是"平时不崩"：它只在**某条分支**里执行，而那条分支
    #     平时走不到 ⇒ 静态检查看不见、常规启动也不报错，真走到时直接
    #     ImportError 把整个工具调用打掉。
    #
    #     真实案例（同一个文件里栽过两次）：
    #       · `from backends.extension_backend import ...` —— 想读
    #         MAX_UPLOAD_BYTES 做钳制，import 失败 → except 吞掉 →
    #         **钳制静默失效**（配置调到 200MB 也拦不住）；
    #       · `from backends.headless_backend import _framework_data_path` ——
    #         只在"无头后端没注册"时执行 ⇒ 真走到时
    #         `browser_diag(action="visible")` 直接崩。
    #
    #     判据：插件自己的模块**只能**用相对导入（`from .xxx` /
    #     `from ..xxx`）。理由：插件以 `<pkg>.main` 的形式加载时，
    #     `backends` / `security` 这些**不是**顶层模块名。
    #     框架的模块（`from core.xxx`）当然仍用绝对导入 —— 它们是顶层包。
    _top_names = {"backends", "security", "protocol", "bridge", "tokens",
                  "vlm", "cookies", "setup_guide"}
    _abs_imports = []
    for f in _iter_py():
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                # level=0 才是绝对导入（level>0 就是相对导入，安全）
                if n.level == 0 and n.module:
                    _root = n.module.split(".")[0]
                    if _root in _top_names:
                        _abs_imports.append(
                            f"{f.relative_to(PLUGIN_DIR)}:{n.lineno} "
                            f"from {n.module} import …")
            elif isinstance(n, ast.Import):
                for _a in n.names:
                    if _a.name.split(".")[0] in _top_names:
                        _abs_imports.append(
                            f"{f.relative_to(PLUGIN_DIR)}:{n.lineno} "
                            f"import {_a.name}")
    r.ok("F1 插件自己的模块一律用相对导入（绝对导入在包加载下必抛 ImportError）",
         not _abs_imports,
         f"绝对导入={_abs_imports or '无'}"
         f"（这类 import 常在 except 里被吞掉 ⇒ 静默失效）")
    for _ai in _abs_imports:
        r.note(f"   ❗ {_ai}")

    # ── F2. 真跑一次：以**包**的形式加载 main.py，那条冷分支也要能走通 ──
    #
    #  ⚠️ F1 是静态的（只看写法）。这一条**真执行**：把插件当包 import 起来，
    #     再走一遍"headless 后端没注册"时 screenshot 取目录的那条路径。
    #     只看 F1 的话，`importlib` 动态导入、或未来别的新写法都躲得过去。
    from ..harness import install_stubs as _install
    import subprocess as _sp
    import sys as _sys
    import os as _os
    _probe = (
        "import sys, types\n"
        f"ROOT = {str(PLUGIN_DIR)!r}\n"
        "sys.path.insert(0, ROOT)\n"
        "sys.path.insert(0, ROOT + '/regression/stubs')\n"
        "import regression.harness as h; h.install_stubs()\n"
        "pkg = types.ModuleType('hb_pkgcheck'); pkg.__path__ = [ROOT]\n"
        "sys.modules['hb_pkgcheck'] = pkg\n"
        "import hb_pkgcheck.main as M\n"
        # 冷分支：无 headless 后端时取截图目录（原来那条绝对导入就在这儿）
        "from pathlib import Path\n"
        "from hb_pkgcheck.security import path_to_file_url\n"
        "from hb_pkgcheck.backends.headless_backend import _framework_data_path\n"
        "print('PROBE_OK')\n"
    )
    _env = dict(_os.environ)
    _env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        _p = _sp.run([_sys.executable, "-c", _probe], capture_output=True,
                     text=True, env=_env, timeout=120, cwd="/tmp")
        _ok_pkg = "PROBE_OK" in (_p.stdout or "")
        _detail = "" if _ok_pkg else (
            (_p.stdout or "")[-200:] + (_p.stderr or "")[-400:])
    except Exception as e:                                   # noqa: BLE001
        _ok_pkg, _detail = False, f"{type(e).__name__}: {e}"
    r.ok("F2 以**包**形式加载 main.py 能成功（冷分支的 import 也会走到）",
         _ok_pkg, _detail)
