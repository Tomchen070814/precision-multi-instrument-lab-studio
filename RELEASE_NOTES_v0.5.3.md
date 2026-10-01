# v0.5.3 — Python 三通道可靠性与仪器查看修复

2026-10-01

## 设备参数和数据切换

- 点击左侧 A/B/C 仪器页签，或在分析仪器下拉框中选一台，参数指标、
  会话信息、趋势、统计和分析会同时切换到该台仪器。
- 选择单台后自动进入单通道查看；勾选“同时显示所有启用通道”可恢复对比。
- 切换仪器时重置原仪器的缩放窗口，避免新仪器的数据被旧时间范围隐藏。
- 右侧参数区支持垂直滚动；较小窗口不会压缩会话、身份与保存卡片并遮住文字。
- 修复 Qt 将字符串枚举保存为字符串后，型号/功能选择错误回退到
  3458A / DCV 的问题；覆盖全部 14 款型号和各自测量功能。

## 曲线与坐标轴

- 实际曲线启用可见区域裁剪和峰值降采样；多 Y 轴绘图区边界一致。
- 副 Y 轴可通过轴上的鼠标操作单独缩放；矩形缩放不再被自动 Y 范围覆盖。
- 刷新和通道轴重新分配时保留手动 Y 范围；标记不再撑大自动范围。
- 悬停与标记只在绘图区内生效，避免坐标轴和边缘区域误选数据。
- 切换可见仪器或物理量坐标轴时清除旧标记，防止标记错挂到其他单位。

## 连接、停止和保存

- 三台仪器、扫描和连接自检共享 VISA 管理器的生命周期；停止某台或扫描时，
  仍在运行的其他通道继续保有连接，最后一个使用者释放后才关闭管理器。
- GPIB 同总线通信继续仲裁；不同 LAN/USB 仪器不再被同一接口前缀错误串行化。
- 同步启动某一通道无法建立自动保存，或启动等待中停止时，取消所有同组通道。
- 关闭窗口等待 GUI 接收排队样本并完成保存，旧采集事件不会污染后续会话。
- 停止请求在连接/配置前后检查；内部 TypeError 不再触发第二次突发采集。
- 保存文件或元数据重命名失败可重试，恢复路径始终指向实际存在的数据。

## 数据与兼容性

- 多通道 CSV 按所选通道配对读数、时间轴和温度，保留原时间戳与实际单位。
- CSV 导出保留双精度读数及时间；替换会话前验证数组长度，避免破坏已有采集。
- Allan 累加前去掉 DC 偏置，减少长记录中极小噪声的数值误差。
- 剔除异常样本后，时间序列不再连续：该通道暂停 FFT/ASD/Allan，并明确
  提示关闭异常过滤后恢复；统计、直方图和漂移继续使用过滤后的数据，
  没有剔除样本的其他通道继续分析，避免产生错误频率。
- 修复 Python 3.10–3.12 清空时间戳数组的兼容问题。
- 内存监控使用 psutil，支持 Windows / Linux / macOS。
- 新增跨 Windows/Linux 的 Python 检查及 Windows EXE 构建工作流。

## 验证范围

在 macOS / Python 3.12 与 3.14 上分别通过 163 项测试及 Ruff 检查。
自动测试使用数字孪生、模拟 VISA 后端和离屏 Qt 界面，覆盖三个通道的独立
点数、同步失败、关闭保存、仪器切换、CSV 往返与大数值缩放。Windows CI
会另外运行测试并打包 EXE。

真实仪表、VISA/GPIB 控制器和固件组合仍需在实验室验收。软件级同步启动
不提供硬件触发同步。逐样本 fsync 和全会话分析仍可能影响超长记录时的界面
响应，后续性能优化需同时保留数据耐久性保证。

## English

Selecting A/B/C now opens that instrument's individual measurements, metrics,
statistics and analysis; the existing all-channel option restores comparison.
The update fixes multi-axis zoom/clipping, shared VISA manager ownership,
synchronized startup cancellation, queued samples at shutdown, model/function
selection, and channel-aligned CSV import with timestamps, units and temperature.
Hardware acceptance remains pending for each real instrument/backend combination.
