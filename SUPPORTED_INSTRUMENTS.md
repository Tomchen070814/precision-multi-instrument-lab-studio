# v0.5.2 支持仪表与能力矩阵

v0.5.2 的 A/B/C 三个通道均可独立选择以下型号。型号选择不是显示标签：连接时会
读取仪表身份并核对型号，测量功能下拉框也会按型号能力约束。

| 厂家 | 型号 | 驱动类型 | v0.5.2 精密模式功能 |
|---|---|---|---|
| Keysight | 3458A | 原生 HP‑IB | DCV、ACV、AC+DCV、2W/4W Ω、DCI、ACI、AC+DCI、频率、周期；另有 DSDC/DSAC 突发 |
| Keysight | 34465A | Truevolt SCPI | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期 |
| Keysight | 34470A | SCPI | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期 |
| Fluke | 8588A | 专用 SCPI 配置 | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期；读取内部模拟板温度 |
| Fluke | 8508A | 原生 IEEE‑488 | DCV、ACV、2W/4W Ω、DCI、ACI |
| Fluke | 8846A | SCPI | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期 |
| Keithley | DMM7510 | SCPI | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期 |
| Rohde & Schwarz | HMC8012 | SCPI | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期 |
| Rigol | DM3068 | SCPI | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期 |
| Siglent | SDM3065X | SCPI | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期 |
| GW Instek | GDM‑9061 | SCPI | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期 |
| Hioki | DM7276 | SCPI | DCV；支持在定期采样时同时读取仪表温度 |
| Yokogawa | DM7560 | SCPI | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期 |
| Picotest | M3510A | SCPI | DCV、ACV、2W/4W Ω、DCI、ACI、频率、周期 |

## 支持层级

- 3458A 保留独立驱动、GPIB 总线仲裁、精密单次读取和仪表缓存突发采集。
- 8508A 使用独立 IEEE‑488 驱动和 `DCV/ACV/OHMS/DCI/ACI/X?` 命令，只
  接受 GPIB；NPLC 请求映射到官方 `RESL/FAST` 模式，Autozero 不会误发送。
- 8588A 使用自己的 SCPI 触发计数、错误队列和内部温度查询；不会发送该型号
  不支持的 `SAMP:COUN` 或 Autozero 命令。
- 其余型号通过各自配置文件定义身份关键字、功能选择、自动量程、NPLC、
  Autozero、错误队列和读取命令；不是把同一串命令盲目发送给所有设备。
- 自动测试覆盖 12 个 SCPI 配置文件以及 8508A 原生 IEEE‑488 驱动的身份
  校验、配置、能力限制和单次读取。
- 除当前实际连接的仪表外，新增型号仍应在目标实验室做首次实机验收。若某台仪表
  的固件或兼容模式拒绝命令，软件会停止该通道、保留已采集 CSV，并将完整命令
  错误写入诊断报告，不会用模拟数据顶替。

## 扩展下一款仪表

主界面、通道、趋势、统计、耐久保存和诊断均不依赖具体型号。增加下一款标准
SCPI 仪表时，通常只需增加：

1. 型号与厂家信息；
2. `*IDN?` 身份关键字；
3. 支持的测量功能；
4. 该型号的量程、NPLC、Autozero 与读取命令模板；
5. 对应的协议回归测试。

如果未来设备不是 SCPI，也只需新增一个实现统一采集接口的驱动，不需要重写 UI
或分析平台。

## 厂家资料依据

- [Keysight 3458A User's Guide](https://www.keysight.com/us/en/assets/9018-01343/user-manuals/9018-01343.pdf)
- [Keysight Truevolt 34465A/34470A Operating and Service Guide](https://www.keysight.com/us/en/assets/9018-03876/service-manuals/9018-03876.pdf)
- [Fluke 8588A/8558A Remote Programmer's Manual](https://media.fluke.com/e8f48daf-3ee8-406d-b67d-b3080178a447_original%20file.pdf)
- [Fluke 8508A User's Manual](https://media.fluke.com/23bc1914-2376-416e-8752-b10800c2afed_original%20file.pdf)
- [Fluke 8845A/8846A Programmer's Manual](https://media.fluke.com/8f58fba8-10bb-438b-a91b-b10800c2bbc4_original%20file.pdf)
- [Keithley DMM7510 Reference Manual](https://download.tek.com/manual/DMM7510-901-01C_Sept_2019_Ref.pdf)
- [Rohde & Schwarz HMC8012 SCPI Programmer's Manual](https://www.rohde-schwarz.com/cz/manual/rs-hmc8012-digital-multimeter-scpi-programmers-manual_78701-172742.html)
- [Rigol DM3068 User Guide](https://www.rigol.com/dam/global/downloads/brochures/en/user-manual/multimeters/DM3068_UserGuide_EN.pdf)
- [Siglent SDM Series Programming Guide](https://siglentna.com/resources/documents/digital-multimeter/)
- [GW Instek GDM‑906x Product and Manual Page](https://www.gwinstek.com/en-global/products/detail/GDM-906x)
- [Hioki DM7276 Product and Communication Manual Page](https://www.hioki.com/global/products/benchtop-dmm/dc-voltmeters/id_6550)
- [Yokogawa DM7560 Communication Interface Manual](https://cdn.tmi.yokogawa.com/1/6241/files/IMDM7560-17EN.pdf)
- [Picotest M3510A Service Manual](https://www.picotest.com/wp-content/uploads/2024/12/M3510A-Service-Manual-v1.05.pdf)
