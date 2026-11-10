# DJI Goggles Streamer 0.1.0

## Windows 安装与使用

1. 运行 `DJI-Goggles-Streamer-0.1.0-Setup.exe`，为当前用户安装或升级，保留原有设置。
2. 打开客户端。在「设备与驱动」确认 NVIDIA 硬件编码测试通过。
3. 将眼镜开机并通过 USB 数据线连接。缺少驱动时点击「下载并安装驱动」。
   首次需要从 DJI 官方下载约 354 MiB 安装包；也可导入匹配的官方 2.1.42
   安装包。客户端校验并提取所需驱动，Windows 提示管理员授权时完成授权。
4. 在眼镜中进入「更多 → DJI Virtual Flight」，等待型号与固件检测完成。
5. 回到「桌面串流」，选择帧率、码率或画质预设，点击「开始串流」。
6. 结束时点击「停止串流」。关闭客户端会先停止后台编码和释放 USB。

需要 Windows 10 2004 / Windows 11 x64、支持 NVENC 的 NVIDIA GPU 和数据线。
已验证固件：Goggles 2 01.11.00.00 / 01.14.00.00，Integra 01.09.00.00。
Goggles 2 01.12 有上游黑屏报告；未知版本会阻止串流，并提供官方更新/恢复教程。
客户端不会自动刷写眼镜。固件是否可升级或降级，以 DJI 官方工具实际列表为准。

本版可选择主屏或独立扩展屏，输出固定 1920×1080。主屏等比缩放补黑边，
不改变带鱼屏的原分辨率。Windows Graphics Capture 使用显示器实际句柄定位。
特定窗口选择、AMD/Intel 编码和 macOS 尚不支持。
USB 发送/队列指标不是端到端可见画面延迟。屏幕内容仅通过 USB 发送。

## 独立扩展屏（实验性）

1. 选择「独立扩展屏」，点击「安装扩展屏驱动」，完成 Windows 管理员授权。
2. 点击「启用 1080p 扩展屏」。Windows 添加主屏右侧的 1920×1080 / 60 Hz 桌面。
3. 把模拟器窗口拖过去，或使用 Win + Shift + → 移动窗口，也可在模拟器中选择显示器。
4. 选择 60 fps 后开始串流。扩展屏使用 Windows Graphics Capture。
5. 停止串流会保留该桌面。不用时保存应用工作并点击「断开扩展屏」。

客户端退出、卸载均不自动移除系统显示驱动。可先在客户端点击「移除扩展屏驱动」；
只移除本客户端创建的设备，保留可能供其他软件使用的驱动仓库包。
已有其他 VDD 时不覆盖其全局设置；通过 Windows 显示设置配置现有唯一的 1080p
非主虚拟屏后可串流。多个 VDD 显示器会拒绝自动选择，避免传错画面。
VDD 25.7.23 已签名，保留原始文件；不导入证书，不关闭系统签名验证。
本版扩展屏仍需首次管理员安装和硬件显示验证。升级 GPU/芯片组驱动前请参阅
[VDD 官方说明](https://github.com/VirtualDrivers/Virtual-Display-Driver)。

## 01.14.0000 黑屏排查结果

同机同眼镜可正常显示固定和运动测试图。0.1.0 在应用层显式转换桌面 RGB 为
限幅 NV12、归一化像素宽高比并每秒强制完整 IDR，避免继承桌面 sRGB 色彩描述。
原 SDK 文件和 USB 协议完全不变。两种桌面采集均已本机解码验证，并通过真实 USB
持续发送测试；用户离开期间无法目视眼镜，所以此项是待硬件确认的兼容修复。
若仍黑屏，先停止、重启眼镜并进入 Virtual Flight，再以 60 fps / 8 Mbps 测试。

安装包尚未附加商业代码签名。Windows 可能显示未知发布者；发行 SHA-256
用于核对下载文件。大疆驱动自身保留原厂签名，不要求关闭系统驱动签名验证。

设置、下载缓存与日志存放在 `%LOCALAPPDATA%\DJI Goggles Streamer`。
「帮助与诊断」可打开日志或导出诊断包；不会自动上传。卸载保留这些用户数据，
也不会移除可能供 DJI 软件共用的驱动。离线教程与第三方许可随软件安装。

## 开发与版本

保持 `goggles_bridge/`、原有 `scripts/`、`tools/research/`、`tests/` 与
`requirements.txt` 不变，应用在 `desktop_app/`，独立测试在 `desktop_tests/`。
SDK 哈希校验：`python packaging/windows/verify_sdk.py`。

Windows 源码运行：Python 3.11 x64，创建 `.venv` 后安装
`requirements-build.txt`，执行 `python packaging/windows/prepare.py`，
然后 `python -m desktop_app`。运行 `packaging/windows/build.ps1` 打包；
用 `-Iscc` 指定 Inno Setup 6.7.4 的编译器路径。

版本规则：初始 0.0.1；新增功能/大更新增加次版本，例如 0.1.0；仅修复或
测试增加补丁版本，例如 0.0.2。同步更新 Python 版本、安装器与 Windows 资源。
提交遵循上游 `type(scope): lowercase imperative description`，文档使用
`chore(docs)`；在功能分支开发，保留上游 CLI，按独立关注点回馈上游。
