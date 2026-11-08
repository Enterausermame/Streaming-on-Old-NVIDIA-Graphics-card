"""nvidia-vdisplay 命令行工具。

用法（root 或 sudo）：
  vdisplay init                     生成默认配置文件
  vdisplay generate 1920 1080 60    生成单个 EDID 并打印/保存
  vdisplay apply                    按配置写入 EDID + Xorg + modprobe + sddm
  vdisplay apply --restart-display  应用后重启显示管理器
  vdisplay status                   查看虚拟显示器与 GPU 状态
  vdisplay disable                  禁用（移走配置）并重启显示管理器
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import CONFIG_PATH, ensure_default, load
from .edid import build_edid
from .xorg import EDID_DIR, write_all


def _need_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        sys.exit("需要 root 权限：请用 sudo 运行（如 sudo vdisplay apply）")


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"(执行失败) {e}"


def cmd_generate(args: argparse.Namespace) -> int:
    data = build_edid(args.width, args.height, args.rate, not args.no_reduced,
                      name=args.name)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        print(f"已生成 EDID ({args.width}x{args.height}@{args.rate}) -> {out}"
              f" ({len(data)} 字节)")
    else:
        sys.stdout.buffer.write(data)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    _need_root()
    path = Path(args.output) if args.output else CONFIG_PATH
    if ensure_default(path):
        print(f"已创建默认配置：{path}")
        print("用编辑器修改分辨率/增加虚拟屏后执行：sudo vdisplay apply")
    else:
        print(f"配置已存在：{path}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    _need_root()
    busid, displays = load()
    print(f"GPU BusID: {busid}")
    print("虚拟显示器：")
    for d in displays:
        print(f"  {d.connector}: {d.width}x{d.height}@{d.refresh} "
              f"位置 +{d.position[0]}+{d.position[1]}")

    written = write_all(displays, busid)
    print("\n已写入：")
    for p in written:
        print(f"  {p}")

    # 持久化模式（无头场景 GPU 保持就绪）
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        out = _run([nvidia_smi, "-pm", "1"])
        print(f"\n持久化模式: {out.strip()}")

    # 模块参数变更需要重建 initramfs 才能开机生效
    if not args.no_initramfs and shutil.which("update-initramfs"):
        print("重建 initramfs ...")
        out = _run(["update-initramfs", "-u"])
        print(out.strip().splitlines()[-1] if out.strip() else "(完成)")

    if args.restart_display:
        print("重启显示管理器 (sddm) ...")
        out = _run(["systemctl", "restart", "sddm"])
        print(out or "已发送重启指令")
    else:
        print("\n提示：执行 'vdisplay apply --restart-display' 或重启"
              " 显示管理器让虚拟屏幕生效")
    return 0


def _find_display_and_xauth():
    """探测活动的 X display 号与认证文件（sddm 下 display 号可能是 :0 或 :1）。"""
    auths = sorted(
        Path("/run/sddm").glob("xauth_*"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    xauth = str(auths[0]) if auths else ""
    for disp in (":0", ":1", ":2"):
        env = os.environ.copy()
        env["DISPLAY"] = disp
        if xauth:
            env["XAUTHORITY"] = xauth
        try:
            r = subprocess.run(["xrandr", "-q"], env=env,
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return disp, xauth, r.stdout
        except FileNotFoundError:
            return disp, xauth, None
    return ":0", xauth, None


def _latest_xorg_log() -> Path | None:
    """最新的 Xorg 日志（用于确认 X 使用的驱动）。"""
    logs = sorted(Path("/var/log").glob("Xorg.*.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def cmd_status(args: argparse.Namespace) -> int:
    print("=== X 服务器状态 ===")
    print(_run(["pgrep", "-a", "Xorg"]) or "(Xorg 未运行)")
    disp, xauth, xrandr_out = _find_display_and_xauth()
    print(f"\n=== 虚拟显示器 (xrandr, display {disp}) ===")
    print(xrandr_out or "(xrandr 查询失败)")
    log = _latest_xorg_log()
    if log:
        driver = _run(["grep", "-m1", "-oE", "nvidia_drv.so|modesetting_drv.so",
                       str(log)]).strip()
        if driver:
            print(f"X 驱动: {driver}")
    print("=== GPU 状态 ===")
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        print(_run([nvidia_smi, "--query-gpu=name,driver_version,"
                    "utilization.gpu,power.draw,temperature.gpu,"
                    "memory.used,memory.total", "--format=csv"])
              or "(nvidia-smi 无输出)")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    _need_root()
    targets = [Path("/etc/X11/xorg.conf.d/20-nvidia-vdisplay.conf")]
    changed = False
    for xorg in targets:
        if xorg.exists():
            xorg.rename(xorg.with_suffix(".conf.disabled"))
            print(f"已禁用：{xorg} -> {xorg.with_suffix('.conf.disabled')}")
            changed = True
    sd = Path("/etc/sddm.conf.d/zz-nvidia-vdisplay.conf")
    if sd.exists():
        sd.rename(sd.with_suffix(".conf.disabled"))
        print(f"已禁用：{sd} -> {sd.with_suffix('.conf.disabled')}")
        changed = True
    if not changed:
        print("未发现生效中的配置")
    if changed and args.restart_display:
        print("重启显示管理器 ...")
        print(_run(["systemctl", "restart", "sddm"]) or "已发送重启指令")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="vdisplay",
        description="无头 NVIDIA GPU 虚拟显示器工具（GT 730 / Kepler / 470 驱动）",
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="生成默认配置文件")
    sp.add_argument("-o", "--output", help="配置文件路径")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("generate", help="生成单个虚拟显示器 EDID")
    sp.add_argument("width", type=int)
    sp.add_argument("height", type=int)
    sp.add_argument("rate", nargs="?", type=int, default=60)
    sp.add_argument("-o", "--output", help="输出 .bin 文件（默认输出到 stdout）")
    sp.add_argument("--no-reduced", action="store_true",
                    help="使用常规 CVT 时序而非 CVT-RB")
    sp.add_argument("--name", default="VDI Virtual Display")
    sp.set_defaults(func=cmd_generate)

    sp = sub.add_parser("apply", help="按配置应用虚拟显示器")
    sp.add_argument("--restart-display", action="store_true",
                    help="应用后重启 sddm 立即生效")
    sp.add_argument("--no-initramfs", action="store_true",
                    help="跳过 update-initramfs")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("status", help="查看虚拟显示器与 GPU 状态")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("disable", help="禁用虚拟显示器配置")
    sp.add_argument("--restart-display", action="store_true")
    sp.set_defaults(func=cmd_disable)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
