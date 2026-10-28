# Integrating the Eurotronic Comet WiFi into Home Assistant

**English** · [Deutsch](README.md)

Unofficial community guide for running the **Eurotronic Comet WiFi** radiator
thermostat (Wi-Fi/MQTT) fully locally in Home Assistant — no cloud, no vendor
app in everyday use. Not affiliated with Eurotronic.

At the end you have:

- a climate entity with target temperature, current temperature and mode,
- a battery sensor,
- a temperature sensor that Alexa can answer by voice,
- and no cloud dependency inside your own network.

> **Status:** 2026-10-28, tested with Home Assistant 2026.10.2 and the
> Mosquitto add-on 7.1.2. The values in the examples (`0012AB34`,
> `AABBCC112233`) are fictional placeholders — replace them with your own.

---

## 0. Quick start

1. Set the device up **in the Eurotronic app first** (with internet access).
2. Note the account number and the MAC address.
3. Read the device's MQTT password once ([§4](#4-obtain-the-mqtt-password)).
4. Add that login to the Mosquitto broker ([§5](#5-add-the-broker-login)).
5. **Redirect all ten** `mqtt*.eurotronic.*` names to your broker via DNS
   ([§6](#6-redirect-dns--the-decisive-step)).
6. Restart the thermostat and check the connection in the broker log
   ([§7](#7-verify-the-connection)).
7. Create the climate entity, the sensors and two automations
   ([§8](#8-climate-entity-in-home-assistant), [§9](#9-sensors),
   [§10](#10-automations)).

The whole trick is step 5. Without the complete DNS redirect everything else
works, but the thermostat disappears into the cloud for hours at a time.

---

## 1. How the device works

The Comet WiFi is not a local device. On wake-up it opens an **MQTT connection
to `mqtt.eurotronic.io`** (port 1883, unencrypted, MQTT 3.1.1), reports its
state there and accepts commands. The app talks to the same broker.

Hence the idea: if the thermostat resolves `mqtt.eurotronic.io` and finds
**your** broker instead of the cloud, it talks to Home Assistant locally —
without changing anything on the device.

```
thermostat ──DNS──▶ mqtt3.eurotronic.io  ──redirected──▶  192.168.x.x (Mosquitto)
     │                                                          │
     └──────────────── MQTT 1883, plaintext ───────────────────▶┘
```

**Things you need to understand:**

| Property | Consequence |
|---|---|
| Battery powered, keepalive 600 s | The thermostat sleeps and does not report continuously. |
| Commands are **applied immediately** | Once connected, it reacts within seconds. |
| It does **not** report the new value by itself | Without a read request HA keeps showing the old value → [§10](#10-automations). |
| MQTT 3.1.1, port 1883, **no TLS** | Credentials travel in plaintext in the first packet ([§4](#4-obtain-the-mqtt-password)). |
| 2.4 GHz only (DA16200 chip) | No 5 GHz Wi-Fi, no guest network with client isolation. |

There is **no official** Home Assistant integration. The "Eurotronic Comet
Blue" integration only covers the Bluetooth variant.

---

## 2. Requirements

- **Home Assistant** with a **Mosquitto broker** (add-on `core_mosquitto` or your
  own broker), reachable from the thermostat's Wi-Fi, port **1883**.
- A **DNS server you control**: AdGuard Home, Pi-hole, dnsmasq,
  OPNsense/pfSense, Unbound …
  A FRITZ!Box on its own cannot map arbitrary host names to an internal IP —
  in that case you need a DNS filter in front of it (e.g. AdGuard Home).
- The thermostat on the **same network** as the broker (no VLAN in between, no
  client isolation).
- Access to the **Eurotronic app** (account) and the device's **MAC address**.
- A machine where you can run **Python 3** if needed.

---

## 3. Collect the values you need

| Value | Where to get it | Example |
|---|---|---|
| **Account number** | Number of your Eurotronic account, 8 hex characters | `0012AB34` |
| **MAC address** | Router/device list, label, app | `AA:BB:CC:11:22:33` |
| **Broker IP** | your Home Assistant | `192.168.1.10` |

The **MAC without colons, in upper case** becomes the topic segment:

```
AA:BB:CC:11:22:33   →   AABBCC112233
```

All topics therefore have the form:

```
02/<ACCOUNT>/<MAC>/S/...   ← commands to the thermostat
02/<ACCOUNT>/<MAC>/V/...   ← replies from the thermostat
```

> The leading `02` is part of the protocol and stays unchanged.

---

## 4. Obtain the MQTT password

The thermostat logs in to the broker with **username = account number** and a
password the app handed to it during setup. That password is not shown anywhere
in the app.

Because MQTT runs **unencrypted** here, both are in plaintext inside the
`CONNECT` packet — the first packet of every connection. You read it once, put
it into the broker, and never need it again.

### Variant A: small listener (recommended)

The script listens on port 1883 and reads the first packet. It exits by itself
after the first hit.

> **Beforehand:** stop Mosquitto briefly so port 1883 is free, and make the DNS
> redirect from [§6](#6-redirect-dns--the-decisive-step) point at this machine.
> Start the broker again afterwards.

> The full script lives in the repo: [`tools/comet_creds.py`](tools/comet_creds.py)

Run it:

```bash
python tools/comet_creds.py
```

Then wake the thermostat (press a button or turn the dial). Output:

```
Connection from 192.168.1.50
  Client ID : da16x020012AB34112233
  Username  : 0012AB34
  Password  : ********
```

The client ID is composed of `da16x02` + account number + the last three MAC
bytes — a good indication that you caught the right device.

### Variant B: packet capture

If you already have a shell on the broker machine, a capture while the
thermostat tries (and fails) to log in is enough:

```bash
sudo tcpdump -A -s0 -i any 'tcp port 1883'
```

The plaintext of the `CONNECT` packet contains username and password.

> Only use this on your own device. The password belongs in the broker — not in
> a repository and not in a guide.

### Variant C: Android app (no Python, no DNS redirect)

If you have neither Python nor a machine with a free port 1883 at hand, you can
also capture on the phone that runs the Eurotronic app:

1. Install **NetworkCapture** (or a comparable capture app) and allow its VPN
   capture.
2. Open the Eurotronic app and sign in.
3. In the capture, look for the connection on port **1883** and open the
   `CONNECT` packet — username and password are in plaintext.

**Limitation:** you are looking at the *app's* session, not the thermostat's.
The username is usually the same account number, but the password may differ.
If the broker login fails afterwards, use variant A — it reads the real device
`CONNECT`. Also note that a capture app is a third-party tool with far-reaching
permissions: install it temporarily and remove it afterwards.

---

## 5. Add the broker login

**Mosquitto add-on:** Settings → Add-ons → Mosquitto broker → Configuration →
add to `logins`:

```yaml
logins:
  - username: "0012AB34"
    password: "YOUR_PASSWORD"
```

Save, then **restart** the add-on.

- The username is the **account number**, not a name of your choosing.
- Special characters in the password are fine but must be quoted.
- The broker must listen on **1883 without TLS**. The thermostat cannot do TLS.
- If your broker runs in a container, port 1883 must be reachable from the LAN
  (no `127.0.0.1` binding).

> **Side note:** Some sources claim Comet WiFi thermostats cannot authenticate
> over MQTT. On the device used here that was demonstrably false — it logs in
> with account number and password. If your thermostat connects without a
> login, you can skip this step.

---

## 6. Redirect DNS — the decisive step

The thermostat tries **ten** host names: `mqtt` and `mqtt1`–`mqtt4` under two
domains:

```
mqtt.eurotronic.io      mqtt.eurotronic.com
mqtt1.eurotronic.io     mqtt1.eurotronic.com
mqtt2.eurotronic.io     mqtt2.eurotronic.com
mqtt3.eurotronic.io     mqtt3.eurotronic.com
mqtt4.eurotronic.io     mqtt4.eurotronic.com
```

**All ten** must point to your broker's IP. If even one is missing, the
thermostat will hit a cloud host on its next wake-up and stay unreachable
locally for hours. That is precisely the most common cause of "the thermostat
only shows up sporadically".

### AdGuard Home

Filters → **DNS rewrites** → *Add rewrite* — once per name from the list above
(ten entries). Example for the first and the last one:

| Domain | Answer |
|---|---|
| `mqtt.eurotronic.io` | `192.168.1.10` |
| `mqtt1.eurotronic.io` | `192.168.1.10` |
| … | … |
| `mqtt4.eurotronic.com` | `192.168.1.10` |

Then clear the DNS cache (AdGuard: *Filters → Clear DNS cache*).

### Pi-hole / dnsmasq

In `/etc/dnsmasq.d/eurotronic.conf`:

```conf
address=/mqtt.eurotronic.io/192.168.1.10
address=/mqtt1.eurotronic.io/192.168.1.10
address=/mqtt2.eurotronic.io/192.168.1.10
address=/mqtt3.eurotronic.io/192.168.1.10
address=/mqtt4.eurotronic.io/192.168.1.10
address=/mqtt.eurotronic.com/192.168.1.10
address=/mqtt1.eurotronic.com/192.168.1.10
address=/mqtt2.eurotronic.com/192.168.1.10
address=/mqtt3.eurotronic.com/192.168.1.10
address=/mqtt4.eurotronic.com/192.168.1.10
```

```bash
sudo systemctl restart dnsmasq     # or: pihole restartdns
```

### NextDNS (no DNS server of your own)

If your router cannot hold custom entries and you do not want to run an AdGuard
or Pi-hole box, the same ten rewrites work in the cloud: NextDNS →
**Settings → Rewrites**, one entry per `mqtt`/`mqtt1`–`mqtt4` under
`.eurotronic.io` and `.eurotronic.com`, all pointing at your broker IP.

Requirement: the thermostat must actually use NextDNS as its resolver — set it
as the upstream in your router or hand it out via DHCP. If the router itself
resolves via DoH/DoT, the rewrites may not apply; in that case only a local DNS
server will do.

### Why not a wildcard?

`*.eurotronic.io` would be shorter, but it also catches the app's HTTPS API.
The Eurotronic app then stops working properly at home. The ten explicit names
leave the rest of the cloud alone.

### Verify

```bash
nslookup mqtt3.eurotronic.io
```

It must return your broker IP — for **all ten** names, not just `mqtt`.

> **If your DNS only supports single names** (some routers): add all ten. One
> forgotten name is enough to cause the dropouts.

---

## 7. Verify the connection

1. Restart the thermostat: briefly remove the batteries or press the reset
   button.
2. Check the Mosquitto log (add-on → Log):

```
New client connected from 192.168.1.50 as da16x020012AB34112233 (p2, c1, k600)
```

- `k600` = keepalive 600 s, correct.
- `S/XX #COMM-TEST` should follow — the device's connection test.
- The client ID starts with `da16x02…`.

If nothing appears: check DNS
([§6](#6-redirect-dns--the-decisive-step)), the login
([§5](#5-add-the-broker-login)) and port 1883 — in that order.

---

## 8. Climate entity in Home Assistant

Home Assistant learns the entity via **MQTT Discovery**. You publish a
configuration to a discovery topic and HA builds the entity from it.

**Topic:**

```
homeassistant/climate/comet_<mac_lower>/config
```

**Payload** (replace the placeholders, publish it `retained`):

```json
{
  "name": "Comet WiFi <ROOM>",
  "unique_id": "comet_wifi_<mac_lower>",
  "device": {
    "identifiers": ["comet_wifi_<mac_lower>"],
    "name": "Comet WiFi <ROOM>",
    "manufacturer": "Eurotronic",
    "model": "Comet WiFi"
  },
  "modes": ["heat"],
  "mode_state_topic": "02/<ACCOUNT>/<MAC>/V/A0",
  "mode_state_template": "heat",
  "temperature_command_topic": "02/<ACCOUNT>/<MAC>/S/A0",
  "temperature_command_template": "{{ '#%02x' | format((value | float * 2) | int) }}",
  "temperature_state_topic": "02/<ACCOUNT>/<MAC>/V/A0",
  "temperature_state_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) / 2 }}",
  "current_temperature_topic": "02/<ACCOUNT>/<MAC>/V/A1",
  "current_temperature_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) / 2 }}",
  "temp_step": 0.5,
  "precision": 0.5,
  "min_temp": 8,
  "max_temp": 28,
  "retain": true
}
```

Concretely for the example device:

```json
{
  "name": "Comet WiFi Bathroom",
  "unique_id": "comet_wifi_aabbcc112233",
  "device": {
    "identifiers": ["comet_wifi_aabbcc112233"],
    "name": "Comet WiFi Bathroom",
    "manufacturer": "Eurotronic",
    "model": "Comet WiFi"
  },
  "modes": ["heat"],
  "mode_state_topic": "02/0012AB34/AABBCC112233/V/A0",
  "mode_state_template": "heat",
  "temperature_command_topic": "02/0012AB34/AABBCC112233/S/A0",
  "temperature_command_template": "{{ '#%02x' | format((value | float * 2) | int) }}",
  "temperature_state_topic": "02/0012AB34/AABBCC112233/V/A0",
  "temperature_state_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) / 2 }}",
  "current_temperature_topic": "02/0012AB34/AABBCC112233/V/A1",
  "current_temperature_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) / 2 }}",
  "temp_step": 0.5,
  "precision": 0.5,
  "min_temp": 8,
  "max_temp": 28,
  "retain": true
}
```

### Publishing

**Option 1 — Developer tools:**

Developer tools → Actions → `mqtt.publish`

```yaml
topic: homeassistant/climate/comet_aabbcc112233/config
payload: |
  {"name": ...}
retain: true
qos: 1
```

> **Important:** HA renders the payload as a Jinja template. The `{{ … }}` in
> the templates would be evaluated and destroyed. Wrap the JSON in
> `{% raw %}` … `{% endraw %}` — or use option 2.

**Option 2 — `mosquitto_pub`:**

```bash
mosquitto_pub -h 192.168.1.10 -p 1883 -u 0012AB34 -P 'YOUR_PASSWORD' \
  -t 'homeassistant/climate/comet_aabbcc112233/config' -r -f comet_climate.json
```

Afterwards, Settings → Devices & services → MQTT shows a device
"Comet WiFi …" with a climate entity.

### What the templates do

| Field | Meaning |
|---|---|
| `temperature_command_template` | `21.0` °C → `#2a` (value × 2 as hex) |
| `temperature_state_template` | `#2a` → `21.0` (hex ÷ 2) |
| `current_temperature_template` | same for `V/A1` |
| `split('#')[-1]` | The app prepends two counter bytes before the `#` — read from the **last** `#`. |

### Entity ID

HA assigns the ID automatically (from the name and possibly the device name).
If it is too long for you, rename it: Settings → Devices & services → Entities
→ open the entity → gear icon → *Entity ID*.

---

## 9. Sensors

The thermostat provides current temperature and battery on separate topics.
Both sensors are optional but useful (and the temperature sensor is the basis
for Alexa).

**Important:** all three entities (climate, temperature, battery) must use the
**same `identifiers`** in their `device` block, otherwise HA creates a second
device.

### 9.1 Current temperature

Topic: `homeassistant/sensor/comet_<mac_lower>_temperature/config`

```json
{
  "name": "Temperature",
  "unique_id": "comet_wifi_<mac_lower>_temperature",
  "device": {
    "identifiers": ["comet_wifi_<mac_lower>"]
  },
  "state_topic": "02/<ACCOUNT>/<MAC>/V/A1",
  "value_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) / 2 }}",
  "unit_of_measurement": "°C",
  "device_class": "temperature",
  "state_class": "measurement"
}
```

Example:

```json
{
  "name": "Temperature",
  "unique_id": "comet_wifi_aabbcc112233_temperature",
  "device": { "identifiers": ["comet_wifi_aabbcc112233"] },
  "state_topic": "02/0012AB34/AABBCC112233/V/A1",
  "value_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) / 2 }}",
  "unit_of_measurement": "°C",
  "device_class": "temperature",
  "state_class": "measurement"
}
```

### 9.2 Battery

Topic: `homeassistant/sensor/comet_<mac_lower>_battery/config`

```json
{
  "name": "Battery",
  "unique_id": "comet_wifi_<mac_lower>_battery",
  "device": {
    "identifiers": ["comet_wifi_<mac_lower>"]
  },
  "state_topic": "02/<ACCOUNT>/<MAC>/V/A6",
  "value_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) }}",
  "unit_of_measurement": "%",
  "device_class": "battery",
  "state_class": "measurement"
}
```

The value arrives as a two-digit hex number: `#55` = 0x55 = **85 %**.

Without a request the sensor stays empty — the automations in
[§10](#10-automations) take care of that.

---

## 10. Automations

Two rules close the loop (a third is optional, see
[§10.4](#104-optional-answer-the-connection-test-not-tested)). Without them
setting a value still works, but HA shows the new value hours later (or never).

### 10.1 Acknowledge the setpoint

The thermostat applies the target temperature immediately but does not report
it back. HA publishes to `S/A0` — the same message triggers this rule, which
asks for current and target temperature one second later.

```yaml
- id: comet_sollwert_quittieren
  alias: "Comet: acknowledge setpoint"
  description: "Asks for current and target temperature after every setpoint command."
  triggers:
    - trigger: mqtt
      topic: "02/<ACCOUNT>/<MAC>/S/A0"
  conditions: []
  actions:
    - delay: "00:00:01"
    - action: mqtt.publish
      data:
        topic: "02/<ACCOUNT>/<MAC>/S/AF"
        payload: "#0b"
        qos: 1
        retain: false
  mode: queued
  max: 5
```

### 10.2 Poll the current value

```yaml
- id: comet_istwert_abfragen
  alias: "Comet: poll state"
  description: "Fetches current, target, battery and flags every 2 hours."
  triggers:
    - trigger: time_pattern
      hours: "/2"
  conditions: []
  actions:
    - action: mqtt.publish
      data:
        topic: "02/<ACCOUNT>/<MAC>/S/AF"
        payload: "#4B"
        qos: 1
        retain: false
  mode: single
```

- `#0b` requests temperatures only, `#4B` additionally battery and flags
  ([§11](#11-protocol-reference)).
- **Interval:** 2 hours is a good compromise. Shorter = more current, but more
  radio traffic and therefore more battery drain. 15 minutes is possible but
  noticeably more expensive.
- The trigger also fires on HA start (retained command). That is harmless.

> **HA version:** `triggers:`/`actions:` applies from HA 2024.10. In older
> versions the keys are `trigger:`/`action:` (singular) — the content stays the
> same.

### 10.3 Optional: report on connect

Publish `#0b` **retained** to `S/AF` once:

```yaml
topic: 02/<ACCOUNT>/<MAC>/S/AF
payload: "#0b"
retain: true
```

The thermostat then receives the request on **every** connection and reports
its state immediately — handy after a power loss or restart.

### 10.4 Optional: answer the connection test (not tested)

In some setups — especially with older firmware — the connection is considered
more stable if the broker acknowledges the thermostat's connection test. The
device sends `#COMM-TEST` on `S/XX`.

**In the setup tested here this was not necessary.** Only add the rule if you
still see dropouts despite complete DNS entries
([§6](#6-redirect-dns--the-decisive-step)).

```yaml
- id: comet_comm_test_beantworten
  alias: "Comet: answer connection test"
  description: "Acknowledges the thermostat's connection test (S/XX)."
  triggers:
    - trigger: mqtt
      topic: "02/<ACCOUNT>/<MAC>/S/XX"
  conditions: []
  actions:
    - delay: "00:01:00"
    - action: mqtt.publish
      data:
        topic: "02/<ACCOUNT>/<MAC>/S/XX"
        payload: "#COMM-TEST"
        qos: 1
        retain: false
  mode: single
```

- Trigger and target topic are **identical**. Without `mode: single` and the
  delay, the rule answers its own reply and loops — which costs battery.
- If the thermostat wakes up more often than before, remove the rule again.

---

## 11. Protocol reference

### Topics

| Topic | Direction | Meaning |
|---|---|---|
| `S/A0` | HA → device | Set target temperature, payload `#<hex>` (value × 2) |
| `S/AF` | HA → device | Read request, payload = bitmask |
| `V/A0` | device → HA | Target temperature, e.g. `#2A` = 21.0 °C |
| `V/A1` | device → HA | Current temperature, e.g. `#22` = 17.0 °C |
| `V/A3` | device → HA | Status/switch flags, e.g. `#2182` |
| `V/A6` | device → HA | Battery, e.g. `#55` = 85 % |

### `S/AF` is a bitmask

Not a fixed command but a selection of which values the device sends back:

| Payload | Fetches |
|---|---|
| `#0b` | target temperature + current temperature |
| `#48000000` | battery + flags |
| `#4B` | both together |
| `#FFFFFFFF` | everything |

`#4B` is shorthand for `#0B000000` + `#48000000`.

### Value format

- Always `#` + hex, °C = hex ÷ 2.
- The device replies in **upper case** (`#2A`), the app sends **lower case**
  (`#2a`). Both are valid.
- The app prepends two counter bytes before the `#` — so always parse from the
  **last** `#`.

### Connection behaviour

| Value | Meaning |
|---|---|
| Client ID `da16x02…` | Device (DA16200 chip) |
| Keepalive 600 s | Session stays open for a long time |
| `S/XX #COMM-TEST` | Connection test right after connecting |

---

## 12. Alexa (optional)

For Alexa to answer "what is the temperature in the bathroom", it needs a
**temperature sensor** as a separate device — the climate entity's attribute is
not enough.

The most reliable path is the **Matter Hub**:

1. Install the **Home-Assistant-Matter-Hub** add-on.
2. Create a bridge and pair it with Alexa (Alexa → Devices → + → Matter).
3. In the bridge, add the sensor under **Filter → Include**:
   `sensor.comet_wifi_<mac_lower>_temperature`
4. **Restart the bridge** — only then does the new endpoint appear.
5. In the Alexa app, run **"Discover devices"**.
6. Assign the sensor to the **room group** "Bathroom".

Only with the room assignment does Alexa understand "in the bathroom". Without
a room it only answers to the device name.

HA's own **Alexa integration** (cloud skill) does show sensors in the app but
is unreliable for voice queries of this kind.

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Thermostat only visible every few hours | One `mqtt*.eurotronic.*` name still points to the cloud | Check all **ten** names ([§6](#6-redirect-dns--the-decisive-step)) |
| Connection rejected immediately | Login missing or wrong | `logins` in the broker, restart ([§5](#5-add-the-broker-login)) |
| No connection, no log entry | Port 1883 unreachable / VLAN / client isolation / 5 GHz Wi-Fi | Check the network, use 2.4 GHz |
| Changing the setpoint works, HA shows it late | Acknowledge automation missing | [§10.1](#101-acknowledge-the-setpoint) |
| Current temperature never changes | No polling | [§10.2](#102-poll-the-current-value) |
| Entity shows 0 °C or `unknown` | Template parses incorrectly | Use `split('#')[-1][0:2]` |
| Two devices in HA | Different `identifiers` | Use identical ones in all payloads |
| Battery stays empty | `#0b` does not include it | Use `#4B` ([§11](#11-protocol-reference)) |
| Alexa cannot find the sensor | Bridge not restarted / filter not set | Filter + restart + "Discover devices" |
| `exceeded timeout` in the broker log | Thermostat is asleep or lost the connection | Harmless if it reports again soon — frequent timeouts point to the DNS gap |
| Thermostat connects but keeps dropping again | Firmware expects an answer to `S/XX #COMM-TEST` | [§10.4](#104-optional-answer-the-connection-test-not-tested) — check the ten DNS names first |

**Always start with:** the broker log. If it shows `New client connected … as
da16x02…`, the connection is fine and the problem is in HA. If the entry is
missing, it is DNS, login or network.

---

## 14. Limitations and side effects

- **No cloud anymore:** remote access via the Eurotronic app no longer works.
  At home the app talks to your broker.
- **Firmware updates** (if the vendor offers any) run through the cloud and are
  unreachable with this redirect. If you ever need one: remove the DNS entries
  briefly, restart the device, wait for the update, restore the entries.
- **Set up first, redirect afterwards.** Provisioning (Wi-Fi, credentials) runs
  through the cloud. After a factory reset, first undo the DNS redirect, set the
  device up in the app, then redirect again.
- **Battery:** every request costs energy. The 2-hour poll is a deliberate
  compromise; 15 minutes works but costs more.
- **No push on device-side changes:** whether the thermostat reports a target
  set manually on the dial by itself has not been conclusively verified. The
  acknowledge automation only covers commands from HA.
- **Only one broker:** the thermostat cannot talk to the cloud and locally at
  the same time.

---

## 15. Alternatives

- **`aiocometwifi`** (Python library) and community integrations built on it
  speak the same protocol and create the entities automatically. They require a
  broker that accepts anonymous connections — that path was not used here
  because the device logs in with an account.
- **`marcinkordas/comet_wifi_integration`** takes a different approach and was
  not used here.

The manual route above has the advantage that you control every entity and
every automation yourself and do not depend on a maintained third-party
package.

---

## 16. Checklist

- [ ] Device set up in the Eurotronic app
- [ ] Account number and MAC noted
- [ ] MQTT password read
- [ ] Login added to the broker, broker restarted
- [ ] All ten DNS names redirected, cache cleared
- [ ] `nslookup mqtt3.eurotronic.io` → broker IP
- [ ] Thermostat restarted, `da16x02…` seen in the broker log
- [ ] Climate entity created, setpoint adjustable
- [ ] Temperature and battery sensors created
- [ ] Both automations active
- [ ] (Optional) sensor in the Matter bridge, discovered by Alexa and assigned to the room

---

## Files in this repo

| File | Content |
|---|---|
| `README.md` | this guide (German) |
| `README.en.md` | this guide (English) |
| `examples/climate-discovery.json` | discovery payload for the climate entity |
| `examples/temperature-sensor-discovery.json` | discovery payload for the current temperature |
| `examples/battery-sensor-discovery.json` | discovery payload for the battery |
| `examples/automations.yaml` | both automations, ready to paste into `automations.yaml` |
| `tools/comet_creds.py` | reads username and password from the `CONNECT` packet |

The example files contain **fictional** data (`0012AB34`, `AABBCC112233`).
Before using them, replace `0012AB34` with your account number and
`AABBCC112233` with your MAC address (no colons, upper case). The files use
German labels (`name`, `alias`) — those are display names, change them freely.

---

## Background

The basic idea — redirecting the thermostat's DNS to your own broker and
tapping the topics — comes from the Home Assistant forum:
[Integrating Comet Wifi – basic functionality](https://community.home-assistant.io/t/integrating-comet-wifi-basic-functionality/493474)
(2022). That thread documented the topics publicly for the first time.

Two things differ deliberately: the thread only redirects `mqtt.` and
`mqtt1.eurotronic.io` and therefore describes exactly the dropouts it never got
rid of. And it publishes credentials in plaintext — this guide reads them
locally with a script instead.

---

## License

[MIT](LICENSE) — use, modify and redistribute freely, with the copyright
notice. No warranty.
