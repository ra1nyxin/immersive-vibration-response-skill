# ESP32-S3 GALAKU 固件

这个目录包含本项目实际使用的 ESP32-S3 固件源码。

固件作用：

1. ESP32-S3 通过 BLE 扫描并连接目标设备 `GK36`。
2. 发现 GALAKU/GK36 写入特征。
3. 通过 USB Serial/JTAG 接收电脑端命令。
4. 把 `SET`、`HIT`、`STOP` 等命令转换为 BLE 控制包。

## 目录结构

```text
firmware/
  CMakeLists.txt
  partitions.csv
  sdkconfig.defaults
  main/
    CMakeLists.txt
    main.c
```

## 环境要求

- ESP-IDF 5.5 或相近版本
- 带 USB Serial/JTAG 的 ESP32-S3 开发板，默认配置要求 16 MB Flash
- USB Serial/JTAG 可用
- 目标 BLE 设备名称为 `GK36`

## 构建与烧录

`firmware/` 本身就是 ESP-IDF 项目根目录。进入固件目录：

```bash
cd firmware
```

设置目标：

```powershell
idf.py set-target esp32s3
```

构建：

```powershell
idf.py build
```

烧录并打开监视器：

```powershell
idf.py -p COM3 flash monitor
```

如果你的开发板不是 `COM3`，把命令里的端口改成自己的实际串口。

## 串口命令

烧录后，固件会通过 USB Serial/JTAG 接收纯文本命令，每条命令以换行结尾：

```text
PING
STATUS
SCAN
SERVICES
SET <0-100>
HIT <damage>
STOP
```

返回示例：

```text
PONG
STATUS ble=1 host_synced=1 scanning=0 connecting=0 connected=1 service_ready=1 target=GK36 level=20 handle=10
OK SET 20
OK HIT damage=3.00 level=30
OK STOP
ERR unknown command: ...
```

## 与 Python 通信桥配合

固件烧录完成后，在仓库根目录启动跨平台 Python 通信桥：

```bash
python3 .agents/skills/immersive-vibration-response/scripts/esp32_bridge.py \
  --serial-port /dev/ttyACM0
```

Windows 示例：

```powershell
python .agents/skills/immersive-vibration-response/scripts/esp32_bridge.py --serial-port COM3
```

macOS 示例：

```bash
python3 .agents/skills/immersive-vibration-response/scripts/esp32_bridge.py \
  --serial-port /dev/cu.usbmodem1101
```

macOS 上优先使用 `/dev/cu.usbmodem*` 或 `/dev/cu.usbserial*` 这类 callout 串口。完整的 macOS 构建、烧录和排查步骤见仓库根目录 README。

## 行为说明

- `SET <0-100>`：直接设置当前强度。
- `HIT <damage>`：事件式反馈。固件会把 damage 换算为强度增量，并维持一段时间后逐步衰减。
- `STOP`：立即归零并发送停止包。

当前固件中的默认行为：

- `HOLD_MS = 7000`：一次触发后约维持 7 秒。
- `DECAY_PER_TICK = 1`：超过维持时间后逐步下降。
- `DAMAGE_TO_PERCENT = 10`：`HIT` 的 damage 到强度增量换算倍率。

`HIT 0`、负数或小于 1 的值都会在当前固件中按至少 1 点伤害处理，因此仍会产生等级 10 的反馈。需要立即归零时使用 `STOP`，不要使用 `HIT 0`。

如果你要改反馈节奏，可以在 `main/main.c` 里调整这些常量。

## 注意

- 建议使用 `sdkconfig.defaults` 作为默认配置来源。
- 如果目标 BLE 名称不是 `GK36`，需要修改 `main/main.c` 里的 `TARGET_NAME`。
