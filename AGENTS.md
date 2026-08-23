# AGENTS.md

Compact guidance for OpenCode (and similar) working in this repo. Derived from CLAUDE.md + verified executable sources (README, compose, configs, scripts).

## Nature du dépôt
- **Config & docs only** for Raspberry Pi 3B `pidesk` (home services). No application code, no builds, no tests, no lint, no typecheck, no package.json/cargo/etc.
- Subdirs = one service each (`pihole/`, `unbound/`, `vaultwarden/`, `mosquitto/`, `zigbee2mqtt/`, `ttn-bridge/`).
- Repo clone lives on dev machine (`~/Documents/pidesk`). **All run/apply happens via SSH or Tailscale on the Pi** (`192.168.2.10` or `*.taile766ec.ts.net`). Never run docker compose or services locally.
- Documentation, commit messages, and notes in **French**.
- See `CLAUDE.md` (core architecture) and `README.md` (step-by-step install + commands) for full procedures.

## Placeholders & secrets (critical)
- Versioned files use placeholders only: `<TAILSCALE_FQDN>`, `<USER>`, `<PASSWORD>`, `<MQTT_USER>`, `<MQTT_PASSWORD>`, `<PI_IP>`, `<BACKUP_HOST>`, `<BACKUP_DIR>`, `<TTN_*>` etc.
- Never commit real values, passwords, keys, or FQDNs.
- Gitignored on Pi (and here via .gitignore):
  - `vaultwarden/data/`, `pihole/etc-*`, `zigbee2mqtt/data/`
  - `mosquitto/config/passwd`, `mosquitto/config/conf.d/*.conf` (except .example)
  - `ttn-bridge/config.json`, `ttn-bridge/venv/`, `__pycache__/`

## Service architecture & wiring (non-obvious)
- **DNS chain** (enforced via router DHCP option 6 = single DNS): `client → Pi-hole:53 (filter) → Unbound:5335 (cache + local DNSSEC validation) → Quad9/Cloudflare via DoT (TCP 853)`. Secondary DNS would bypass Pi-hole.
- `pihole/`: Docker, `network_mode: host`. TLS disabled manually (see README) to free 443. v6-specific: `pihole-FTL --config ...` + restart; `misc.etc_dnsmasq_d=true` + `dns.domain.local=false` for .lan forwarding.
- `unbound/`: **Not Docker**. systemd on host. Copy `unbound/pi-hole.conf` → `/etc/unbound/unbound.conf.d/`. Forwards via DoT (TCP 853) because the mobile network interferes with plain UDP/53; still validates DNSSEC locally. Small caches (8m/16m/8m) to avoid OOM on 905 MiB Pi 3B. `num-threads: 4` (4-core Pi 3B). `tls-cert-bundle` must be set explicitly or TLS verification of forwarders fails under systemd.
- `vaultwarden/`: Exposed **only** via `tailscale serve --bg 8222` (no public ports). `DOMAIN` = Tailscale FQDN. Backup via `backup.sh` (sqlite3 .backup + rsync, 7-day retention, syslog tag `backup-vaultwarden` for vigie monitoring).
- `mosquitto/`: Auth via `config/passwd` (must exist **before** first `up`, else container refuses start). Owned by UID 1883. Version **pinned** `eclipse-mosquitto:2.1.2-alpine` (PBKDF2 hashes; downgrade to 2.0 or upgrade breaks all clients incl. vigie-capteurs).
- `zigbee2mqtt/`: `network_mode: host`, `/dev/ttyAMA0` (RasPBee 2). Requires `dtoverlay=disable-bt` + disable hciuart in `/boot/firmware/config.txt` + reboot (to free UART from BT).
- `ttn-bridge/`: Python (paho-mqtt) + systemd service. Relays TTN eu1 ⇄ local Mosquitto. **Replaces** the native mosquitto bridge (ttn-bridge.conf.example kept for ref; real .conf is gitignored + was disabled 2026-05-09 due to "unacceptable protocol version"). Uplinks on `ttn/devices/<dev>/up` etc.; downlinks push on `ttn/devices/<dev>/down/push`.
- Dependencies: Mosquitto before Zigbee2MQTT / TTN-bridge / any MQTT clients. Unbound before full Pi-hole DNS.

## Commands & workflows (exact, non-obvious)
- Edit here → apply on Pi via SSH (copy files, `docker compose` in service dir, `systemctl` for unbound/ttn, etc.). Follow per-service sections in `README.md`.
- Mosquitto passwd (before any up):
  ```bash
  docker run --rm -v $(pwd)/config:/data eclipse-mosquitto:2 \
    mosquitto_passwd -c -b /data/passwd <USER> <PASSWORD>
  sudo chown 1883:1883 config/passwd && chmod 600 config/passwd
  ```
- Pi-hole TLS disable (v6, host mode):
  ```bash
  docker exec -it pihole pihole-FTL --config webserver.tls.cert ""
  docker exec -it pihole pihole-FTL --config webserver.port "80o,[::]:80o"
  docker restart pihole
  ```
- Unbound (on Pi host):
  ```bash
  sudo cp .../unbound/pi-hole.conf /etc/unbound/unbound.conf.d/pi-hole.conf
  sudo unbound-checkconf && sudo systemctl restart unbound
  ```
- Tailscale for vault: `sudo tailscale serve --bg 8222`; verify `tailscale serve status`.
- Zigbee pre-req: edit `/boot/firmware/config.txt`, `sudo systemctl disable hciuart`, reboot.
- TTN install: `cp config.json.example config.json`, edit, `sudo bash install.sh` (creates venv + systemd).
- Common: `docker compose up -d`, `docker compose pull && docker compose up -d`, `docker logs -f <svc>`, `docker compose restart`.
- No local equivalents. Use `ssh <user>@pidesk...` or Tailscale for everything.

## Conventions
- When documenting non-obvious config (e.g. `unbound/pi-hole.conf` `num-threads`, `pihole/dnsmasq.d/03-...`), keep a **concise** comment explaining *why*. No dated history in files — that's git's job.
- Keep .example for secrets/templates; real files gitignored.
- Ecosystem note: Mosquitto is shared with `vigie-capteurs` (publishes `vigie/*`) and Android `vigie` app. Changes to auth/ports/topics impact them—verify first.
- Prefer executable sources (compose, .conf, scripts, README steps) over prose when they conflict.

## What to avoid
- Running docker/systemd commands locally.
- Assuming standard Docker networking or default versions.
- Committing generated data, passwds, or filled config.json.
- Using native mosquitto TTN bridge (use Python service).
- Adding secondary DNS or enabling Pi-hole DNSSEC (Unbound handles it).
- Large cache increases in unbound (OOM risk).

See `README.md` for full install order, validation commands, and troubleshooting. See `CLAUDE.md` for architecture summary.
