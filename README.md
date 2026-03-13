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
```

Lancer la GUI :

```bash
sudo rpi-imager
```

**Écran de sélection :**

1. **Modèle** : `Raspberry Pi 3`
2. **OS** : `Raspberry Pi OS (other)` → `Raspberry Pi OS Lite (64-bit)` (Bookworm)
3. **Stockage** : sélectionner la carte SD

**Personnalisation OS :**

| Paramètre | Valeur |
|---|---|
| Hostname | `pidesk` |
| Utilisateur | `alex` |
| Mot de passe | *(défini dans la GUI)* |
| WiFi SSID | `my_wifi` |
| WiFi password | *(défini dans la GUI)* |
| Pays WiFi | `FR` |
| Timezone | `Europe/Paris` |
| Clavier | `fr` (pc105) |
| SSH | Clé publique uniquement |
| Clé SSH | `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJc17WY4OZRwvyZoJG0KG7C5BBzIjRaV+LeQqnJMANu3 alex@latitude` |

Cliquer sur **Écrire**, attendre la fin du flash et de la vérification (~6 min).

### 2. Premier boot

Insérer la SD dans le Pi, brancher l'Ethernet, alimenter.

```bash
ssh alex@pidesk.local
```

> La connexion par mot de passe SSH est désactivée. Seule la clé `alex@latitude` est autorisée.

### 3. Mise à jour + Docker

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker alex
```

Se déconnecter/reconnecter pour appliquer le groupe `docker`.

### 4. IP statique

Vérifier le nom de la connexion :

```bash
nmcli con show
```

> Sur Bookworm avec cloud-init, la connexion Ethernet s'appelle `netplan-eth0`.

Fixer l'IP avec Cloudflare en DNS :

```bash
sudo nmcli con mod "netplan-eth0" \
  ipv4.addresses 192.168.2.10/24 \
  ipv4.gateway 192.168.2.1 \
  ipv4.dns "1.1.1.1 1.0.0.1" \
  ipv4.method manual

sudo nmcli con up "netplan-eth0"
```

Reconnecter SSH sur la nouvelle IP :

```bash
ssh alex@192.168.2.10
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

Lancer :

```bash
docker compose up -d
```

### Accès

Interface web : `http://192.168.2.10/admin`

### Changer le mot de passe admin (Pi-hole v6)

```bash
docker exec -it pihole pihole setpassword
```

### Configuration du routeur

Sur le routeur (OpenWrt), ajouter l'option DHCP suivante pour rediriger le DNS de tous les clients vers Pi-hole :

```
6,192.168.2.10
```

> Ne pas mettre le routeur en DNS secondaire (`6,192.168.2.10,192.168.2.1`), sinon les clients utilisent l'un ou l'autre aléatoirement et contournent Pi-hole.

Après sauvegarde, reconnecter les appareils ou attendre le renouvellement des baux DHCP.

### Commandes utiles

```bash
# Logs
docker logs -f pihole

# Mise à jour
docker compose pull && docker compose up -d

# Status
docker exec pihole pihole status

# Version
docker exec pihole pihole -v
```

---

## Prochaines étapes

- [ ] Installation de deCONZ (Phoscon / RasPBee 2)
- [ ] Unbound (résolveur DNS récursif local, optionnel)
