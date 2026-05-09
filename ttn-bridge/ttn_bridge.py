#!/usr/bin/env python3
"""
TTN Bridge — relais MQTT bidirectionnel entre The Things Network et le broker
Mosquitto local. Remplace la directive `connection ttn-eu1` du fichier
`ttn-bridge.conf` qui ne fonctionne plus depuis le 2026-05-09 (rejet TTN du
CONNECT envoyé par Mosquitto bridge en 2.0.22 et 2.1.2, alors que mosquitto_pub
et mosquitto_sub passent sans souci avec les mêmes credentials).

Topologie :
- TTN  → topic `v3/<user>/devices/<dev>/{up,join,down/sent,...}`
   relayé vers `ttn/devices/<dev>/{up,join,down/sent,...}` localement
- local → topic `ttn/devices/<dev>/down/{push,replace}`
   relayé vers `v3/<user>/devices/<dev>/down/{push,replace}` sur TTN
"""

import json
import logging
import signal
import ssl
import sys
import time

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ttn-bridge")

running = True


def handle_signal(signum, _frame):
    global running
    log.info("Signal %s reçu, arrêt en cours…", signum)
    running = False


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def make_ttn_client(cfg: dict, on_message) -> mqtt.Client:
    client = mqtt.Client(client_id=cfg.get("client_id", "ttn-bridge"), clean_session=True)
    client.username_pw_set(cfg["username"], cfg["password"])
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.on_message = on_message

    def on_connect(_c, _u, _f, rc):
        if rc != 0:
            log.error("TTN connect échoué : rc=%d", rc)
            return
        log.info("TTN connecté à %s:%d", cfg["broker"], cfg["port"])
        for topic in cfg["subscribe_topics"]:
            full = cfg["topic_prefix"] + topic
            client.subscribe(full, qos=0)
            log.info("TTN subscribe : %s", full)

    def on_disconnect(_c, _u, rc):
        if rc != 0:
            log.warning("TTN déconnecté (rc=%d), reconnect auto", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    return client


def make_local_client(cfg: dict, on_message) -> mqtt.Client:
    client = mqtt.Client(client_id=cfg.get("client_id", "ttn-bridge-local"), clean_session=True)
    if cfg.get("username"):
        client.username_pw_set(cfg["username"], cfg.get("password", ""))
    client.on_message = on_message

    def on_connect(_c, _u, _f, rc):
        if rc != 0:
            log.error("Local connect échoué : rc=%d", rc)
            return
        log.info("Local connecté à %s:%d", cfg["broker"], cfg["port"])
        for topic in cfg["subscribe_topics"]:
            full = cfg["ttn_prefix"] + topic
            client.subscribe(full, qos=0)
            log.info("Local subscribe : %s", full)

    def on_disconnect(_c, _u, rc):
        if rc != 0:
            log.warning("Local déconnecté (rc=%d), reconnect auto", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    return client


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    config = load_config(config_path)
    ttn_cfg = config["ttn"]
    local_cfg = config["local"]

    # Forward déclaratif (les clients sont définis plus bas)
    ttn_client = None
    local_client = None

    def on_ttn_message(_c, _u, msg):
        if not msg.topic.startswith(ttn_cfg["topic_prefix"]):
            return
        suffix = msg.topic[len(ttn_cfg["topic_prefix"]):]
        local_topic = local_cfg["ttn_prefix"] + suffix
        local_client.publish(local_topic, msg.payload, qos=msg.qos, retain=msg.retain)
        log.info("TTN→local : %s → %s (%d bytes)", msg.topic, local_topic, len(msg.payload))

    def on_local_message(_c, _u, msg):
        if not msg.topic.startswith(local_cfg["ttn_prefix"]):
            return
        suffix = msg.topic[len(local_cfg["ttn_prefix"]):]
        ttn_topic = ttn_cfg["topic_prefix"] + suffix
        ttn_client.publish(ttn_topic, msg.payload, qos=msg.qos)
        log.info("local→TTN : %s → %s (%d bytes)", msg.topic, ttn_topic, len(msg.payload))

    ttn_client = make_ttn_client(ttn_cfg, on_ttn_message)
    local_client = make_local_client(local_cfg, on_local_message)

    log.info("Démarrage du bridge TTN ⇄ local")
    ttn_client.connect_async(ttn_cfg["broker"], ttn_cfg["port"], keepalive=60)
    local_client.connect_async(local_cfg["broker"], local_cfg["port"], keepalive=60)
    ttn_client.loop_start()
    local_client.loop_start()

    try:
        while running:
            time.sleep(1)
    finally:
        ttn_client.loop_stop()
        ttn_client.disconnect()
        local_client.loop_stop()
        local_client.disconnect()
        log.info("Arrêté proprement.")


if __name__ == "__main__":
    main()
