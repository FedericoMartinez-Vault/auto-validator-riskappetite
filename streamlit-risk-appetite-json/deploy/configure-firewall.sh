#!/bin/bash
# Ejecutar EN LA VM (sesion SSH / Azure Virtual Desktop)
# Uso: bash deploy/configure-firewall.sh

set -eu

PORT=8502

echo "==> Host: $(hostname)"
echo "==> IPs:"
hostname -I || true

PUBLIC_IP=""
if command -v curl >/dev/null 2>&1; then
  PUBLIC_IP=$(curl -s -H Metadata:true \
    "http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text" \
    2>/dev/null || true)
fi
if [ -z "$PUBLIC_IP" ]; then
  echo "sin metadata publica"
else
  echo "IP publica: $PUBLIC_IP"
fi

echo ""
echo "==> Streamlit en puerto $PORT"
ss -tlnp | grep ":$PORT " || echo "ADVERTENCIA: nada escucha en $PORT. Arranca la app primero."

echo ""
echo "==> Configurando ufw"
sudo ufw allow OpenSSH
sudo ufw allow "${PORT}/tcp"
sudo ufw --force enable
sudo ufw status verbose

echo ""
echo "==> Prueba local HTTP"
HTTP_CODE="000"
if command -v curl >/dev/null 2>&1; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}/" || echo "000")
fi
echo "HTTP localhost:$PORT -> $HTTP_CODE"

PRIVATE_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "URLs para probar:"
echo "  http://${PRIVATE_IP}:${PORT}"
if [ -n "$PUBLIC_IP" ] && [ "$PUBLIC_IP" != "null" ]; then
  echo "  http://${PUBLIC_IP}:${PORT}"
  echo ""
  echo "Si la IP publica no responde desde fuera, abre el puerto $PORT en el NSG de Azure."
fi
