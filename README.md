# Eurotronic Comet WiFi in Home Assistant einbinden

Inoffizielle Community-Anleitung, um den Heizkörperthermostat **Eurotronic
Comet WiFi** (WLAN/MQTT) komplett lokal in Home Assistant zu betreiben — ohne
Cloud, ohne Hersteller-App im Alltag. Keine Verbindung zu Eurotronic.

Am Ende hast du:

- eine Klima-Entität mit Sollwert, Ist-Temperatur und Modus,
- einen Batteriesensor,
- einen Temperatursensor, den auch Alexa per Sprache beantworten kann,
- und keinen Cloud-Zwang mehr im eigenen WLAN.

> **Stand:** 2026-10-26, getestet mit Home Assistant 2026.10.2 und dem
> Mosquitto-Add-on 7.1.2. Die Werte in den Beispielen (`0012AB34`,
> `AABBCC112233`) sind fiktive Beispieldaten — ersetze sie
> durch deine.

---

## 0. Kurzfassung

1. Gerät **zuerst normal in der Eurotronic-App** einrichten (mit Internet).
2. Kontonummer und MAC-Adresse notieren.
3. MQTT-Passwort des Geräts einmalig auslesen ([§4](#4-mqtt-passwort-ermitteln)).
4. Diesen Login im Mosquitto-Broker anlegen ([§5](#5-broker-login-anlegen)).
5. **Alle zehn** `mqtt*.eurotronic.*`-Namen per DNS auf deinen Broker umbiegen
   ([§6](#6-dns-umbiegen--der-entscheidende-schritt)).
6. Regler neu starten, Verbindung im Broker-Log prüfen ([§7](#7-verbindung-prüfen)).
7. Klima-Entität, Sensoren und zwei Automatiken anlegen
   ([§8](#8-klima-entität-in-home-assistant), [§9](#9-sensoren), [§10](#10-automatiken)).

Der ganze Trick ist Punkt 5. Ohne die vollständige DNS-Umleitung funktioniert
alles andere, aber der Regler verschwindet stundenlang in der Cloud.

---

## 1. Wie das Gerät funktioniert

Der Comet WiFi ist kein lokales Gerät. Er baut beim Aufwachen eine
**MQTT-Verbindung zu `mqtt.eurotronic.io`** auf (Port 1883, unverschlüsselt,
MQTT 3.1.1), meldet dort seinen Zustand und nimmt Befehle entgegen. Die App
spricht mit demselben Broker.

Daraus folgt die Idee: Wenn der Regler `mqtt.eurotronic.io` auflöst und dabei
**deinen** Broker statt der Cloud findet, spricht er lokal mit Home Assistant —
ohne dass am Gerät etwas geändert werden muss.

```
Regler ──DNS──▶ mqtt3.eurotronic.io  ──umgebogen──▶  192.168.x.x (Mosquitto)
   │                                                        │
   └────────────── MQTT 1883, Klartext ────────────────────▶┘
```

**Wichtig zu verstehen:**

| Eigenschaft | Konsequenz |
|---|---|
| Batteriebetrieb, Keepalive 600 s | Der Regler schläft und meldet sich nicht dauernd. |
| Befehle werden **sofort übernommen** | Sobald er verbunden ist, reagiert er in Sekunden. |
| Er meldet den neuen Wert **nicht von selbst** | Ohne Leseabfrage bleibt HA auf dem alten Stand → [§10](#10-automatiken). |
| MQTT 3.1.1, Port 1883, **kein TLS** | Zugangsdaten stehen im Klartext im ersten Paket ([§4](#4-mqtt-passwort-ermitteln)). |
| Nur 2,4 GHz (DA16200-Chip) | Kein 5-GHz-WLAN, kein Gastnetz mit Client-Isolation. |

Eine **offizielle** Home-Assistant-Integration gibt es nicht. Die Integration
„Eurotronic Comet Blue" ist ausschließlich für die Bluetooth-Variante.

---

## 2. Voraussetzungen

- **Home Assistant** mit **Mosquitto-Broker** (Add-on `core_mosquitto` oder ein
  eigener Broker), erreichbar aus dem WLAN des Reglers, Port **1883**.
- Ein **DNS-Server, den du selbst konfigurieren kannst**: AdGuard Home,
  Pi-hole, dnsmasq, OPNsense/pfSense, Unbound …
  Eine FRITZ!Box allein kann keine beliebigen Hostnamen auf eine interne IP
  umbiegen — dann brauchst du einen DNS-Filter davor (z. B. AdGuard Home).
- Der Regler im **gleichen Netz** wie der Broker (kein VLAN dazwischen,
  keine Client-Isolation).
- Zugang zur **Eurotronic-App** (Konto) und die **MAC-Adresse** des Geräts.
- Ein Rechner, auf dem du notfalls **Python 3** starten kannst.

---

## 3. Benötigte Werte sammeln

| Wert | Woher | Beispiel |
|---|---|---|
| **Kontonummer** | Nummer deines Eurotronic-Kontos, 8 Hexzeichen | `0012AB34` |
| **MAC-Adresse** | Router-/Geräteliste, Aufkleber, App | `AA:BB:CC:11:22:33` |
| **Broker-IP** | dein Home Assistant | `192.168.1.10` |

Die **MAC ohne Doppelpunkte und in Großbuchstaben** ergibt den Topic-Teil:

```
AA:BB:CC:11:22:33   →   AABBCC112233
```

Alle Topics haben damit die Form:

```
02/<KONTO>/<MAC>/S/...   ← Befehle an den Regler
02/<KONTO>/<MAC>/V/...   ← Antworten des Reglers
```

> Die führende `02` ist Teil des Protokolls und bleibt unverändert.

---

## 4. MQTT-Passwort ermitteln

Der Regler meldet sich am Broker mit **Benutzername = Kontonummer** und einem
Passwort, das ihm die App bei der Einrichtung mitgegeben hat. Das Passwort
steht in keiner App-Oberfläche.

Da MQTT hier **unverschlüsselt** läuft, steht beides im Klartext im
`CONNECT`-Paket — dem ersten Paket jeder Verbindung. Du liest es einmal aus,
trägst es im Broker ein und brauchst es danach nie wieder.

### Variante A: kleiner Listener (empfohlen)

Das Skript lauscht auf Port 1883 und liest das erste Paket. Es beendet sich
nach dem ersten Treffer von selbst.

> **Vorher:** Mosquitto kurz stoppen, damit Port 1883 frei ist, und die
> DNS-Umleitung aus [§6](#6-dns-umbiegen--der-entscheidende-schritt) bereits
> auf diesen Rechner zeigen lassen. Danach Broker wieder starten.

> Das vollständige Skript liegt im Repo: [`tools/comet_creds.py`](tools/comet_creds.py)

Aufruf:

```bash
python tools/comet_creds.py
```

Dann den Regler aufwecken (Taste drücken oder am Rad drehen). Ausgabe:

```
Verbindung von 192.168.1.50
  Client-ID : da16x020012AB34112233
  Benutzer  : 0012AB34
  Passwort  : ********
```

Die Client-ID setzt sich zusammen aus `da16x02` + Kontonummer + den letzten
drei MAC-Bytes — ein gutes Indiz, dass du den richtigen Teilnehmer erwischt hast.

### Variante B: mitschneiden

Wenn du auf dem Broker-Rechner ohnehin eine Shell hast, reicht auch ein
Mitschnitt, während der Regler sich (erfolglos) anzumelden versucht:

```bash
sudo tcpdump -A -s0 -i any 'tcp port 1883'
```

Im Klartext des `CONNECT`-Pakets stehen Benutzername und Passwort.

> Nur für das eigene Gerät verwenden. Das Passwort gehört in den Broker, nicht
> ins Repository und nicht in eine Anleitung.

---

## 5. Broker-Login anlegen

**Mosquitto-Add-on:** Einstellungen → Add-ons → Mosquitto broker →
Konfiguration → `logins` ergänzen:

```yaml
logins:
  - username: "0012AB34"
    password: "DEIN_PASSWORT"
```

Speichern, Add-on **neu starten**.

- Benutzername ist die **Kontonummer**, nicht ein Wunschname.
- Sonderzeichen im Passwort sind erlaubt, müssen aber in Anführungszeichen stehen.
- Der Broker muss auf **1883 ohne TLS** lauschen. Der Regler kann kein TLS.
- Läuft dein Broker in einem Container, muss Port 1883 im LAN erreichbar sein
  (kein `127.0.0.1`-Binding).

> **Randnotiz:** Manche Quellen behaupten, die Comet-WiFi-Regler könnten keine
> MQTT-Anmeldung. Bei dem hier verwendeten Gerät war das nachweislich falsch —
> es meldet sich mit Kontonummer und Passwort an. Wenn dein Regler sich ohne
> Login verbindet, kannst du den Schritt überspringen.

---

## 6. DNS umbiegen — der entscheidende Schritt

Der Regler probiert **zehn** Hostnamen durch, jeweils `mqtt` und `mqtt1`–`mqtt4`
unter zwei Domains:

```
mqtt.eurotronic.io      mqtt.eurotronic.com
mqtt1.eurotronic.io     mqtt1.eurotronic.com
mqtt2.eurotronic.io     mqtt2.eurotronic.com
mqtt3.eurotronic.io     mqtt3.eurotronic.com
mqtt4.eurotronic.io     mqtt4.eurotronic.com
```

**Alle zehn** müssen auf die IP deines Brokers zeigen. Fehlt auch nur einer,
erwischt der Regler beim nächsten Aufwachen einen Cloud-Host und ist für
Stunden nicht lokal erreichbar. Genau das ist die häufigste Ursache für
„der Regler ist nur sporadisch da".

### AdGuard Home

Filter → **DNS-Umschreibungen** → *Umschreibung hinzufügen* — einmal pro Name
aus der Liste oben (zehn Einträge). Beispiel für die ersten und den letzten:

| Domain | Antwort |
|---|---|
| `mqtt.eurotronic.io` | `192.168.1.10` |
| `mqtt1.eurotronic.io` | `192.168.1.10` |
| … | … |
| `mqtt4.eurotronic.com` | `192.168.1.10` |

Danach den DNS-Cache leeren (AdGuard: *Filter → DNS-Cache leeren*).

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
sudo systemctl restart dnsmasq     # bzw. pihole restartdns
```

### Warum keine Wildcard?

`*.eurotronic.io` wäre kürzer, trifft aber auch die HTTPS-API der App. Dann
funktioniert die Eurotronic-App zu Hause nicht mehr richtig. Die zehn exakten
Namen lassen den Rest der Cloud in Ruhe.

### Prüfen

```bash
nslookup mqtt3.eurotronic.io
```

Muss deine Broker-IP liefern — für **alle** zehn Namen, nicht nur für `mqtt`.

> **Wenn dein DNS nur einzelne Namen kennt** (manche Router): alle zehn
> eintragen. Ein einzelner vergessener Name genügt für die Aussetzer.

---

## 7. Verbindung prüfen

1. Regler neu starten: Batterien kurz entnehmen oder Reset-Taste drücken.
2. Im Mosquitto-Log nachsehen (Add-on → Log):

```
New client connected from 192.168.1.50 as da16x020012AB34112233 (p2, c1, k600)
```

- `k600` = Keepalive 600 s, passt.
- Danach sollte `S/XX #COMM-TEST` auftauchen — der Verbindungstest des Geräts.
- Die Client-ID beginnt mit `da16x02…`.

Wenn dort nichts kommt: DNS ([§6](#6-dns-umbiegen--der-entscheidende-schritt)),
Login ([§5](#5-broker-login-anlegen)) und Port 1883 prüfen — in dieser
Reihenfolge.

---

## 8. Klima-Entität in Home Assistant

Home Assistant lernt die Entität über **MQTT Discovery** kennen. Du
veröffentlichst eine Konfiguration auf einem Discovery-Topic, HA baut daraus
die Entität.

**Topic:**

```
homeassistant/climate/comet_<mac_klein>/config
```

**Payload** (Platzhalter ersetzen, `retained` veröffentlichen):

```json
{
  "name": "Comet WiFi <RAUM>",
  "unique_id": "comet_wifi_<mac_klein>",
  "device": {
    "identifiers": ["comet_wifi_<mac_klein>"],
    "name": "Comet WiFi <RAUM>",
    "manufacturer": "Eurotronic",
    "model": "Comet WiFi"
  },
  "modes": ["heat"],
  "mode_state_topic": "02/<KONTO>/<MAC>/V/A0",
  "mode_state_template": "heat",
  "temperature_command_topic": "02/<KONTO>/<MAC>/S/A0",
  "temperature_command_template": "{{ '#%02x' | format((value | float * 2) | int) }}",
  "temperature_state_topic": "02/<KONTO>/<MAC>/V/A0",
  "temperature_state_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) / 2 }}",
  "current_temperature_topic": "02/<KONTO>/<MAC>/V/A1",
  "current_temperature_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) / 2 }}",
  "temp_step": 0.5,
  "precision": 0.5,
  "min_temp": 8,
  "max_temp": 28,
  "retain": true
}
```

Konkret für das Beispielgerät:

```json
{
  "name": "Comet WiFi Bad",
  "unique_id": "comet_wifi_aabbcc112233",
  "device": {
    "identifiers": ["comet_wifi_aabbcc112233"],
    "name": "Comet WiFi Bad",
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

### Veröffentlichen

**Variante 1 — Entwicklerwerkzeuge:**

Entwicklerwerkzeuge → Aktionen → `mqtt.publish`

```yaml
topic: homeassistant/climate/comet_aabbcc112233/config
payload: |
  {"name": ...}
retain: true
qos: 1
```

> **Wichtig:** HA rendert den Payload als Jinja-Template. Die `{{ … }}` in den
> Templates würden dabei ausgewertet und zerstört. Lege deshalb
> `{% raw %}` … `{% endraw %}` um das JSON — oder nutze Variante 2.

**Variante 2 — `mosquitto_pub`:**

```bash
mosquitto_pub -h 192.168.1.10 -p 1883 -u 0012AB34 -P 'DEIN_PASSWORT' \
  -t 'homeassistant/climate/comet_aabbcc112233/config' -r -f comet_climate.json
```

Danach erscheint unter Einstellungen → Geräte & Dienste → MQTT ein Gerät
„Comet WiFi …" mit einer Klima-Entität.

### Was die Templates tun

| Feld | Bedeutung |
|---|---|
| `temperature_command_template` | `21.0` °C → `#2a` (Wert × 2 als Hex) |
| `temperature_state_template` | `#2a` → `21.0` (Hex ÷ 2) |
| `current_temperature_template` | dito für `V/A1` |
| `split('#')[-1]` | Die App schickt vor dem `#` zwei Zählerbytes — ab dem **letzten** `#` lesen. |

### Entitäts-ID

HA vergibt die ID automatisch (aus Name und ggf. Gerätenamen). Wenn sie dir zu
lang ist, benenne sie um: Einstellungen → Geräte & Dienste → Entitäten →
Entität öffnen → Zahnrad → *Entitäts-ID*.

---

## 9. Sensoren

Der Regler liefert Ist-Temperatur und Batterie auf eigenen Topics. Beide
Sensoren sind optional, aber praktisch (und der Temperatursensor ist die
Grundlage für Alexa).

**Wichtig:** Alle drei Entitäten (Klima, Temperatur, Batterie) müssen im
`device`-Block **dieselben `identifiers`** verwenden, sonst legt HA ein
zweites Gerät an.

### 9.1 Ist-Temperatur

Topic: `homeassistant/sensor/comet_<mac_klein>_temperatur/config`

```json
{
  "name": "Temperatur",
  "unique_id": "comet_wifi_<mac_klein>_temperatur",
  "device": {
    "identifiers": ["comet_wifi_<mac_klein>"]
  },
  "state_topic": "02/<KONTO>/<MAC>/V/A1",
  "value_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) / 2 }}",
  "unit_of_measurement": "°C",
  "device_class": "temperature",
  "state_class": "measurement"
}
```

Beispiel:

```json
{
  "name": "Temperatur",
  "unique_id": "comet_wifi_aabbcc112233_temperatur",
  "device": { "identifiers": ["comet_wifi_aabbcc112233"] },
  "state_topic": "02/0012AB34/AABBCC112233/V/A1",
  "value_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) / 2 }}",
  "unit_of_measurement": "°C",
  "device_class": "temperature",
  "state_class": "measurement"
}
```

### 9.2 Batterie

Topic: `homeassistant/sensor/comet_<mac_klein>_batterie/config`

```json
{
  "name": "Batterie",
  "unique_id": "comet_wifi_<mac_klein>_batterie",
  "device": {
    "identifiers": ["comet_wifi_<mac_klein>"]
  },
  "state_topic": "02/<KONTO>/<MAC>/V/A6",
  "value_template": "{{ (value.split('#')[-1][0:2] | int(0, 16)) }}",
  "unit_of_measurement": "%",
  "device_class": "battery",
  "state_class": "measurement"
}
```

Der Wert kommt als zweistelliger Hex-Wert: `#55` = 0x55 = **85 %**.

Ohne Abfrage bleibt der Sensor leer — er wird von den Automatiken in
[§10](#10-automatiken) mit versorgt.

---

## 10. Automatiken

Zwei Regeln schließen den Kreis. Ohne sie funktioniert das Setzen zwar, aber HA
zeigt den neuen Wert erst Stunden später (oder nie).

### 10.1 Sollwert quittieren

Der Regler übernimmt den Sollwert sofort, meldet ihn aber nicht zurück. HA
publiziert auf `S/A0` — dieselbe Nachricht löst diese Regel aus, die eine
Sekunde später Ist und Soll abfragt.

```yaml
- id: comet_sollwert_quittieren
  alias: "Comet: Sollwert quittieren"
  description: "Fragt nach jedem Sollwert-Befehl Ist und Soll ab."
  triggers:
    - trigger: mqtt
      topic: "02/<KONTO>/<MAC>/S/A0"
  conditions: []
  actions:
    - delay: "00:00:01"
    - action: mqtt.publish
      data:
        topic: "02/<KONTO>/<MAC>/S/AF"
        payload: "#0b"
        qos: 1
        retain: false
  mode: queued
  max: 5
```

### 10.2 Istwert regelmäßig abfragen

```yaml
- id: comet_istwert_abfragen
  alias: "Comet: Istwert abfragen"
  description: "Holt alle 2 Stunden Ist, Soll, Batterie und Flags."
  triggers:
    - trigger: time_pattern
      hours: "/2"
  conditions: []
  actions:
    - action: mqtt.publish
      data:
        topic: "02/<KONTO>/<MAC>/S/AF"
        payload: "#4B"
        qos: 1
        retain: false
  mode: single
```

- `#0b` fragt nur Temperaturen ab, `#4B` zusätzlich Batterie und Flags
  ([§11](#11-protokoll-referenz)).
- **Intervall:** 2 Stunden sind ein guter Kompromiss. Kürzer = aktueller,
  aber mehr Funkverkehr und damit Batterieverbrauch. 15 Minuten sind möglich,
  kosten spürbar mehr.
- Der Trigger feuert auch beim HA-Start (retained Command). Das ist harmlos.

> **HA-Version:** `triggers:`/`actions:` gilt ab HA 2024.10. In älteren
> Versionen heißen die Schlüssel `trigger:`/`action:` (Einzahl) — Inhalt bleibt
> gleich.

### 10.3 Optional: Sofortmeldung beim Verbinden

Einmalig `#0b` **retained** auf `S/AF` setzen:

```yaml
topic: 02/<KONTO>/<MAC>/S/AF
payload: "#0b"
retain: true
```

Dann bekommt der Regler die Abfrage bei **jeder** Verbindung und meldet sofort
seinen Zustand — praktisch nach Stromausfall oder Neustart.

---

## 11. Protokoll-Referenz

### Topics

| Topic | Richtung | Bedeutung |
|---|---|---|
| `S/A0` | HA → Gerät | Sollwert setzen, Payload `#<hex>` (Wert × 2) |
| `S/AF` | HA → Gerät | Leseabfrage, Payload = Bitmaske |
| `V/A0` | Gerät → HA | Sollwert, z. B. `#2A` = 21,0 °C |
| `V/A1` | Gerät → HA | Ist-Temperatur, z. B. `#22` = 17,0 °C |
| `V/A3` | Gerät → HA | Status-/Schalter-Flags, z. B. `#2182` |
| `V/A6` | Gerät → HA | Batterie, z. B. `#55` = 85 % |

### `S/AF` ist eine Bitmaske

Kein fester Befehl, sondern eine Auswahl, welche Werte das Gerät zurückschickt:

| Payload | Holt |
|---|---|
| `#0b` | Sollwert + Ist-Temperatur |
| `#48000000` | Batterie + Flags |
| `#4B` | beides zusammen |
| `#FFFFFFFF` | alles |

`#4B` ist die Abkürzung für `#0B000000` + `#48000000`.

### Werteformat

- Immer `#` + Hex, °C = Hex ÷ 2.
- Das Gerät antwortet in **Großbuchstaben** (`#2A`), die App sendet
  **Kleinbuchstaben** (`#2a`). Beides ist gültig.
- Die App stellt dem `#` zwei Zählerbytes voran — deshalb immer ab dem
  **letzten** `#` parsen.

### Verbindungsverhalten

| Wert | Bedeutung |
|---|---|
| Client-ID `da16x02…` | Gerät (DA16200-Chip) |
| Keepalive 600 s | Sitzung bleibt lange offen |
| `S/XX #COMM-TEST` | Verbindungstest direkt nach dem Verbinden |

---

## 12. Alexa (optional)

Damit Alexa „wie ist die Temperatur im Bad" beantworten kann, braucht
sie einen **Temperatursensor** als eigenes Gerät — das Attribut der
Klima-Entität genügt nicht.

Der zuverlässigste Weg ist der **Matter Hub**:

1. Add-on **Home-Assistant-Matter-Hub** installieren.
2. Eine Bridge anlegen und in Alexa koppeln (Alexa → Geräte → + → Matter).
3. In der Bridge unter **Filter → Include** den Sensor ergänzen:
   `sensor.comet_wifi_<mac_klein>_temperatur`
4. **Bridge neu starten** — erst dann erscheint der neue Endpoint.
5. In der Alexa-App **„Geräte suchen"**.
6. Den Sensor der **Raumgruppe** „Bad" zuordnen.

Erst mit der Raumzuordnung versteht Alexa die Formulierung „im Bad".
Ohne Raum antwortet sie nur auf den Gerätenamen.

Die HA-eigene **Alexa-Integration** (Cloud-Skill) zeigt Sensoren zwar in der
App an, ist für Sprachabfragen dieser Art aber unzuverlässig.

---

## 13. Fehlersuche

| Symptom | Wahrscheinliche Ursache | Lösung |
|---|---|---|
| Regler ist nur alle paar Stunden sichtbar | Ein `mqtt*.eurotronic.*`-Name zeigt noch in die Cloud | Alle **zehn** Namen prüfen ([§6](#6-dns-umbiegen--der-entscheidende-schritt)) |
| Verbindung wird sofort abgelehnt | Login fehlt oder falsch | `logins` im Broker, Neustart ([§5](#5-broker-login-anlegen)) |
| Keine Verbindung, kein Log-Eintrag | Port 1883 nicht erreichbar / VLAN / Client-Isolation / 5-GHz-WLAN | Netz prüfen, 2,4 GHz nutzen |
| Sollwert ändern wirkt, HA zeigt ihn aber erst spät | Quittungs-Automatik fehlt | [§10.1](#101-sollwert-quittieren) |
| Ist-Temperatur bleibt stehen | Kein Poll | [§10.2](#102-istwert-regelmäßig-abfragen) |
| Entität zeigt 0 °C oder `unknown` | Template liest falsch | `split('#')[-1][0:2]` verwenden |
| Zwei Geräte in HA | Unterschiedliche `identifiers` | In allen Payloads identisch setzen |
| Batterie bleibt leer | `#0b` fragt sie nicht mit ab | `#4B` verwenden ([§11](#11-protokoll-referenz)) |
| Alexa findet den Sensor nicht | Bridge nicht neu gestartet / Filter nicht gesetzt | Filter + Restart + „Geräte suchen" |
| `exceeded timeout` im Broker-Log | Regler schläft oder hat die Verbindung verloren | Unkritisch, wenn er sich bald neu meldet — häufige Timeouts deuten auf die DNS-Lücke hin |

**Erste Diagnose immer:** Broker-Log. Steht dort ein `New client connected …
as da16x02…`, ist die Verbindung in Ordnung und das Problem liegt in HA.
Fehlt der Eintrag, liegt es an DNS, Login oder Netz.

---

## 14. Grenzen und Nebenwirkungen

- **Keine Cloud mehr:** Fernzugriff über die Eurotronic-App von unterwegs
  funktioniert nicht mehr. Zu Hause spricht die App mit deinem Broker.
- **Firmware-Updates** (sofern der Hersteller welche anbietet) laufen über die
  Cloud und sind mit dieser Umleitung nicht erreichbar. Falls du je eines
  brauchst: DNS-Einträge kurz entfernen, Gerät neu starten, Update abwarten,
  Einträge wiederherstellen.
- **Einrichtung zuerst, Umleitung danach.** Die Provisionierung (WLAN,
  Zugangsdaten) läuft über die Cloud. Nach einem Werksreset also erst die
  DNS-Umleitung zurücknehmen, Gerät in der App einrichten, dann wieder
  umbiegen.
- **Batterie:** Jede Abfrage kostet Energie. Die 2-Stunden-Abfrage ist ein
  bewusster Kompromiss; 15 Minuten funktionieren, kosten aber mehr.
- **Kein Push bei Änderung am Gerät:** Ob der Regler ein manuell am Rad
  verstelltes Ziel von selbst meldet, ist nicht abschließend geprüft. Die
  Quittungs-Automatik greift nur bei Befehlen aus HA.
- **Nur ein Broker:** Der Regler kann nicht gleichzeitig Cloud und lokal.

---

## 15. Alternativen

- **`aiocometwifi`** (Python-Bibliothek) und darauf aufbauende
  Community-Integrationen sprechen dasselbe Protokoll und leisten die
  Entitäten-Erzeugung automatisch. Sie setzen einen Broker voraus, der
  anonyme Verbindungen erlaubt — dieser Weg wurde hier nicht verwendet, weil
  das Gerät sich mit Konto-Login anmeldet.
- **`marcinkordas/comet_wifi_integration`** verfolgt einen anderen Ansatz und
  wurde hier nicht eingesetzt.

Der manuelle Weg oben hat den Vorteil, dass du jede Entität und jede
Automatik selbst kontrollierst und nichts von einem gepflegten Fremdpaket
abhängt.

---

## 16. Checkliste zum Abhaken

- [ ] Gerät in der Eurotronic-App eingerichtet
- [ ] Kontonummer und MAC notiert
- [ ] MQTT-Passwort ausgelesen
- [ ] Login im Broker angelegt, Broker neu gestartet
- [ ] Alle zehn DNS-Namen umgebogen, Cache geleert
- [ ] `nslookup mqtt3.eurotronic.io` → Broker-IP
- [ ] Regler neu gestartet, `da16x02…` im Broker-Log gesehen
- [ ] Klima-Entität angelegt, Sollwert änderbar
- [ ] Temperatur- und Batteriesensor angelegt
- [ ] Beide Automatiken aktiv
- [ ] (Optional) Sensor in der Matter-Bridge, in Alexa gefunden und im Raum

---

## Dateien in diesem Repo

| Datei | Inhalt |
|---|---|
| `README.md` | diese Anleitung |
| `examples/climate-discovery.json` | Discovery-Payload für die Klima-Entität |
| `examples/temperature-sensor-discovery.json` | Discovery-Payload für die Ist-Temperatur |
| `examples/battery-sensor-discovery.json` | Discovery-Payload für die Batterie |
| `examples/automations.yaml` | beide Automatiken zum Einfügen in `automations.yaml` |
| `tools/comet_creds.py` | liest Benutzername und Passwort aus dem `CONNECT`-Paket |

Die Beispieldateien enthalten **fiktive** Daten (`0012AB34`, `AABBCC112233`).
Vor dem Verwenden `0012AB34` durch deine Kontonummer und `AABBCC112233` durch
deine MAC-Adresse (ohne Doppelpunkte, Großbuchstaben) ersetzen.

---

## Lizenz

[MIT](LICENSE) — Nutzung, Veränderung und Weitergabe erlaubt, mit
Copyright-Hinweis. Ohne Gewährleistung.

