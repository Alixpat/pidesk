#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
CONF_DIR="/etc/owntracks-archive"
DATA_DIR="/var/lib/owntracks-archive"

echo "Installation du owntracks-archive depuis : $DIR"

# Créer le venv si absent
if [ ! -d "$DIR/venv" ]; then
    echo "Création du venv..."
    python3 -m venv "$DIR/venv"
    "$DIR/venv/bin/pip" install -r "$DIR/requirements.txt"
fi

# Copier la config si elle n'existe pas
if [ ! -f "$CONF_DIR/config.json" ]; then
    echo "Copie de la configuration vers $CONF_DIR"
    mkdir -p "$CONF_DIR"
    cp "$DIR/config.json" "$CONF_DIR/config.json"
    chmod 600 "$CONF_DIR/config.json"
    echo "  → Pensez à éditer $CONF_DIR/config.json avec vos paramètres"
fi

# Dossier de la base SQLite
mkdir -p "$DATA_DIR"

# Générer le service avec le bon chemin
sed "s|__WORKING_DIR__|$DIR|g" "$DIR/owntracks-archive.service.template" \
    > /etc/systemd/system/owntracks-archive.service

systemctl daemon-reload
systemctl enable --now owntracks-archive

echo "Service owntracks-archive installé et démarré."
echo "  → Configuration : $CONF_DIR/config.json"
echo "  → Base : $DATA_DIR/positions.db"
echo "  → journalctl -u owntracks-archive -f"
