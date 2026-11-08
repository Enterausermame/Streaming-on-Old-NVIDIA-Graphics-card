"""Modeline 计算：优先调用 Xorg 的 cvt 工具，其次内置 VESA 标准表，最后公式推算。

EDID 详细时序描述符 (DTD) 需要一组自洽的时序参数。对虚拟显示器来说，
时序只用于驱动程序的模式校验，并不真正发送信号，因此重点是"合法、自洽"。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Modeline:
    pixclk_mhz: float
    h_active: int
    h_sync_start: int
    h_sync_end: int
    h_total: int
    v_active: int
    v_sync_start: int
    v_sync_end: int
    v_total: int
    hsync_pos: bool = False
    vsync_pos: bool = False

    @property
    def h_blanking(self) -> int:
        return self.h_total - self.h_active

    @property
    def h_front_porch(self) -> int:
        return self.h_sync_start - self.h_active

    @property
    def h_sync_width(self) -> int:
        return self.h_sync_end - self.h_sync_start

    @property
    def v_blanking(self) -> int:
        return self.v_total - self.v_active

    @property
    def v_front_porch(self) -> int:
        return self.v_sync_start - self.v_active

    @property
    def v_sync_width(self) -> int:
        return self.v_sync_end - self.v_sync_start

    def mode_name(self) -> str:
        return f"{self.h_active}x{self.v_active}"


# 内置表：VESA 标准 / CVT-RB 已验证时序（与 xorg cvt 输出一致）
# key: (width, height, refresh, kind)  kind 为空表示 CVT-RB（低带宽优先）
_TABLE: dict[tuple, Modeline] = {
    # ---- CVT-RB（推荐，带宽小、时钟低）----
    (1920, 1080, 60): Modeline(138.50, 1920, 1968, 2000, 2080,
                               1080, 1083, 1088, 1111, True, False),
    (1280, 720, 60): Modeline(63.75, 1280, 1328, 1360, 1440,
                              720, 723, 728, 741, True, False),
    (1600, 900, 60): Modeline(97.75, 1600, 1648, 1680, 1760,
                              900, 903, 908, 921, True, False),
    (2560, 1440, 60): Modeline(241.50, 2560, 2608, 2640, 2720,
                               1440, 1443, 1448, 1481, True, False),
    # ---- 常规 CVT / VESA ----
    (1920, 1080, 60, "cvt"): Modeline(173.00, 1920, 2048, 2248, 2576,
                                      1080, 1083, 1088, 1120, False, True),
    (1920, 1080, 30): Modeline(74.25, 1920, 2008, 2052, 2200,
                               1080, 1084, 1094, 1125, True, True),
    (3840, 2160, 30): Modeline(297.00, 3840, 4016, 4104, 4400,
                               2160, 2168, 2178, 2250, True, True),
    (1024, 768, 60): Modeline(65.00, 1024, 1048, 1184, 1344,
                              768, 771, 777, 806, False, False),
    (800, 600, 60): Modeline(40.00, 800, 840, 968, 1056,
                             600, 601, 605, 628, True, True),
    (640, 480, 60): Modeline(25.18, 640, 656, 752, 800,
                             480, 490, 492, 525, False, False),
}

_MODELINE_RE = re.compile(
    r'Modeline\s+"[^"]*"\s+([\d.]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)'
    r'\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([+-]hsync)?\s*([+-]vsync)?'
)


def _parse_cvt(out: str) -> Modeline | None:
    m = _MODELINE_RE.search(out)
    if not m:
        return None
    nums = [float(x) for x in m.group(1, 2, 3, 4, 5, 6, 7, 8, 9)]
    return Modeline(
        pixclk_mhz=nums[0],
        h_active=int(nums[1]), h_sync_start=int(nums[2]),
        h_sync_end=int(nums[3]), h_total=int(nums[4]),
        v_active=int(nums[5]), v_sync_start=int(nums[6]),
        v_sync_end=int(nums[7]), v_total=int(nums[8]),
        hsync_pos=bool(m.group(10) and m.group(10).startswith("+")),
        vsync_pos=bool(m.group(11) and m.group(11).startswith("+")),
    )


def _fallback_modeline(w: int, h: int, r: int) -> Modeline:
    """无 cvt、不在内置表时的自洽时序推算（对虚拟显示器足够）。"""
    h_blank = max(64, ((w * 8 // 100) + 7) // 8 * 8)
    h_fp = max(16, h_blank // 3)
    h_sync = max(32, h_blank // 5)
    v_blank = max(20, h * 3 // 100)
    v_fp = max(3, v_blank // 10)
    v_sync = max(3, v_blank // 6)
    h_total = w + h_blank
    v_total = h + v_blank
    pixclk = round(h_total * v_total * r / 1_000_000.0 * 4) / 4.0
    return Modeline(pixclk, w, w + h_fp, w + h_fp + h_sync, h_total,
                    h, h + v_fp, h + v_fp + v_sync, v_total, True, False)


def get_modeline(w: int, h: int, r: int = 60, reduced: bool = True) -> Modeline:
    """获取 (宽, 高, 刷新率) 的 Modeline。优先 cvt -> 内置表 -> 公式推算。"""
    if reduced:
        key = (w, h, r)
        if key in _TABLE:
            return _TABLE[key]
    key2 = (w, h, r, "cvt")
    if key2 in _TABLE:
        return _TABLE[key2]
    if key in _TABLE:
        return _TABLE[key]

    cvt = shutil.which("cvt")
    if cvt:
        try:
            args = [cvt]
            if reduced:
                args.append("-r")
            args += [str(w), str(h), str(r)]
            out = subprocess.run(args, capture_output=True, text=True,
                                 timeout=10).stdout
            ml = _parse_cvt(out)
            if ml:
                return ml
        except Exception:
            pass
    return _fallback_modeline(w, h, r)
