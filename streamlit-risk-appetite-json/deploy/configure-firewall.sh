#!/bin/bash
set -eu
PORT=8502
echo "Host: $(hostname)"
echo "IPs: $(hostname -I)"
echo "Puerto: $PORT"
ss -tlnp | grep ":$PORT " || echo "Nada escucha en $PORT"
sudo ufw allow OpenSSH
sudo ufw allow ${PORT}/tcp
sudo ufw --force enable
sudo ufw status verbose
PRIVATE_IP=$(hostname -I | awk '{print $1}')
echo "Probar: http://${PRIVATE_IP}:${PORT}"
echo "Probar: http://20.228.231.195:${PORT}"
