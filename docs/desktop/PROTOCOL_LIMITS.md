# USB 串流协议、性能边界与审阅记录

审阅日期：2026-11-11。上游基线为
[`a34690a58d48f0cd9b43cdeddf39b5efaf024b9c`](https://github.com/Ammaar-Alam/g2-bridge/commit/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c)。
联网核对时，上游 `main` 仍指向此提交；该提交合并了 macOS 捕获时间戳抖动修复。
下文区分代码约束、原作者的硬件观察、数学估计和未知项，**不包含新版桌面客户端的实测结果**。
本次协议审阅没有连接设备、发送测试视频、重新运行厂商二进制仿真或测量镜片显示延迟。

## 已恢复的 PC 视频路径

已验证路径是 Goggles 2 的 Virtual Flight 模式，通过 USB MI04 接收 H.264。
设备 VID/PID 为 `2ca3:0020`，接口 class/subclass/protocol 为 `ff/43/01`；
bulk OUT 为 `0x04`，bulk IN 为 `0x85`，已支持的高速端点最大包长为 512 字节。
SDK 会拒绝曾观察到的 64 字节、12 Mbps full-speed 回退状态。
这些描述符说明当前连接路径，不证明设备具有一个可由软件开启的 SuperSpeed 视频接口。
换用 USB 3.x 主机端口不会自动改变此设备端点的速率和传输类型。

初始化依次确认心跳、身份和 simulator mode 成功回复，之后每 500 ms 发送心跳。
视频从 PC `10/1` 发往 `28/1`，命令为 DUML V1 `0b/53`，**不请求应用层确认**。
心跳成功只能说明控制会话仍有响应，不能证明某张画面已经解码或显示。
详见[上游 PC 协议](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/docs/PROTOCOL.md)。

| 项目 | 已恢复的含义 | 不能据此推断的结论 |
| --- | --- | --- |
| DUML V1 长度 | 10 位长度，总包最多 1,023 字节 | 不是整张编码帧的大小上限 |
| 视频分片 | 每片 978 字节编码数据，另有 32 字节元数据与 13 字节 DUML 开销 | 不是每次 USB API 调用的大小 |
| DUML sequence | 16 位循环计数，控制与视频共用；跳过未完成控制请求的序号 | 不限制为 100 fps；回绕不是流结束 |
| fragment counter | 全局 32 位循环计数，每片递增 | 不提供逐帧播放确认 |
| first/last 标志 | 表达一张编码帧的分片边界 | 不指定面板展示时间 |
| 时间戳 | 封包时逐片采样 Unix 毫秒，保留低 32 位、按有符号数扩展至 64 位 | 不是捕获 PTS，也不是与接收端同步的高精度展示时钟 |
| H.264 SPS | 可以声明编码分辨率、时间信息和解码缓冲约束 | 不证明眼镜采用同样的实际刷新节奏或固定解码延迟 |

32 字节视频元数据中没有已恢复的码率、目标帧率、面板模式、播放截止时间、
展示时钟同步或接收队列深度字段。接收代码没有逐帧接收、解码完成或面板展示反馈。
目前不能排除尚未恢复的其他命令，但不能把未找到的能力当作可用功能。

Android 原生视频使用 V2，每片最多 65,404 字节编码数据；这是移动端的分片大小。
PC 上对 V2、LogicLink、不同源地址、不同写入大小的多轮尝试均未成功显示。
因此不能将 PC V1 直接换成 V2 来减少封装，也不能把 65,404 当作已确认的 PC 接收帧上限。
参考[移动协议](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/docs/research/MOBILE_PROTOCOL.md)
与[传输实验](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/docs/research/EXPERIMENTS.md#transport-tests)。

## 帧率、码率与整帧大小

DJI 公布的 Goggles 2 单眼分辨率为 1920×1080，刷新率最高为 100 Hz。
同一页面的 50 Mbps 和 1080p100 下 30 ms 指标属于飞机无线图传，不能套用到 Virtual Flight USB 路径。
来源：[DJI 官方规格](https://www.dji.com/support/product/goggles-2)。

上游支持 60、75、90、100 fps 编码目标，但明确说明这些选项不选择眼镜面板模式。
100 fps 的发送计数不证明镜片显示了 100 张不同画面。
不同画面的实际输出能力受源应用、显示合成、捕获、编码、传输、解码和面板共同限制：

```text
Fdistinct <= min(Fsource, Fcapture, Fencode, Ftransport, Fdecode, Fpanel)
```

例如，实际只有 60 Hz 更新的桌面不能凭 240 fps 捕获设置产生 100 张新的桌面画面。
100 Hz 虚拟显示器也只有在应用和合成器及时产生新帧时才可能供应 100 张新画面。
统一捕获实现可以消除额外路径差异，不能消除真实源刷新率和渲染负载的差异。

上游 Windows SDK 使用平均每帧 50,000 字节的配置预算，以及 56,000 字节的发送前单帧保护。
在其离散码率选项下，对应上限如下；`Mbps` 均按十进制 `1,000,000 bits/s` 计算。

| 编码目标 | 目标间隔 | 50,000 字节平均预算对应码率 | SDK 可选最大码率 |
| ---: | ---: | ---: | ---: |
| 60 fps | 16.667 ms | 24 Mbps | 24 Mbps |
| 75 fps | 13.333 ms | 30 Mbps | 30 Mbps |
| 90 fps | 11.111 ms | 36 Mbps | 32 Mbps |
| 100 fps | 10 ms | 40 Mbps | 40 Mbps |

**40 Mbps 是选项和实验预算形成的工程上限，不是 DUML 协议的硬上限。**
90 fps 的 36 Mbps 是预算计算值，没有作为当前选项提供，也没有据此完成硬件验证。
Windows NVENC 的 VBV 设置为：

```text
VBVbits = min(2 × min(bitrate_bits_per_second, 20,000,000) / fps, 448,000)
```

实现使用整数除法。20 Mbps/100 fps 对应 400,000 bits，即 50,000 字节的模型缓冲。
这不是“每帧强制等待 20 ms”的计时器，也不保证每张编码帧都小于此大小。

上游在 01.14 固件上的复杂分形画面实验显示：约 49 KB 的帧显示成功；约 65 KB 的关键帧出现冻结；
79–103 KB 的关键帧导致黑屏，部分状态需要眼镜断电重启才能恢复。
限制帧尺寸后，40 Mbps/100 fps 的一次 30 秒测试正常显示、未跳过编码帧。
这些是有限样本的接受/失败观察，未逆向得到接收端的确切分配大小或所有内容的阈值。
56,000 字节保护值不应描述为已确认的硬件缓冲区大小，也不能通过提高该值保证提高画质。
来源：[原作者帧尺寸与码率实验](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/docs/research/EXPERIMENTS.md#frame-size-limit-and-bitrate)。

## USB 数学预算与延迟边界

设去掉 AUD/filler 后的编码帧长为 `B` 字节。PC V1 的精确封装长度为：

```text
n(B) = ceil(B / 978)
W(B) = B + 45 × n(B)
Rwire = 8 × sum(W(Bi)) / observation_seconds
```

`W` 是提交给 USB API 的视频字节数，未计入 USB 自身的 token、握手、CRC、间隔、bit stuffing 和控制流量。
下表仅举等于平均预算的帧；真实编码帧大小不会逐张相等。

| 编码帧 B | DUML 片数 | W(B) | 按每秒 100 张计算的视频 wire 码率 | W×8/480 Mbps |
| ---: | ---: | ---: | ---: | ---: |
| 25,000 B，20 Mbps 平均帧 | 26 | 26,170 B | 20.936 Mbps | 0.4362 ms |
| 50,000 B，40 Mbps 平均帧 | 52 | 52,340 B | 41.872 Mbps | 0.8723 ms |
| 56,000 B，SDK 单帧保护值 | 58 | 58,610 B | 46.888 Mbps | 0.9768 ms |

最后一列只是忽略 USB 协议成本的**原始串行化时间乐观下界**，不是传输实测值，更不是端到端最低延迟。
USB-IF 将 High Speed 信号速率定义为 480 Mb/s；USB 2.0 规范 5.8、表 5-10 的理想 bulk 预算为
每个 125 μs microframe 最多 13 个 512 字节载荷，即 53,248,000 B/s（425.984 Mbps）。
再扣满 DUML 分片的比例，编码数据渐近预算约为 `425.984 × 978 / 1023 = 407.246 Mbps`。
这仍排除了实际控制流量、调度、重试等，并且不代表眼镜解码器能够接收此码率。
规范包内 `usb_20.pdf` 第 54–55 页说明主控不一定达到表中的最大事务数。
来源：[USB-IF High Speed 定义](https://www.usb.org/node/214)、
[USB-IF USB 2.0 规范页面](https://www.usb.org/document-library/usb-20-specification)、
[该页面提供的官方规范包](https://www.usb.org/sites/default/files/usb_20_20250603.zip)。

USB bulk 使用可用带宽，设备忙可返回 NAK，校验失败会重传；它没有带宽和延迟预留。
低平均占用率不排除主控调度、驱动完成回调或接收端反压造成的长尾。
Microsoft 文档明确指出总线繁忙时 bulk 可以无限等待。因此，此路径没有可由应用保证的有限最坏传输延迟。
来源：[Microsoft USB bulk 说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/usb-bulk-and-interrupt-transfer)。

为了避免混淆，端到端延迟需要分解为：

```text
L = 源渲染/呈现到捕获
  + 捕获转换与编码
  + 主机缓存与封包
  + USB 提交到传输完成
  + 眼镜接收、解码、等待扫描及像素响应
```

控制器到光子的延迟还包含控制器轮询、游戏输入与模拟更新。
上述 USB 串行化预算只能描述第四项的一部分。
未公开的眼镜解码/显示策略使得现有源码不能给出精确的端到端理论最小值。
也不能将一帧 10 ms 武断视为总延迟的硬下界：扫描位置、异步阶段的相位和测量参考都会改变某个像素的时间差。

如果接收端确实使用固定 100 Hz 扫描且与到达时刻异步，等待下一次扫描的相位模型可产生约 0–10 ms 的等待；
仅在相位均匀的假设下平均值才是约 5 ms。这是说明风险的模型，**不是对 Virtual Flight 内部实现的测量**。

## 原作者约 12 ms 测量的真实含义

原作者报告的是特定条件下，电脑显示器与一个眼镜镜片相同亮度变化之间的附加延迟。
它不是每张帧的固定延迟，也不是控制器到光子的延迟。

| 条件 | 原作者记录 |
| --- | --- |
| 捕获 | native D3D11 原型，非当时发布 CLI 的 Windows Graphics Capture 路径 |
| 硬件 | RTX 5060 Laptop，240 Hz 源显示器，无附加 GPU 负载 |
| 眼镜 | Goggles 2，固件 01.11.00.00 |
| 编码 | 1920×1080，100 fps 目标，20 Mbps，NVENC High/P4 |
| 样本 | 20 次黑白变化，比较两处 50% 亮度交叉点 |
| 结果 | 中位 12.1 ms，均值 10.3 ms，p95 16.0 ms，范围 2.1–16.5 ms |

这些数值来自[原作者测量报告](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/docs/LATENCY.md)。
同一硬件的 Windows CLI 曾报告空闲中位 13.3 ms、范围 6.7–26.7 ms，GPU 争用测试中位 14.6 ms、范围 12.5–20.8 ms；
这些记录的捕获方式、图案和负载不同，不能视为严格匹配的 A/B 比较。
来源：[上游 monitor-to-lens 实验](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/docs/research/EXPERIMENTS.md#monitor-to-lens-delay)。

240 fps 相机每个样本间隔约 4.17 ms，线性插值不提供亚毫秒物理精度。
原作者自己的范围已明显大于中位值的 1%，而该测量方案也不足以验证 100 μs 级稳定性。
报告新版时必须独立记录测试条件，不能复用原作者的中位数作为当前客户端实测。

## 为什么不能保证全程 1% 波动与逐帧零差异

100 fps 的间隔为 10 ms，其 1% 为 100 μs；12 ms 延迟的 1% 为 120 μs。
Windows 不提供固有硬实时调度，线程无论优先级如何都可能被硬件和部分软件中断抢占。
提高进程、线程或 GPU 优先级能够减少部分争用，不等于获得最坏执行时限保证。
来源：[Microsoft 调度说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/kernel/always-preemptible-and-always-interruptible)。

当前还缺少眼镜展示时钟、接收队列和逐帧展示反馈，发送端无法对镜片展示相位闭环控制或证明不丢显示帧。
不能单凭 USB 的 125 μs microframe 断言所有 100 μs 稳定目标在数学上不可能；真正缺失的是全链路的时限保证与观测能力。
对于任意系统负载和任意持续时间，当前平台和协议不能承诺以下组合：最低延迟、每帧等间隔、零重复、零丢帧。
源应用某张帧迟到后，保留固定展示节奏必须重复/舍弃内容或预留等待缓冲；预留缓冲又增加正常延迟。

“码率波动 1%”还必须定义测量窗口、编码字节与 wire 字节、是否含 filler、启动段和采集暂停的处理。
CBR 是编码器的平均目标，不等于每张帧大小相等或 USB 字节均匀到达。
NVIDIA 对严格码率遵从单独提供 filler 插入功能；filler 不增加可见画面信息。
来源：[NVIDIA NVENC rate control](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-video-encoder-api-prog-guide/index.html#rate-control)。

上游低延迟模式主动移除 type 12 filler；其灰画面实验在保持解码像素相同的情况下，300 帧 wire 数据由约 7.85 MB 降到 28.7 KB。
因此静态画面的实际码率下降不自动意味着画质下降或传输卡顿。
重新填充数据可以改变仪表读数，但不能解决源帧迟到或接收端显示抖动。
来源：[上游捕获与封装实验](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/docs/research/EXPERIMENTS.md#capture-and-host-framing)。

1080p100 的未压缩 8-bit NV12 为 `1920×1080×100×12 = 2.48832 Gbps`，
RGB24 为 `1920×1080×100×24 = 4.97664 Gbps`，均超过上述 USB 路径。
当前有损 H.264 4:2:0 不能承诺任意内容与 RGB 有线显示器逐像素等价。
可优化的目标是视觉质量、低且可恢复的帧龄、较小的长尾，以及没有程序主动累积的延迟。

## 基线代码中的优化机会与注意事项

以下描述针对被审阅的上游基线；后续修复和验证结果应另记版本文档，不应改写成这里已经完成的测试。

- `engine.py` 的一帧 `Queue` 不能代表全链只缓存一帧；reader 的局部解析结果、FFmpeg pipe、编码器内部和当前发送帧仍然存在。
  应追踪各阶段最早可得时间与背压，避免把局部队列长度当作整个视频链路的延迟。
- `completed_at` 在 `splitter.feed()` 返回后逐帧采样。一个 read 解出多张小帧，且前面的 `put()` 阻塞时，后帧的时间戳会推迟。
  因此基线的 `queue_ms` 可能低估已经到达 reader 的数据年龄，且它始终不包含捕获与编码时间。
- 每个 16 KiB 同步 USB write 的 timeout 为 500 ms；平均 20 Mbps/100 fps 帧通常需要两次调用，允许的最大帧需要四次。
  单帧总 deadline、可取消等待和失效恢复可避免程序无限积压；缩短 timeout 本身不会消除物理传输抖动。
- 原作者逆向记录表明 DJI DLL 的同步 write 为每次调用创建、提交、等待并释放 async context。
  复用上下文和减少提交间空档值得研究，但必须验证 cancellation、缓冲区寿命、短写和拔线清理。
- 240 Hz 输入选择为 100 fps 时，选中帧的源时间可能交替落在 8.333/12.5 ms 间隔上。
  `setpts` 只更改媒体时间戳，不会把实际事件变成严格 10 ms；发送后排队平滑可能换来额外延迟。
- 保留 AVI 完整包边界释放与快速 CRC。Annex-B 等下一 AUD 的解析方式在上游同源比较中增加了约一帧等待。
  `bufsize=0` 的 raw pipe `read(16384)` 不应直接解释为“必须凑满 16 KiB 才返回”。
- 不能任意丢弃已经编码的参考 P 帧。丢原始陈旧捕获帧与丢编码参考帧不同；后者需要明确的 IDR/参考链恢复。
- VBV 不是单帧大小的硬保证。上游测试中缩到一帧 VBV 使 20 Mbps 目标的运动数据降至约 13.4 Mbps，并降低画质指标；
  放大 VBV、启用 AQ 或增大帧保护值也需要检查关键帧突发及接收兼容性。
- 控制回复和显示确认不能混用。不得为了显示“实时端到端延迟”而把 USB write 耗时或心跳 RTT 重新命名为光学延迟。

对应证据：[上游 engine.py](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/goggles_bridge/engine.py)、
[上游 USB transport](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/goggles_bridge/usb_transport.py)、
[原生 DLL 分析](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/docs/research/NATIVE_ANALYSIS.md)、
[Windows 质量与捕获抖动研究](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/docs/research/WINDOWS_QUALITY.md)。

## 本次实际审阅范围

清单按上游提交的 Git tree 与目录枚举核对。阅读与计算不等同于执行测试。
厂商 APK、DLL、固件和相机原始录制未在本次重新获取或独立重现。

| 类别 | 已阅读内容 |
| --- | --- |
| 入口与贡献要求 | `README.md`、`CONTRIBUTING.md`、`docs/LATENCY.md`、`docs/PROTOCOL.md` |
| 全部研究 Markdown，**12 个，包含研究 README** | `ARTIFACTS.md`、`DEVICE_DIAGNOSTICS.md`、`EXPERIMENTS.md`、`GOGGLES3.md`、`MOBILE_PROTOCOL.md`、`NATIVE_ANALYSIS.md`、`OPEN_QUESTIONS.md`、`README.md`、`RELATED.md`、`REPRODUCE.md`、`STEREO.md`、`WINDOWS_QUALITY.md` |
| 全部 SDK 源文件 | `__init__.py`、`annexb.py`、`avi.py`、`control.py`、`duml.py`、`engine.py`、`mac_capture.py`、`mac_capture.swift`、`pc_video.py`、`protocol.py`、`session.py`、`usb_transport.py` |
| 原始运行脚本 | `scripts/stream_desktop.py`、`scripts/latency_pattern.py`、`scripts/linux/60-dji-goggles.rules` |
| 全部 19 个 Python 测试模块 | `test_avi.py`、`test_control.py`、`test_crc_fast.py`、`test_encoder_recovery.py`、`test_engine.py`、`test_firmware.py`、`test_latency_pattern.py`、`test_mac_frame_rate.py`、`test_native_wire.py`、`test_pc_video.py`、`test_probe_goggles.py`、`test_protocol.py`、`test_session.py`、`test_stereo_probe.py`、`test_stream_desktop.py`、`test_streams.py`、`test_usb_descriptors.py`、`test_usb_profile.py`、`test_usb_writes.py` |
| 测试辅助源文件 | `tests/avi_fixture.py`、`tests/mac_frame_rate.swift` |
| 全部 15 个研究 Python 工具 | `benchmark_framing.py`、`check_frame_pacing.py`、`compare_quality.py`、`emulate_serializer.py`、`emulate_v1.py`、`emulate_video.py`、`emulate_video_wire.py`、`firmware.py`、`listen_endpoint.py`、`packetize_mobile_frame.py`、`packetize_pc_frame.py`、`probe_goggles.py`、`read_usb_descriptors.py`、`research_common.py`、`stereo_probe.py` |
| 其他研究源码与配置 | `Get-GogglesUsbInventory.ps1`、`requirements.txt`、`ghidra/FocusedNative.java`、`ghidra/FocusedPe.java`、`ghidra/InspectTransport.java`，以及 `targets/` 下全部 7 个 TSV 地址/符号清单 |
| 直接检查的结构化证据 | `tests/fixtures/usb-link-profiles.json`、`docs/research/evidence/usb-write-equivalence.json`、`docs/research/evidence/crc-benchmark.json`；另解析了 `tests/fixtures/` 全部 6 个 JSON 的结构与案例数量 |

没有把所有归档 evidence JSON、二进制 fixture、图片逐项重新测量；文中其他历史硬件/质量数值以原作者已链接的实验记录为来源。
本次补读的 probe、firmware、stereo 与 macOS 工具没有提供隐藏的 PC 展示时钟或接收队列控制能力。
最终未解问题仍与[上游开放问题](https://github.com/Ammaar-Alam/g2-bridge/blob/a34690a58d48f0cd9b43cdeddf39b5efaf024b9c/docs/research/OPEN_QUESTIONS.md)一致：
接收端缓冲与展示策略、实际不同画面的镜片帧率、SEI 时间信息是否被采用，以及 USB 中断的硬件/驱动原因。
