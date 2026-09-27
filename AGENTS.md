# AGENTS.md

Consignes pour les agents de code (Claude Code, OpenCode, Codex…) travaillant dans ce dépôt.
Source unique : `CLAUDE.md` ne fait que l'importer.

## Nature du dépôt

Dépôt de **configuration et documentation** pour le Raspberry Pi 3B `pidesk` (services domestiques) : `docker-compose.yml`, fichiers de config, scripts, et un `README.md` qui sert de procédure d'installation pas-à-pas (ordre, commandes, validation). Ni code applicatif à construire, ni tests.

- Un sous-répertoire par service : `pihole/`, `unbound/`, `vaultwarden/`, `mosquitto/`, `zigbee2mqtt/`, `ttn-bridge/`, `pollux/`.
- Le dépôt vit sur le poste (`latitude`, `~/Documents/pidesk`) ; les services tournent sur `pidesk` (LAN `192.168.2.10`, Tailscale `*.taile766ec.ts.net`). **Tout se lance via SSH ou Tailscale sur le Pi**, jamais localement (docker, systemd…).
- Documentation, commentaires et messages de commit en **français**, sans mention ni attribution d'agent.
- En cas de conflit, les sources exécutables (compose, `.conf`, scripts, étapes du README) priment sur la prose.

## Placeholders et secrets

- Les fichiers versionnés ne contiennent que des placeholders : `<TAILSCALE_FQDN>`, `<USER>`, `<PASSWORD>`, `<MQTT_USER>`, `<MQTT_PASSWORD>`, `<PI_IP>`, `<BACKUP_HOST>`, `<BACKUP_DIR>`, `<TTN_*>`, `<SECRET>`… Ne jamais committer de valeurs réelles (mots de passe, clés, FQDN, IP clientes) : les instances en prod sont éditées sur `pidesk`. Garder un `.example` pour chaque fichier secret.
- Gitignorés, présents seulement sur le Pi : `vaultwarden/data/`, `pihole/etc-pihole/`, `pihole/etc-dnsmasq.d/`, `zigbee2mqtt/data/`, `mosquitto/config/passwd`, `mosquitto/config/conf.d/*.conf`, `ttn-bridge/config.json`, `ttn-bridge/venv/`, `pollux/.env`.

## Services

Chaîne DNS : `client → Pi-hole (53, filtrage) → Unbound (5335, cache + validation DNSSEC locale) → Quad9/Cloudflare en DNS-over-TLS (TCP 853)`. Le routeur distribue l'IP de `pidesk` comme **unique** DNS (DHCP option 6) : un DNS secondaire contournerait Pi-hole. Ordre : Unbound avant Pi-hole ; Mosquitto avant Zigbee2MQTT, ttn-bridge et tout client MQTT.

- `pihole/` : Docker, `network_mode: host`. TLS désactivé à la main pour libérer le port 443 (v6 : `pihole-FTL --config …` puis redémarrage, cf. README). Ne pas activer son DNSSEC : Unbound s'en charge.
- `unbound/` : **pas Docker**, systemd sur l'hôte ; `pi-hole.conf` copié dans `/etc/unbound/unbound.conf.d/` puis `unbound-checkconf` et redémarrage. Forwarde en DoT car l'UDP/53 clair est parasité par le réseau mobile ; `tls-cert-bundle` doit être explicite sous systemd. Caches volontairement petits (8m msg / 16m rrset / 8m key) : le Pi 3B n'a que ~905 Mo, toute augmentation expose à l'OOM. `num-threads: 4`.
- `vaultwarden/` : exposé **seulement** via `tailscale serve --bg 8222`, aucun port public ; `DOMAIN` = FQDN Tailscale. `backup.sh` : `sqlite3 .backup` (sûr à chaud) puis rsync vers `pidrive`, 7 jours gardés, journalisé avec le tag syslog `backup-vaultwarden`, consommé par `capteur-backup` (dépôt `vigie-capteurs`).
- `mosquitto/` : auth par `config/passwd`, qui doit exister **avant** le premier `up` (sinon le conteneur refuse de démarrer) et appartenir à l'UID 1883. Image figée `eclipse-mosquitto:2.1.2-alpine` : le hachage du `passwd` dépend de la version (SHA-512 en 2.0, PBKDF2 en 2.1+) ; changer de version sans le regénérer casse l'auth de tous les clients.
- `zigbee2mqtt/` : `network_mode: host`, `/dev/ttyAMA0` (RasPBee 2) ; exige `dtoverlay=disable-bt` dans `/boot/firmware/config.txt`, `hciuart` désactivé et un redémarrage.
- `ttn-bridge/` : service Python (paho-mqtt + systemd) qui relaie TTN eu1 ⇄ Mosquitto. Il **remplace** le bridge natif de Mosquitto (rejeté par TTN : « unacceptable protocol version ») ; ne pas le réactiver. Uplinks sur `ttn/devices/<dev>/{up,join,down/*}`, downlinks à publier sur `ttn/devices/<dev>/down/{push,replace}`.
- `pollux/` : SSH et mosh du Pi à travers des requêtes HTTP courtes (dépôt `Alixpat/pollux`), servis par un Quick Tunnel Cloudflare (`pollux-tunnel`, URL changée à chaque redémarrage du tunnel). Image construite depuis `~/pollux` : le Pi ne compile rien, les artefacts viennent du poste (`GOARCH=arm64 ./build.sh`, puis `rsync`, puis `docker compose up -d --build pollux`, qui garde l'URL). `.env` : `POLLUX_TOKEN` (secret partagé qui signe les échanges, jamais transmis ; même valeur chez les clients) et `POLLUX_ALLOW_IP` (IP clientes vues par Cloudflare). Client et serveur doivent parler la même version de protocole.

## Commandes utiles (sur le Pi)

```bash
docker compose up -d                              # dans le dossier du service
docker compose pull && docker compose up -d       # mise à jour
docker logs -f <service>
sudo unbound-checkconf && sudo systemctl restart unbound
sudo tailscale serve --bg 8222 && tailscale serve status
docker run --rm -v $(pwd)/config:/data eclipse-mosquitto:2.1.2-alpine \
  mosquitto_passwd -c -b /data/passwd <USER> <PASSWORD>   # puis chown 1883:1883, chmod 600
```

Les procédures complètes (Pi-hole TLS, Zigbee, TTN, pollux) sont dans le `README.md`.

## Conventions et pièges

- Un changement de config non évident garde un commentaire **concis** expliquant *pourquoi* ; pas d'historique daté dans les fichiers (c'est le rôle de git). README court : commandes et tableaux plutôt que prose.
- Mosquitto est partagé avec `vigie-capteurs` (publie sur `vigie/*`, `~/Documents/vigie-capteurs`) et l'application Android `vigie` : vérifier leur impact avant de toucher à l'auth, aux ports ou aux topics.
- À éviter : lancer des services localement ; supposer un réseau Docker ou des versions par défaut ; committer données, `passwd`, `config.json` ou `.env` remplis ; ajouter un DNS secondaire ; grossir les caches d'Unbound.
