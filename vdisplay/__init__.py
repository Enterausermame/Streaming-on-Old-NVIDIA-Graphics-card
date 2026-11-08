"""nvidia-vdisplay - 为无头 NVIDIA GPU（GT 730 / Kepler）创建硬件渲染虚拟显示器。

通过向 NVIDIA 专有 X 驱动注入虚拟 EDID，让没有连接物理显示器的 GPU
"看到"虚拟显示器，KDE / 游戏 / 串流软件等即可在 GPU 上硬件渲染输出。
"""

__version__ = "1.0.0"
