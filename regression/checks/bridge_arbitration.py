"""桥接「先自证、后仲裁」与扩展侧重连纪律。

## 为什么单独一个检查（2026-10-06 的重连风暴）

线上日志：每 2~6 秒一轮「已有扩展连接，主动断开旧连接 → 扩展已连接」，
八分钟刷了上百行，**永不停止**。根因是四个缺陷叠加：

1. 服务端 accept 后**先踢旧连接**、再等新连接 hello —— 任何不说 hello 的
   幽灵连接（迟到的孤儿 socket / 探测流量）都能把健康连接顶掉；
   而且 hello 超时后「仍继续建立连接」，幽灵被扶正。
2. 扩展被踢（close code 4001 Replaced）不区分对待，1 秒后照常重连。
3. 扩展 `onopen` 就清零 `reconnectAttempt` —— 互踢时每次都能"连上"，
   指数退避永远停在 1 秒档。
4. 实例去重键是字符串 `host:port`：`localhost` 与 `127.0.0.1` 是同一台
   服务器的两个写法，被存成两条实例、两条连接互踢。

修法（两侧）：
- 服务端：**两段式**（hello 自证 → 才仲裁踢人）+ 世代守卫（被替换的旧会话
  立即停收，帧不串到新连接）+ 每会话发送锁与发送超时 + 顶替日志降噪
  （同一 client_id 重连 = MV3 唤醒，DEBUG；另一处顶号才 WARNING）。
- 扩展：认 4001 退让 / 退避不被"假成功"重置 / 孤儿 socket 立即处死 /
  实例按归一化 host + 身份（token / data_dir）去重 / page_pair 的
  changed 判断修对 / 保活闹钟不清退避。

这里钉住这些行为，防回退。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess

from ..harness import JS_DIR, PLUGIN_DIR, install_stubs, load_module, src_safe

TITLE = "桥接仲裁（先自证后踢人）与重连纪律"


# ── Mock WebSocket（Starlette 接口形状）─────────────────────────────────────

class _WS:
    def __init__(self, script=None):
        self.sent = []
        self.closed = None
        self.accepted = False
        self._q = asyncio.Queue()
        for f in (script or []):
            self._q.put_nowait(f)

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        item = await self._q.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)
        from starlette.websockets import WebSocketDisconnect
        self._q.put_nowait(WebSocketDisconnect(code=code))


def _hello(cid=""):
    return json.dumps({"type": "hello", "extension_version": "1.6.0",
                       "browser": "Chrome", "protocol": 1, "client_id": cid})


class _LogTap:
    """把 core.logging_manager 的 logger 换成可读取的（按名字缓存）。"""

    logs: list = []

    @classmethod
    def install(cls):
        cls.logs = []
        import core.logging_manager as lm

        def _get(name, color=None):
            class _L:
                def _e(self, lv, m): cls.logs.append((lv, m))
                def info(self, m): self._e("INFO", m)
                def warning(self, m): self._e("WARNING", m)
                def error(self, m): self._e("ERROR", m)
                def debug(self, m): self._e("DEBUG", m)
            return _L()
        lm.get_logger = _get


def _load_bridge(r):
    install_stubs()
    _LogTap.install()
    pkg = "hb_arbitration"
    load_module("protocol", PLUGIN_DIR / "protocol.py", pkg, PLUGIN_DIR)
    return load_module("bridge", PLUGIN_DIR / "bridge.py", pkg, PLUGIN_DIR)


def run(r) -> None:
    # ══════════════════════════════════════════════════════════════════
    # A. 服务端行为（真 bridge.py + mock ws）
    # ══════════════════════════════════════════════════════════════════
    try:
        mod = _load_bridge(r)
        B = mod.BrowserBridge

        async def _behavior():
            out = {}

            # A1 幽灵连接（永不说 hello）不得踢掉健康连接
            b = B()
            b.HELLO_TIMEOUT = 0.25          # 压短等待，测试不必真等 5 秒
            good = _WS(script=[_hello("ext-aaa")])
            t1 = asyncio.create_task(b.handle_connection(good))
            await asyncio.sleep(0.1)
            ghost = _WS()
            t2 = asyncio.create_task(b.handle_connection(ghost))
            await asyncio.sleep(0.6)
            out["ghost_rejected_count"] = b.ghost_rejected
            out["good_alive"] = good.closed is None and b.connected
            out["ghost_closed"] = ghost.closed is not None and ghost.closed[0] == 4000
            t1.cancel(); t2.cancel()
            for t in (t1, t2):
                try:
                    await t
                except BaseException:
                    pass

            # A2 自证通过的新连接才踢人（4001）
            _LogTap.logs.clear()
            b2 = B()
            a = _WS(script=[_hello("ext-one")])
            ta = asyncio.create_task(b2.handle_connection(a))
            await asyncio.sleep(0.1)
            a2 = _WS(script=[_hello("ext-one")])       # 同一实例重连
            ta2 = asyncio.create_task(b2.handle_connection(a2))
            await asyncio.sleep(0.2)
            out["old_kicked_4001"] = a.closed is not None and a.closed[0] == 4001
            warns = [m for lv, m in _LogTap.logs
                     if lv == "WARNING" and "顶替" in m]
            out["same_client_no_warning"] = not warns
            out["connected_after"] = b2.connected
            ta.cancel(); ta2.cancel()
            for t in (ta, ta2):
                try:
                    await t
                except BaseException:
                    pass

            # A3 另一处连接顶号 → 恰好一条 WARNING（该看见的看得见）
            _LogTap.logs.clear()
            b3 = B()
            x = _WS(script=[_hello("ext-AAA")])
            tx = asyncio.create_task(b3.handle_connection(x))
            await asyncio.sleep(0.1)
            y = _WS(script=[_hello("ext-BBB")])
            ty = asyncio.create_task(b3.handle_connection(y))
            await asyncio.sleep(0.2)
            warns3 = [m for lv, m in _LogTap.logs
                      if lv == "WARNING" and "顶替" in m]
            out["other_client_warns"] = len(warns3) == 1
            out["replaced_total"] = b3.replaced_total
            tx.cancel(); ty.cancel()
            for t in (tx, ty):
                try:
                    await t
                except BaseException:
                    pass

            # A4 世代守卫：被替换会话的帧不再被处理（不 resolve、不派事件）
            b4 = B()
            old = _WS(script=[_hello("ext-o")])
            to = asyncio.create_task(b4.handle_connection(old))
            await asyncio.sleep(0.1)
            new = _WS(script=[_hello("ext-n")])
            tn = asyncio.create_task(b4.handle_connection(new))
            await asyncio.sleep(0.1)
            fut = asyncio.get_running_loop().create_future()
            b4._pending["victim"] = fut

            class _Stale:                      # 一个"非当前"会话对象
                pass

            await b4._on_message(_Stale(), json.dumps(
                {"type": "result", "id": "victim", "ok": True, "data": {}}))
            out["stale_frame_dropped"] = not fut.done()
            # 当前会话的同名 result 仍正常 resolve
            cur = b4._session
            await b4._on_message(cur, json.dumps(
                {"type": "result", "id": "victim", "ok": True, "data": {"ok": 1}}))
            out["live_frame_works"] = fut.done() and fut.result().ok
            to.cancel(); tn.cancel()
            for t in (to, tn):
                try:
                    await t
                except BaseException:
                    pass

            # A5 心跳用**实例参数**（压到 0.05s 要能观察到 ping）
            b5 = B(heartbeat_interval=0.05)
            w = _WS(script=[_hello("ext-hb")])
            th = asyncio.create_task(b5.handle_connection(w))
            await asyncio.sleep(0.25)
            pings = [m for m in w.sent if m.get("type") == "ping"]
            out["heartbeat_uses_instance_param"] = len(pings) >= 2
            th.cancel()
            try:
                await th
            except BaseException:
                pass
            return out

        res = asyncio.run(_behavior())

        r.ok("A1 幽灵连接被安静关闭、**不踢**健康连接",
             res.get("good_alive") and res.get("ghost_closed")
             and res.get("ghost_rejected_count", 0) >= 1,
             f"good_alive={res.get('good_alive')} "
             f"ghost_closed={res.get('ghost_closed')} "
             f"ghosts={res.get('ghost_rejected_count')}")
        r.ok("A2 自证通过才仲裁：旧连接收 4001；同一实例重连不刷 WARNING",
             res.get("old_kicked_4001") and res.get("same_client_no_warning")
             and res.get("connected_after"),
             f"4001={res.get('old_kicked_4001')} "
             f"无告警={res.get('same_client_no_warning')}")
        r.ok("A3 另一处顶号 → 恰好一条 WARNING（含降噪计数）",
             res.get("other_client_warns") and res.get("replaced_total") == 1,
             f"warns={res.get('other_client_warns')} "
             f"total={res.get('replaced_total')}")
        r.ok("A4 世代守卫：旧会话的帧丢弃、当前会话的帧正常",
             res.get("stale_frame_dropped") and res.get("live_frame_works"),
             f"丢弃={res.get('stale_frame_dropped')} "
             f"正常={res.get('live_frame_works')}")
        r.ok("A5 心跳间隔用实例参数（不被类常量钉死）",
             res.get("heartbeat_uses_instance_param"),
             "heartbeat_interval=0.05 时 0.25s 内应发出 >=2 个 ping")
    except Exception as e:
        r.ok("A 组：桥接仲裁行为可运行", False, f"{type(e).__name__}: {e}"[:180])

    # ══════════════════════════════════════════════════════════════════
    # B. 服务端静态守卫（防把两段式改回去）
    # ══════════════════════════════════════════════════════════════════
    bridge = src_safe("bridge.py")

    def _two_stage_gate(text: str) -> list:
        bad = []
        if "HELLO_TIMEOUT" not in text:
            bad.append("没有 hello 时限（幽灵会一直挂着）")
        if "Hello required" not in text:
            bad.append("幽灵没有被关闭（Hello required）")
        if "仍继续建立连接" in text:
            bad.append("hello 超时仍扶正 —— 幽灵又会被当成正式连接")
        # 仲裁必须在 hello 解析**之后**：比较两段文本的位置
        i_hello = text.find("P.HelloPayload.from_wire(msg)")
        i_retire = text.find("await self._retire(old,")
        if not (0 < i_hello < i_retire):
            bad.append("仲裁（retire）不在 hello 解析之后 —— 又回到先踢后问")
        return bad

    _badB = _two_stage_gate(bridge)
    # 反向自检：把关键片段抹掉，判据必须报出来
    _selfB = bool(_two_stage_gate(
        bridge.replace("HELLO_TIMEOUT", "").replace("Hello required", "")))
    r.ok("B1 两段式（先 hello 自证、后仲裁踢人），且反向自检有效",
         not _badB and _selfB,
         f"问题={_badB or '无'}；反向自检={'通过' if _selfB else '失败'}")

    r.ok("B2 每会话发送锁 + 发送超时（防锁 convoy / 反压挂死）",
         "send_lock" in bridge and "SEND_TIMEOUT" in bridge
         and "_send_to" in bridge,
         "全局锁会让慢客户端堵住所有会话；无发送超时会无限挂")

    r.ok("B3 世代守卫存在（旧会话停收）",
         "sess is not self._session" in bridge,
         "没有世代守卫，被替换的旧会话会继续收消息、串到新连接")

    r.ok("B4 顶替日志按 client_id 分级且降噪",
         "replaced_same_client" in bridge and "REPLACED_LOG_WINDOW" in bridge
         and "_note_replaced" in bridge,
         "同一实例重连要 DEBUG，另一处顶号才 WARNING（窗口内一次）")

    # ══════════════════════════════════════════════════════════════════
    # C. 扩展侧重连纪律（静态守卫 + JS 行为探针）
    # ══════════════════════════════════════════════════════════════════
    bg = src_safe("browser-bridge/background.js")
    proto = src_safe("browser-bridge/protocol.js")

    r.ok("C1 扩展认 4001（被顶替 → 退让期，不立即反踢）",
         "ev.code === 4001" in bg and "parkUntil" in bg
         and "REPLACED_PARK_MS" in bg,
         "被踢立刻重连 = 把对方踢掉、对方再踢回来（乒乓风暴）")

    # onopen 不再清零退避；稳定存活才清。
    # ⚠️ 判据要认"清零在 stableTimer 的 setTimeout 回调**里面**" ——
    #    不能只看 onopen 片段里有没有 `reconnectAttempt = 0` 子串：
    #    稳定计时器的回调就在 onopen 里（它本来就**应该**在那）。
    _onopen = bg.split("ws.onopen = ", 1)[1] if "ws.onopen = " in bg else ""
    _onopen_seg = _onopen[:1800]
    _timer_at = _onopen_seg.find("this.stableTimer = setTimeout(")
    _reset_at = _onopen_seg.find("this.reconnectAttempt = 0")
    r.ok("C2 onopen 不重置退避（清零只在稳定计时器回调里）",
         "STABLE_RESET_MS" in bg and _timer_at > 0
         and _reset_at > _timer_at,
         f"timer@{_timer_at} reset@{_reset_at} —— "
         f"onopen 直接清零 = 互踢时退避永远停在 1 秒档")

    r.ok("C3 孤儿 socket 被处死（onopen/onmessage/onclose 都调 disown）",
         bg.count("disown()") >= 3 and "const disown" in bg,
         "迟到的 onopen 只 return 的话，孤儿永远不发 hello（服务端的幽灵）")

    r.ok("C4 实例去重走归一化 key（localhost ⟷ 127.0.0.1 合并）",
         "normalizeHost" in proto and "instanceKey" in proto
         and "instanceKey(" in bg,
         "字符串 host:port 当 key = 同一台服务器被连两次，互踢")

    r.ok("C5 page_pair 的 changed 判断基于实例列表（不再恒 true）",
         "instanceKey(p)" in bg and "existing.token !== p.token" in bg,
         "before.token 是 undefined —— 恒 true 会让手动断开被自动撤销")

    r.ok("C6 保活闹钟不清退避、不越过退让期",
         "l.reconnectAttempt = 0" not in bg.split("ensureAlive", 1)[1][:2600]
         if "ensureAlive" in bg else False,
         "每 30s 清零一次 = 指数退避名存实亡")

    r.ok("C7 hello 携带持久化 client_id（服务端才能分辨同实例重连）",
         "getClientId" in bg and "client_id" in bg
         and "CLIENT_ID" in proto,
         "没有稳定身份，MV3 唤醒和另一台浏览器顶号就分不出来")

    # ── JS 行为探针（真跑 background.js 的 Link / upsertInstance）────
    probe = JS_DIR / "reconnect_arbitration.mjs"
    node = shutil.which("node")
    if not probe.is_file():
        r.ok("C8 重连纪律行为探针存在", False, f"缺少 {probe}")
    elif not node:
        r.warn("没有 node，跳过重连纪律行为验证", "安装 Node.js 后可启用")
    else:
        try:
            cp = subprocess.run(
                [node, str(probe)], cwd=str(JS_DIR), capture_output=True,
                text=True, timeout=60,
                env={"PATH": os.environ.get("PATH", "") + ":/usr/bin:/bin",
                     "KIRA_PLUGIN_DIR": str(PLUGIN_DIR)})
            items = json.loads((cp.stdout or "[]").strip().splitlines()[-1])
        except Exception as e:
            r.ok("C8 重连纪律行为验证可运行", False,
                 f"{type(e).__name__}: {e}"[:160])
            items = None
        if items is not None:
            for it in items:
                r.ok(f"C8 {it.get('name', '?')}", bool(it.get("ok")),
                     str(it.get("detail", ""))[:140])

    # ══════════════════════════════════════════════════════════════════
    # D. 面板配对要带实例标识（身份去重的燃料）
    # ══════════════════════════════════════════════════════════════════
    main = src_safe("main.py")
    appjs = src_safe("web/app.js")
    pairjs = src_safe("browser-bridge/pairing-page.js")
    r.ok("D1 /token 响应带实例标识（instance/data_dir）",
         "_instance_label()" in main.split("api_issue_token", 1)[1][:2000]
         if "api_issue_token" in main else False,
         "扩展拿不到 data_dir 就没法做身份级合并")
    r.ok("D2 面板推送配对时带 instance/data_dir",
         "data_dir" in appjs and "pairWithExtension" in appjs,
         "面板是配对主入口，它不带标识 = 身份合并形同虚设")
    r.ok("D3 pairing-page 转发 instance/data_dir",
         "d.instance" in pairjs and "d.data_dir" in pairjs)
