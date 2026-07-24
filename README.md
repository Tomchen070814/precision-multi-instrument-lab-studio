# Precision Multi-Instrument Lab Studio

**简体中文** | [English](README_EN.md)

面向 Windows 的中英双语、多设备精密采集与分析平台。A、B 为默认启用通道，
C 为默认关闭的第三仪器通道。每个通道可从 10 个厂家、14 款仪表中独立选择
型号，并拥有独立 VISA 会话、采集线程、测量功能、单位、时间轴和安全自动保存
文件；没有仪表时也可以使用对应型号的数字孪生演示功能。

English UI is available from the language switch in the top-right corner. The
selected language, window geometry, panel widths and Channel C state are
remembered automatically.

> 3458A 使用自己的 HP‑IB 命令集，8508A 使用自己的 IEEE‑488 命令集；二者
> 都不能套用通用 SCPI。其余 12 款型号使用各自的 SCPI 配置文件。所有真机
> 连接都会查询并严格核对型号身份，三类协议驱动相互隔离。

当前版本：v0.5.2。本版在 v0.5.1 的 14 型号架构上增加连接自检、驱动/GPIB
分层诊断、数据来源强制标识、实时内存监控和长时间采集性能优化。

## 已实现

- A / B 默认双通道，C 为可随时启用的第三仪器通道
- A / B / C 可分别选择 10 个厂家、14 款型号、数字孪生或真实 VISA
- 每个真机通道启动前自动自检 VISA、GPIB 控制器、总线、地址和型号身份
- 驱动、GPIB、地址、超时、占用和型号错误分别弹窗，不再统一显示“连接失败”
- 每通道提供独立“连接自检”按钮，错误弹窗可直接打开厂商官方下载页
- 型号目录包含 Keysight、Fluke、Keithley、Rohde & Schwarz、Rigol、Siglent、
  GW Instek、Hioki、Yokogawa 和 Picotest
- SCPI 型号可使用被 VISA 识别的 USB、LAN、串口或 GPIB 资源；3458A 与
  8508A 严格使用 GPIB
- 每台独立地址、测量功能、量程、NPLC、位数、Autozero 和采样间隔
- 每台可分别启动/停止，也可自由勾选 A+B、A+C、B+C 或 A+B+C 同步启动
- 中文 / English 即时切换，不重启、不丢失采集设置
- 自动记住语言、窗口尺寸、左右面板宽度和 C 通道启用状态
- 精密模式可选持续采集或固定点数（例如 20,000 点），到点后该仪表自动停止
- 同步启动只作用于勾选通道：先分别完成连接和配置，再统一释放采集线程
- 多通道实时读数、独立状态和真实日期时间 X 轴
- 顶栏每秒显示整台电脑 RAM 占用率和本软件工作集内存
- 所有指标卡明确显示来源通道；指标区固定显示通道、型号、功能、地址和单位
- V、Ω、A 等不同物理量自动分配独立 Y 轴，同单位通道自动共用 Y 轴
- A/B/C 悬停与固定 Mark 均显示准确通道、数值、单位和毫秒时间戳
- 框选时间范围放大，并按当前可见数据分别缩放每个物理量 Y 轴
- 可分别执行 X 轴放大/缩小，并选择全部或单独 V/Ω/A/Hz/s Y 轴精细缩放
- 缩放时间轴后从完整会话重新提取局部数据，短窗口恢复逐点显示
- 主监控区直接显示最小值和最大值
- FFT/ASD、统计分布、Allan 稳定性和漂移/温漂可同时显示全部启用通道
- A 固定为青色、B 固定为紫色、C 固定为绿色；也可切换为单通道查看
- 多通道 FFT/ASD 分别使用各自采样率计算，直方图使用共同分箱半透明叠加
- A、B、C 分别显示统计摘要、Allan 曲线、漂移拟合和温度系数
- 分析页持续显示所有启用仪表的实际 VISA 地址、样本数和单位
- 混合单位趋势同时显示；FFT/ASD/Allan 跟随所选通道分别分析，避免单位混用
- 单通道 CSV 和保留各自独立时间轴的 A+B/A+B+C CSV 导出
- 持久化轮转日志：关闭或崩溃后仍保留，单文件 5 MB，最多四代
- 精密模式每接收一个样本立即追加 CSV 并执行 `flush + fsync`
- GPIB/VISA 断联、蓝屏或进程崩溃后，已落盘数据保留为可直接打开的恢复文件
- 启动时检测未完成恢复文件，右侧可直接打开自动保存目录
- 一键导出 ZIP 诊断报告：HTML 摘要、JSON 状态、当前事件和历史错误日志
- 诊断报告不包含测量样本，避免无意复制大体积或敏感测试数据
- 深色中性简约界面，降低高饱和装饰，强化通道、状态和主要操作层级
- 防止多个线程误连同一个 VISA 资源
- 同一 GPIB 控制器上的多路 VISA 操作使用共享总线仲裁，避免线程争用
- 混合 NI/Keysight VISA 环境中 `viClear` 失败时，继续使用 `ID?` 验证真实通信
- VISA 扫描按型号过滤：3458A/8508A 只显示 GPIB；SCPI 型号显示 VISA
  可识别的 USB/LAN/串口/GPIB 仪表资源
- 多仪表扫描会清除过期选择并明确分配 A/B/C，事件区记录扫描结果和实际地址
- 趋势图以 10 FPS、最多每通道 20,000 显示点刷新；完整数据仍用于分析和落盘
- FFT/ASD/统计/Allan 仅在收到新数据时约每秒刷新，避免重复全量计算
- 时间戳使用紧凑 64 位存储，减少长时间多通道会话内存
- `ID?`、`REV?`、`OPT?`、`LINE?` 身份信息
- DCV、ACV、AC+DCV、二/四线电阻、DCI、ACI、AC+DCI、频率、周期
- 3.5–8.5 位、NPLC 0–1000、Autozero
- `TRIG SGL` 精密连续采集
- DSDC / DSAC 高速突发采集，使用 3458A TIMER 和 reading memory
- 内部温度 `TEMP?` 定期采集
- 十字光标、滚轮缩放、点击固定精确值标签
- 平均值、标准差、峰峰值、RMS、离散系数 ppm、线性漂移
- FFT、幅度谱和 ASD（单位 `unit/√Hz`）
- 直方图、MAD 异常值过滤、Overlapping Allan deviation
- CSV 自动识别 X/Y 数据列

## Windows 多仪表连接

### 3458A

需要：

1. 两台或三台 3458A。
2. 一个至三个可作为 System Controller 的 GPIB 接口。
3. 仪表可共用一条 GPIB 总线，也可分别使用独立 GPIB-USB 控制器（例如
   `GPIB0::21::INSTR`、`GPIB1::22::INSTR` 和 `GPIB2::23::INSTR`）。
4. Windows 10/11 x64。
5. 与控制器匹配的 64 位 VISA/GPIB 驱动。

同一 GPIB 总线上的仪表必须使用不同的 Primary Address。软件按当前实际设备设置
默认：

```text
3458A A = GPIB0::21::INSTR
3458A B = GPIB1::22::INSTR
3458A C = GPIB2::23::INSTR  （预留，默认关闭）
```

地址应在 3458A 前面板设置。实际地址不一定必须是 22/23，但绝对不能相同。

### SCPI 型号

在任一通道选择 SCPI 型号后，精密采集模式可使用 NI MAX、Keysight
Connection Expert 或厂家 VISA 能识别的 USB、LAN/LXI、串口或 GPIB 仪表资源。
程序先执行 `*IDN?` 并按所选型号核对身份，再使用该型号配置文件生成命令。典型
命令结构为：

```text
*IDN?
CONF:<function>
SENS:<function>:RANG:AUTO ON       （自动量程时）
SENS:<function>:NPLC <value>       （支持 NPLC 的功能）
SENS:<function>:ZERO:AUTO <mode>   （支持 Autozero 的功能）
TRIG:SOUR IMM
SAMP:COUN 1
READ?
```

不同厂家在 `CONF`/`SENS:FUNC`、NPLC 和 Autozero 语法上的差异由配置文件处理，
不会把同一串命令盲目发送给所有仪表。具体型号、功能和首次实机验收边界见
`SUPPORTED_INSTRUMENTS.md`。SCPI 型号的厂家专用高速 digitize 暂不开放，避免
在未完成实机验证前把 3458A 的突发实现错误套用到其他仪表。

### Fluke 8508A

8508A 仅接受 GPIB VISA 资源，并使用独立 IEEE‑488 驱动。程序不会向它发送
`CONF`、`SENS` 或 `READ?`，而是按官方手册使用 `DCV`、`ACV`、`OHMS`、
`DCI`、`ACI`、`TRG_SRCE EXT` 和 `X?`。8508A 不直接接受 NPLC；界面中的
NPLC 值会映射到最接近的官方 `RESL/FAST` 积分组合，Autozero 控件自动禁用。

### NI GPIB-USB-HS

1. 安装 NI-488.2 和 64 位 NI-VISA，然后重启。
2. 在 NI MAX 中展开 `Devices and Interfaces > GPIB0 (GPIB-USB-HS)`。
3. 点击 `Scan for Instruments`，确认能看到每台真实仪表的 GPIB 资源。
4. 对每个地址发送 `ID?`，不要发送 `*IDN?`。
5. 关闭 NI MAX 的通信窗口，再打开本软件并点击“扫描”。

软件启动真机通道时会优先尝试 VISA Device Clear；如果当前 VISA 组合对
`viClear` 返回 `VI_ERROR_NLISTENERS`，程序不会仅凭这一项判定仪表离线，而会继续
发送 3458A 原生命令 `ID?`。只有正常命令也无法得到应答时才报告连接失败。

### Keysight USB-GPIB

使用 82357B/82357C 时，在 Keysight Connection Expert 中确认 GPIB 接口和仪表
资源。扫描结果只有 `USB0::...::INSTR` 时，不要将它当作 3458A；软件中需要的
地址仍然是 `GPIB0::<地址>::INSTR`。

## 独立与同步启动

- 在 `3458A A / B / C` 页签点击该仪表的按钮：只控制这一台。
- 在“同步启动组合”中勾选目标通道，可选择 A+B、A+C、B+C 或 A+B+C；
  按钮会实时显示本次实际启动组合。
- 只勾选一个通道时，按钮退化为普通单通道启动；未勾选且正在采集的通道不会
  被启动、停止或清空。
- 精密连续模式中可将“采集长度”设为“固定点数，完成后自动停止”，并分别为
  A、B、C 输入目标样本数；实时读数区显示已采集点数/目标点数。
- 同步启动时，各通道按自己的目标计数独立结束；一台先完成不会终止其他仪表。
- 某台已运行时，仍可切到另一台页签单独启动；开始时间可以不同。
- 所有勾选通道均停止时点击同步启动：所选仪表完成连接和配置后再放行采集。
- 同步启动是电脑端的软件级近同时启动，受 Windows 调度和 GPIB 串行传输影响，
  不等于微秒级同时采样。严格相位同步需要外部触发或专门的硬件触发方案。
- 各通道有独立 VISA 会话和采集状态，但共用一个 GPIB 控制器时，实际总线传输
  会由软件依次执行；这是 GPIB 的正常工作方式。

## 直接运行

推荐 Python 3.11 x64：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
python run.py
```

只看界面时，各通道保持“演示模式”，不需要 VISA 驱动。

## Windows 一次安装，以后直接启动

第一次解压新版后，只运行一次：

```text
INSTALL_ONCE_WINDOWS.bat
```

它会自动安装本项目依赖、执行完整测试、生成单文件程序，并创建：

```text
桌面快捷方式：Precision Multi-Instrument Lab Studio
开始菜单快捷方式：Precision Multi-Instrument Lab Studio
程序：%LOCALAPPDATA%\Programs\Precision Multi-Instrument Lab Studio\
      Precision-Multi-Instrument-Lab-Studio.exe
```

以后直接使用桌面图标、开始菜单或 EXE，不再运行 BAT，也不会重复安装或构建。
安装后的快捷方式不依赖 ZIP 解压目录，升级完成后可以移动或删除解压文件夹。
为了兼容旧习惯，`START_HERE_WINDOWS.bat` 发现 EXE 已存在时也只会直接启动。

安装过程会自动保留完整日志：

```text
%LOCALAPPDATA%\Precision Multi-Instrument Lab Studio\install_logs
```

如果 EXE 生成前发生依赖、测试或打包错误，将最新的 `install_*.log` 与截图一起
发送即可定位，不需要重新运行软件内的诊断功能。

EXE 包含 Python 和 UI 依赖；真实 GPIB 通信仍要求电脑已安装 NI-VISA/NI-488.2
或 Keysight IO Libraries。驱动只需安装一次。官方链接与故障分类见
`DRIVER_INSTALL_GUIDE.md`。

## 错误留痕与诊断报告

软件启动后会将以下信息持续写入本机应用数据目录中的轮转日志：

- 启动、退出、语言切换和用户操作事件
- 每台仪表的型号、实际 VISA 地址、连接身份和采集配置
- VISA `clear` 警告、连接/配置/采集错误
- 采集线程完整异常堆栈
- CSV 导入导出错误及未捕获的软件异常

每个日志文件最大 5 MB，并保留三个备份，加当前文件最多四代，防止长期采集无限
占用磁盘。发生问题后，即使已经重启软件，也可在右侧“事件”区域点击
“导出诊断报告”。生成的 ZIP 包含：

```text
diagnostic.html        可直接打开的摘要
diagnostic.json        结构化系统、软件和通道状态
events.txt             当前窗口事件
logs/application.log*  当前及历史轮转日志
README.txt             报告内容说明
```

报告会记录 A/B/C 的启用状态、同步组合、仪表地址、功能、量程、NPLC、点数、
最后连接诊断、系统 RAM 和应用内存，但不会打包 CSV、Excel 或内存中的测量样本。

## 3458A 专用采集策略

### 精密连续模式

每个通道独立执行：

```text
PRESET NORM
END ALWAYS
OFORMAT ASCII
DCV <range>
NPLC <value>
NDIG <3..8>
AZERO <ON|OFF|ONCE>
TRIG SGL
```

如果采样间隔小于 `NPLC / line_frequency`，实际速率由仪表积分时间限制。

### 高速突发模式

软件使用 `APER`、`NRDGS ... TIMER`、`TIMER`、`MEM FIFO` 和 `RMEM`，先在
3458A 内定时采样，再整批传回电脑。GUI 限制为最多 148,000 点、间隔不低于
10 µs、孔径不低于 500 ns。

第一次接真机建议先用：

- 1,000 点
- 1 ms 间隔
- 100 µs APER
- 10 V 量程

高速模式需要在具体 3458A、GPIB 控制器和固件组合上做首次实机验证。

## CSV 格式

单通道：

```text
timestamp_iso,elapsed_s,reading (V),internal_temperature_c
```

多通道导出不会假设各通道严格对齐，而是分别保留各自的时间轴：

```text
timestamp_A,elapsed_A_s,reading_A (...),temperature_A_c,
timestamp_B,elapsed_B_s,reading_B (...),temperature_B_c
timestamp_C,elapsed_C_s,reading_C (...),temperature_C_c
```

导入会自动识别常见时间和读数列。如果只有一个数值列，使用样本序号作为 X 轴。

## 测试

```powershell
pip install -e .[dev]
ruff check src tests
pytest
```

## 项目结构

```text
src/hp3458a_studio/
  drivers.py          3458A VISA 驱动与数字孪生
  channel_groups.py   A/B/C 任意启动组合解析
  i18n.py             中文 / English 翻译与测量功能名称
  instrument_panel.py A/B/C 独立仪表配置面板
  workers.py          后台采集线程与同步启动门控
  analysis.py         FFT、ASD、Allan、统计和漂移
  csv_io.py           单/多通道 CSV 导入导出
  diagnostics.py      持久化轮转日志和 ZIP 诊断报告
  widgets.py          交互式多通道图表
  main_window.py      多通道主界面和会话控制
```
