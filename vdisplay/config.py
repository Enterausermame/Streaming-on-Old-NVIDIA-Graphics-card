"""配置文件读写（INI 格式，/etc/nvidia-vdisplay/config.ini）。"""

from __future__ import annotations

import configparser
from pathlib import Path

from .xorg import VirtualDisplay

CONFIG_PATH = Path("/etc/nvidia-vdisplay/config.ini")

DEFAULT_CONFIG = """\
# nvidia-vdisplay 配置文件
# [display:连接器名] 每个小节定义一个虚拟显示器
# 连接器名一般从 DFP-0 开始递增（GT 730 支持 DFP-0 ~ DFP-3）

[global]
gpu_busid = auto

[display:DFP-0]
width = 1920
height = 1080
rate = 60

# 多屏示例：取消下面注释即可再开一块 720p 虚拟屏（位于主屏右侧）
# [display:DFP-1]
# width = 1280
# height = 720
# rate = 60
"""


def load(path: Path = CONFIG_PATH) -> tuple[str, list[VirtualDisplay]]:
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    busid = cp.get("global", "gpu_busid", fallback="auto")
    displays: list[VirtualDisplay] = []
    x_cursor = 0
    for section in cp.sections():
        if not section.startswith("display:"):
            continue
        connector = section.split(":", 1)[1].strip()
        width = cp.getint(section, "width", fallback=1920)
        height = cp.getint(section, "height", fallback=1080)
        rate = cp.getint(section, "rate", fallback=60)
        displays.append(
            VirtualDisplay(connector, width, height, rate, (x_cursor, 0))
        )
        x_cursor += width
    if not displays:
        displays.append(VirtualDisplay("DFP-0", 1920, 1080, 60, (0, 0)))
    return busid, displays


def ensure_default(path: Path = CONFIG_PATH) -> bool:
    """配置文件不存在时写入默认配置。返回是否新建。"""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return True
