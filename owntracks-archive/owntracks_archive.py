#!/usr/bin/env python3
"""
OwnTracks Archive — archive dans SQLite les messages OwnTracks publiés sur le
broker MQTT (topics `owntracks/#`) : positions (`_type=location`), points
d'intérêt (`waypoint`) et transitions (`transition`). Le payload brut est
conservé, les colonnes nommées ne servent qu'aux requêtes.
"""

import json
import logging
import signal
import sqlite3
import threading
import time

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("owntracks-archive")

running = True
last_prune = 0.0
# Les inserts arrivent du thread réseau de paho, la purge du thread principal.
db_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS locations (
    tst      INTEGER NOT NULL,   -- epoch s, horodaté par l'app, pas par le serveur
    user     TEXT NOT NULL,
    device   TEXT NOT NULL,
    lat      REAL NOT NULL,
    lon      REAL NOT NULL,
    acc      REAL,
    batt     REAL,
    bs       REAL,
    vel      REAL,
    alt      REAL,
    tid      TEXT,
    payload  TEXT NOT NULL,
    received REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_locations_tst ON locations (tst);
-- Relivraison qos 1 (redémarrage du service, session persistante) :
-- ignorer plutôt que stocker deux fois le même point.
CREATE UNIQUE INDEX IF NOT EXISTS uq_locations ON locations (user, device, tst);

CREATE TABLE IF NOT EXISTS waypoints (
    tst      INTEGER NOT NULL,
    user     TEXT NOT NULL,
    device   TEXT NOT NULL,
    lat      REAL NOT NULL,
    lon      REAL NOT NULL,
    rad      REAL,
    name     TEXT,
    payload  TEXT NOT NULL,
    received REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS transitions (
    tst      INTEGER,
    user     TEXT NOT NULL,
    device   TEXT NOT NULL,
    event    TEXT NOT NULL,      -- enter / leave
    lat      REAL,
    lon      REAL,
    tid      TEXT,
    payload  TEXT NOT NULL,
    received REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transitions_tst ON transitions (tst);
CREATE UNIQUE INDEX IF NOT EXISTS uq_transitions ON transitions (user, device, tst, event);
"""

# Repli de migration : dédoublonner avant de poser l'index unique.
DEDUP = """
DELETE FROM locations WHERE rowid NOT IN
    (SELECT MIN(rowid) FROM locations GROUP BY user, device, tst);
DELETE FROM transitions WHERE rowid NOT IN
    (SELECT MIN(rowid) FROM transitions GROUP BY user, device, tst, event);
"""


def handle_signal(signum, _frame):
    global running
    log.info("Signal %s reçu, arrêt en cours…", signum)
    running = False


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def open_db(path: str) -> sqlite3.Connection:
    # paho livre les messages dans son thread réseau : autoriser le partage
    # de la connexion, l'accès concurrent est sérialisé par db_lock.
    conn = sqlite3.connect(path, check_same_thread=False)
    # WAL : le service écrit pendant que des requêtes sqlite3 en CLI lisent.
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.executescript(SCHEMA)
    except sqlite3.IntegrityError:
        # base antérieure contenant des doublons : dédoublonner puis repasser
        # le schéma (l'index unique peut maintenant être posé)
        conn.executescript(DEDUP + SCHEMA)
    conn.commit()
    return conn


def prune(conn: sqlite3.Connection, retention_days) -> None:
    if not retention_days:
        return
    cutoff = time.time() - retention_days * 86400
    with db_lock:
        cur = conn.cursor()
        for table in ("locations", "waypoints", "transitions"):
            cur.execute(f"DELETE FROM {table} WHERE COALESCE(tst, received) < ?", (cutoff,))
            if cur.rowcount:
                log.info("Purge %s : %d ligne(s) de plus de %d j", table, cur.rowcount, retention_days)
        conn.commit()


def handle_message(conn: sqlite3.Connection, topic: str, payload: bytes) -> None:
    # OwnTracks publie un payload vide pour effacer un message retained.
    if not payload:
        return
    try:
        msg = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        log.warning("Payload non JSON sur %s, ignoré", topic)
        return
    if not isinstance(msg, dict):
        return

    # owntracks/<user>/<device>[/<reste>]
    parts = topic.split("/")
    if len(parts) < 3:
        return
    user, device = parts[1], parts[2]
    mtype = msg.get("_type")
    now = time.time()
    raw = json.dumps(msg, ensure_ascii=False)

    if mtype == "location":
        if "lat" not in msg or "lon" not in msg:
            return
        with db_lock:
            cur = conn.execute(
                "INSERT OR IGNORE INTO locations (tst, user, device, lat, lon, acc, batt, bs,"
                " vel, alt, tid, payload, received) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    msg.get("tst", int(now)), user, device,
                    msg.get("lat"), msg.get("lon"),
                    msg.get("acc"), msg.get("batt"), msg.get("bs"),
                    msg.get("vel"), msg.get("alt"), msg.get("tid"), raw, now,
                ),
            )
    elif mtype == "waypoint":
        if "lat" not in msg or "lon" not in msg:
            return
        with db_lock:
            cur = conn.execute(
                "INSERT INTO waypoints (tst, user, device, lat, lon, rad, name,"
                " payload, received) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    msg.get("tst", int(now)), user, device,
                    msg.get("lat"), msg.get("lon"), msg.get("rad"), msg.get("name"),
                    raw, now,
                ),
            )
    elif mtype == "transition":
        with db_lock:
            cur = conn.execute(
                "INSERT OR IGNORE INTO transitions (tst, user, device, event, lat, lon, tid,"
                " payload, received) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    msg.get("tst"), user, device, msg.get("event"),
                    msg.get("lat"), msg.get("lon"), msg.get("tid"), raw, now,
                ),
            )
    else:
        return
    with db_lock:
        conn.commit()
    if cur.rowcount:
        log.info("Archivé %s (%s) tst=%s", topic, mtype, msg.get("tst"))
    else:
        # relivraison qos 1 d'un message déjà en base
        log.debug("Doublon ignoré : %s tst=%s", topic, msg.get("tst"))


def main() -> None:
    import sys
    if len(sys.argv) != 2:
        print("usage: owntracks_archive.py <config.json>", file=sys.stderr)
        sys.exit(2)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        cfg = json.load(f)
    mqtt_cfg = cfg["mqtt"]
    retention_days = cfg.get("retention_days")

    conn = open_db(cfg.get("db_path", "/var/lib/owntracks-archive/positions.db"))
    prune(conn, retention_days)
    global last_prune
    last_prune = time.time()

    client = mqtt.Client(
        client_id=mqtt_cfg.get("client_id", "owntracks-archive"),
        clean_session=False,  # qos 1 : rattraper les messages manqués hors ligne
    )
    if mqtt_cfg.get("username"):
        client.username_pw_set(mqtt_cfg["username"], mqtt_cfg.get("password", ""))
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    def on_connect(_c, _u, _f, rc):
        if rc != 0:
            log.error("Connexion MQTT échouée : rc=%d", rc)
            return
        topic = mqtt_cfg.get("topic", "owntracks/#")
        client.subscribe(topic, qos=1)
        log.info("Connecté à %s:%d, subscribe : %s", mqtt_cfg["broker"], mqtt_cfg["port"], topic)

    def on_message(_c, _u, msg):
        try:
            handle_message(conn, msg.topic, msg.payload)
        except Exception:
            log.exception("Échec d'archivage du message sur %s", msg.topic)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(mqtt_cfg["broker"], mqtt_cfg.get("port", 1883), keepalive=60)
    client.loop_start()

    try:
        while running:
            time.sleep(10)
            # Purge quotidienne de la rétention, sans redémarrer le service.
            if retention_days and time.time() - last_prune > 86400:
                prune(conn, retention_days)
                last_prune = time.time()
    finally:
        client.loop_stop()
        client.disconnect()
        conn.close()
        log.info("Arrêté.")


if __name__ == "__main__":
    main()
