#!/usr/bin/env python3
"""Liest die MQTT-Zugangsdaten aus dem CONNECT-Paket eines Eurotronic Comet WiFi.

Der Regler spricht MQTT 3.1.1 unverschluesselt auf Port 1883. Im ersten Paket
(CONNECT) stehen Benutzername und Passwort im Klartext.

Aufruf auf dem Rechner, auf den die Eurotronic-Hostnamen per DNS zeigen:

    python comet_creds.py            # lauscht auf 1883
    python comet_creds.py 18830      # anderer Port (dann DNS entsprechend setzen)

Danach am Regler eine Taste druecken bzw. am Rad drehen, damit er aufwacht.
Das Skript beendet sich nach dem ersten CONNECT.

Nur fuer das eigene Geraet verwenden.
"""

import socket
import struct
import sys

MQTT_PORT = 1883


def read_packet(sock):
    """Liest ein vollstaendiges MQTT-Paket und gibt (header, body) zurueck."""
    first = sock.recv(1)
    if not first:
        return None, None
    header = first[0]

    multiplier = 1
    length = 0
    while True:
        b = sock.recv(1)
        if not b:
            return None, None
        byte = b[0]
        length += (byte & 0x7F) * multiplier
        if not byte & 0x80:
            break
        multiplier *= 128

    body = b""
    while len(body) < length:
        chunk = sock.recv(length - len(body))
        if not chunk:
            break
        body += chunk
    return header, body


def parse_connect(body):
    """Zerlegt den CONNECT-Body (ab Protocol Name) in seine Felder."""
    if body is None or len(body) < 10:
        return None

    pos = 0
    (name_len,) = struct.unpack_from("!H", body, pos)
    pos += 2
    protocol = body[pos:pos + name_len].decode(errors="replace")
    pos += name_len
    level = body[pos]
    pos += 1
    flags = body[pos]
    pos += 1
    (keepalive,) = struct.unpack_from("!H", body, pos)
    pos += 2

    def take():
        nonlocal pos
        (ln,) = struct.unpack_from("!H", body, pos)
        pos += 2
        value = body[pos:pos + ln]
        pos += ln
        return value

    client_id = take().decode(errors="replace")
    if flags & 0x04:  # Will-Flag: Will-Topic und Will-Nachricht ueberspringen
        take()
        take()
    username = take().decode(errors="replace") if flags & 0x80 else None
    password = take().decode(errors="replace") if flags & 0x40 else None

    return {
        "protocol": protocol,
        "level": level,
        "client_id": client_id,
        "keepalive": keepalive,
        "username": username,
        "password": password,
    }


def serve(port=MQTT_PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", port))
        server.listen(5)
        print(f"Lausche auf Port {port} - jetzt den Regler aufwecken ...")
        while True:
            conn, addr = server.accept()
            with conn:
                conn.settimeout(10)
                print(f"Verbindung von {addr[0]}")
                header, body = read_packet(conn)
                if header != 0x10:
                    print(f"  kein CONNECT (0x{header:02x}), weiter ...")
                    continue
                info = parse_connect(body)
                if not info:
                    print("  CONNECT nicht lesbar")
                    continue
                print(f"  Client-ID : {info['client_id']}")
                print(f"  Benutzer  : {info['username']}")
                print(f"  Passwort  : {info['password']}")
                return info


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else MQTT_PORT)
