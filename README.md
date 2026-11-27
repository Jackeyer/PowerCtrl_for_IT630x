# IT6300 电源控制台

用于控制 IT630x 系列直流电源的 Windows x64 上位机，支持独立通道输出控制、电流监控和过流保护。直接运行 [PowerControl.exe](dist/PowerControl.exe)。串口适配器需已安装驱动并在 Windows 中显示为 COM 端口。

## 连接与控制

1. 将每台电源接到独立的 COM 端口。请根据电源具体型号和接口标识选择电平匹配的适配器。设备端为 TTL UART 时使用匹配电平的 USB–TTL；设备端为 RS‑232 时使用 RS‑232 转接。
2. 点击「刷新串口」，按住 Ctrl 或 Shift 选择端口，再点「连接所选端口」。默认使用 9600 baud、8N1、LF、无硬件流控；按仪器配置修改。同一批端口使用当前参数，参数不同的设备可分批连接。应用连接后首先发送 `*IDN?`，并在标签页中显示型号和端口。
3. 在设备页操作 CH1～CH3。「读取」更新该通道的设定值、实测值和输出状态。「下发设定」将电压和限流值设给该通道，并回读设备实际采用的值。首次操作建议先读取现有设定。

## 电流监控

输入该通道的监控阈值（mA），点击「开始监控」。程序立即采样，随后每 400 ms 调度读取；同一台电源的多个通道共用串口，按顺序查询。串口超时或设备响应缓慢会影响采样时序。

实测电流严格大于阈值时，程序立即尝试关闭当前通道，并回读输出状态。确认关闭后，该通道显示触发电流并进入过流状态。处理后可点击「复位过流」，再按需手动开启输出或重新开始监控。其余通道继续监控。通道设为串联、并联或同步时，关断行为由仪器的组合配置决定。

通信失败会中止该设备的监控并提示输出状态未知。若看到「过流关断未确认」，请在仪器面板核实输出。断开设备或退出程序会停止上位机监控，应用不会在此时主动关断输出。需要持续保护时请同时设好电源端限流等保护。

## 目录与构建

| 路径 | 用途 |
| --- | --- |
| `dist/PowerControl.exe` | Windows x64 单文件程序 |
| `main.py` | 应用入口 |
| `power_supply/scpi.py` | 串口及 SCPI 协议 |
| `power_supply/worker.py` | 每台电源的后台通信及电流监控 |
| `power_supply/window.py` | PyQt 控制界面 |
| `tests/` | 双设备模拟测试 |
| `build.ps1` | Windows 打包脚本 |

在项目目录运行以下命令（Python 3.9～3.13 x64）。

```powershell
py -m pip install -r requirements.txt
py main.py
.\build.ps1
```

运行模拟测试。

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
py -m unittest discover -s tests -v
```

SCPI 指令以同目录的 IT6300A/B 中文通讯协议为准。串口默认值和结束符参考 [ITECH IT6300 编程手册](https://usa.itechate.com/uploadfiles/%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C/user%20manual/it6300/IT6300%20Programming%20Guide-EN.pdf)。
