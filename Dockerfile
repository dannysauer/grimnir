# CSI Human Localization

Wi-Fi Channel State Information (CSI) based human presence detection and
room-level localization. ESP32-S3 devices capture CSI, stream it over UDP to
a containerized aggregator, which writes to PostgreSQL/TimescaleDB. A FastAPI
backend serves a live web dashboard with labeling tools for building training data.

## Architecture

```
ESP32-S3 (tx)  ─┐
ESP32-S3 (rx)  ─┤  UDP :5005   ┌─────────────┐    ┌──────────────────┐
ESP32-S3 (rx)  ─┘──────────────▶  aggregator  │───▶│  PostgreSQL +    │
                                └─────────────┘    │  TimescaleDB     │
                                                    └────────┬─────────┘
                                ┌─────────────┐             │
                       HTTP ────▶   backend   │─────────────┘
                     Browser    │  (FastAPI)  │
                                └─────────────┘
```

## Directory Structure

```
csi-project/
├── firmware/
│   ├── config.h              # Shared config — edit before flashing
│   ├── transmitter/          # Flash to ESP32-S3 #1
│   └── receiver/             # Flash to ESP32-S3 #2 and #3
├── aggregator/               # UDP → Postgres writer
├── backend/                  # FastAPI REST + SSE
├── frontend/                 # Single-file web dashboard
├── db/                       # SQL schema
├── compose/                  # Docker Compose (standalone)
├── helm/csi/                 # Helm chart (k8s)
└── ansible/                  # Ansible deployment playbook
```

## Quick Start

### 1. Database

Install TimescaleDB on your Postgres server, then:

```bash
psql -U postgres -c "CREATE DATABASE csi; CREATE USER csi_user WITH PASSWORD 'changeme'; GRANT ALL ON DATABASE csi TO csi_user;"
psql -U postgres -d csi -f db/001_schema.sql
```

### 2. Firmware

Install ESP-IDF v5.1+: https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/

Edit `firmware/config.h`:
- Set `WIFI_SSID` and `WIFI_PASSWORD`
- Set `AGGREGATOR_HOST` to the DNS name you'll assign to the aggregator container
- Set `CSI_WIFI_CHANNEL` to a quiet channel on your network

Flash the transmitter (ESP32-S3 #1):
```bash
cd firmware/transmitter
idf.py set-target esp32s3
idf.py build flash monitor
```

Flash each receiver (edit `RECEIVER_NAME` in config.h per device):
```bash
cd firmware/receiver
# Edit ../../config.h: set RECEIVER_NAME="rx_ground"
idf.py set-target esp32s3
idf.py build flash monitor
# Repeat with RECEIVER_NAME="rx_upstairs" for the second receiver
```

### 3. Set DNS

In your router / Pi-hole / AdGuard, create an A record:
```
csi-aggregator.home.arpa  →  <aggregator container IP>
```

### 4a. Deploy with Docker Compose (standalone)

```bash
cd compose
cp .env.example .env
# Edit .env: set DATABASE_URL

docker compose up -d
```

Dashboard at http://localhost:8000

### 4b. Deploy to Kubernetes with Ansible

```bash
pip install ansible kubernetes
ansible-galaxy collection install kubernetes.core community.docker

ansible-playbook ansible/deploy.yaml \
  -e db_url="postgresql://csi_user:changeme@your-nas:5432/csi" \
  -e registry="your-registry.example.com" \
  -e aggregator_lb_ip="192.168.1.50"
```

Or directly with Helm:
```bash
helm install csi ./helm/csi \
  --namespace csi --create-namespace \
  --set database.url="postgresql://..." \
  --set image.aggregator.repository="your-registry/csi-aggregator"
```

## Collecting Training Data

1. Open the dashboard in your browser
2. Move to a room and stay there for 5–15 minutes
3. Use the "Training Labels" panel to tag that time window with a room name
4. Repeat for each room and for "empty" (no one home)
5. Aim for 20–30 labeled windows per class before training

## Expanding to 6 Devices

The schema and code support up to 6 receivers out of the box. When you add
new ESP32s, flash the receiver firmware with a new `RECEIVER_NAME` value.
New receivers self-register in the database on first packet received.

## Packet Format

The ESP32 firmware sends little-endian binary UDP packets. See
`aggregator/src/csi_aggregator/parser.py` for the full format spec
and `firmware/receiver/main/main.c` for the serialization code.

## Notes

- CSI amplitude is more reliable than phase for beginners; phase requires
  hardware-specific calibration to remove timing offset noise.
- The `csi_variance_1min` continuous aggregate pre-computes per-minute
  variance summaries for efficient dashboard queries.
- Compression kicks in after 7 days, reducing storage by ~90%.
- The P100/M4 GPU machines are not part of this stack — they connect
  directly to Postgres to pull labeled training data.
