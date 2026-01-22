# 🌱 Generic Plant – Home Assistant Integration

**Generic Plant** is a lightweight Home Assistant custom integration that treats a plant as a first-class device.

Each plant:
- Has **one moisture sensor**
- Has **one water pump**
- Knows when its data is **fresh or stale**
- Can **auto-water safely**
- Notifies you when something goes wrong

This integration is designed to remove the need for per-plant helpers, blueprints, and fragile automations.

---

## ✨ Key Features

- One **device per plant**
- Auto-watering with **cooldown protection**
- **Stale sensor detection** (even for sensors that repeat values, e.g. Ecowitt)
- Manual **“Water Now”** and **“Evaluate Now”** controls
- Optional **MQTT heartbeat** for accurate freshness tracking
- Clear **Problem / OK** status
- Optional notifications for:
  - Watering
  - Stale readings
  - Failed watering attempts

---

## 📦 Installation

### Option A – HACS (Recommended)

1. Open **HACS → Integrations**
2. Click **⋮ → Custom repositories**
3. Add this repository URL:  https://github.com/bodhi-pi/ha-generic-plant
4. Category: **Integration**
5. Install **Generic Plant**
6. Restart Home Assistant

---

### Option B – Manual Install

1. Copy this folder:  custom_components/generic_plant
2. Paste it into:  /config/custom_components/
3. Restart Home Assistant

---

## ⚙️ Setup

1. Go to **Settings → Devices & Services**
2. Click **Add Integration**
3. Search for **Generic Plant**
4. Select:
- Plant name
- Moisture sensor (percentage)
- Pump switch

That’s it — the plant device is created.

---

## 🧠 How It Works

The integration periodically evaluates whether the plant should be watered.

Watering only occurs if **all** of the following are true:

- Auto-watering is enabled
- Moisture reading is **fresh**
- Moisture is below the threshold
- Cooldown period has passed
- Pump confirms it turned on

If anything blocks watering, the plant enters a **Problem** state instead of silently failing.

---

## 🧩 Entities Created

### Sensors

| Entity | Description |
|------|-------------|
| **Moisture** | Proxy of the selected moisture sensor |
| **Last Seen** | When a fresh reading was last received |
| **Last Watered** | Timestamp of the last successful watering |
| **Status** | OK / Problem based on freshness and errors |

---

### Numbers (Controls)

| Control | Description |
|-------|-------------|
| **Moisture Threshold (%)** | Below this, watering is allowed |
| **Pump Duration (s)** | How long the pump runs |
| **Cooldown (min)** | Minimum time between waterings |
| **Stale After (min)** | Max age of a reading before blocking watering |

---

### Switches

| Switch | Description |
|-------|-------------|
| **Auto Water** | Enable / disable automatic watering |

---

### Buttons

| Button | Description |
|-------|-------------|
| **Water Now** | Immediately run the pump |
| **Evaluate Now** | Run the full evaluation cycle instantly |

---

## 🔔 Notifications (Optional)

You can enable notifications for:

- ✅ Successful watering
- ⚠️ Watering blocked due to stale data
- ❌ Failed watering (pump didn’t turn on)

All notifications are **throttled** to avoid spam.

---

## 📡 MQTT Heartbeat (Optional)

Some sensors (e.g. Ecowitt) publish updates even when the value does not change.

To track freshness accurately:

1. Open the **integration options**
2. Set an **MQTT heartbeat topic**
3. Any message on that topic updates *Last Seen*

This is optional — non-MQTT sensors work without it.

---

## 🧪 Tested With

- Ecowitt soil sensors (via ecowitt2mqtt)
- MQTT switches
- GPIO-controlled pumps
- Template / helper switches (for testing)

---

## 🚧 Alpha Status

This integration is currently **alpha**.

Things may change:
- Entity names
- UI labels
- Option defaults

Please report issues and ideas on GitHub.

---

## 📄 License

MIT License  
© 2026 bodhi-pi