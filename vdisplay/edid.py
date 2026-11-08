"""纯 Python EDID 1.4 基础块生成器（无第三方依赖）。

生成合法的 128 字节 EDID 基础块：
  - 头部 / 厂商 ID / 产品信息 / EDID 1.4 版本
  - sRGB 色度坐标、gamma 2.2、DPMS
  - 标准时序 + 详细时序描述符 (DTD, 首选模式)
  - 显示器名称描述符 + 校验和

用于注入 NVIDIA 驱动的 CustomEDID，模拟"插着一台显示器"。
"""

from __future__ import annotations

import struct

from .modelines import Modeline, get_modeline

EDID_HEADER = bytes.fromhex("00 ff ff ff ff ff ff 00")

# sRGB 原色/白点（10bit，低 2 位集中打包在后两个字节）
_CHROMA = bytes([0xA3, 0x54, 0x4C, 0x99, 0x26, 0x0F, 0x50, 0x54, 0xEE, 0x91])

# 厂商三字母编码（A=1..Z=26，每字母 5 bit）
_MANUFACTURER = "VDI"  # Virtual Display Interface

# 标准时序纵横比编码（EDID 1.4 字节 2 的 bit7-6）
_RATIO_16_10, _RATIO_4_3, _RATIO_5_4, _RATIO_16_9 = 0, 1, 2, 3


def manufacturer_code(name: str) -> bytes:
    a, b, c = (ord(ch.upper()) - 64 for ch in name[:3])
    code = (a << 10) | (b << 5) | c
    return struct.pack("<H", code)


def standard_timing_bytes(w: int, h: int, refresh: int = 60) -> bytes | None:
    """把分辨率编码进 EDID 标准时序槽（要求宽 <= 2288 且为 8 的倍数）。"""
    if w % 8 or not (256 <= w <= 2288) or refresh < 60 or refresh > 123:
        return None
    b1 = w // 8 - 31
    if not (1 <= b1 <= 255):
        return None
    if w == h * 16 // 9:
        ratio = _RATIO_16_9
    elif w == h * 4 // 3:
        ratio = _RATIO_4_3
    elif w == h * 5 // 4:
        ratio = _RATIO_5_4
    else:
        ratio = _RATIO_16_10
    b2 = (ratio << 6) | (refresh - 60)
    return bytes([b1, b2])


def _dtd(ml: Modeline, mm_w: int, mm_h: int) -> bytes:
    """构造 18 字节详细时序描述符 (DTD)。"""
    d = bytearray(18)
    pclk = int(round(ml.pixclk_mhz * 100))  # 单位 10 kHz
    struct.pack_into("<H", d, 0, pclk)

    ha, hbl = ml.h_active, ml.h_blanking
    va, vbl = ml.v_active, ml.v_blanking
    hfp, hsw = ml.h_front_porch, ml.h_sync_width
    vfp, vsw = ml.v_front_porch, ml.v_sync_width

    d[2] = ha & 0xFF
    d[3] = hbl & 0xFF
    d[4] = ((ha >> 8) << 4) | ((hbl >> 8) & 0x0F)
    d[5] = va & 0xFF
    d[6] = vbl & 0xFF
    d[7] = ((va >> 8) << 4) | ((vbl >> 8) & 0x0F)
    d[8] = hfp & 0xFF
    d[9] = hsw & 0xFF
    d[10] = ((vfp & 0x0F) << 4) | (vsw & 0x0F)
    d[11] = (((hfp >> 8) & 0x03) << 6) | (((hsw >> 8) & 0x03) << 4) \
        | (((vfp >> 4) & 0x03) << 2) | ((vsw >> 4) & 0x03)
    d[12] = mm_w & 0xFF
    d[13] = mm_h & 0xFF
    d[14] = ((mm_w >> 8) << 4) | ((mm_h >> 8) & 0x0F)
    d[15] = 0  # H border
    d[16] = 0  # V border
    flags = 0x18  # 数字信号、独立同步
    if ml.vsync_pos:
        flags |= 0x04
    if ml.hsync_pos:
        flags |= 0x02
    d[17] = flags
    return bytes(d)


def _name_descriptor(name: str) -> bytes:
    """显示器名称描述符（放在第 4 个 DTD 槽位）。"""
    d = bytearray(18)
    d[3] = 0xFC  # Monitor name tag
    raw = name.encode("ascii", "replace")[:13]
    d[5:5 + len(raw)] = raw
    for i in range(5 + len(raw), 18):
        d[i] = 0x0A  # 换行填充（EDID 规范）
    return bytes(d)


def build_edid(
    width: int,
    height: int,
    refresh: int = 60,
    reduced: bool = True,
    *,
    name: str = "VDI Virtual Display",
    serial: int = 0x00000001,
    product: int = 0x4701,
    year: int = 2026,
    week: int = 1,
    extra_modes: tuple[tuple[int, int, int], ...] = (),
) -> bytes:
    """生成 128 字节 EDID 1.4 基础块。

    extra_modes: 追加到第 2/3 个 DTD 槽位的备选模式，如 ((1280,720,60),)。
    """
    edid = bytearray(128)
    edid[0:8] = EDID_HEADER
    edid[8:10] = manufacturer_code(_MANUFACTURER)
    edid[10:12] = struct.pack("<H", product & 0xFFFF)
    edid[12:16] = struct.pack("<I", serial & 0xFFFFFFFF)
    edid[16] = week & 0xFF
    edid[17] = (year - 1990) & 0xFF
    edid[18] = 1   # EDID 版本 1.4
    edid[19] = 4
    edid[20] = 0x80  # 数字输入
    # 物理尺寸：按 96dpi 折算（虚拟屏幕的"面板尺寸"）
    mm_w = min(2550, round(width * 2.54 / 96 * 10))
    mm_h = min(2550, round(height * 2.54 / 96 * 10))
    edid[21] = mm_w // 10
    edid[22] = mm_h // 10
    edid[23] = 0x78  # gamma 2.2
    edid[24] = 0x0A  # RGB 4:4:4, sRGB, DPMS 待机/挂起/关闭
    edid[25:35] = _CHROMA
    # 建立时序：640x480@60 + 800x600@60 + 1024x768@60
    edid[35:38] = bytes([0x21, 0x08, 0x00])
    # 标准时序：首选我们的分辨率，其余填常用模式
    std = [standard_timing_bytes(width, height, refresh),
           standard_timing_bytes(1920, 1080, 60),
           standard_timing_bytes(1280, 720, 60),
           standard_timing_bytes(1024, 768, 60),
           standard_timing_bytes(800, 600, 60)]
    std = [b for b in std if b]
    for i, b in enumerate(std[:8]):
        edid[38 + i * 2:40 + i * 2] = b
    for i in range(len(std), 8):
        edid[38 + i * 2:40 + i * 2] = bytes([0x01, 0x01])  # 未用

    ml = get_modeline(width, height, refresh, reduced)
    # DTD 槽位 1：首选模式
    edid[54:72] = _dtd(ml, mm_w // 10, mm_h // 10)
    # DTD 槽位 2/3：备选模式
    slot = 72
    for em in extra_modes:
        if slot >= 108:
            break
        eml = get_modeline(*em)
        mm_w2 = min(2550, round(em[0] * 2.54 / 96 * 10)) // 10
        mm_h2 = min(2550, round(em[1] * 2.54 / 96 * 10)) // 10
        edid[slot:slot + 18] = _dtd(eml, mm_w2, mm_h2)
        slot += 18
    # DTD 槽位 4：显示器名称
    edid[108:126] = _name_descriptor(name)
    edid[126] = 0  # 无扩展块
    edid[127] = (-sum(edid[:127])) & 0xFF  # 校验和
    return bytes(edid)


def edid_for_resolution(width: int, height: int, refresh: int = 60,
                        reduced: bool = True, name: str | None = None) -> bytes:
    """便捷接口：为一个虚拟显示器生成 EDID。"""
    return build_edid(
        width, height, refresh, reduced,
        name=name or f"VDI {width}x{height}@{refresh}",
        extra_modes=((1280, 720, 60), (1024, 768, 60)),
    )
