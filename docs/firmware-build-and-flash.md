# Firmware Build and Flash Guide

Huginn (transmitter) and Muninn (receiver) are built with Espressif ESP-IDF v5.1+
for the ESP32-S3 target.

Because the firmware embeds Wi-Fi credentials and the aggregator hostname at compile
time, builds are done locally and firmware is not published as CI artefacts.

---

## Before you build

Edit `firmware/config.h` with your values:

```c
#define WIFI_SSID           "YourNetworkSSID"
#define WIFI_PASSWORD       "YourNetworkPassword"

// DNS name that Muninn receivers will send UDP packets to.
// Options:
//   • A static DNS A record pointing at your Geri LoadBalancer IP
//   • An external-dns managed hostname (e.g. csi-aggregator.home.example.com)
//   • The raw IP address as a string (not recommended — use DNS instead)
#define AGGREGATOR_HOST     "csi-aggregator.home.example.com"

// Unique name for this board — visible in the dashboard and stored in the DB.
// Change for each Muninn you flash: "rx_ground", "rx_upstairs", etc.
#define RECEIVER_NAME       "rx_ground"
```

The transmitter (Huginn) does not use `AGGREGATOR_HOST` or `RECEIVER_NAME` — those
fields are ignored by `firmware/huginn/main/main.c`.

---

## Linux (ESP-IDF CLI)

### 1. Install ESP-IDF

```bash
# Prerequisites
sudo apt-get install -y git wget flex bison gperf python3 python3-pip \
  python3-venv cmake ninja-build ccache libffi-dev libssl-dev dfu-util \
  libusb-1.0-0

# Clone ESP-IDF v5.3 (or any v5.1+ release)
mkdir -p ~/esp && cd ~/esp
git clone -b v5.3 --depth 1 --recurse-submodules \
  https://github.com/espressif/esp-idf.git

# Run the installer (downloads toolchain, sets up virtualenv)
cd ~/esp/esp-idf
./install.sh esp32s3

# Activate the environment in each shell session
source ~/esp/esp-idf/export.sh
```

### 2. Build Huginn (transmitter)

```bash
cd firmware/huginn
idf.py set-target esp32s3
idf.py build
```

### 3. Build Muninn (receiver)

Edit `firmware/config.h` — set `RECEIVER_NAME` to the unique name for this board.

```bash
cd firmware/muninn
idf.py set-target esp32s3
idf.py build
```

### 4. Flash

Connect the ESP32-S3 via USB, then:

```bash
# Flash and open serial monitor (Ctrl+] to exit)
idf.py flash monitor

# Or flash without monitor
idf.py flash

# Specify port explicitly if auto-detection fails
idf.py -p /dev/ttyUSB0 flash monitor
```

On first boot, watch the monitor output to confirm:
- Wi-Fi connects
- DNS resolves `AGGREGATOR_HOST`
- Muninn shows "CSI capture enabled" and starts streaming

### 5. Produce a standalone flash binary (optional)

To produce a single `.bin` file that can be flashed without the IDF toolchain:

```bash
# From inside the firmware/huginn (or muninn) directory, after building:
python $IDF_PATH/components/esptool_py/esptool/esptool.py \
  --chip esp32s3 merge_bin \
  --output build/merged-flash.bin \
  @build/flash_args
```

Flash the merged binary on any machine with `esptool.py` installed:

```bash
pip install esptool
esptool.py --chip esp32s3 --port /dev/ttyUSB0 write_flash 0x0 build/merged-flash.bin
```

---

## Windows (Espressif IDE / IDF Tools)

### Option A — VS Code + ESP-IDF extension (recommended)

1. Install [VS Code](https://code.visualstudio.com/)
2. Install the **ESP-IDF** extension from the VS Code marketplace
3. Run **ESP-IDF: Configure ESP-IDF Extension** from the command palette
   - Choose **Express** setup
   - Select ESP-IDF version **v5.3** (or latest v5.x)
   - Target: **esp32s3**
4. Open the `firmware/huginn` or `firmware/muninn` folder in VS Code
5. Click the **Build** button (🔨) in the status bar
6. Click the **Flash** button (⚡) to flash

### Option B — IDF Installation Manager (standalone GUI)

1. Download `eim-gui-windows-x64.msi` from the [ESP-IDF releases page](https://github.com/espressif/idf-component-manager/releases)
2. Run the installer and select ESP-IDF **v5.3** + target **esp32s3**
3. Open the **ESP-IDF PowerShell** or **ESP-IDF CMD** shortcut installed by EIM
4. In that shell:

```powershell
cd path\to\grimnir\firmware\huginn   # or muninn
idf.py set-target esp32s3
idf.py build flash monitor
```

The serial port is typically `COM3`, `COM4`, etc. — check Device Manager if
`idf.py flash` cannot find the device, and pass `-p COM4` explicitly.

---

## PlatformIO

PlatformIO is **not recommended** for this project. While it can build ESP-IDF projects
(using `framework = espidf` in `platformio.ini`), there are practical downsides:

- PlatformIO packages ESP-IDF as a versioned platform dependency and lags behind upstream
  releases. The CSI capture APIs changed in ESP-IDF v5.x; an outdated bundled version
  can cause subtle breakage without a clear error.
- The ESP-IDF Arduino framework (PlatformIO's typical default) does **not** expose the
  `esp_wifi_set_csi_config` / `esp_wifi_set_csi_rx_cb` APIs that Muninn requires.
  You must explicitly specify `framework = espidf` — which means you are essentially
  using raw ESP-IDF anyway, without PlatformIO's main benefit (library management).
- The firmware has no external library dependencies, so PlatformIO's component registry
  adds nothing here.

The official **ESP-IDF VSCode extension** (Option A on Windows, or the Linux CLI) gives
the same build/flash/monitor IDE experience with no version-lag risk.

---

## Flashing multiple Muninn receivers

Each Muninn must have a unique `RECEIVER_NAME` in `firmware/config.h`.
The recommended workflow for multiple boards:

1. Edit `config.h` — set `RECEIVER_NAME = "rx_ground"`
2. Flash board 1
3. Edit `config.h` — set `RECEIVER_NAME = "rx_upstairs"`
4. Flash board 2
5. Repeat for additional boards

New receivers auto-register in the database on their first packet — no manual
DB setup is required.

---

## Verifying operation

With `idf.py monitor` running on a Muninn board, you should see:

```
I (1234) CSI_WIFI: Connected: SSID=YourNet ch=6
I (1456) CSI_UDP: Aggregator: csi-aggregator.home.example.com → 192.168.1.50:5005
I (1678) CSI_DATA: CSI capture enabled
I (1900) CSI_DATA: Streaming CSI → csi-aggregator.home.example.com:5005
```

On the dashboard (`http://<freki-host>:8000`), the receiver card for this board
should appear within a few seconds and show a live RSSI reading.
