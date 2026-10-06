"""Bridge —— 与浏览器扩展的长连接管理与会话路由。

设计要点：

1. **扩展主动连出**。浏览器扩展无法监听端口，所以由扩展作为 WebSocket 客户端
   连到 KiraAI 的 ``/ws/plugin/headless_browser/bridge``。

2. **请求/应答配对**。插件下发 ``cmd``（带唯一 ``id``），为每个 id 建一个
   ``asyncio.Future``，扩展返回 ``result`` 时按 id 唤醒。这样 Tool 调用可以
   ``await`` 到扩展的返回值。

3. **单连接模型 + 先自证后仲裁**。同一时刻只接受一个扩展连接 —— 但新连接
   必须先说过 ``hello`` 才有资格踢掉旧连接（旧版是 accept 完就踢，于是
   任何幽灵连接都能把健康连接顶掉，这是"重连风暴"的服务端半边）。
   被替换的旧会话由**世代守卫**立即停收，它的帧不会再串到新连接上。

4. **事件回调**。扩展主动上报的 ``event`` 不等待应答，直接分发给注册的监听者，
   用于"可感知"（页面加载、标签切换）。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from core.logging_manager import get_logger

from . import protocol as P

logger = get_logger("browser_bridge", "cyan")


class BridgeNotConnected(RuntimeError):
    """扩展尚未连接。"""


class BridgeTimeout(RuntimeError):
    """等待扩展响应超时。"""


class BridgeError(RuntimeError):
    """扩展返回了错误。"""

    #: 扩展上报的错误类别（如 ``"timeout"``）。None 表示未分类。
    err_code: Optional[str] = None


class _Session:
    """一条**已完成 hello 自证**的扩展连接。

    为什么需要一个对象而不只是几个散字段：被替换的旧会话要能"整套退役"
    （它自己的 socket、自己的发送锁、自己的心跳任务、自己的计时），
    而不是和新会话共用 —— 旧版共用全局 ``self._ws`` 与全局发送锁，
    于是旧会话迟到的帧会发到**新连接**上（串话），给慢客户端发大消息时
    还会把所有会话的发送全堵住（锁 convoy）。
    """

    __slots__ = ("ws", "session_id", "hello", "client_id", "generation",
                 "connected_at", "send_lock", "heartbeat_task",
                 "last_inbound", "probing")

    def __init__(self, ws, session_id: str, hello: "P.HelloPayload",
                 generation: int):
        self.ws = ws
        self.session_id = session_id
        self.hello = hello
        self.client_id = getattr(hello, "client_id", "") or ""
        self.generation = generation
        self.connected_at = time.time()
        #: 每会话自己的发送锁：同一条 socket 上的多协程发送串行化，
        #: 但不连累其它会话。
        self.send_lock = asyncio.Lock()
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.last_inbound = time.time()
        self.probing = False


class BrowserBridge:
    """管理唯一的扩展连接，并提供 ``send_command`` 请求/应答能力。"""

    #: 心跳间隔（秒）。扩展的 MV3 Service Worker 会被浏览器回收，
    #: 这个间隔决定了回收后多久能被发现。
    HEARTBEAT_INTERVAL = 25.0

    #: 判定"对面彻底没动静"要经历几个心跳周期。
    #:
    #: ⚠️ **别调小**（调小就会重演"假断开"）：扩展的 MV3 Service Worker 被
    #:    浏览器回收时，会有几十秒完全不回话，然后被保活闹钟唤醒、自己回来 ——
    #:    从服务端看，"睡着了"和"真死了"**长得一模一样**。
    #:    所以容错窗口要盖过一个完整的"回收 → 唤醒"周期（实测 30~60 秒）。
    IDLE_HEARTBEATS = 3

    #: 探测窗口（秒）：静默超过上限后**先发一个探测包**再等这么久。
    #: 回来了就是虚惊一场（不计断开、不刷日志、session 不变），
    #: 还是没动静才判死。
    IDLE_PROBE_GRACE = 6.0

    #: 同一时间窗内"探测后判死"的日志只喊一次（秒）。
    #: 连接抖动本身没什么可看性，但整页刷屏会淹掉真正的错误。
    IDLE_LOG_WINDOW = 300.0

    #: 等新连接自报家门（hello）的时限（秒）。
    #: 真正的扩展 onopen 就立刻发 hello，几秒足够；**超时不说 = 幽灵连接**
    #: （迟到的孤儿 socket / 探测流量 / 不说话的旧客户端），安静关掉，
    #: 绝不扶正、更不踢掉现有连接。
    HELLO_TIMEOUT = 5.0

    #: 单帧发送超时（秒）。慢客户端（Service Worker 睡眠 + TCP 反压）会把
    #: ``send_text`` 挂住 —— 不能让它握着锁无限等（大截图数 MB 时尤其明显）。
    SEND_TIMEOUT = 10.0

    #: "被另一处连接顶替"的告警降噪窗口（秒）。
    #: 两处扩展互踢时每几秒就会有一次替换，整页刷屏会淹掉真正的错误。
    REPLACED_LOG_WINDOW = 300.0

    def __init__(self, command_timeout: float = 20.0,
                 heartbeat_interval: Optional[float] = None,
                 idle_probe_grace: Optional[float] = None,
                 idle_timeout: Optional[float] = None):
        self.command_timeout = command_timeout
        # 这三个开放成实例参数，测试里可以压到毫秒级（否则一条用例要等一分多钟）
        self.heartbeat_interval = float(
            self.HEARTBEAT_INTERVAL if heartbeat_interval is None else heartbeat_interval)
        self.idle_probe_grace = float(
            self.IDLE_PROBE_GRACE if idle_probe_grace is None else idle_probe_grace)
        self.idle_timeout = idle_timeout          # None → 按下面的公式推

        # 空闲与探活的统计（面板自检 / 诊断用）
        self.idle_probes = 0            # 发过多少次探测包
        self.idle_disconnects = 0       # 探测后仍然没动静、真判死了多少次
        self._idle_log_at = 0.0
        self._idle_log_suppressed = 0

        # ── 当前会话（唯一）。所有"当前连接"状态都在这个对象上 ──
        self._session: Optional[_Session] = None
        #: 世代号：每次扶正新会话 +1。旧会话的接收循环据此知道自己被替换，
        #: 立即停收 —— 它的帧不会再被处理（也不会串到新连接上）。
        self._generation = 0

        # 连接质量统计（面板/诊断）
        self.ghost_rejected = 0         # 没说 hello 被安静关掉的幽灵连接数
        self.replaced_total = 0         # 发生过的"踢人"总数
        self.replaced_same_client = 0   # 其中"同一扩展实例重连"（MV3 唤醒）的次数
        self._replaced_log_at = 0.0
        self._replaced_suppressed = 0

        # cmd_id -> Future[BridgeResult]
        self._pending: Dict[str, asyncio.Future] = {}

        # 事件监听者：name -> [callback]
        self._event_listeners: Dict[str, list] = {}
        self._any_listener: list = []

        # cmd_id -> 一个「分块接收器」。下载时扩展边收边回传，
        # 这里**边收边写盘**，不把整份文件攒在内存里。
        #   {"path": 目标文件, "handle": 打开的文件对象, "total": 已收字节}
        self._sinks: Dict[str, dict] = {}

        # 统计
        self.commands_sent = 0
        self.commands_failed = 0

    # ─── 兼容镜像（外部与回归测试读/写这些字段）─────────────────────────
    #  真实状态在 self._session 上；这几个属性只是它的投影，便于
    #  `bridge._session_id` / `bridge._hello` 这类既有读写不破
    #  （回归里 ext_update 会 `_ws = object()` + 直写 `_hello` 来模拟
    #   "扩展连着且报了版本"，语义必须与旧版一致）。

    def _ensure_shell(self):
        """没有会话时造一个"外部直写用"的壳会话（仅测试/展示路径会触发）。"""
        if self._session is None:
            self._generation += 1
            self._session = _Session(None, "external",
                                     P.HelloPayload(), self._generation)
        return self._session

    @property
    def _ws(self):
        return self._session.ws if self._session else None

    @_ws.setter
    def _ws(self, value):
        if value is None:
            self._session = None
        else:
            self._ensure_shell().ws = value

    @property
    def _session_id(self) -> Optional[str]:
        return self._session.session_id if self._session else None

    @_session_id.setter
    def _session_id(self, value):
        if value is None:
            self._session = None
        else:
            self._ensure_shell().session_id = value

    @property
    def _hello(self) -> Optional["P.HelloPayload"]:
        return self._session.hello if self._session else None

    @_hello.setter
    def _hello(self, value):
        if value is None:
            if self._session is not None:
                self._session.hello = None
            return
        self._ensure_shell().hello = value

    @property
    def _connected_at(self) -> float:
        return self._session.connected_at if self._session else 0.0

    @_connected_at.setter
    def _connected_at(self, value):
        if not value:
            self._session = None
        else:
            self._ensure_shell().connected_at = float(value)

    # ─── 连接生命周期 ────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        # ⚠️ 必须连 ws 一起看：兼容壳会话（外部直写 _hello 的展示壳）没有
        #    socket，不能算"已连接"。旧版语义就是 `self._ws is not None`。
        return self._session is not None and self._session.ws is not None

    @property
    def read_timeout(self) -> float:
        """多久没收到扩展任何数据就**开始探测**（不是直接断开）。

        取「心跳间隔的 IDLE_HEARTBEATS 倍」和「命令超时 + 余量」里更大的那个：
        前者盖住 MV3 那次"回收 → 唤醒"的静默（实测 30~60 秒），
        后者保证不会在正常等长命令时误判。
        """
        if self.idle_timeout:
            return float(self.idle_timeout)
        return max(self.heartbeat_interval * self.IDLE_HEARTBEATS,
                   self.command_timeout + 10.0)

    @property
    def last_inbound_ago(self) -> float:
        """距离上次收到扩展数据过了多久（秒）；从没收到过返回 0。"""
        sess = self._session
        if sess is None or not sess.last_inbound:
            return 0.0
        return time.time() - sess.last_inbound

    def note_idle_disconnect(self, now: Optional[float] = None) -> bool:
        """记一次"探测过、仍然没动静"的判死。

        返回**这次要不要记 WARNING** —— 同一个 ``IDLE_LOG_WINDOW`` 窗口里
        只喊一次，其余只累加计数（日志刷屏会把真正的错误淹掉）。
        """
        now = time.time() if now is None else now
        self.idle_disconnects += 1
        if self._idle_log_at and (now - self._idle_log_at) < self.IDLE_LOG_WINDOW:
            self._idle_log_suppressed += 1
            return False
        self._idle_log_at = now
        self._idle_log_suppressed = 0
        return True

    def _note_replaced(self, same_client: bool, new_id: str, old_id: str) -> None:
        """记一次"顶替"日志。

        - 同一 ``client_id`` 回来 = MV3 Service Worker 回收后被闹钟唤醒，
          **正常现象**，DEBUG 一笔带过；
        - 不同 client_id 顶号 = 第二台浏览器 / 重复实例条目在互踢 ——
          这是用户**必须看见**的，但互踢时几秒一条会刷屏，
          所以 REPLACED_LOG_WINDOW 内只 WARNING 一次，其余计数。
        """
        self.replaced_total += 1
        if same_client:
            self.replaced_same_client += 1
            logger.debug(f"同一扩展实例重连，替换旧连接（MV3 唤醒，正常）"
                         f" ({old_id} → {new_id})")
            return
        now = time.time()
        if self._replaced_log_at and (now - self._replaced_log_at) < self.REPLACED_LOG_WINDOW:
            self._replaced_suppressed += 1
            logger.debug(f"连接被另一处顶替（已降噪，{self.REPLACED_LOG_WINDOW:.0f}s 内"
                         f"累计 {self.replaced_total} 次）({old_id} → {new_id})")
            return
        suppressed = self._replaced_suppressed
        self._replaced_log_at = now
        self._replaced_suppressed = 0
        logger.warning(
            f"扩展连接被另一处连接顶替 ({old_id} → {new_id})。"
            f"如果日志里这条反复出现：多半是有**两个浏览器/两条重复实例**同时连着"
            f"本插件在互踢 —— 在扩展弹窗里删掉重复实例，或让另一台浏览器断开。"
            + (f"（上一窗口内还有 {suppressed} 次被降噪）" if suppressed else ""))

    @property
    def info(self) -> dict:
        sess = self._session
        hello = sess.hello if sess else None
        return {
            "connected": self.connected,
            "session_id": sess.session_id if sess else None,
            "extension_version": getattr(hello, "extension_version", None),
            "browser": getattr(hello, "browser", None),
            "protocol": getattr(hello, "protocol", None),
            "client_id": getattr(hello, "client_id", "") or "",
            "connected_at": sess.connected_at if sess else None,
            "uptime": (time.time() - sess.connected_at) if sess else 0,
            # 空闲探活的诊断：探测过多少次、真判死过多少次、上次收到数据多久前。
            # （面板上"扩展一断一合"到底是不是问题，看这三个数就清楚了）
            "idle_probes": self.idle_probes,
            "idle_disconnects": self.idle_disconnects,
            "last_inbound_ago": round(self.last_inbound_ago, 1),
            # 风暴诊断：幽灵数 / 顶替总数 / 其中同一实例的正常重连数。
            # "扩展一断一合"时：同实例数涨 = MV3 正常唤醒；总数涨得更快 = 互踢。
            "ghost_rejected": self.ghost_rejected,
            "replaced_total": self.replaced_total,
            "replaced_same_client": self.replaced_same_client,
            "commands_sent": self.commands_sent,
            "commands_failed": self.commands_failed,
        }

    async def handle_connection(self, ws) -> None:
        """处理一条新的扩展连接。由插件 WS 端点调用。

        **必须先 accept**：KiraAI 的插件 WS 路由把原始 ``WebSocket`` 对象直接交给
        插件 handler（见 ``plugin_registry._register_plugin_ws_for``），鉴权依赖
        ``require_ws_auth`` 只做校验、不负责握手。所以 ``accept()`` 由本函数负责。
        漏掉它会得到「ASGI callable returned without sending handshake」，
        客户端表现为连上即断、反复重连。

        **两段式**（v2.2.0 重构的核心）：

          第一段「自证」：accept 之后先等 hello（``HELLO_TIMEOUT`` 秒）。
            不说 hello 的连接 = 幽灵（迟到的孤儿 socket / 探测流量），
            **安静关掉** —— 绝不扶正，更**绝不踢掉现有连接**。
            （旧版是 accept 完就先踢旧的，于是任何能连上的人都能把
              健康连接顶掉 —— 这是"重连风暴"日志刷屏的服务端半边。）

          第二段「仲裁」：hello 合法之后，才踢掉旧连接、扶正自己。
            踢人日志按 ``client_id`` 区分"同一实例重连"（正常）与
            "另一处顶号"（该告警，但降噪），见 :meth:`_note_replaced`。
        """
        session_id = uuid.uuid4().hex[:8]

        # 握手：接受连接后才能收发消息
        try:
            await ws.accept()
        except Exception as e:
            logger.warning(f"WebSocket 握手失败: {type(e).__name__}: {e}")
            return

        # ── 第一段：自证 ────────────────────────────────────────────────
        try:
            raw = await asyncio.wait_for(ws.receive_text(),
                                         timeout=self.HELLO_TIMEOUT)
        except asyncio.TimeoutError:
            self.ghost_rejected += 1
            logger.debug(
                f"连接 {self.HELLO_TIMEOUT:.0f}s 内没有 hello，按幽灵连接关闭"
                f"（不触碰现有连接；累计 {self.ghost_rejected} 次）")
            await self._close_ws(ws, code=4000, reason="Hello required")
            return
        except Exception as e:
            # 对方自己走了（断开/帧坏）—— 它自己放弃的，不必留 INFO 痕迹
            logger.debug(f"连接在 hello 之前结束: {type(e).__name__}")
            return

        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self.ghost_rejected += 1
            logger.debug(f"首帧不是合法 JSON，按幽灵连接关闭 (session={session_id})")
            await self._close_ws(ws, code=4000, reason="Hello required")
            return
        if msg.get("type") != P.MSG_HELLO:
            self.ghost_rejected += 1
            logger.debug(f"首帧不是 hello（实际为 {msg.get('type')!r}），关闭")
            await self._close_ws(ws, code=4000, reason="Hello required")
            return

        hello = P.HelloPayload.from_wire(msg)

        # ── 第二段：仲裁（自证通过之后才踢人）─────────────────────────
        old = self._session
        if old is not None:
            same = bool(hello.client_id) and hello.client_id == old.client_id
            self._note_replaced(same, session_id, old.session_id)
            # ⚠️ retire 会一次性做完：cancel 心跳 + 失败在途命令 + 收掉下载
            #    sink + 关 socket。只关 socket 的话，旧连接上的在途命令会一直
            #    等到超时，下载 sink 的文件句柄也一直开着到那时。
            await self._retire(old, code=4001,
                               reason="Replaced by a new connection")

        self._generation += 1
        sess = _Session(ws, session_id, hello, self._generation)
        self._session = sess

        logger.info(
            f"扩展已连接 (session={session_id})"
            f" [{hello.browser} v{hello.extension_version} proto={hello.protocol}"
            + (f" id={hello.client_id[:8]}]" if hello.client_id else "]"))
        if hello.protocol != P.PROTOCOL_VERSION:
            logger.warning(
                f"协议版本不一致: 扩展={hello.protocol} "
                f"插件={P.PROTOCOL_VERSION}，可能出现兼容问题"
            )

        try:
            await self._send_to(sess, {"type": P.MSG_WELCOME,
                                       "protocol": P.PROTOCOL_VERSION,
                                       "session_id": session_id})

            sess.heartbeat_task = asyncio.create_task(self._heartbeat_loop(sess))

            # 主接收循环。
            #
            # 读超时的作用：只靠心跳 ping 是不够的 —— 扩展被休眠/唤醒、
            # MV3 Service Worker 被系统回收之后，socket 会成为**半开连接**：
            # send 可能不报错，但对面永远不回。此时会话仍然显示"已连接"，
            # 而每个工具调用都卡到超时。
            #
            # ⚠️⚠️ 但**不能一超时就断开** —— 那正是"假断开"的来源：
            #     扩展的 Service Worker 被回收时会静默几十秒，从服务端看
            #     跟"真死了"一模一样；等保活闹钟把它唤醒，它自己就回来了
            #     （用户在日志里看到的就是"断开 → 1 秒后又连上"，还刷屏）。
            #     所以走**两段式**：
            #       第一段：静默超过 read_timeout → 只**发一个探测包**，
            #               再用 IDLE_PROBE_GRACE 的短窗口等它回话；
            #       第二段：探测窗口里依然一个字都没有 → 才判定失效、断开。
            #     任何一帧数据（pong / 命令结果 / 事件）都会把状态清零。
            sess.last_inbound = time.time()
            sess.probing = False
            while True:
                # 世代守卫：被新连接替换之后，本会话**立刻停收** ——
                # 它的帧（含迟到的 WELCOME/PONG）不再处理，更不会发到别处。
                if sess is not self._session:
                    break
                try:
                    raw = await asyncio.wait_for(
                        ws.receive_text(),
                        timeout=(self.idle_probe_grace if sess.probing
                                 else self.read_timeout))
                except asyncio.TimeoutError:
                    if sess is not self._session:
                        break
                    if not sess.probing:
                        sess.probing = True
                        self.idle_probes += 1
                        logger.info(
                            f"{self.read_timeout:.0f}s 没收到扩展数据，发探测包确认"
                            f"（MV3 的 Service Worker 休眠时就是这样，通常马上回来）"
                            f" (session={session_id})"
                        )
                        try:
                            await self._send_to(sess, {"type": P.MSG_PING,
                                                       "ts": int(time.time()),
                                                       "probe": True})
                        except Exception as e:
                            logger.warning(
                                f"探测包发送失败（{type(e).__name__}），"
                                f"判定连接已失效 (session={session_id})"
                            )
                            self.note_idle_disconnect()
                            await self._retire(sess, code=4002,
                                               reason="Heartbeat failed")
                            break
                        continue
                    # 探测窗口内也没动静 → 这次是真死了
                    if self.note_idle_disconnect():
                        logger.warning(
                            f"探测包也没有回应，判定连接已失效，主动断开"
                            f" (session={session_id})"
                            f"（最近 {self.IDLE_LOG_WINDOW:.0f} 秒内第 "
                            f"{self.idle_disconnects} 次；扩展下次醒来会自动重连）"
                        )
                    else:
                        logger.debug(
                            f"连接判死后又被判死一次（静默超过 "
                            f"{self.read_timeout:.0f}s），不再重复告警"
                            f" (session={session_id})"
                        )
                    await self._retire(sess, code=4002,
                                       reason="No data from extension")
                    break
                sess.probing = False
                sess.last_inbound = time.time()
                if raw is None:
                    # 显式收到关闭帧（部分实现回 None 而不是抛异常）
                    break
                await self._on_message(sess, raw)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            # 扩展正常关闭也会走到这里，所以不刷 ERROR；但要留下可诊断的痕迹
            from starlette.websockets import WebSocketDisconnect
            if isinstance(e, WebSocketDisconnect):
                logger.info(
                    f"扩展关闭连接 (session={session_id}, code={e.code})"
                )
            else:
                logger.warning(
                    f"扩展连接异常结束 (session={session_id}): "
                    f"{type(e).__name__}: {e}"
                )
        finally:
            self._cleanup(sess)

    async def _retire(self, sess: _Session, code: int, reason: str) -> None:
        """让一个会话退役：取消心跳、失败在途命令、收掉下载 sink、关 socket。

        ⚠️ 全局状态（self._session 等镜像）只在它仍是**当前会话**时清；
           被替换的旧会话晚到这里的退役调用只收它自己的东西，不动全局。
        ⚠️ 不能取消**自己**：心跳循环在发送失败时会调 _retire，
           那时 current_task() 就是心跳任务 —— cancel() 会把当前协程在
           下一个 await 点取消掉，**后面的关 socket 根本执行不到**。
           自己调用自己时只需把引用清掉（本协程随后就会 return）。
        """
        is_current = sess is self._session
        if is_current:
            self._session = None

        try:
            _cur = asyncio.current_task()
        except RuntimeError:
            _cur = None
        if (sess.heartbeat_task and not sess.heartbeat_task.done()
                and sess.heartbeat_task is not _cur):
            sess.heartbeat_task.cancel()
        sess.heartbeat_task = None

        if is_current:
            # 在途命令全部失败，避免调用方无限等待。
            # 这些命令都是在**这条**连接上下发的（pending 按 cmd_id 唯一），
            # 连接没了它们不可能再有结果。
            for cmd_id, fut in list(self._pending.items()):
                if not fut.done():
                    fut.set_exception(BridgeNotConnected("扩展连接已失效"))
            self._pending.clear()
            for cid in list(self._sinks):
                self._abort_sink(cid, RuntimeError("disconnected"))

        await self._close_ws(sess.ws, code=code, reason=reason)

    def _cleanup(self, sess: _Session) -> None:
        if sess is not self._session:
            # 已被新连接替换，全局状态归新会话管（retire 时已经收拾过）
            return

        logger.info(f"扩展断开 (session={sess.session_id})")
        if sess.heartbeat_task and not sess.heartbeat_task.done():
            sess.heartbeat_task.cancel()
        sess.heartbeat_task = None

        # 未完成的命令全部失败，避免调用方无限等待
        for cmd_id, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_exception(BridgeNotConnected("扩展连接已断开"))
        self._pending.clear()
        for cid in list(self._sinks):
            self._abort_sink(cid, RuntimeError("disconnected"))

        self._session = None

    async def close(self) -> None:
        """插件卸载时调用，干净地断开扩展。"""
        sess = self._session
        if sess is not None and sess.heartbeat_task and not sess.heartbeat_task.done():
            sess.heartbeat_task.cancel()
        if sess is not None:
            sess.heartbeat_task = None

        for cmd_id, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_exception(BridgeNotConnected("插件正在关闭"))
        self._pending.clear()

        # 关掉所有还开着的下载 sink，删掉半成品文件
        for cid in list(self._sinks):
            self._abort_sink(cid, RuntimeError("插件正在关闭"))

        if sess is not None:
            await self._close_ws(sess.ws, code=1001, reason="Plugin shutting down")

        self._session = None

    @staticmethod
    async def _close_ws(ws, code: int, reason: str) -> None:
        if ws is None:
            return
        try:
            await ws.close(code=code, reason=reason)
        except Exception:
            pass

    # ─── 收发 ────────────────────────────────────────────────────────────

    async def _send_to(self, sess: _Session, payload: dict) -> None:
        """往**指定会话**发一帧。

        ⚠️ 两个硬规矩：
          · **每会话自己的锁** —— 不用全局锁。给慢客户端发大消息（截图
            数 MB + TCP 反压）时，全局锁会把所有会话的发送全堵住
            （锁 convoy），还会连累进程里别的服务。
          · **发送超时** —— send_text 可能因反压挂住，超时就抛，
            让调用方判死这条连接，而不是无限等。
        """
        async with sess.send_lock:
            await asyncio.wait_for(
                sess.ws.send_text(json.dumps(payload, ensure_ascii=False)),
                timeout=self.SEND_TIMEOUT)

    async def _send(self, payload: dict) -> None:
        """往**当前会话**发一帧（命令下发等主动发送走这里）。

        ⚠️ 会话处理器内部的回话（WELCOME / PONG / 探测包）请用
           ``_send_to(sess, ...)`` —— 它们必须发到**自己那条**连接，
           读全局当前会话会把旧会话迟到的帧串到新连接上。
        """
        sess = self._session
        if sess is None:
            raise BridgeNotConnected("扩展未连接")
        await self._send_to(sess, payload)

    async def _on_message(self, sess: _Session, raw: str) -> None:
        # 世代守卫：await 出让期间会话可能已被替换 —— 旧会话的帧不再处理
        # （其结果对应的 future 在 retire 时已经失败，不会有人等它）。
        if sess is not self._session:
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("收到无法解析的扩展消息")
            return

        mtype = msg.get("type")

        if mtype == P.MSG_RESULT:
            result = P.BridgeResult.from_wire(msg)
            fut = self._pending.pop(result.cmd_id, None)
            if fut and not fut.done():
                fut.set_result(result)
            else:
                logger.debug(f"收到无人认领的命令结果: {result.cmd_id}")

        elif mtype == P.MSG_CHUNK:
            # 下载分块：只接受**属于当前活动下载命令**的分块，并立刻写盘。
            # （旧实现把所有分块攒进列表，大文件会占住与完整文件相当的内存；
            #   而且未知 cmd_id 的分块会一直留着不释放。）
            cid = str(msg.get("id", ""))
            data = msg.get("data")
            sink = self._sinks.get(cid)
            if not (cid and data and sink):
                return
            # ⚠️ 关于"同步写盘会不会阻塞事件循环 / 会不会与 _abort_sink 竞态"：
            #    · **竞态：没有**。从 `self._sinks.get(cid)` 取到 sink 引用、
            #      到 `handle.write()` 之间**没有任何 await** —— 在事件循环里
            #      这一段是原子的，_abort_sink()（另一个 task）插不进来，
            #      所以不会出现"写已经关掉的句柄"。
            #    · **阻塞：量很小**。分块是 ~340KB（扩展侧 256KB 原始块
            #      base64 而来），写普通文件是毫秒级。慢盘/网络挂载上会有
            #      短暂阻塞，但这是单文件顺序写，排队不会改善。
            #    曾考虑过 per-sink 队列 + to_thread 彻底移出事件循环，
            #    但那样要额外维护"写入/abort/close 三者的生命周期协调"，
            #    为一个毫秒级操作引入并发复杂度不划算 —— 保持现状。
            try:
                import base64 as _b64
                raw = _b64.b64decode(data)
                sink["handle"].write(raw)
                sink["total"] += len(raw)
                limit = sink.get("limit") or 0
                if limit and sink["total"] > limit:
                    self._abort_sink(cid, RuntimeError(f"下载超过上限 {limit} 字节"))
                    # 通知调用方失败
                    fut = self._pending.pop(cid, None)
                    if fut and not fut.done():
                        fut.set_result(P.BridgeResult(
                            cmd_id=cid, ok=False, error=f"下载超过上限 {limit} 字节"))
            except Exception as e:
                logger.warning(f"写入下载分块失败: {e}")
                self._abort_sink(cid, e)
                # ⚠️ 必须**同样把这个 future resolve 掉**（上面"超上限"分支就是
                #    这么做的）。只 abort sink 的话 future 一直挂着 →
                #    send_command 会干等到 download_timeout（默认 600 秒），
                #    磁盘写满 / base64 非法这种情况要卡 10 分钟才报错。
                fut = self._pending.pop(cid, None)
                if fut and not fut.done():
                    fut.set_result(P.BridgeResult(
                        cmd_id=cid, ok=False, error=f"写入下载分块失败: {e}"))

        elif mtype == P.MSG_PONG:
            pass

        elif mtype == P.MSG_PING:
            # 扩展也会**主动**发保活 ping（它每次被保活闹钟唤醒时发一条）。
            # 回一条 pong 即可 —— 这条路径的意义是：让"扩展那边还活着"这件事
            # 在服务端可见（收到任何一帧都会重置空闲计时），
            # 于是 MV3 回收 Service Worker 造成的静默不会一点痕迹都不留。
            # ⚠️ 回到**自己这条**连接（_send_to）：用全局当前会话的话，
            #    被替换的旧会话会把 PONG 串到新连接上。
            await self._send_to(sess, {"type": P.MSG_PONG, "ts": int(time.time())})

        elif mtype == P.MSG_EVENT:
            await self._dispatch_event(str(msg.get("name", "")), msg.get("data") or {})

        elif mtype == P.MSG_ERROR:
            logger.warning(f"扩展上报错误: {msg.get('error')}")

        else:
            logger.debug(f"忽略未知消息类型: {mtype}")

    async def _heartbeat_loop(self, sess: _Session) -> None:
        """定期 ping，探测扩展是否还活着（MV3 的 Service Worker 会被回收）。

        ping 发不出去说明 socket 已经烂了：这里必须**主动**把连接判死，
        不能只 `return` —— 接收循环可能正卡在半开连接上永远等下去，
        那样面板会一直显示"已连接"。

        ⚠️ 心跳间隔用**实例参数**（self.heartbeat_interval）：测试会把它压到
           毫秒级；用类常量的话那个参数就是摆设。
        """
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval)
                if sess is not self._session:
                    return
                try:
                    await self._send_to(sess, {"type": P.MSG_PING,
                                               "ts": int(time.time())})
                except Exception as e:
                    logger.warning(f"心跳发送失败（{type(e).__name__}），判定连接已失效")
                    await self._retire(sess, code=4002, reason="Heartbeat failed")
                    return
        except asyncio.CancelledError:
            return

    # ─── 命令下发 ────────────────────────────────────────────────────────

    async def send_command(self, name: str, params: Optional[dict] = None,
                           timeout: Optional[float] = None,
                           cmd_id: Optional[str] = None) -> Any:
        """下发一条命令并等待扩展返回结果。

        Args:
            name: 命令名，见 ``protocol.CMD_*``
            params: 命令参数
            timeout: 覆盖默认超时

        Returns:
            扩展返回的 ``data`` 字段

        Raises:
            BridgeNotConnected: 扩展没连上
            BridgeTimeout: 超时
            BridgeError: 扩展执行失败
        """
        if not self.connected:
            raise BridgeNotConnected(
                "浏览器扩展未连接。请确认已在浏览器中安装并启用了 Kira Browser Bridge 扩展"
            )

        if name not in P.ALL_COMMANDS:
            raise BridgeError(f"未知命令: {name}")

        cmd_id = cmd_id or uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[cmd_id] = fut

        wait = timeout if timeout is not None else self.command_timeout

        try:
            await self._send(P.BridgeCommand(cmd_id, name, params or {}).to_wire())
            self.commands_sent += 1
            result: P.BridgeResult = await asyncio.wait_for(fut, timeout=wait)
        except asyncio.TimeoutError:
            self._pending.pop(cmd_id, None)
            # ⚠️ 超时/异常/失败三条路径都必须收掉 sink，否则下载文件句柄
            #    会一直挂到进程退出，磁盘上还留着半成品。
            self._abort_sink(cmd_id, BridgeTimeout(f"命令 {name} 超时"))
            self.commands_failed += 1
            raise BridgeTimeout(f"命令 {name} 超时（{wait}s），扩展没有响应") from None
        except Exception as e:
            self._pending.pop(cmd_id, None)
            self._abort_sink(cmd_id, e)
            self.commands_failed += 1
            raise

        if not result.ok:
            _err = BridgeError(result.error or f"命令 {name} 执行失败")
            # ⚠️ 把错误类别透传上去 —— 上层（extension_backend）据此判定
            #    "超时 = 不确定，禁止换后端重试"，不依赖文案匹配。
            _err.err_code = result.error_code
            self._abort_sink(cmd_id, _err)
            self.commands_failed += 1
            raise _err

        # 下载类命令：分块已经边收边写进了 sink，这里只把落盘结果报回去
        sink = self._finish_sink(cmd_id)
        if sink:
            data = dict(result.data or {}) if isinstance(result.data, dict) else {}
            data["bytes"] = sink["total"]
            data["path"] = sink["path"]
            return data
        return result.data

    # ─── 下载分块接收器 ──────────────────────────────────────────────

    def open_download_sink(self, cmd_id: str, path: str, limit: int = 0) -> None:
        """为某个下载命令开一个落盘接收器（调用方在 send_command 之前调）。

        ⚠️ 打不开**必须抛出去**，不能只记日志就 return ——
        那样 sink 没注册，后续所有 chunk 会被丢掉，`_finish_sink` 返回 None，
        `send_command` 就把扩展的原始 payload（ok:true, bytes:N）原样返回，
        调用方会**报告下载成功但磁盘上根本没有文件**。
        """
        h = open(path, "wb")     # 失败就让调用方看到
        self._sinks[cmd_id] = {"path": path, "handle": h, "total": 0, "limit": limit}

    def _finish_sink(self, cmd_id: str):
        sink = self._sinks.pop(cmd_id, None)
        if not sink:
            return None
        try:
            sink["handle"].close()
        except Exception:
            pass
        return sink

    def abort_download_sink(self, cmd_id: str) -> None:
        """公开的收尾入口（调用方在命令失败时用，不必碰私有方法）。"""
        self._abort_sink(cmd_id, RuntimeError("命令未成功完成"))

    def _abort_sink(self, cmd_id: str, exc: Exception) -> None:
        """出错/超限/断开时：关文件并删掉半成品，不留垃圾。"""
        sink = self._sinks.pop(cmd_id, None)
        if not sink:
            return
        try:
            sink["handle"].close()
        except Exception:
            pass
        try:
            import os as _os
            if _os.path.exists(sink["path"]):
                _os.remove(sink["path"])
        except Exception:
            pass
        logger.warning(f"下载已中止并清理临时文件: {sink['path']}")

    # ─── 事件订阅（"可感知"） ────────────────────────────────────────────

    def on_event(self, name: str, callback: Callable[[dict], Awaitable[None]]) -> None:
        """注册某个扩展事件的异步回调。``name`` 传 ``"*"`` 表示监听全部。"""
        if name == "*":
            self._any_listener.append(callback)
        else:
            self._event_listeners.setdefault(name, []).append(callback)

    def clear_event_listeners(self) -> None:
        """清空所有已注册的事件回调。

        为什么需要：框架**热重载插件**时会重新走一遍 ``initialize()``，
        而 ``on_event`` 是**追加**语义 —— 不清的话回调会一次次累积，
        同一个事件被重复处理（`_on_user_confirmed` 这类还会重复推进状态）。

        ⚠️ 这个方法名是被 `main.py` 的 ``initialize()`` 调用的：写漏了就是
        **插件直接起不来**（``AttributeError``，日志里只有一行
        "Failed to initialize plugin"）。而它是在**协作者对象**上调用
        （``self.bridge.xxx()``），当时的调用图检查只扫 ``self.xxx()``，
        所以没抓到 —— 现在检查已经补上那一类（callgraph B1）。
        """
        self._event_listeners.clear()
        self._any_listener.clear()

    async def _dispatch_event(self, name: str, data: dict) -> None:
        callbacks = list(self._event_listeners.get(name, [])) + list(self._any_listener)
        for cb in callbacks:
            try:
                await cb(data)
            except Exception as e:
                logger.error(f"事件回调 {name} 执行失败: {e}")
