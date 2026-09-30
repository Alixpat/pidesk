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
2. **OS** : `Raspberry Pi OS (other)` → `Raspberry Pi OS Lite (64-bit)` (Trixie)
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

### Mises à jour

```bash
sudo apt update && sudo apt full-upgrade
sudo reboot            # si /var/run/reboot-required existe (nouveau kernel)
```

Les images sont figées : changer le tag dans le `docker-compose.yml` (dépôt et Pi),
sauvegarder les données du service, puis `docker compose pull && docker compose up -d`.
Ne pas changer celui de Mosquitto sans regénérer `passwd` (cf. [Mosquitto](#mosquitto--broker-mqtt)).
Ménage : `docker image prune -a && docker builder prune -a`.

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

> Avec cloud-init, la connexion Ethernet s'appelle `netplan-eth0`.

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

### Commandes utiles

```bash
docker logs -f vaultwarden                        # Logs
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
docker run --rm -v $(pwd)/config:/data eclipse-mosquitto:2.1.2-alpine \
  mosquitto_passwd -c -b /data/passwd <USER> <PASSWORD>
```

Fixer les permissions pour l'utilisateur `mosquitto` du conteneur (UID 1883) :

```bash
sudo chown 1883:1883 config/passwd
chmod 600 config/passwd
```

> Remplacer `<USER>` et `<PASSWORD>` par les identifiants souhaités. Pour ajouter d'autres utilisateurs par la suite, retirer le flag `-c` (qui recrée le fichier) :
> ```bash
> docker run --rm -v $(pwd)/config:/data eclipse-mosquitto:2.1.2-alpine \
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
docker compose restart                          # Redémarrer
```

---

## TTN Bridge — relais LoRaWAN

Service Python (paho-mqtt + systemd) qui relaye The Things Stack Community
(cluster `eu1`) ⇄ Mosquitto local : uplinks LoRaWAN exposés sur le LAN,
downlinks publiables depuis le LAN. Le code est dans le répertoire
[`ttn-bridge/`](ttn-bridge/) du dépôt.

> Le bridge natif de Mosquitto (`connection ttn-eu1`) est rejeté par TTN
> (« unacceptable protocol version ») : ne pas le réactiver.

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
docker compose restart                            # Redémarrer
```

---

## pollux — SSH via requêtes HTTP courtes

SSH et mosh du Pi malgré le CGNAT 4G : chaque échange est une **requête/réponse
HTTP courte et complète** (`Content-Length` fixe, pas de flux), donc traverse un
proxy qui met en tampon. Dépôt : `Alixpat/pollux`.

```
client pollux / navigateur ─(proxy)─▶ Tailscale Funnel (https://pollux.<TAILNET>.ts.net)
  ─▶ pollux-ts (Pi, nœud Tailscale dédié) ─▶ pollux 127.0.0.1:8081 ─▶ localhost:22
```

| Accès | Protection |
|---|---|
| Page web `/` (terminal SSH) | IP autorisée + compte Google (`web.env`) + jeton |
| `/t` (clients en ligne de commande, page) | IP autorisée + jeton |

- Débit ≈ fenêtre × lot / RTT (`POLLUX_WINDOW`, 8 requêtes en vol par défaut).
- **IP clientes** (`POLLUX_ALLOW_IP` dans `.env`) : lues dans `X-Forwarded-For`, que
  Funnel remplace par l'IP réelle (un en-tête forgé est écrasé ; vérifié). Liste
  générée chaque minute par `pollux-allow-ip` (rôle Ansible `pollux_allow_ip`) :
  `POLLUX_ALLOW_IP_FIXE` (IP hors de la maison, à éditer à la main) + l'IP publique
  actuelle de la maison (`allow-ip-auto`), que le Pi partage avec les appareils de la
  box 4G. Pollux n'est redémarré que si la liste change ; `pollux-ts` l'est à chaque
  nouvelle IP publique, sinon les relais Funnel coupent le TLS (le nom reste publié).
- **Jeton** `POLLUX_TOKEN` : signe requêtes et réponses sans jamais circuler (invisible
  même pour un proxy qui déchiffre le TLS). Changer le secret : `openssl rand -hex 32`
  dans le `.env` du Pi et des clients, puis redémarrer `pollux` et les clients.
- **Nœud dédié** : le 443 de `pidesk` sert Vaultwarden au seul tailnet et ne doit pas
  passer en Funnel. `pollux-ts` tourne en userspace (réseau de l'hôte, socket et port
  WireGuard distincts du tailscaled de l'hôte).
- `.env`, `web.env`, `ts.env` et `ts-state/` sont gitignorés ; seuls les `.example` sont versionnés.

### Lancement (Pi)

Le Pi ne compile rien (trop peu de RAM) : les artefacts sont construits sur le poste
puis poussés avec la source.

```bash
# sur le poste
cd ~/Documents/pollux && GOARCH=arm64 ./build.sh     # serveur arm64 + client web (WASM)
rsync -a --delete --exclude .venv --exclude .git ~/Documents/pollux/ pidesk:~/pollux/

# sur le Pi (première fois)
cd ~/pidesk/pollux
for f in .env web.env ts.env; do cp $f.example $f; done && chmod 600 .env web.env ts.env
sed -i "s/<SECRET>/$(openssl rand -hex 32)/" .env
$EDITOR .env web.env ts.env     # IP fixes, client Google, clé Tailscale (ci-dessous)
docker compose up -d --build    # build l'image depuis ~/pollux, lance pollux + pollux-ts
```

1. Console Tailscale > Settings > Keys : clé d'auth **sans tag**, non réutilisable,
   non éphémère → `ts.env` (lue au premier démarrage, état dans `ts-state/`). Funnel
   doit être autorisé aux membres (`nodeAttrs` `funnel` de la politique d'accès).
2. Console Tailscale > Machines > `pollux` : **Disable key expiry**.
3. Client OAuth Google « Application Web », redirection
   `https://pollux.<TAILNET>.ts.net/oidc/callback` → `web.env`.

L'enregistrement DNS public du nom Funnel peut mettre ~20 min à apparaître. Tailscale
le retire parfois alors que Funnel reste actif (NXDOMAIN, [#20892](https://github.com/tailscale/tailscale/issues/20892),
[#21429](https://github.com/tailscale/tailscale/issues/21429)) : un timer (rôle Ansible
`pollux_funnel_watch`, toutes les 5 min) interroge Google et Cloudflare en DoH et, si le
nom manque chez les deux, redémarre `pollux-ts` (republié en ~30 s) puis vide le cache
d'Unbound et de Pi-hole. 15 min au moins entre deux redémarrages ; rien si les résolveurs
sont injoignables.

```bash
cd ansible && ansible-playbook site.yml --tags pollux_funnel_watch
ssh pidesk 'journalctl -t pollux-funnel-watch'     # silencieux tant que le nom est publié
ansible-playbook site.yml --tags pollux_allow_ip
ssh pidesk 'journalctl -t pollux-allow-ip'         # « nouvelle IP publique … » à chaque changement
```

Mise à jour : `build.sh` + `rsync` ci-dessus, puis rebuild. Client et serveur doivent
parler la même version de protocole (sinon `CONNECT refusé: version`).

```bash
ssh pidesk 'cd ~/pidesk/pollux && docker compose up -d --build pollux'
docker logs pollux              # IP autorisées, « client web réservé (OIDC …) à : … »
docker exec pollux-ts tailscale --socket /var/lib/tailscale/tailscaled.sock funnel status
```

### Client

Client : le même exécutable `pollux` (rien à installer), copié avec un `.env` :

```bash
# exécutable pollux : release GitHub pour la plateforme, ou compilé sur le poste :
cd ~/Documents/pollux/go && GOOS=linux GOARCH=amd64 go build -o pollux ./cmd/pollux
cp ../client.env.example .env
# éditer : POLLUX_SERVER=https://pollux.<TAILNET>.ts.net/t
#          POLLUX_TOKEN=<= jeton du .env serveur>
#          POLLUX_PROXY=http://<PROXY>:<PORT>   (si proxy)
#          POLLUX_LISTEN_PORT=2223   POLLUX_TARGET=127.0.0.1:22
./pollux client --env .env                 # ou : ./pollux client install --env .env (service systemd)

ssh -p 2223 -o StrictHostKeyChecking=accept-new <USER>@127.0.0.1
```

mosh (paquet `mosh` installé sur le Pi et le client) : `POLLUX_UDP=60001-60004` dans le
`.env` client, puis `mosh --ssh="ssh -p 2223" --port=60001:60004 <USER>@127.0.0.1`
(une session mosh simultanée par port ; plage autorisée côté serveur par `--allow udp:…`).
Une session abandonnée sans `exit` garde son port : `mosh-server` s'arrête après 72 h
sans nouvelles du client (`MOSH_SERVER_NETWORK_TMOUT`, passé par sshd ; rôle Ansible
`mosh` : `cd ansible && ansible-playbook site.yml --tags mosh`). Le relais UDP de pollux
se referme après 60 s sans datagramme et se rouvre au suivant (mosh envoie des keepalives).

Proxy à inspection TLS : la machine cliente doit faire confiance à la CA du
proxy (sinon `SSLCertVerificationError`).

### Tests validés

| Test | Résultat |
|---|---|
| Bannière SSH via Tailscale Funnel (client en ligne de commande) | OK |
| Page `/` : connexion Google, puis terminal | OK |
| IP hors `POLLUX_ALLOW_IP` (page et `/t`) | Refusée (HTTP 403) |
| `X-Forwarded-For` forgé à travers Funnel | Écrasé par l'IP réelle |
| Sans jeton / mauvais jeton | Refusé (HTTP 403) |
| Cible hors `--allow` | Refusée (`forbidden`) |
| Serveur Go en production : SSH, 2 mosh simultanés, client web, 4 Mo aller-retour | OK (~130 ms d'écho, 6 Mo de RAM) |

---

## Prochaines étapes

- [ ] Restreindre Mosquitto sur localhost (`127.0.0.1:1883`)
- [ ] Renforcer le mot de passe MQTT
