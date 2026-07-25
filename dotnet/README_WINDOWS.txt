PrecisionLab .NET 10 v0.6.0-beta.1
==================================

ENGLISH
-------
Requirements:
1. Windows 10/11 x64 and .NET 10 Desktop Runtime.
2. For physical instruments, install one compatible VISA 7.4+ implementation
   (NI-VISA, Keysight IO Libraries, or another IVI VISA implementation).

Install:
1. Extract every file from the ZIP.
2. Right-click INSTALL_WINDOWS.ps1 and run with PowerShell, or start
   PrecisionLab.Desktop.Wpf.exe directly for portable use.
3. The desktop starts PrecisionLab.Service.exe when needed. Closing the desktop
   does not terminate a running acquisition.

Data:
  %LOCALAPPDATA%\PrecisionLab\precisionlab-sessions.db
Exports:
  %USERPROFILE%\Documents\PrecisionLab\Exports

Physical VISA/GPIB drivers have automated command-transcript coverage, but a
specific instrument is not considered hardware-verified until it passes the
real-device checklist in MIGRATION_STATUS.md.

简体中文
--------
要求：
1. Windows 10/11 x64 和 .NET 10 Desktop Runtime。
2. 使用真机时，安装一个兼容的 VISA 7.4+ 实现，例如 NI-VISA、
   Keysight IO Libraries 或其他 IVI VISA 实现。

安装：
1. 完整解压 ZIP。
2. 右键用 PowerShell 运行 INSTALL_WINDOWS.ps1；也可直接运行
   PrecisionLab.Desktop.Wpf.exe 作为便携版。
3. 桌面端会在需要时启动 PrecisionLab.Service.exe。关闭桌面不会终止
   正在运行的采集。

数据：
  %LOCALAPPDATA%\PrecisionLab\precisionlab-sessions.db
导出：
  %USERPROFILE%\Documents\PrecisionLab\Exports

真实 VISA/GPIB 驱动已覆盖自动命令 Transcript；但具体仪表只有完成
MIGRATION_STATUS.md 的真机清单后，才会标记为“实机验证完成”。
