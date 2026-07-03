# InvisOutlet for Home Assistant

[![codecov](https://codecov.io/gh/tinkerborg/homeassistant-invisoutlet/graph/badge.svg)](https://codecov.io/gh/tinkerborg/homeassistant-invisoutlet)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/tinkerborg/homeassistant-invisoutlet/blob/HEAD/LICENSE)

A native Home Assistant integration for [Intecular](https://intecular.com) InvisOutlet smart outlets and their InvisDeco / Aura faceplates.

It talks to the device directly over its local WebSocket API — no cloud, no broker, no polling. Everything is event-driven, so state shows up the instant it changes on the device.

If you've been running your InvisOutlet through Matter or MQTT and wondering where the rest of its features went, this is where they went.

## Requirements

- Home Assistant
- An Intecular InvisOutlet on the same network as Home Assistant

## Installation

### HACS (recommended)

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tinkerborg&repository=homeassistant-invisoutlet&category=integration)

Click the button above to add the repository directly, or add it manually:

1. Add this repository as a custom repository in HACS (category: Integration).
2. Search for **InvisOutlet** and install it.
3. Restart Home Assistant.

### Manual

Copy `custom_components/invisoutlet` into your Home Assistant `config/custom_components/` directory and restart.

## Setup

Once installed, your outlets are discovered automatically over the network — you'll see them show up under **Settings → Devices & Services** ready to add. If you'd rather add one by hand, use **Add Integration → InvisOutlet** and enter its IP address.

Everything else — the sensors, lights, config, firmware entities — appears on the device page. Aura effects are added from the hub's **+ Add Aura Effect** button.

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

Aura effects are **reusable lighting designs** you build once and share across your Aura lights. Each effect is its own virtual device — nine addressable pixels plus a mode (static, breathing, strobing, color cycle, rainbow, starry night), a speed, and a random toggle. The virtual device drives no hardware on its own; it's purely the design.

To use one, pick it from the **effect dropdown** on a physical Aura light — that resolves the design and pushes it to the light. Because the effect is a shared object, **any change you make to the virtual device is applied live to every physical light that has it selected.** Recolor a pixel or bump the speed, and all of them update at once.

- Add effects from the hub's **+ Add Aura Effect** button; each shows up in every Aura light's effect dropdown
- While an effect is running, the physical light collapses to on/off + brightness, and **brightness acts as a master ceiling** — turn it to 50% and the whole animation dims to 50% of itself
- Turn the light off and back on and the effect just resumes; pick **None** and the light's own base color comes right back

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

## Issues & contributions

Bug reports and ideas are welcome over on the [issue tracker](https://github.com/tinkerborg/homeassistant-invisoutlet/issues).
