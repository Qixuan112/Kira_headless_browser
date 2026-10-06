"""桥接的**空闲判死**与半开连接自愈。

## 为什么要单独一个检查（这次是用户报的"假断开"）

日志里反复出现：

    50s 没收到扩展任何数据，判定连接已失效，主动断开 (session=90f7f6cf)
    扩展已连接 (session=3133e158)          ← 1 秒后又连上

这不是故障，却比故障更难缠：**刷屏**，而且用户完全没法判断它要不要修。

真根因：读超时（原来 = 心跳 25s × 2 = 50s）**一超时就断开**，而
* 扩展的 MV3 Service Worker 被浏览器回收时会静默几十秒 ——
  从服务端看，"睡着了"和"真死了"**完全一样**；
* 保活闹钟（30s）把 Service Worker 唤醒后，扩展自己就回来了 ——
  于是断开 1 秒后又连上。

修法（两侧一起）：

* **服务端两段式**：静默超过上限先**发探测包**，再给一个探测窗口；
  窗口内回话 = 虚惊一场（不断开、不换 session、不刷日志）；
  窗口内还是没动静才判死，而且同一个时间窗内只告警一次。
* **扩展侧自愈**：保活闹钟醒来时，如果"看着 OPEN 但已经 60 秒没收到服务端
  任何一帧"（服务端每 25 秒 ping 一次，所以这必不正常）→ 自己换一条新连接；
  否则发一条 ping，让服务端看见"扩展这边醒着"。

行为真验证在 ``bridge_e2e.py``（真 WebSocket）：E9 虚惊一场不许断、
E10 探测窗口内没回应才判死、E11 探测期间迟到的命令结果不许丢。
这里补的是**静态守卫 + 纯函数行为**，以及把所有权的细节钉住：
探测顺序、日志降噪、计时字段、扩展侧接线。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from ..harness import JS_DIR, PLUGIN_DIR, src_safe

TITLE = "桥接空闲判死与半开连接自愈"


def _run_js_probe(r) -> None:
    probe = JS_DIR / "bridge_stale.mjs"
    node = shutil.which("node")
    if not probe.is_file():
        r.ok("半开连接探针存在（bridge_stale.mjs）", False, f"缺少 {probe}")
        return
    if not node:
        r.warn("没有 node，跳过半开连接行为验证", "安装 Node.js 后可启用")
        return
    try:
        cp = subprocess.run(
            [node, str(probe)], cwd=str(JS_DIR), capture_output=True, text=True,
            timeout=60,
            env={"PATH": os.environ.get("PATH", "") + ":/usr/bin:/bin",
                 "KIRA_PLUGIN_DIR": str(PLUGIN_DIR)})
        items = json.loads((cp.stdout or "[]").strip().splitlines()[-1])
    except Exception as e:
        r.ok("半开连接行为验证可运行", False, f"{type(e).__name__}: {e}"[:160])
        return
    need = ("静默超过阈值判为陈旧（半开连接）",
            "保活时用 isLinkStale 判断并主动换连接",
            "保活时发一条 ping 证明自己还活着（服务端就不会误判空闲）",
            # 这条是用户问出来的："换一条新连接"这句话本身会不会刷屏？
            # 会 —— 链路真半开时每分钟一次。所以它也必须降噪。
            "换连接的日志有降噪：同一窗口只喊一次（计数照记）",
            "换连接走降噪入口（不是每次都 console.log）",
            "弹窗里能看到这个次数（用户不用翻控制台）")
    names = [str(x.get("name", "")) for x in items]
    miss = [n for n in need if n not in names]
    if miss:
        r.ok("B1 半开连接的判定与自愈接线（覆盖度）", False,
             f"缺={miss}；实际={names}")
        return
    for it in items:
        r.ok(f"B1 {it['name']}", bool(it.get("ok")), str(it.get("detail", ""))[:140])


def run(r) -> None:
    _run_js_probe(r)

    js = src_safe("browser-bridge/background.js")
    shared = src_safe("browser-bridge/shared.js")
    bridge = src_safe("bridge.py")

    # ── B2 服务端：静默之后**先探测**，不许一超时就断开 ──────────────
    #    判据做成"对源码文本的判断函数"，并自带反向自检 ——
    #    否则判据写瞎了（比如关键词改成永不命中）也照样全绿。
    def _two_stage(text: str) -> list:
        bad = []
        if "idle_probe_grace" not in text:
            bad.append("没有探测窗口（静默后直接断开 = 用户的'假断开'）")
        if "发探测包" not in text:
            bad.append("静默后没有先发探测包")
        if "note_idle_disconnect" not in text:
            bad.append("判死没有走计数/降噪的入口")
        if "IDLE_HEARTBEATS" not in text:
            bad.append("空闲上限没有按心跳周期数推导（改心跳会失配）")
        return bad

    _bad2 = _two_stage(src_safe("bridge.py"))
    # 反向自检：把探测那两段删掉，判据必须报出来
    _self2 = bool(_two_stage(
        bridge.replace("idle_probe_grace", "").replace("发探测包", "")
              .replace("note_idle_disconnect", "").replace("IDLE_HEARTBEATS", "")))
    r.ok("B2 服务端是两段式（先探测、再判死），且反向自检有效",
         not _bad2 and _self2,
         f"问题={_bad2 or '无'}；反向自检={'通过' if _self2 else '失败'}")

    # ── B3 容错窗口要盖得住 MV3 那次"回收 → 唤醒" ────────────────────
    #    实测静默 30~60 秒，所以上限不能低于 3 个心跳周期
    from ..harness import install_stubs, load_module
    install_stubs()
    try:
        # ⚠️ bridge.py 里有相对导入（`from . import protocol as P`），
        #    直接 spec_from_file_location 会 ImportError —— 必须像其它检查
        #    那样用 harness.load_module 挂在一个包下面加载。
        _pkg = "hb_bridge_idle"
        load_module("protocol", PLUGIN_DIR / "protocol.py", _pkg, PLUGIN_DIR)
        mod = load_module("bridge", PLUGIN_DIR / "bridge.py", _pkg, PLUGIN_DIR)
        B = mod.BrowserBridge

        b = B()                                   # 生产默认值
        rt = b.read_timeout
        r.ok("B3 默认空闲上限 >= 3 个心跳周期（盖得住 MV3 的休眠）",
             b.IDLE_HEARTBEATS >= 3 and rt >= b.heartbeat_interval * 3,
             f"上限={rt:.0f}s（心跳 {b.heartbeat_interval:.0f}s × "
             f"{b.IDLE_HEARTBEATS}），探测窗口 {b.IDLE_PROBE_GRACE:.0f}s")
        r.ok("B3 探测窗口短于空闲上限（探测要快问快答）",
             0 < b.IDLE_PROBE_GRACE <= b.read_timeout,
             f"探测 {b.IDLE_PROBE_GRACE:.0f}s vs 上限 {rt:.0f}s")

        # ── B4 判死日志降噪：同一时间窗内只喊一次 ────────────────────
        c = B()
        first = c.note_idle_disconnect(now=1000.0)
        second = c.note_idle_disconnect(now=1001.0)
        third = c.note_idle_disconnect(now=1002.0)
        later = c.note_idle_disconnect(now=1000.0 + c.IDLE_LOG_WINDOW + 1)
        r.ok("B4 判死日志降噪（同窗口只告警一次，但计数照记）",
             first is True and second is False and third is False and later is True
             and c.idle_disconnects == 4,
             f"第1次={first} 第2次={second} 第3次={third} 窗口后={later}；"
             f"计数={c.idle_disconnects}")
    except Exception as e:                                  # pragma: no cover
        r.ok("B3/B4 桥接空闲参数与降噪行为", False,
             f"{type(e).__name__}: {e}"[:160])

    # ── B5 扩展侧：半开连接自愈的接线 ────────────────────────────────
    _bad5 = []
    if "WS_STALE_MS" not in shared or "isLinkStale" not in shared:
        _bad5.append("shared.js 没有半开连接判定（isLinkStale / WS_STALE_MS）")
    if "this.lastInboundAt = Date.now()" not in js:
        _bad5.append("background.js 没有记录 lastInboundAt")
    if "isLinkStale(l.lastInboundAt)" not in js:
        _bad5.append("保活路径没有用 isLinkStale 判断")
    if "type: MSG.PING" not in js:
        _bad5.append("保活路径没有发 ping（服务端就看不见扩展醒着）")
    r.ok("B5 扩展侧：记录最后一帧时间 + 陈旧就自己换连接 + 发 ping 保活",
         not _bad5, f"问题={_bad5 or '无'}")

    # ── B6 服务端要能回应扩展主动发来的 ping（否则保活 ping 是单向的）──
    #    ⚠️ v2.2.0 起 PONG 走 _send_to(sess, ...)（每会话自己的连接）——
    #    用全局 _send 的话，被替换的旧会话会把帧串到新连接上。
    #    判据因此认"回 pong 且走每会话发送"这一对组合。
    r.ok("B6 服务端处理扩展主动发来的 ping（回 pong，并重置空闲计时）",
         "MSG_PING" in bridge and "MSG_PONG" in bridge
         and "await self._send_to(sess, {\"type\": P.MSG_PONG" in bridge,
         "收到扩展 ping 要回 pong（回到自己那条连接）；"
         "任何一帧都会把空闲计时清零")
