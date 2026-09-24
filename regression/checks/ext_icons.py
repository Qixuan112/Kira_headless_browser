"""扩展图标：尺寸对不对、是不是真 PNG、体积有没有失控。

## 为什么要有它

v2.1.84 把 `browser-bridge/icons/` 从扁平 logo 换成了**二次元立绘**。
立绘是位图，天生比矢量 logo 大得多 —— 于是引入了一个很容易失控的量：
**扩展包体积**。用户装/更新扩展时，这些字节是要下载一遍的；
而"顺手把 1024 原画丢进 icons/"这种动作，在评审时几乎看不出来
（文件能正常显示，浏览器也不报错，只是包白胖十几倍）。

同一批改动还带来两个风险，都是"图片能显示、但行为不对"的类型：

* **三个尺寸各自出图**（16px 用面部特写裁切，不是把 128 缩三次）——
  manifest 声明的只是尺寸**数字**，文件里到底是多大，以前没人比对过；
* 图标是**圆角 + 透明**的（跟旧图标一致）。如果哪天换成不透明实心方块，
  在深色工具栏上会变成一块突兀的白砖 —— 而这在浅色背景下看不出来。

所以这里把"图标该满足的硬指标"钉成断言，并带**反向自检**：
往临时副本塞几张坏图标，判据必须报红（证明这些断言真的会响，不是摆设）。

只用标准库解析 PNG（读 IHDR），**不引入 Pillow 依赖**。
"""

from __future__ import annotations

import json
import shutil
import struct
import tempfile
import zlib
from pathlib import Path

from ..harness import PLUGIN_DIR, section

TITLE = "扩展图标（尺寸 / 格式 / 体积预算）"

#: 单张体积预算（字节）。按 v2.1.84 实测量的 ~3 倍留余量：
#: 实测 16→782 B、48→2962 B、128→11474 B。
BUDGET = {16: 4096, 48: 12288, 128: 40960}
#: 三个尺寸合计预算。
TOTAL_BUDGET = 61440

PNG_SIG = b"\x89PNG\r\n\x1a\n"


# ── 纯标准库的 PNG 解析 ────────────────────────────────────────────────

def png_info(path: Path):
    """返回 (宽, 高, 颜色类型, 是否有透明, 字节数)；不是 PNG 返回 None。"""
    try:
        head = path.read_bytes()
    except OSError:
        return None
    if head[:8] != PNG_SIG or head[12:16] != b"IHDR" or len(head) < 33:
        return None
    w, h = struct.unpack(">II", head[16:24])
    ctype = head[25]
    # 颜色类型 4=灰度+alpha、6=RGBA；3=调色板，需要 tRNS 块才算带透明
    has_alpha = ctype in (4, 6) or (ctype == 3 and b"tRNS" in head[:4096])
    return w, h, ctype, has_alpha, len(head)


def make_png(w: int, h: int, ctype: int = 2, filler: int = 0) -> bytes:
    """造一张合法的纯色 PNG（反向自检用）—— 颜色类型可指定以便测透明判据。"""
    raw = b"".join(b"\x00" + bytes([filler] * (w * (4 if ctype == 6 else 3)))
                   for _ in range(h))
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (PNG_SIG
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


# ── 判据 ──────────────────────────────────────────────────────────────

def declared_icons(ext_dir: Path) -> dict:
    """manifest 里声明的图标：{声明尺寸: 相对路径}（含 action.default_icon）。"""
    mf = ext_dir / "manifest.json"
    if not mf.is_file():
        return {}
    data = json.loads(mf.read_text(encoding="utf-8"))
    out = {}
    for key in ("icons",):
        for size, rel in (data.get(key) or {}).items():
            out[int(size)] = str(rel)
    for size, rel in ((data.get("action") or {}).get("default_icon") or {}).items():
        out.setdefault(int(size), str(rel))
    return out


def icon_problems(ext_dir: Path) -> list:
    """返回问题列表（空 = 图标全部合规）。"""
    problems = []
    icons = declared_icons(ext_dir)
    if not icons:
        return ["manifest 里没有任何图标声明（icons / action.default_icon）"]

    total = 0
    seen_hashes = {}
    for size in sorted(icons):
        rel = icons[size]
        path = ext_dir / rel
        if not path.is_file():
            problems.append(f"manifest 声明了 {size}px（{rel}），但文件不存在")
            continue
        info = png_info(path)
        if info is None:
            problems.append(f"{rel} 不是合法 PNG")
            continue
        w, h, ctype, has_alpha, nbytes = info
        total += nbytes
        if (w, h) != (size, size):
            problems.append(f"{rel} 实际是 {w}x{h}，manifest 声明的是 {size}x{size}")
        if not has_alpha:
            problems.append(f"{rel} 不带透明通道 —— 深色工具栏上会变成一块白砖")
        budget = BUDGET.get(size)
        if budget and nbytes > budget:
            problems.append(f"{rel} 体积 {nbytes} 字节，超过 {size}px 的预算 {budget} 字节")
        digest = path.read_bytes()[:64] + struct.pack(">I", nbytes)
        if digest in seen_hashes:
            problems.append(f"{rel} 与 {seen_hashes[digest]} 是同一个文件（不该三个尺寸同一张）")
        seen_hashes[digest] = rel

    if total > TOTAL_BUDGET:
        problems.append(f"图标合计 {total} 字节，超过总预算 {TOTAL_BUDGET} 字节")

    # 目录里不该有"没被 manifest 声明"的 PNG（旧文件残留 / 误放大图）
    icon_dir = (ext_dir / next(iter(icons.values()))).parent
    if icon_dir.is_dir():
        declared = {(ext_dir / r).resolve() for r in icons.values()}
        strays = [p.name for p in sorted(icon_dir.glob("*.png"))
                  if p.resolve() not in declared]
        if strays:
            problems.append(f"图标目录里有 manifest 没声明的图片：{strays}")
    return problems


# ── 主检查 ────────────────────────────────────────────────────────────

def run(r) -> None:
    section("I. 扩展图标（尺寸 / 格式 / 体积预算）")
    ext_dir = PLUGIN_DIR / "browser-bridge"

    icons = declared_icons(ext_dir)
    problems = icon_problems(ext_dir)
    detail = "；".join(problems) if problems else ""
    sizes = ", ".join(f"{s}px→{icons[s]}" for s in sorted(icons))
    r.ok("I1 manifest 声明与文件一致：像素尺寸对得上、是真 PNG、带透明、体积在预算内",
         not problems,
         detail or f"{sizes}（单张预算 {BUDGET}，合计 ≤ {TOTAL_BUDGET} 字节）")

    # ── 反向自检：坏图标必须被抓出来（证明断言真的会响）──────────────
    # ⚠️ 这一段的 `shutil.copy2(ext_dir / "manifest.json", ...)` 在文件缺失时
    #    会抛 FileNotFoundError → **整段检查中断**（I2~I5 全都不跑）。
    #    删文件矩阵会抓到它。所以整个反向自检块要能"缺文件就跳过并报出来"。
    _mf_src = ext_dir / "manifest.json"
    if not _mf_src.is_file():
        r.ok("I2 反向自检：坏图标必须被抓出来",
             False, f"manifest.json 缺失（{_mf_src}），反向自检无法进行")
    else:
        _run_icons_selftest(r, ext_dir, icons)


def _run_icons_selftest(r, ext_dir, icons) -> None:
    """反向自检的正身：往临时副本塞坏图标，判据必须报红。

    ⚠️ 抽成独立函数是为了让"manifest 缺失"这种情况能**优雅跳过**
    （见 run() 里的那个 if）—— 否则 `shutil.copy2` 抛的
    FileNotFoundError 会让 I2~I5 一条都不跑，报告上只剩笼统的"未抛异常"。
    """
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "browser-bridge"
        fake.mkdir(parents=True)
        shutil.copy2(ext_dir / "manifest.json", fake / "manifest.json")
        rel_dir = (ext_dir / next(iter(icons.values()))).parent.relative_to(ext_dir)
        (fake / rel_dir).mkdir(parents=True, exist_ok=True)
        for size, rel in icons.items():
            shutil.copy2(ext_dir / rel, fake / rel)

        # a) 尺寸不符：16px 的位置放一张 64x64
        first = fake / icons[16]
        first.write_bytes(make_png(64, 64, ctype=6))
        caught_size = any("实际是 64x64" in p for p in icon_problems(fake))
        r.ok("I2 反向自检：实际像素与 manifest 声明不符 → 报红", caught_size,
             "塞了一张 64x64 冒充 16px" if caught_size else "没抓到（判据失效）")

        # b) 超预算：128px 的位置塞一张大图（噪声压缩不掉）
        big = make_png(128, 128, ctype=6, filler=0) + b"\x00" * 200000
        (fake / icons[128]).write_bytes(big)
        caught_budget = any("预算" in p for p in icon_problems(fake))
        r.ok("I3 反向自检：体积超预算 → 报红", caught_budget,
             "塞了一张 200KB+ 的图" if caught_budget else "没抓到（判据失效）")

        # c) 缺透明：不透明真彩图
        (fake / icons[128]).write_bytes(make_png(128, 128, ctype=2))
        caught_alpha = any("透明" in p for p in icon_problems(fake))
        r.ok("I4 反向自检：不透明图标 → 报红", caught_alpha,
             "换成了不透明真彩 PNG" if caught_alpha else "没抓到（判据失效）")

        # d) 文件缺失 + 目录里多出未声明的图
        (fake / icons[48]).unlink()
        (fake / rel_dir / "icon256.png").write_bytes(make_png(256, 256))
        probs = icon_problems(fake)
        caught_missing = any("文件不存在" in p for p in probs)
        caught_stray = any("没声明" in p for p in probs)
        r.ok("I5 反向自检：图标缺失 / 目录里多出未声明的图 → 都报红",
             caught_missing and caught_stray,
             f"缺失={'抓到' if caught_missing else '漏'}、多余={'抓到' if caught_stray else '漏'}")
