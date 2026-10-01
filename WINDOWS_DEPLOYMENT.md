# Windows 使用与离线部署

本次发布目标为 Windows x64；不提供 macOS/Linux 安装包。源码可用于开发测试。

## 无硬件演示

下载 GitHub Actions 中 `Precision-Lab-Studio-Windows`，解压后双击
`Precision-Multi-Instrument-Lab-Studio.exe`。无需安装 Python、pip 或联网下载依赖。
程序使用 Windows 字体并包含 Qt、NumPy、SciPy、PyVISA 及应用代码。

现有 DMM 通道选择 SIMULATOR，可三路同步启动、切换单仪表和测量函数。
右侧“数据”中的“二极管 I-V 模拟”打开虚拟三台 SMU 演示；点击开始，查看
三种二极管曲线和模拟 GPIB/SCPI 指令。该窗口未打开 VISA、未输出真实电压。
可选择 A/B/C 单路、缩放图表、停止并导出模拟 CSV。

## 连接真实 DMM

先在实验室机器安装与 GPIB 控制器匹配的 Windows x64 驱动及 VISA 运行时。
例如 NI 控制器通常需要 NI-488.2 与 NI-VISA；Keysight 控制器使用对应
IO Libraries。单个 EXE 不包含厂商内核驱动或驱动安装流程。
可在有网电脑准备厂商离线安装包后复制到实验室安装；管理员权限取决于厂商安装器。
在厂商工具中验证地址和仪表身份，再在软件中选择型号、VISA 地址并执行自检。

参考：[NI 仪器控制软件要求](https://knowledge.ni.com/KnowledgeArticleDetails?id=kA00Z0000019XKkSAM&l=en-US)。

## 保存与恢复

默认自动保存目录为 `%LOCALAPPDATA%\Precision Multi-Instrument Lab Studio\autosave`。
界面入队和后台落盘分开，批次正常约 200 ms 同步一次；慢磁盘会延长窗口。
正常停止或关闭会排空已接收队列后完成文件。不要在保存期间用任务管理器强制结束。
异常终止留下 `.partial.csv`，已落盘行可直接导入；队列中尚未同步的末尾不保证保留。

通信中断仅让受影响通道进入“正在重连”，最多 5 次退避尝试。重连成功继续原会话。
采集错误、磁盘满或队列满时查看事件和诊断报告；内存中数据可导出，切勿在导出前清空。

## 构建与验证

GitHub Actions 在 Windows 运行 Python 3.11/3.14 回归，并用 3.11 构建单文件 EXE。
构建后直接运行 EXE 的 `--smoke-test`，验证三路 DMM 与虚拟 I-V、Qt 计时器和安全退出，
验证阶段移除 PATH 中的 Python，结果保存在 `Windows-frozen-validation` 工件。
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
