# Windows 使用与离线部署

本次发布目标为 Windows x64；不提供 macOS/Linux 安装包。源码可用于开发测试。
首次启动默认 English；右上角 **LANGUAGE（语言）** 可选择 English / 中文。
手动偏好会保存并在下次启动恢复，已有中文选择保持不变。下面使用英文界面的
实际按钮名称，并附必要中文对应。

## 无硬件演示

下载 GitHub Actions 中 `Precision-Lab-Studio-Windows`，解压后双击
`Precision-Multi-Instrument-Lab-Studio.exe`。无需安装 Python、pip 或联网下载依赖。
程序使用 Windows 字体并包含 Qt、NumPy、SciPy、PyVISA 及应用代码。

在 DMM 通道的 **Data source（数据来源）** 中选择 **Demo · digital twin（演示模式 · 数字孪生）**。
通过 **Enable instrument channel C（启用第三仪器通道 C）** 启用第三路，
在 **SYNCHRONIZED START GROUP（同步启动组合）** 勾选 A/B/C 后点击
**Synchronized start A+B+C（同步启动 A+B+C）**。可切换单仪表和测量功能；
**Compare all channels（同时显示所有启用通道）** 恢复多路对比。
曲线图不再显示内嵌 A/B/C 图例，通道页签与通道选择仍保留。

右侧 **DATA（数据）** 中的 **Diode I-V demo（二极管 I-V 模拟）** 打开虚拟
三台 SMU 演示；点击 **Run A+B+C（开始模拟 A+B+C）**，查看三种二极管曲线和模拟
GPIB/SCPI 指令。该窗口未打开 VISA、未输出真实电压。
可选择 A/B/C 单路、缩放图表，点击 **Stop（停止）** 停止，
再用 **Export CSV（导出 CSV）** 导出模拟 CSV。真实硬件采集范围为受支持 DMM，
本演示不提供真实 SMU 源表驱动。

## 连接真实 DMM

先在实验室机器安装与 GPIB 控制器匹配的 Windows x64 驱动及 VISA 运行时。
例如 NI 控制器通常需要 NI-488.2 与 NI-VISA；Keysight 控制器使用对应
IO Libraries。单个 EXE 不包含厂商内核驱动或驱动安装流程。
可在有网电脑准备厂商离线安装包后复制到实验室安装；管理员权限取决于厂商安装器。
在厂商工具中验证地址和仪表身份，再在软件中选择 **Instrument model（仪表型号）**，
将 **Data source（数据来源）** 设为 **Physical instrument · VISA / GPIB（真实仪表 · VISA / GPIB）**，
选择 VISA 地址后点击 **Self-check（连接自检）**。

参考：[NI 仪器控制软件要求](https://knowledge.ni.com/KnowledgeArticleDetails?id=kA00Z0000019XKkSAM&l=en-US)。

## 保存与恢复

默认自动保存目录为 `%LOCALAPPDATA%\Precision Multi-Instrument Lab Studio\autosave`。
右侧 **SAFE AUTOSAVE（安全自动保存）** 中的 **Open autosave folder（打开自动保存目录）**
可直接打开该目录。
界面入队和后台落盘分开，批次正常约 200 ms 同步一次；慢磁盘会延长窗口。
正常停止或关闭会排空已接收队列后完成文件。不要在保存期间用任务管理器强制结束。
异常终止留下 `.partial.csv`，已落盘行可直接导入；队列中尚未同步的末尾不保证保留。

通信中断仅让受影响通道进入 **Reconnecting（正在重连）**，最多 5 次退避尝试。
重连成功继续原会话。采集错误、磁盘满或队列满时查看 **EVENTS（事件）**，
点击 **Export diagnostics（导出诊断报告）** 导出诊断。
内存中数据可通过 **Export selected（导出所选）** 或 **Export all（导出全部）** 保存，
切勿在导出前点击 **Clear selected（清空所选）**。

## 构建与验证

GitHub Actions 在 Windows 运行 Python 3.11/3.14 回归，并用 3.11 构建单文件 EXE。
构建后直接运行 EXE 的 `--smoke-test`，检查三路 DMM 各 15 点、V/Ω/A 单位与
实际 CSV、虚拟 I-V 三路各 21 点、Qt 计时器和安全退出。该阶段使用原生 Windows Qt
插件，移除 PATH 中的 Python 和 PYTHONPATH；JSON 结果与窗口 PNG 保存在
`Windows-frozen-validation` 工件。只有相应运行的完整回归与 frozen smoke 成功，
才视为该修订通过 Windows 打包验证；当前修订仍待成功结果。
本机硬件验收仍须覆盖具体仪表型号、固件、控制器和长时间连续采集。

可在 Windows 构建：

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python -m PyInstaller --noconfirm --clean 3458A_Lab_Studio.spec
.\dist\Precision-Multi-Instrument-Lab-Studio.exe --smoke-test .\dist\frozen-smoke.json
```

PyInstaller 输出针对构建操作系统；EXE 由 Windows runner 构建。
参考：[PyInstaller 的构建与运行机制](https://pyinstaller.org/en/stable/operating-mode.html)。
