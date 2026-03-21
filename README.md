# pidesk

Raspberry Pi 3B de bureau — plateforme de services domestiques.

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

### 4. IP statique

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

```bash
mkdir -p ~/pidesk/pihole && cd ~/pidesk/pihole
```

Créer `docker-compose.yml` :

```yaml
services:
  pihole:
    container_name: pihole
    image: pihole/pihole:latest
    network_mode: host
    environment:
      TZ: 'Europe/Paris'
      WEBPASSWORD: 'changeme'
      FTLCONF_dns_listeningMode: 'all'
    volumes:
      - ./etc-pihole:/etc/pihole
      - ./etc-dnsmasq.d:/etc/dnsmasq.d
    restart: unless-stopped
```

> Remplacer `changeme` par le mot de passe souhaité pour l'interface web.

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

### Commandes utiles

```bash
docker logs -f pihole                        # Logs
docker compose pull && docker compose up -d  # Mise à jour
docker exec pihole pihole status             # Status
docker exec pihole pihole -v                 # Version
```

---

## Unbound — résolveur DNS récursif local

Unbound résout les requêtes DNS directement auprès des serveurs autoritaires (racine → TLD → domaine) sans passer par un intermédiaire (Cloudflare, Google, etc.). Couplé à Pi-hole, il offre filtrage publicitaire + résolution privée.

```
Client → Pi-hole (port 53, filtrage) → Unbound (port 5335, récursion) → Serveurs autoritaires
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

Créer `/etc/unbound/unbound.conf.d/pi-hole.conf` :

```ini
server:
    # ---- Interface et port ----
    # Écoute uniquement sur localhost, seul Pi-hole peut l'interroger
    interface: 127.0.0.1
    # Port 5335 pour ne pas entrer en conflit avec Pi-hole (port 53)
    port: 5335
    do-ip4: yes
    do-ip6: no
    do-udp: yes
    do-tcp: yes

    # ---- Contrôle d'accès ----
    access-control: 127.0.0.0/8 allow
    access-control: 0.0.0.0/0 refuse

    # ---- Sécurité ----
    # Refuse les glue records hors zone (anti-redirection)
    harden-glue: yes
    # Refuse les réponses dont la signature DNSSEC a été retirée
    harden-dnssec-stripped: yes
    # Vérifie la cohérence du chemin de délégation
    harden-referral-path: yes
    # Refuse les downgrades d'algorithme DNSSEC
    harden-algo-downgrade: yes
    # Applique le statut NXDOMAIN aux sous-domaines (RFC 8020)
    harden-below-nxdomain: yes
    # Randomise la casse des requêtes (0x20 encoding, anti-spoofing)
    use-caps-for-id: yes

    # ---- Vie privée ----
    # Cache l'identité et la version du serveur aux requêtes CHAOS TXT
    hide-identity: yes
    hide-version: yes
    # QNAME minimisation (RFC 7816) : n'envoie que le minimum nécessaire
    # à chaque niveau de la hiérarchie DNS
    #   racine → ne voit que ".fr"
    #   TLD    → ne voit que "example.fr"
    #   auth   → voit "www.example.fr"
    qname-minimisation: yes
    # N'inclut pas les sections additionnelles inutiles
    minimal-responses: yes

    # ---- Cache et performance ----
    num-threads: 1
    msg-cache-size: 64m
    # Règle : rrset-cache = 2x msg-cache
    rrset-cache-size: 128m
    # TTL minimum 5 min (ignore les TTL très courts des CDN/pubs)
    cache-min-ttl: 300
    cache-max-ttl: 86400
    # Renouvelle les entrées populaires avant expiration → 0ms pour les
    # domaines fréquents
    prefetch: yes
    prefetch-key: yes
    # Sert une réponse expirée pendant la re-résolution en arrière-plan
    # → résilience si un serveur autoritaire est down
    serve-expired: yes
    serve-expired-ttl: 86400

    # ---- Protection DNS rebinding ----
    # Refuse les réponses pointant vers des IP privées pour un domaine public
    private-address: 192.168.0.0/16
    private-address: 172.16.0.0/12
    private-address: 10.0.0.0/8
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

### Vérifier qu'aucun tiers n'est contacté

```bash
# Ne doit montrer aucun trafic vers des résolveurs tiers
sudo tcpdump -i eth0 port 53 -n | grep -E '1.1.1.1|8.8.8.8|9.9.9.9'
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

Serveur Bitwarden auto-hébergé, léger et compatible avec toutes les extensions navigateur et apps mobiles Bitwarden. L'accès distant est assuré par un tunnel Cloudflare (voir section suivante).

### Installation

```bash
mkdir -p ~/pidesk/vaultwarden && cd ~/pidesk/vaultwarden
```

Créer `docker-compose.yml` :

```yaml
services:
  vaultwarden:
    container_name: vaultwarden
    image: vaultwarden/server:latest
    environment:
      TZ: Europe/Paris
      DOMAIN: https://<SUBDOMAIN>.<DOMAIN>
      SIGNUPS_ALLOWED: "true"
      INVITATIONS_ALLOWED: "false"
      SHOW_PASSWORD_HINT: "false"
      PASSWORD_HINTS_ALLOWED: "false"
    volumes:
      - ./data:/data
    restart: unless-stopped

  cloudflared:
    container_name: cloudflared
    image: cloudflare/cloudflared:latest
    command: tunnel run
    environment:
      TUNNEL_TOKEN: "<TUNNEL_TOKEN>"
    restart: unless-stopped
    depends_on:
      - vaultwarden
```

> Remplacer `<SUBDOMAIN>.<DOMAIN>` par le FQDN choisi (ex. `vault.example.fr`) et `<TUNNEL_TOKEN>` par le token du tunnel Cloudflare.

```bash
docker compose up -d
```

### Configuration du tunnel Cloudflare

1. Se connecter au [dashboard Cloudflare Zero Trust](https://one.dash.cloudflare.com/)
2. **Networks → Tunnels → Create a tunnel**
3. Choisir **Cloudflared** comme type de connecteur
4. Nommer le tunnel (ex. `pidesk-vaultwarden`)
5. Copier le token affiché → le reporter dans `<TUNNEL_TOKEN>` du compose
6. Ajouter un **Public Hostname** :
   - **Subdomain** : `vault` (ou autre)
   - **Domain** : sélectionner le domaine géré dans Cloudflare
   - **Service** : `HTTP` — `vaultwarden:80`

> Pas besoin de certificat auto-signé ni de TLS côté Vaultwarden : Cloudflare termine le TLS avec un certificat Let's Encrypt valide sur le domaine. Le trafic entre `cloudflared` et `vaultwarden` reste en HTTP sur le réseau Docker interne.

### Premier accès

Aller sur `https://<SUBDOMAIN>.<DOMAIN>` et créer son compte.

### Sécurisation post-installation

Une fois le compte créé, désactiver les inscriptions :

```bash
cd ~/pidesk/vaultwarden
vi docker-compose.yml
# Changer SIGNUPS_ALLOWED: "true" → "false"
docker compose up -d
```

> Les données sont persistées dans `./data`, elles survivent à la recréation du conteneur.

### Accès LAN direct (optionnel)

Pour accéder à Vaultwarden sans passer par le tunnel (ex. en cas de coupure Internet) :

```yaml
services:
  vaultwarden:
    # ... (config existante)
    ports:
      - "8222:80"
```

Accès local : `http://<IP>:8222` (HTTP simple, pas de TLS nécessaire en LAN).

### Extension navigateur

Dans l'extension Bitwarden : paramètres → **Auto-hébergé** → URL du serveur : `https://<SUBDOMAIN>.<DOMAIN>`.

### Gestion du tunnel

```bash
# Logs du tunnel
docker logs -f cloudflared

# Vérifier l'état du tunnel dans le dashboard Cloudflare Zero Trust
# Networks → Tunnels → le tunnel doit être "Healthy"

# Redémarrer le tunnel
docker compose restart cloudflared
```

### Sécurisation Cloudflare

Le tunnel Cloudflare protège déjà contre l'exposition directe (aucun port ouvert sur la box, pas d'IP publique). Les données du coffre sont chiffrées côté client (AES-256) — même en cas de compromission du serveur, les mots de passe restent illisibles sans le master password.

Les règles suivantes ajoutent une protection supplémentaire au niveau de l'edge Cloudflare, avant que le trafic n'atteigne le Pi.

#### Security rules

Dans le dashboard Cloudflare du domaine : **Security → Security rules → Create rule**.

**Règle : `Block Non-FR`** — bloque tout le trafic provenant de l'extérieur de la France :

```
(http.host eq "<SUBDOMAIN>.<DOMAIN>") and (ip.geoip.country ne "FR")
```

Action : **Block**

> Si besoin d'accéder depuis l'étranger (voyage), désactiver temporairement cette règle dans le dashboard.

#### Rate limiting rules

Dans le dashboard Cloudflare du domaine : **Security → Security rules → Create rule** (onglet rate limiting).

**Règle : `Rate Limit Login`** — limite les tentatives de connexion (anti brute-force) sur l'endpoint d'authentification :

```
(http.host eq "<SUBDOMAIN>.<DOMAIN>") and (http.request.uri.path contains "/identity/connect/token")
```

Action : **Block**

> Le plan gratuit Cloudflare offre 1 rate limiting rule. L'endpoint `/identity/connect/token` est l'endpoint OAuth2 utilisé par tous les clients Bitwarden (extension, app mobile, web vault) pour l'authentification.

### Sauvegarde

La base SQLite `./data/db.sqlite3` contient tous les comptes et coffres chiffrés. Mettre en place une sauvegarde régulière :

```bash
# Créer le répertoire de backups
mkdir -p ~/pidesk/vaultwarden/backups

# Ajouter dans crontab -e
0 3 * * * cp ~/pidesk/vaultwarden/data/db.sqlite3 ~/pidesk/vaultwarden/backups/db-$(date +\%F).sqlite3
```

> Idéalement, synchroniser les backups vers une autre machine via rsync.

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

> Remplacer `<USER>` et `<PASSWORD>` par les identifiants souhaités. Pour ajouter d'autres utilisateurs par la suite, retirer le flag `-c` (qui recrée le fichier) :
> ```bash
> docker run --rm -v $(pwd)/config:/data eclipse-mosquitto:2 \
>   mosquitto_passwd -b /data/passwd <USER2> <PASSWORD2>
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

## Prochaines étapes

- [ ] Installation de deCONZ (Phoscon / RasPBee 2)
