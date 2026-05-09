# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Nature du dépôt

Dépôt de **configuration et documentation** pour le Raspberry Pi 3B `pidesk` (serveur de services domestiques). Il ne contient ni code applicatif, ni build, ni tests : seulement des `docker-compose.yml`, des fichiers de config, un script de backup, et un `README.md` qui sert de procédure d'installation pas-à-pas.

Le dépôt vit sur la machine de travail (`latitude`, `~/Documents/pidesk`) mais les services tournent sur `pidesk` (LAN `192.168.2.10`, Tailscale `*.taile766ec.ts.net`). Toute action « run » se fait via SSH ou Tailscale sur `pidesk`, pas localement.

Documentation et messages de commit en **français**.

## Architecture des services

Chaque sous-répertoire correspond à un service ; le `README.md` racine décrit l'ordre d'installation et les dépendances entre services.

Chaîne DNS : `client → Pi-hole (port 53, filtrage) → Unbound (port 5335, récursion DNSSEC) → serveurs autoritaires`. Le routeur distribue l'IP de `pidesk` comme **unique** DNS (DHCP option 6) — un DNS secondaire ferait contourner Pi-hole.

- `pihole/` — Docker, `network_mode: host`. TLS désactivé manuellement (cf. README) pour libérer le port 443.
- `unbound/` — **Pas Docker**. Le binaire tourne en systemd sur l'hôte ; `pi-hole.conf` est copié dans `/etc/unbound/unbound.conf.d/`. Les caches sont volontairement petits (8M msg / 16M rrset / 8M key) car le Pi 3B n'a que ~905 Mo de RAM — toute augmentation expose à l'OOM. `num-threads: 2` (passé de 1 à 2 le 2026-04-04 après saturation de la requestlist).
- `vaultwarden/` — Exposé uniquement via Tailscale Serve (`tailscale serve --bg 8222`), pas de port public. `DOMAIN` doit pointer vers le FQDN Tailscale du Pi. `backup.sh` fait un `sqlite3 .backup` (safe online) puis rsync vers `pidrive`, garde 7 jours, log via `logger -t backup-vaultwarden` — c'est ce tag syslog qui est consommé par `capteur-backup` (dépôt `vigie-capteurs`) et republié sur `vigie/backup/vaultwarden`.
- `mosquitto/` — Auth par fichier `passwd` qui doit exister **avant** le premier `up` (sinon le conteneur refuse de démarrer) et appartenir à UID 1883. Le hash du `passwd` dépend de la version de mosquitto (SHA-512 en 2.0, PBKDF2 en 2.1+) : downgrader l'image sans regénérer le passwd casse l'auth de tous les clients.
- `zigbee2mqtt/` — `network_mode: host`, utilise `/dev/ttyAMA0` (RasPBee 2). Nécessite `dtoverlay=disable-bt` dans `/boot/firmware/config.txt` pour libérer le port série du Bluetooth intégré.
- `ttn-bridge/` — Service Python (paho-mqtt + systemd) qui relaye TTN ⇄ Mosquitto local. Remplace la directive `connection ttn-eu1` du fichier `mosquitto/config/conf.d/ttn-bridge.conf` (renommé en `.disabled` le 2026-05-09) parce que le bridge mosquitto a soudainement été rejeté par TTN avec « unacceptable protocol version » (en mqttv311) ou disconnect silencieux (en mqttv50), alors que `mosquitto_pub`/`_sub` du même conteneur passent. Les uplinks TTN arrivent sur `ttn/devices/<dev>/{up,join,down/*}`, les downlinks à pousser vers TTN se publient sur `ttn/devices/<dev>/down/{push,replace}` localement.

## Conventions

- Les fichiers versionnés contiennent des **placeholders** à remplacer à l'installation : `<TAILSCALE_FQDN>`, `<USER>`, `<PASSWORD>`, `<MQTT_USER>`, `<MQTT_PASSWORD>`, `<PI_IP>`, `<BACKUP_HOST>`, `<BACKUP_DIR>`. Ne pas committer de valeurs réelles à leur place — les instances en prod sont éditées localement sur `pidesk`.
- Les répertoires de données (`vaultwarden/data/`, `pihole/etc-pihole/`, `pihole/etc-dnsmasq.d/`, `zigbee2mqtt/data/`) sont gitignorés et n'existent que sur le Pi.
- Quand on documente un changement non-évident dans un fichier de config (ex. `unbound/pi-hole.conf` ligne 44 sur `num-threads`), garder un commentaire daté qui explique *pourquoi* — utile pour ne pas régresser.

## Écosystème associé

- `vigie-capteurs` (`~/Documents/vigie-capteurs`, `Alixpat/vigie-capteurs`) — capteurs de monitoring qui publient sur `vigie/*` (MQTT broker = ce Mosquitto).
- App Android `vigie` — consomme les topics `vigie/*`.

Toucher au broker (auth, port, topics) impacte ces deux composants ; vérifier avant de changer.
