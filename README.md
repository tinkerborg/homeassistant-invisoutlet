# InvisOutlet for Home Assistant

[![pipeline](https://github.com/tinkerborg/homeassistant-invisoutlet/actions/workflows/pipeline.yaml/badge.svg)](https://github.com/tinkerborg/homeassistant-invisoutlet/actions/workflows/pipeline.yaml)
[![codecov](https://codecov.io/gh/tinkerborg/homeassistant-invisoutlet/graph/badge.svg)](https://codecov.io/gh/tinkerborg/homeassistant-invisoutlet)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/tinkerborg/homeassistant-invisoutlet/blob/HEAD/LICENSE)

A native Home Assistant integration for [Intecular](https://intecular.com) InvisOutlet smart outlets and their InvisDeco / Aura faceplates.

It talks to the device directly over its local WebSocket API — no cloud, no broker, no polling. Everything is event-driven, so state shows up the instant it changes on the device.

If you've been running your InvisOutlet through Matter or MQTT and wondering where the rest of its features went, this is where they went.

## Why this instead of Matter or MQTT?

The InvisOutlet is a lot more than an outlet — there's a whole environmental sensor suite, a radar occupancy sensor, addressable Aura lighting, and firmware you can update. MQTT will happily hand you the sensors, but the lighting, configuration, and firmware side is where a native integration pulls ahead.

| Capability | This integration | Matter | MQTT |
| --- | --- | --- | --- |
| The two outlets | ✅ | ✅ | ✅ |
| Full sensor suite (temp, humidity, AQI, CO₂, VOC, pressure, lux, radar distance) | ✅ | ⚠️ partial | ✅ |
| Occupancy + motion | ✅ | occupancy only | ✅ |
| Proper device classes & unit conversion | ✅ | ⚠️ raw values | ⚠️ raw values |
| Nightlight (dimmable) | ✅ | ✅ | ✅ |
| Aura color array | ✅ | single static color / temp | single static color / temp |
| Aura effect designer (per-pixel, modes, speed) | ✅ | ❌ | ❌ |
| Device config & restart actions | ✅ | ❌ | ❌ |
| Firmware updates from inside HA | ✅ | ❌ | ❌ |
| No extra server required | ✅ | ❌ (Matter Server) | ❌ (broker) |

## Features

### Outlets & control

- Both outlets as switches, with real-time state (physical button presses show up instantly)
- Restart buttons for the outlet and the attached faceplate

### Environment (faceplate sensors)

- Temperature, humidity, air quality index, CO₂, VOC, atmospheric pressure, illuminance, radar distance
- Occupancy and motion binary sensors
- A device-health status sensor that tells you when a faceplate is offline or needs a restart
- Only the sensors your faceplate actually has are created — no phantom "unknown" entities

### Lighting

- The faceplate nightlight as a dimmable light
- The Aura color array as a full HS / color-temperature light

### Aura effects

- Build your own effects as devices — nine addressable pixels, plus mode (static, breathing, strobing, color cycle, rainbow, starry night), speed, and a random toggle
- Assign an effect to the physical Aura light from its effect dropdown; edits re-apply live
- While an effect is running, the light becomes on/off + brightness, and **brightness acts as a master ceiling** — turn it to 50% and the whole animation dims to 50% of itself
- Turn it off and back on and the effect just resumes; pick "None" and your previous color comes right back

### Device configuration

- Toggles for the outlet power indicator, capacitive control, magic-touch control, AQI color RGB, motion-away, and adaptive/occupancy nightlight features
- Sliders for indicator and adaptive-nightlight brightness
- Pick how the faceplate's firmware updates are delivered (its own Wi-Fi or via the outlet)

### Firmware

- Update entities for the outlet and the InvisDeco, with live progress, release notes, and one-click install — right from the device page

### Under the hood

- Local push over WebSocket — no polling, no cloud
- Zeroconf discovery — devices are found automatically and follow DHCP address changes
- Auto-reconnect that survives reboots and firmware updates
- One integration entry manages every outlet on your network; add or remove one without disturbing the others

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS (category: Integration).
2. Search for **InvisOutlet** and install it.
3. Restart Home Assistant.

### Manual

Copy `custom_components/invisoutlet` into your Home Assistant `config/custom_components/` directory and restart.

## Setup

Once installed, your outlets are discovered automatically over the network — you'll see them show up under **Settings → Devices & Services** ready to add. If you'd rather add one by hand, use **Add Integration → InvisOutlet** and enter its IP address.

Everything else — the sensors, lights, config, firmware entities — appears on the device page. Aura effects are added from the hub's **+ Add Aura Effect** button.

## Requirements

- Home Assistant
- An Intecular InvisOutlet on the same network as Home Assistant

## Issues & contributions

Bug reports and ideas are welcome over on the [issue tracker](https://github.com/tinkerborg/homeassistant-invisoutlet/issues).
