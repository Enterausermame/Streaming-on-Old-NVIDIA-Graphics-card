"""生成 NVIDIA 专有 X 驱动的虚拟显示器配置（xorg.conf.d / sddm / modprobe）。"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

EDID_DIR = Path("/etc/nvidia-vdisplay/edid")


@dataclass
class VirtualDisplay:
    connector: str        # 如 DFP-0
    width: int
    height: int
    refresh: int = 60
    position: tuple[int, int] = (0, 0)

    @property
    def edid_path(self) -> str:
        return str(EDID_DIR / f"{self.connector}.bin")

    @property
    def mode(self) -> str:
        return f"{self.width}x{self.height}"


def detect_nvidia_busid() -> str:
    """自动探测第一块 NVIDIA VGA 卡的 PCI 地址，转换为 Xorg BusID 格式。"""
    if shutil.which("lspci"):
        try:
            out = subprocess.run(
                ["lspci"], capture_output=True, text=True, timeout=10
            ).stdout
            for line in out.splitlines():
                low = line.lower()
                if "vga" in low and "nvidia" in low:
                    pci = line.split()[0]  # 如 01:00.0
                    b, d, f = pci.replace(".", ":").split(":")
                    return f"PCI:{int(b)}:{int(d)}:{int(f)}"
        except Exception:
            pass
    return "PCI:1:0:0"


def render_xorg_conf(displays: list[VirtualDisplay], busid: str) -> str:
    conns = ", ".join(d.connector for d in displays)
    edid_opts = "; ".join(f"{d.connector}:{d.edid_path}" for d in displays)
    metamodes = ", ".join(
        f"{d.connector}: {d.mode} +{d.position[0]}+{d.position[1]}"
        for d in displays
    )
    modes = " ".join(f'"{d.mode}"' for d in displays)

    return f"""# 由 nvidia-vdisplay 生成，请勿手动编辑（vdisplay apply 会覆盖）
# 虚拟显示器方案：ConnectedMonitor + CustomEDID 注入
Section "Device"
    Identifier     "NVIDIAVirtual"
    Driver         "nvidia"
    VendorName     "NVIDIA Corporation"
    BusID          "{busid}"
    Option         "ConnectedMonitor" "{conns}"
    Option         "CustomEDID" "{edid_opts}"
    Option         "UseEDID" "True"
    # 放宽校验：虚拟屏幕无真实信号，允许非标准组合
    Option         "ModeValidation" "AllowNon60HzDFPModes, NoExtendedGpuCapabilitiesCheck, NoTotalSizeCheck, NoMaxPClkCheck"
    # 性能选项：三重缓冲 + 超频/风扇控制位（Coolbits）
    Option         "TripleBuffer" "True"
    Option         "Coolbits" "28"
EndSection

Section "Screen"
    Identifier     "VirtualScreen"
    Device         "NVIDIAVirtual"
    DefaultDepth   24
    Option         "MetaModes" "{metamodes}"
    SubSection     "Display"
        Depth       24
        Modes       {modes}
    EndSubSection
EndSection
"""


def render_modprobe_conf() -> str:
    """NVIDIA 内核模块性能参数：PowerMizer 全开、锁定最高性能等级。"""
    return """# 由 nvidia-vdisplay 生成：让 GT 730 始终跑满性能（无头环境无需省电）
options nvidia NVreg_RegistryDwords="PowerMizerEnable=0x1;PerfLevelSrc=0x2222"
"""


def detect_x11_session() -> str | None:
    """探测可用的 Plasma/KDE X11 会话文件名（如 plasmax11.desktop）。"""
    xs = Path("/usr/share/xsessions")
    if xs.is_dir():
        candidates = sorted(xs.glob("*.desktop"), key=lambda p: p.name)
        for c in candidates:
            name = c.stem.lower()
            if "plasma" in name or "kde" in name:
                return c.stem
        if candidates:
            return candidates[0].stem
    return None


def render_sddm_conf() -> str:
    """强制 SDDM 使用 X11（Wayland 无法用虚拟连接器方案）。

    同时把自动登录会话切到 X11 会话（trixie 上 Session=plasma 默认是 Wayland）。
    """
    session = detect_x11_session()
    lines = [
        "# 由 nvidia-vdisplay 生成：虚拟显示器方案要求 X11",
        "[General]",
        "DisplayServer=x11",
    ]
    if session:
        lines += ["", "[Autologin]", f"Session={session}"]
    return "\n".join(lines) + "\n"


def write_all(displays: list[VirtualDisplay], busid: str = "auto",
              apply_modprobe: bool = True, apply_sddm: bool = True) -> list[Path]:
    """写出全部配置文件，返回写过的路径列表。"""
    written: list[Path] = []
    if busid == "auto":
        busid = detect_nvidia_busid()

    EDID_DIR.mkdir(parents=True, exist_ok=True)
    for d in displays:
        from .edid import edid_for_resolution  # 延迟导入避免循环
        data = edid_for_resolution(d.width, d.height, d.refresh)
        Path(d.edid_path).write_bytes(data)
        written.append(Path(d.edid_path))

    xorg_dir = Path("/etc/X11/xorg.conf.d")
    xorg_dir.mkdir(parents=True, exist_ok=True)
    xorg = xorg_dir / "20-nvidia-vdisplay.conf"
    xorg.write_text(render_xorg_conf(displays, busid))
    written.append(xorg)

    if apply_modprobe:
        mp_dir = Path("/etc/modprobe.d")
        mp_dir.mkdir(parents=True, exist_ok=True)
        mp = mp_dir / "nvidia-vdisplay.conf"
        mp.write_text(render_modprobe_conf())
        written.append(mp)

    if apply_sddm:
        sd_dir = Path("/etc/sddm.conf.d")
        sd_dir.mkdir(parents=True, exist_ok=True)
        # zz- 前缀确保覆盖 autologin.conf 等既有配置
        sd = sd_dir / "zz-nvidia-vdisplay.conf"
        sd.write_text(render_sddm_conf())
        written.append(sd)
        # 迁移旧版本生成的文件
        old_sd = sd_dir / "20-nvidia-vdisplay.conf"
        if old_sd.exists():
            old_sd.rename(old_sd.with_suffix(".conf.disabled"))

    return written
