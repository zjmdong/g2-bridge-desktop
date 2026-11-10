# DJI Goggles Streamer 0.0.1

## Windows 安装与使用

1. 运行 `DJI-Goggles-Streamer-0.0.1-Setup.exe`，为当前用户安装。
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

本版使用 SDK 默认显示器索引 0，输出固定 1920×1080。只支持桌面来源；
特定窗口、独立扩展桌面、AMD/Intel 编码和 macOS 不属于 0.0.1。
USB 发送/队列指标不是端到端可见画面延迟。屏幕内容仅通过 USB 发送。

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
