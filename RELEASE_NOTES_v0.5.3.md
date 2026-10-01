# v0.5.3 — Python 三通道可靠性与仪器查看修复

2026-10-01

## 默认语言与图表显示

- 首次启动默认 English，右上角 LANGUAGE 可手动选择 English / 中文；
  保存并恢复用户偏好，已有中文选择保持不变。
- 移除曲线图中的内嵌 A/B/C 图例。仪器页签、分析通道选择和
  “Compare all channels（同时显示所有启用通道）”仍可用于单路查看和多路对比。

## 设备参数和数据切换

- 点击左侧 A/B/C 仪器页签，或在分析仪器下拉框中选一台，参数指标、
  会话信息、趋势、统计和分析会同时切换到该台仪器。
- 选择单台后自动进入单通道查看；勾选“同时显示所有启用通道”可恢复对比。
- 切换仪器时重置原仪器的缩放窗口，避免新仪器的数据被旧时间范围隐藏。
- 单台停止、改测量功能后重启时重置该台的旧时间窗口；
  其他通道继续采集，未显示通道的重启不会打断当前仪器的缩放查看。
- 读数卡显示本次采集设定的 Δt，并说明慢采样等待；仪器设置的滚轮操作
  只滚动面板，防止采样间隔、测量功能或量程被意外修改。
- 右侧参数区支持垂直滚动；较小窗口不会压缩会话、身份与保存卡片并遮住文字。
- VISA 地址独占一行，扫描/自检按钮按完整文本分配宽度，避免英文按钮被固定宽度截断。
- 隐藏分析页不再影响中心区高度分配；启动、采集中及保存终结时，指标卡与标签栏保持间距。
- 长状态文字独占一行并换行；采样间隔/温度按视口宽度分配，同步启动与停止按钮上下排列，按原生字体宽度保留全文换行，避免小窗口横向截字。
- 窄窗口或较大字体下，右侧按钮、复选框和长自动保存路径按宽度换行；
  左侧仪器选项不再撑宽参数区或在获得焦点时横向移动。
- 采样间隔 Δt 独立显示，趋势工具栏分两行；语言切换保留实时仪器来源、
  温度和各台采集状态。
- 读数卡按可用宽度缩小数字字号，保留完整精密读数和单位；采样间隔与温度
  在窄卡片中分行。覆盖不同字体、原生滚动条与最小窗口的布局验证。
- 停止后修改下一次测量的功能、型号或地址，不再重标旧会话数据。
  指标、读数卡和诊断保留本次采集的配置；CSV 未提供的功能显示未知，避免
  把导入数据错误标为当前仪器的 DCV/ACV。
- 修复 Qt 将字符串枚举保存为字符串后，型号/功能选择错误回退到
  3458A / DCV 的问题；覆盖全部 14 款型号和各自测量功能。

## 曲线与坐标轴

- 实际曲线启用可见区域裁剪和峰值降采样；多 Y 轴绘图区边界一致。
- 新采集只有一个样本时显示点标记；各通道共同确定时间轴范围，避免
  不同开始时间、采样速度或空副轴使曲线消失。
- 手动缩放时保留时间窗口两侧的相邻点，慢速采样曲线跨过窗口时仍可见。
- 仅显示所选通道的滑动平均线，防止均值线错挂到其他单位的轴。
- 修正深度缩放后重复使用旧裁剪缓存的问题；绘图库最低版本为已验证的
  pyqtgraph 0.14。
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
- 内存监控使用 psutil；本次发布仅支持 Windows x64。
- Windows Python 3.11/3.14 自动回归，3.11 构建单文件 EXE，并直接运行打包后的三路 DMM 与虚拟 SMU 冒烟测试。

## 工业级可靠性与演示

- 精密 DMM 在可恢复 VISA 超时/断线后最多退避重连 5 次，保留会话、累计样本和目标数；同行独立运行。未知结果的高速突发不自动重复触发。
- 非有限和溢出读数不会进入会话。重连造成的时间缺口暂停 FFT/ASD/Allan，统计与漂移仍可查看。
- 后台有界队列批次落盘，正常约 200 ms 同步一次；磁盘延迟时窗口延长。队列满/写入失败明确停止并保留已有文件，停止/关闭异步排空。
- 实时及长记录分析移至后台，合并待处理刷新，只保留最新一份待算快照。过期来源/最终刷新前的结果不覆盖当前会话。
- 新增独立虚拟 SMU 二极管 I-V 演示，高斯测量噪声、串联电阻模型、电流限值、三路/单路显示及 CSV。模拟指令记录明确标注 SIM。

## 验证范围

自动回归数量与 Windows 打包验证结果见对应 GitHub Actions 运行。
自动测试使用数字孪生、模拟 VISA 后端和离屏 Qt 界面，覆盖三个通道的独立
点数、同步失败、关闭保存、仪器切换、CSV 往返与大数值缩放。Windows CI
会另外运行测试并打包 EXE。只有对应修订的完整回归和 frozen EXE
冒烟验证都成功，才视为该修订通过；构建流程的存在不代表验证成功。

真实仪表、VISA/GPIB 控制器和固件组合仍需在实验室验收。软件级同步启动
不提供硬件触发同步。进程突然终止可能丢失尚未同步的队列末尾；已落盘数据保留。
Windows EXE 包含 Python/Qt/分析依赖，真实 GPIB 仍需匹配控制器的系统驱动与 VISA 运行时。

## English

Selecting A/B/C now opens that instrument's individual measurements, metrics,
statistics and analysis; the existing all-channel option restores comparison.
English is the first-launch default, and saved English/Chinese preferences are
restored. Embedded A/B/C curve legends are removed while instrument selection
and **Compare all channels** remain available.
The update fixes multi-axis zoom/clipping, shared VISA manager ownership,
synchronized startup cancellation, queued samples at shutdown, model/function
selection, and channel-aligned CSV import with timestamps, units and temperature.
Hardware acceptance remains pending for each real instrument/backend combination.
Check the corresponding GitHub Actions run for this revision's Windows regression
and frozen-EXE smoke results; both must pass for a validated build.
