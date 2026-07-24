# Precision Multi-Instrument Lab Studio v0.5.1

## 新增型号

- Keysight 34465A：Truevolt SCPI 身份校验、量程、NPLC、Autozero、触发与读取。
- Fluke 8588A：独立 SCPI 配置，使用 `TRIG:COUN`、`SYST:ERR:NEXT?` 和
  `SYST:TEMP?`，不发送不兼容的 `SAMP:COUN` 或 Autozero 命令。
- Fluke 8508A：新增原生 IEEE‑488 驱动，使用厂家命令
  `DCV/ACV/OHMS/DCI/ACI/TRG_SRCE EXT/X?`，严格限制为 GPIB。

## 能力约束

- 8508A 开放 DCV、ACV、2W/4W Ω、DCI 和 ACI；不虚假开放独立频率/周期。
- 8508A 不直接接受 NPLC；软件将 NPLC 请求映射到最接近的官方
  `RESL/FAST` 积分组合。
- 8508A 与 8588A 自动禁用 Autozero 控件，避免发送不存在的远程命令。
- 8588A NPLC 输入按官方范围限制为 0–600。
- VISA 扫描将 8508A 与 3458A 一样限制到 GPIB 资源；其他 SCPI 型号仍可
  使用 VISA 识别的 USB、LAN、串口或 GPIB。

## 验证

- 型号目录：10 个厂家、14 款仪表。
- SCPI 配置：12 个。
- 协议测试覆盖身份校验、功能配置、触发、读取、温度查询、错误命令拒绝和
  8508A 非 GPIB 拒绝。
- 新增型号仍需在对应真机和固件版本上执行首次实验室验收。
