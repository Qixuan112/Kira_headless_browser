"""检查脚本登记表。

加新检查：在 ``checks/`` 下建一个模块，写 ``TITLE`` 和 ``run(report)``，
然后在这里登记。``run_all.py`` 会按顺序跑。
"""

from __future__ import annotations

from . import (
    bridge_e2e,
    callgraph,
    lifecycle,
    content_dom,
    contract,
    file_hygiene,
    runtime_behavior,
    security_rules,
    static_audit,
    tool_merge,
    wiring,
    claims,
    spec_compliance,
    vlm_describe,
    lost_features,
    timeout_semantics,
    execjs_gates,
    paths_default,
)

#: 检查**模块**列表（按顺序执行）。
#  ⚠️ 元素就是模块本身，不是 `(模块, 是否启用)` 元组 ——
#    `run_all.py` 直接取 `m.TITLE` / 调 `m.run(report)`，
#    写成元组会在跑的时候抛 AttributeError。
#    要新增检查：import 进来，加到这个列表里即可。
ALL_CHECKS = [
    paths_default,       # 默认目录基准（截图/下载/cookie 必须绝对 + 跟框架走）
    static_audit,        # 静态一致性 / README / 历史回归 / 运行时坑 / 打包
    tool_merge,          # 工具合并零丢失
    wiring,              # 接线完整性（配置接通 / 数据透传）
    contract,            # 两后端返回契约一致性
    callgraph,           # 调用图完整性（未定义方法 / 签名合规）
    lifecycle,           # 启动/停止生命周期（真跑 initialize —— 静态检查之外的保险）
    security_rules,      # 域名与本机地址规则
    file_hygiene,        # 文件冗余/缺失清点
    runtime_behavior,    # 生命周期 / 路由 / 内存（假 Playwright）
    bridge_e2e,          # 真实 WebSocket 端到端
    content_dom,         # 扩展点击行为（真实 DOM）
    claims,              # 声称 ↔ 实际（防止"写了但没改"）
    spec_compliance,     # KiraAI 规范符合性（包结构 / manifest / 入口 / 路由）
    vlm_describe,        # 截图 → VLM 描述（bot 看图；防止该能力再次丢失）
    lost_features,       # v2.1.0 重写时丢掉的能力（cookie 自动加载 / 下载浏览器 / VLM 自查）
    timeout_semantics,   # 「结果不确定」链路（超时不得触发换后端重试）
    execjs_gates,        # 扩展执行 JS 的两道关口（USER_SCRIPT world CSP / 端口值域）
]

__all__ = ["ALL_CHECKS"]
