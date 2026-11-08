"""EDID 生成器结构校验（本地无依赖测试）。"""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vdisplay.edid import build_edid, edid_for_resolution  # noqa: E402
from vdisplay.modelines import Modeline, get_modeline  # noqa: E402


class TestModeline(unittest.TestCase):
    def test_builtin_1080p60_rb(self):
        ml = get_modeline(1920, 1080, 60)
        self.assertEqual(ml.pixclk_mhz, 138.50)
        self.assertEqual(ml.h_total, 2080)
        self.assertEqual(ml.v_total, 1111)
        self.assertTrue(ml.hsync_pos)
        self.assertFalse(ml.vsync_pos)

    def test_builtin_720p60_rb(self):
        ml = get_modeline(1280, 720, 60)
        self.assertEqual(ml.pixclk_mhz, 63.75)
        self.assertEqual(ml.h_total, 1440)
        self.assertEqual(ml.v_total, 741)

    def test_fallback_consistency(self):
        ml = get_modeline(1366, 768, 60)
        self.assertGreater(ml.h_total, ml.h_active)
        self.assertGreater(ml.v_total, ml.v_active)
        self.assertGreater(ml.pixclk_mhz, 0)


class TestEdid(unittest.TestCase):
    def test_header_and_size(self):
        edid = edid_for_resolution(1920, 1080, 60)
        self.assertEqual(len(edid), 128)
        self.assertEqual(edid[:8], bytes.fromhex("00 ff ff ff ff ff ff 00"))

    def test_checksum(self):
        for w, h in [(1920, 1080), (1280, 720), (2560, 1440)]:
            edid = edid_for_resolution(w, h, 60)
            self.assertEqual(sum(edid) % 256, 0, f"{w}x{h} 校验和错误")

    def test_version(self):
        edid = edid_for_resolution(1920, 1080)
        self.assertEqual(edid[18], 1)
        self.assertEqual(edid[19], 4)

    def test_dtd_1080p60_rb(self):
        edid = edid_for_resolution(1920, 1080, 60)
        dtd = edid[54:72]
        pclk = struct.unpack("<H", dtd[0:2])[0]
        self.assertEqual(pclk, 13850)  # 138.50 MHz = 13850 * 10kHz
        ha = dtd[2] | ((dtd[4] >> 4) << 8)
        va = dtd[5] | ((dtd[7] >> 4) << 8)
        hbl = dtd[3] | ((dtd[4] & 0x0F) << 8)
        vbl = dtd[6] | ((dtd[7] & 0x0F) << 8)
        self.assertEqual(ha, 1920)
        self.assertEqual(va, 1080)
        self.assertEqual(ha + hbl, 2080)
        self.assertEqual(va + vbl, 1111)

    def test_standard_timing_slot(self):
        edid = edid_for_resolution(1920, 1080, 60)
        found = False
        for i in range(8):
            b1, b2 = edid[38 + i * 2], edid[39 + i * 2]
            if b1 == 0xD1 and b2 == 0xC0:  # 1920x1080@60, 16:9
                found = True
        self.assertTrue(found, "标准时序槽中应有 1920x1080@60")

    def test_name_descriptor(self):
        edid = edid_for_resolution(1920, 1080, 60)
        self.assertEqual(edid[108 + 3], 0xFC)  # Monitor name tag


if __name__ == "__main__":
    unittest.main(verbosity=2)
