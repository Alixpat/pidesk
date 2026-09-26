# pidesk

Raspberry Pi 3B de bureau — plateforme de services domestiques.

## Sommaire

- [Matériel](#matériel)
- [Installation de base](#installation-de-base)
- [Pi-hole](#pi-hole)
- [Unbound — résolveur DNS local (DoT)](#unbound--résolveur-dns-local-dot)
- [Vaultwarden — gestionnaire de mots de passe](#vaultwarden--gestionnaire-de-mots-de-passe)
- [Mosquitto — broker MQTT](#mosquitto--broker-mqtt)
- [TTN Bridge — relais LoRaWAN](#ttn-bridge--relais-lorawan)
- [Zigbee2MQTT — passerelle Zigbee↔MQTT](#zigbee2mqtt--passerelle-zigbeemqtt)
- [wstunnel — SSH via WebSocket (test, arrêté)](#wstunnel--ssh-via-websocket-test-arrêté)
- [pollux — SSH via requêtes HTTP courtes](#pollux--ssh-via-requêtes-http-courtes)
- [Prochaines étapes](#prochaines-étapes)

## Matériel

| Composant | Détail |
|---|---|
| Board | Raspberry Pi 3 Model B (1 Go RAM) |
| Stockage | Carte SD |
| Accessoire | RasPBee 2 (Phoscon) — passerelle Zigbee |
| Réseau | Ethernet (recommandé) + WiFi |

## Installation de base

### 1. Flasher la carte SD

Depuis une machine Debian 13 (Trixie), installer rpi-imager (paquet absent des dépôts) :

```bash
wget https://downloads.raspberrypi.org/imager/imager_latest_amd64.deb
sudo apt install ./imager_latest_amd64.deb
sudo rpi-imager
```

**Écran de sélection :**

1. **Modèle** : `Raspberry Pi 3`
2. **OS** : `Raspberry Pi OS (other)` → `Raspberry Pi OS Lite (64-bit)` (Bookworm)
3. **Stockage** : sélectionner la carte SD

**Personnalisation OS** : configurer hostname, utilisateur, WiFi, timezone (`Europe/Paris`), clavier (`fr`), et activer SSH par clé publique.

### 2. Premier boot

Insérer la SD dans le Pi, brancher l'Ethernet, alimenter.

```bash
ssh <user>@<hostname>.local
```

### 3. Mise à jour + Docker

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Se déconnecter/reconnecter pour appliquer le groupe `docker`.

### 4. Tailscale

Tailscale crée un VPN mesh (WireGuard) entre les appareils. Il permet l'accès distant aux services du Pi sans exposer de port sur Internet.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Suivre le lien affiché pour authentifier l'appareil. Vérifier :

```bash
tailscale status   # liste des appareils du tailnet
tailscale ip       # IP Tailscale du Pi (100.x.x.x)
```

Le FQDN Tailscale du Pi (ex. `pidesk.tailXXXXX.ts.net`) est utilisé par les services qui nécessitent un accès HTTPS distant (voir Vaultwarden).

### 5. IP statique

Vérifier le nom de la connexion :

```bash
nmcli con show
```

> Sur Bookworm avec cloud-init, la connexion Ethernet s'appelle `netplan-eth0`.

```bash
sudo nmcli con mod "netplan-eth0" \
  ipv4.addresses <IP>/24 \
  ipv4.gateway <GATEWAY> \
  ipv4.dns "<DNS1> <DNS2>" \
  ipv4.method manual

sudo nmcli con up "netplan-eth0"
```

---

## Pi-hole

Bloqueur de publicités et trackers au niveau DNS pour tout le réseau.

### Installation

Le fichier `docker-compose.yml` est dans le répertoire `pihole/` du dépôt.

```bash
cd ~/pidesk/pihole
```

> Remplacer `changeme` par le mot de passe souhaité pour l'interface web dans `docker-compose.yml`.

```bash
docker compose up -d
```

### Accès

Interface web : `http://<IP>/admin`

### Changer le mot de passe admin (Pi-hole v6)

```bash
docker exec -it pihole pihole setpassword
```

### Désactiver le TLS de Pi-hole

Pi-hole v6 active le TLS par défaut et écoute sur le port 443 sur toutes les interfaces. En `network_mode: host`, cela peut entrer en conflit avec d'autres services sur le port 443. Pour désactiver :

```bash
docker exec -it pihole pihole-FTL --config webserver.tls.cert ""
docker exec -it pihole pihole-FTL --config webserver.port "80o,[::]:80o"
docker restart pihole
```

> Les deux commandes sont nécessaires : supprimer le certificat **et** retirer le port 443 de l'écoute. Sans la seconde, Pi-hole tente de démarrer SSL sans certificat et le webserver ne se lance pas du tout.
> L'accès reste disponible en HTTP sur le port 80, ce qui est suffisant en réseau local.

### Configuration du routeur

Configurer le serveur DHCP du routeur pour distribuer l'IP du Pi comme seul serveur DNS (option DHCP 6). Ne pas ajouter de DNS secondaire, sinon les clients contournent Pi-hole aléatoirement.

### Résolution des hostnames `.lan` locaux

Pi-hole ne fait pas DHCP — c'est le routeur qui distribue les baux et connaît les hostnames clients. Sans config, Pi-hole renvoie `NXDOMAIN` pour tout `*.lan`. Pour déléguer la zone locale au routeur :

```bash
sudo cp ~/pidesk/pihole/dnsmasq.d/02-lan-forward.conf ~/pidesk/pihole/etc-dnsmasq.d/
sudo sed -i 's|<ROUTER_IP>|192.168.2.1|; s|<LAN_CIDR>|192.168.2.0/24|' \
  ~/pidesk/pihole/etc-dnsmasq.d/02-lan-forward.conf
```

Pi-hole v6 ignore `/etc/dnsmasq.d/` par défaut et se déclare autoritaire pour la zone `lan` (ce qui court-circuite le forward). Activer les deux toggles :

```bash
docker exec pihole pihole-FTL --config misc.etc_dnsmasq_d true
docker exec pihole pihole-FTL --config dns.domain.local false
docker restart pihole
```

> `misc.etc_dnsmasq_d=true` charge nos fichiers `02-*.conf`. `dns.domain.local=false` retire le `local=/lan/` implicite qui rendait Pi-hole autoritaire et bloquait le `server=/lan/...`.

Vérification :

```bash
dig @127.0.0.1 +short pidrive.lan        # → 192.168.2.246
dig @127.0.0.1 +short -x 192.168.2.246   # → pidrive.lan.
```

> **Côté Tailscale (accès tailnet)** : pour que `.lan` résolve aussi depuis les appareils du tailnet, ajouter un nameserver custom dans la [console Tailscale → DNS](https://login.tailscale.com/admin/dns) — *Add nameserver → Custom*, restreint au domaine `lan`, IP `192.168.2.10`.

### Commandes utiles

```bash
docker logs -f pihole                        # Logs
docker compose pull && docker compose up -d  # Mise à jour
docker exec pihole pihole status             # Status
docker exec pihole pihole -v                 # Version
```

---

## Unbound — résolveur DNS local (DoT)

Unbound reçoit les requêtes de Pi-hole, les met en cache, valide DNSSEC localement, et les forwarde en **DNS-over-TLS** (TCP/853) vers Quad9 et Cloudflare. Le DoT rend le trafic DNS indiscernable d'HTTPS : l'opérateur mobile ne peut plus ni lire ni casser le DNS (l'UDP/53 clair était parasité sur ce chemin — trous noirs sélectifs).

```
Client → Pi-hole (port 53, filtrage) → Unbound (port 5335, cache + DNSSEC) → Quad9 / Cloudflare (DoT, TCP 853)
```

### Installation

```bash
sudo apt update && sudo apt install -y unbound dns-root-data
```

Le paquet `dns-root-data` fournit et maintient à jour les root hints et la clé DNSSEC racine.

### Configuration

Si le module `subnetcache` est chargé par défaut (warnings au démarrage), le désactiver :

```bash
echo 'server:
    module-config: "validator iterator"' | sudo tee /etc/unbound/unbound.conf.d/modules.conf
```

Vérifier si `auto-trust-anchor-file` est déjà déclaré (Debian le fournit dans un fichier séparé) :

```bash
grep -r "auto-trust-anchor" /etc/unbound/
```

S'il existe déjà, ne pas le redéclarer dans la config ci-dessous.

Copier le fichier de configuration depuis le dépôt :

```bash
sudo cp ~/pidesk/unbound/pi-hole.conf /etc/unbound/unbound.conf.d/pi-hole.conf
```

### Démarrage

```bash
sudo unbound-checkconf
sudo systemctl restart unbound
sudo systemctl enable unbound
```

### Validation

```bash
# Installer dig si nécessaire
sudo apt install -y dnsutils

# Test de résolution (1ère requête ~500-1500ms, cache froid)
dig @127.0.0.1 -p 5335 example.com

# 2ème requête : devrait être 0ms (cache)
dig @127.0.0.1 -p 5335 example.com

# Vérifier DNSSEC : flag "ad" attendu dans la réponse
dig @127.0.0.1 -p 5335 cloudflare.com

# DNSSEC cassé volontairement : doit retourner SERVFAIL
dig @127.0.0.1 -p 5335 dnssec-failed.org

# Confirmer que le SERVFAIL vient bien de DNSSEC (+cd bypass la validation)
dig @127.0.0.1 -p 5335 +cd dnssec-failed.org
```

### Configurer Pi-hole

Dans **Pi-hole Admin → Settings → DNS** :

1. Décocher tous les upstream DNS préconfigurés (Google, Cloudflare, etc.)
2. Dans **Custom DNS (IPv4)** : `127.0.0.1#5335`
3. **Ne pas cocher** "Use DNSSEC" — c'est unbound qui gère la validation. Activer les deux provoque des faux positifs.

### Vérifier le DoT

```bash
# Doit montrer des sessions TLS établies vers 9.9.9.9 / 149.112.112.112 / 1.1.1.1
ss -tn state established '( dport = :853 )'
```

### Maintenance

```bash
# Statistiques du cache
sudo unbound-control stats_noreset

# Debug temporaire
sudo unbound-control verbosity 2
sudo journalctl -u unbound -f
sudo unbound-control verbosity 0

# Vider le cache d'un domaine
sudo unbound-control flush_zone example.com
```

> Pour utiliser `unbound-control`, activer le contrôle distant une fois :
> ```bash
> sudo unbound-control-setup
> echo 'remote-control:
>     control-enable: yes
>     control-interface: 127.0.0.1' | sudo tee /etc/unbound/unbound.conf.d/remote.conf
> sudo systemctl restart unbound
> ```

---

## Vaultwarden — gestionnaire de mots de passe

Serveur Bitwarden auto-hébergé, léger et compatible avec toutes les extensions navigateur et apps mobiles Bitwarden. L'accès distant est assuré par Tailscale (VPN mesh WireGuard) — seuls les appareils du tailnet peuvent atteindre le service.

### Prérequis

Tailscale installé et actif sur le Pi :

```bash
tailscale status   # doit afficher le hostname et l'IP Tailscale (100.x.x.x)
```

### Installation

Le fichier `docker-compose.yml` est dans le répertoire `vaultwarden/` du dépôt.

```bash
cd ~/pidesk/vaultwarden
```

> Remplacer `<TAILSCALE_FQDN>` par le FQDN Tailscale du Pi (ex. `pidesk.tailXXXXX.ts.net`) dans `docker-compose.yml`.

```bash
docker compose up -d
```

### HTTPS via Tailscale Serve

Tailscale Serve agit comme reverse proxy avec un certificat Let's Encrypt valide pour le domaine `*.ts.net`. Il termine le TLS et transfère en HTTP vers Vaultwarden sur le port 8222.

```bash
sudo tailscale serve --bg 8222
```

> Pour ne pas avoir besoin de `sudo` à chaque fois :
> ```bash
> sudo tailscale set --operator=$USER
> ```

Vérifier la configuration :

```bash
tailscale serve status
```

Pour désactiver :

```bash
tailscale serve --https=443 off
```

### Premier accès

Depuis un appareil connecté au même tailnet :

```
https://<TAILSCALE_FQDN>
```

Créer son compte, puis désactiver les inscriptions :

```bash
vi docker-compose.yml
# Changer SIGNUPS_ALLOWED: "true" → "false"
docker compose up -d
```

> Les données sont persistées dans `./data`, elles survivent à la recréation du conteneur.

### Extension navigateur / app mobile

Dans l'extension Bitwarden : paramètres → **Auto-hébergé** → URL du serveur : `https://<TAILSCALE_FQDN>`.

> L'appareil doit être connecté au tailnet pour accéder au coffre.

### Sécurité

- **Réseau** : Vaultwarden n'est accessible que via Tailscale — aucun port exposé sur Internet, pas de DNS public. Tailscale chiffre tout le trafic de bout en bout (WireGuard).
- **Chiffrement des données** : les données du coffre sont chiffrées côté client (AES-256) — même en cas de compromission du serveur, les mots de passe restent illisibles sans le master password.
- **Contrôle d'accès** : seuls les appareils autorisés dans le tailnet peuvent joindre le service. Gérer les appareils depuis la [console d'admin Tailscale](https://login.tailscale.com/admin/machines).

### Sauvegarde

La base SQLite `./data/db.sqlite3` contient tous les comptes et coffres chiffrés. Le script `backup.sh` effectue un backup safe (`sqlite3 .backup`) et l'envoie vers une machine distante via rsync.

```bash
# Adapter REMOTE_HOST et REMOTE_DIR dans backup.sh si nécessaire

# Test manuel
./backup.sh

# Cron (tous les jours à 3h)
crontab -e
0 3 * * * /home/alex/pidesk/vaultwarden/backup.sh
```

Le script conserve les 7 derniers backups sur la machine distante.

Le script logge dans syslog (tag `backup-vaultwarden`). Si `capteur-backup` (voir [vigie-capteurs](https://github.com/Alixpat/vigie-capteurs)) est installé sur le Pi, il détecte les succès/échecs et publie sur MQTT `vigie/backup/vaultwarden` → notification dans l'app Vigie.

Le PiDrive sert aussi de cible à la synchro quotidienne des documents du poste principal : `~/Documents/` → `pidrive:/media/pidrive/DOCS_SYNC/` (script `rsync-to-pidrive.sh` via cron, doc dans le dépôt `~/Documents/rsync`).

### Commandes utiles

```bash
docker logs -f vaultwarden                        # Logs
docker compose pull && docker compose up -d       # Mise à jour
docker compose restart                            # Redémarrer
```

---

## Mosquitto — broker MQTT

Broker MQTT léger utilisé comme hub central d'événements. Les services publient et s'abonnent à des topics pour communiquer de manière découplée (domotique, capteurs, automatisations).

```
Producteur → MQTT (port 1883) → Consommateur(s)
```

### Installation

Les fichiers de configuration (`mosquitto.conf`, `docker-compose.yml`) sont dans le répertoire `mosquitto/` du dépôt.

```bash
cd ~/pidesk/mosquitto
```

Créer le fichier de mots de passe et ajouter un utilisateur :

```bash
docker run --rm -v $(pwd)/config:/data eclipse-mosquitto:2 \
  mosquitto_passwd -c -b /data/passwd <USER> <PASSWORD>
```

Fixer les permissions pour l'utilisateur `mosquitto` du conteneur (UID 1883) :

```bash
sudo chown 1883:1883 config/passwd
chmod 600 config/passwd
```

> Remplacer `<USER>` et `<PASSWORD>` par les identifiants souhaités. Pour ajouter d'autres utilisateurs par la suite, retirer le flag `-c` (qui recrée le fichier) :
> ```bash
> docker run --rm -v $(pwd)/config:/data eclipse-mosquitto:2 \
>   mosquitto_passwd -b /data/passwd <USER2> <PASSWORD2>
> sudo chown 1883:1883 config/passwd
> ```

> **Important** : le fichier `passwd` doit exister **avant** de lancer le conteneur, sinon Mosquitto refuse de démarrer.

Démarrer le broker :

```bash
docker compose up -d
```

### Vérification

```bash
# Vérifier que le conteneur tourne
docker ps | grep mosquitto

# Logs du broker
docker logs -f mosquitto
```

### Test pub/sub

Installer le client MQTT sur le Pi (ou une autre machine) :

```bash
sudo apt install -y mosquitto-clients
```

Dans un premier terminal, s'abonner à un topic :

```bash
mosquitto_sub -h localhost -p 1883 -u <USER> -P <PASSWORD> -t "test/hello"
```

Dans un second terminal, publier un message :

```bash
mosquitto_pub -h localhost -p 1883 -u <USER> -P <PASSWORD> -t "test/hello" -m "Bonjour MQTT"
```

Le message `Bonjour MQTT` doit apparaître dans le premier terminal.

### Commandes utiles

```bash
docker logs -f mosquitto                        # Logs
docker compose pull && docker compose up -d     # Mise à jour
docker compose restart                          # Redémarrer
```

---

## TTN Bridge — relais LoRaWAN

Service Python (paho-mqtt + systemd) qui relaye The Things Stack Community
(cluster `eu1`) ⇄ Mosquitto local : uplinks LoRaWAN exposés sur le LAN,
downlinks publiables depuis le LAN. Le code est dans le répertoire
[`ttn-bridge/`](ttn-bridge/) du dépôt.

> Pourquoi un service Python plutôt que la directive `connection ttn-eu1`
> du bridge mosquitto natif ? Le bridge mosquitto a été rejeté par TTN à
> partir du 2026-05-09 avec « unacceptable protocol version » (mqttv311) ou
> disconnect silencieux (mqttv50), sur les versions 2.0.22 ET 2.1.2, alors
> que `mosquitto_pub`/`_sub` du même conteneur passent avec les mêmes
> credentials. Le fichier `mosquitto/config/conf.d/ttn-bridge.conf` est
> renommé en `.disabled` sur le Pi (gitignored).

Topics après installation :

| Sens | Topic local | Topic TTN distant |
|---|---|---|
| TTN → local | `ttn/devices/<dev>/up` | `v3/<app>@<tenant>/devices/<dev>/up` |
| TTN → local | `ttn/devices/<dev>/{join,down/queued,sent,ack,nack,failed}` | idem |
| local → TTN | `ttn/devices/<dev>/down/{push,replace}` | idem |

### Installation

1. Console TTN → application → *Integrations → MQTT → Generate new API key*.
   Copier la clé (`NNSXS.…`) et le username (`<app>@<tenant>`).
2. Sur le Pi :
   ```bash
   cd ~/pidesk/ttn-bridge
   cp config.json.example config.json
   # éditer config.json : remplacer <TTN_APPLICATION_ID>, <API_KEY>,
   # <MQTT_USER>, <MQTT_PASSWORD>
   sudo bash install.sh
   ```
   `install.sh` crée le venv, installe `paho-mqtt`, copie `config.json` vers
   `/etc/ttn-bridge/`, génère le service systemd et l'active.

### Vérification

```bash
systemctl status ttn-bridge          # doit être active (running)
journalctl -u ttn-bridge -f          # logs : doit montrer "TTN connecté" + 7 subscribes

# Voir les uplinks arriver (déclencher le device, ou attendre) :
mosquitto_sub -h localhost -u <USER> -P <PASS> -t 'ttn/#' -v

# Tester un downlink :
mosquitto_pub -h localhost -u <USER> -P <PASS> \
  -t 'ttn/devices/<dev>/down/push' \
  -m '{"downlinks":[{"f_port":10,"frm_payload":"aGVsbG8=","priority":"NORMAL"}]}'
```

> Le fichier `ttn-bridge/config.json` (avec la clé) est gitignoré ; seul
> `config.json.example` est versionné.

---

## Zigbee2MQTT — passerelle Zigbee↔MQTT

Zigbee2MQTT utilise la clé RasPBee 2 pour piloter les appareils Zigbee via MQTT, sans dépendre du cloud. Les appareils publient leur état sur des topics MQTT consommés par d'autres services (automatisations, dashboards, etc.).

```
Appareil Zigbee → RasPBee 2 → Zigbee2MQTT → MQTT (Mosquitto) → Consommateur(s)
```

### Prérequis

- Mosquitto opérationnel (voir section précédente)
- RasPBee 2 connecté et accessible sur `/dev/ttyAMA0`
- Désactiver le Bluetooth intégré pour libérer le port série :

```bash
echo "dtoverlay=disable-bt" | sudo tee -a /boot/firmware/config.txt
sudo systemctl disable hciuart
sudo reboot
```

### Installation

Le fichier `docker-compose.yml` est dans le répertoire `zigbee2mqtt/` du dépôt.

```bash
cd ~/pidesk/zigbee2mqtt
```

Copier le fichier de configuration template et l'adapter :

```bash
cp configuration.yaml data/configuration.yaml
vi data/configuration.yaml
```

> Remplacer `<PI_IP>`, `<MQTT_USER>` et `<MQTT_PASSWORD>` par les valeurs réelles. La `network_key` sera générée automatiquement au premier démarrage si laissée à `GENERATE`.

```bash
docker compose up -d
```

### Vérification

```bash
# Vérifier que le conteneur tourne
docker ps | grep zigbee2mqtt

# Logs (doit afficher "Zigbee2MQTT started!")
docker logs -f zigbee2mqtt
```

### Appairer un appareil

Activer temporairement le mode appairage :

```bash
mosquitto_pub -h localhost -p 1883 -u <USER> -P <PASSWORD> \
  -t "zigbee2mqtt/bridge/request/permit_join" -m '{"value": true, "time": 120}'
```

Mettre l'appareil Zigbee en mode appairage (selon la doc du fabricant). Zigbee2MQTT publiera un message sur `zigbee2mqtt/bridge/event` quand l'appareil sera détecté.

### Commandes utiles

```bash
docker logs -f zigbee2mqtt                        # Logs
docker compose pull && docker compose up -d       # Mise à jour
docker compose restart                            # Redémarrer
```

---

## wstunnel — SSH via WebSocket (test, arrêté)

> **Statut : expérimentation, non déployée en permanence.** Le compose est
> versionné mais les conteneurs sont arrêtés (`docker compose down`).
>
> **Fonctionne** pour joindre le SSH du Pi malgré la 4G (CGNAT), y compris à
> travers un proxy HTTP « classique » (CONNECT sans déchiffrement).
> **Ne passe PAS** un proxy à inspection TLS (déchiffrement) : celui-ci casse
> l'upgrade WebSocket. Le transport HTTP/2 de wstunnel (`https://`) et le
> polling HTTP de gost (PHT) ont été essayés comme alternatives — aucun ne
> traverse ce type de proxy (ni le Quick Tunnel Cloudflare, qui met en
> tampon les réponses longues). Cf. [Recherche d'un contournement](#pas-de-contournement-simple-du-proxy-à-inspection-tls).

Objectif : joindre le SSH du Pi depuis un réseau restrictif (proxy HTTP
d'entreprise, seul le 443 sortant autorisé) alors que le Pi est derrière
une clé 4G (CGNAT : pas d'IP publique, aucun port entrant possible).

```
client wstunnel ─(proxy CONNECT)─▶ Cloudflare (wss://…trycloudflare.com:443)
  ─▶ cloudflared (Pi) ─▶ wstunnel server 127.0.0.1:8081 ─▶ localhost:22
```

- **Quick Tunnel Cloudflare** : gratuit, sans compte ni domaine, mais l'URL
  `*.trycloudflare.com` change à chaque redémarrage de `wstunnel-tunnel`.
- **Serveur restreint** : `--restrict-to localhost:22` (sinon proxy ouvert
  sur internet) et préfixe de chemin secret
  (`WSTUNNEL_RESTRICT_HTTP_UPGRADE_PATH_PREFIX` dans `wstunnel/.env`,
  gitignoré — seul `.env.example` est versionné). Un client sans le bon
  secret reçoit un HTTP 400.

### Lancement (Pi)

```bash
cd ~/pidesk/wstunnel
cp .env.example .env
sed -i "s/<SECRET>/$(openssl rand -hex 16)/" .env && chmod 600 .env
docker compose up -d
docker logs wstunnel-tunnel 2>&1 | grep trycloudflare   # URL publique
```

### Client (image Docker)

Image : `ghcr.io/erebe/wstunnel` (amd64 + arm64). Le binaire n'est pas dans
le `PATH` : appeler `/home/app/wstunnel` (le `CMD` par défaut lance un serveur).

```bash
docker run -d --name wstunnel-client -p 127.0.0.1:2222:2222 \
  ghcr.io/erebe/wstunnel:v11.0.0 \
  /home/app/wstunnel client \
    -L tcp://0.0.0.0:2222:localhost:22 \
    -P <SECRET> \
    --http-proxy <PROXY>:<PORT> \
    wss://<URL>.trycloudflare.com

ssh -p 2222 <USER>@localhost
```

`--http-proxy` est optionnel (`user:pass@host:port` si le proxy est
authentifié).

### Tests validés

| Test | Résultat |
|---|---|
| Client direct, bon secret | Session SSH OK sur `pidesk` |
| Client direct, mauvais secret | Refusé (HTTP 400) |
| Client dans un réseau Docker `--internal` (sans accès internet), sortie uniquement via un Squid en `CONNECT` (sans déchiffrement) | Session SSH OK ; Squid log `CONNECT …trycloudflare.com:443 TCP_TUNNEL/200` |
| Client derrière un proxy à **inspection TLS** | ❌ échec : l'upgrade WebSocket est cassé, le serveur reçoit un GET simple (`Invalid protocol version request`) |

### Pas de contournement simple du proxy à inspection TLS

Un proxy qui déchiffre le TLS voit (et casse) le HTTP en clair. Les pistes
testées, toutes infructueuses **à travers le Quick Tunnel Cloudflare** :

- **wstunnel en HTTP/2 streaming** (`https://` + `cloudflared --http2-origin`) :
  la périphérie Cloudflare rejette le flux bidirectionnel (`stream error`,
  rien n'atteint le serveur). Seuls WebSocket et gRPC sont relayés en flux.
- **gost PHT** (polling HTTP, image `gogost/gost`) : le `POST`/push passe, mais
  la réponse `GET`/pull reste une réponse longue tenue ouverte — Cloudflare en
  renvoie l'en-tête puis retient les données. Même blocage qu'un proxy à
  inspection TLS, qui bufferise ce genre de réponse.

Conclusion : contre un proxy à inspection TLS, il faudrait un transport où
**chaque réponse est courte et se termine** (au prix de la latence). C'est
exactement ce que fait **pollux** (section suivante). Un tunnel nommé sur un
domaine perso (au lieu du Quick Tunnel) reste à essayer et donnerait au passage
une URL fixe.

---

## pollux — SSH via requêtes HTTP courtes

Même objectif que wstunnel (SSH du Pi malgré le CGNAT 4G), mais un transport qui
passe là où wstunnel échoue : chaque échange est une **requête/réponse HTTP
courte et complète** (`Content-Length` fixe, pas de flux), donc traverse un CDN
ou un proxy qui met en tampon. Dépôt : `Alixpat/pollux`.

```
client pollux ─(proxy)─▶ Cloudflare (https://…trycloudflare.com/t)
  ─▶ cloudflared (Pi) ─▶ pollux server 127.0.0.1:8081 ─▶ localhost:22
```

- **Testé OK à travers le Quick Tunnel Cloudflare** : bannière + handshake SSH
  complet (~4 s), là où wstunnel/gost sont bufferisés.
- Débit plafonné par le RTT (un aller-retour par lot) : bon pour SSH interactif,
  pas pour du transfert.
- **Sécurité** : `--allow 127.0.0.1:22` (cible unique) et jeton partagé
  `POLLUX_TOKEN` (en-tête `X-Pollux-Token`, sinon HTTP 403). `pollux/.env` est
  gitignoré, seul `.env.example` est versionné.
- Comme wstunnel, l'URL `*.trycloudflare.com` change à chaque redémarrage de
  `pollux-tunnel`.

### Lancement (Pi)

Le dépôt pollux est **privé** : le cloner sur le Pi demande un accès GitHub. À
défaut, pousser la source depuis le poste (le build ne prend que les `.py` +
`requirements.txt` + `Dockerfile`) :

```bash
# option A — clone (Pi authentifié sur GitHub)
git clone git@github.com:Alixpat/pollux.git ~/pollux
# option B — depuis le poste
rsync -a --exclude .venv --exclude .git ~/Documents/pollux/ pidesk:~/pollux/

cd ~/pidesk/pollux
cp .env.example .env
sed -i "s/<SECRET>/$(openssl rand -hex 16)/" .env && chmod 600 .env
docker compose up -d --build   # construit l'image depuis ~/pollux, lance server + tunnel
docker logs pollux-tunnel 2>&1 | grep trycloudflare   # URL publique
```

### Client

Image `pollux:local` (construite sur le Pi) ou le dépôt en local. Le jeton doit
correspondre à celui du `.env` serveur.

```bash
POLLUX_TOKEN=<SECRET> python tunnel_client.py \
  --listen-port 2223 --target 127.0.0.1:22 \
  --server https://<URL>.trycloudflare.com/t \
  [--proxy http://<PROXY>:<PORT>]

ssh -p 2223 -o StrictHostKeyChecking=accept-new <USER>@127.0.0.1
```

### Tests validés

| Test | Résultat |
|---|---|
| Bannière + handshake SSH via Quick Tunnel Cloudflare | OK (~4 s) |
| Sans jeton / mauvais jeton | Refusé (HTTP 403) |
| Cible hors `--allow` | Refusée (`forbidden`) |
| Proxy bufferisant / défaillant (réponses perdues, 502, rejeu) | OK, sans perte (suite pytest) |

---

## Prochaines étapes

- [ ] Restreindre Mosquitto sur localhost (`127.0.0.1:1883`)
- [ ] Renforcer le mot de passe MQTT
