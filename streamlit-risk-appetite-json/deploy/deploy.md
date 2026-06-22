# Despliegue — Risk Appetite Streamlit en VM UAT

Guía paso a paso para desplegar `streamlit-risk-appetite-json` en la VM UAT.

| Dato | Valor |
|------|--------|
| VM | `10.72.64.196` |
| Usuario | `azureuser` |
| Puerto app | `8502` |
| URL | `http://10.72.64.196:8502` |
| Ruta en VM | `/home/azureuser/apps/streamlit-risk-appetite-json` |

> No subas `.env` ni claves `.pem` al repositorio.

---

## 0. Preparar la clave PEM en tu PC

En **PowerShell**, desde la raíz del repo:

```powershell
cd C:\Users\FedericoMartinez\Desktop\Repos\auto-validator-riskappetite

New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh\vault-keys" | Out-Null

Copy-Item -Force `
  "streamlit-risk-appetite-json\deploy\AI_UAT.pem.txt" `
  "$env:USERPROFILE\.ssh\vault-keys\AI_UAT.pem"

$KEY = "$env:USERPROFILE\.ssh\vault-keys\AI_UAT.pem"

icacls $KEY /inheritance:r
icacls $KEY /grant:r "$($env:USERNAME):(R)"
```

---

## 1. Conectar por SSH

```powershell
ssh -o StrictHostKeyChecking=accept-new azureuser@10.72.64.196 -i $KEY
```

Salir de la VM:

```bash
exit
```

---

## 2. Preparar la VM (primera vez)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git rsync
mkdir -p ~/apps

sudo ufw allow OpenSSH
sudo ufw allow 8502/tcp
sudo ufw --force enable
sudo ufw status
```

O ejecuta el script incluido (desde la carpeta del proyecto en la VM):

```bash
bash deploy/configure-firewall.sh
```

> `ufw inactive` solo afecta el firewall **local**. Para acceso **desde Internet** hace falta abrir el puerto **8502** en el **NSG de Azure** (ver sección 10).

---

## 3. Copiar el proyecto desde tu PC a la VM

En **PowerShell**:

```powershell
cd C:\Users\FedericoMartinez\Desktop\Repos\auto-validator-riskappetite
$KEY = "$env:USERPROFILE\.ssh\vault-keys\AI_UAT.pem"

scp -i $KEY -r `
  streamlit-risk-appetite-json\app.py `
  streamlit-risk-appetite-json\requirements.txt `
  streamlit-risk-appetite-json\README.md `
  streamlit-risk-appetite-json\src `
  streamlit-risk-appetite-json\scripts `
  streamlit-risk-appetite-json\.env.example `
  azureuser@10.72.64.196:/home/azureuser/apps/streamlit-risk-appetite-json/
```

Si la carpeta destino no existe:

```bash
mkdir -p ~/apps/streamlit-risk-appetite-json
```

---

## 4. Configurar entorno en la VM

```bash
cd ~/apps/streamlit-risk-appetite-json

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Configurar `.env`

```bash
cd ~/apps/streamlit-risk-appetite-json
cp .env.example .env
nano .env
```

Ejemplo:

```env
FOUNDRY_PROJECT_ENDPOINT=https://azr-dev-foundry-af-1617.services.ai.azure.com/api/projects/azr-dev-proj-af-1617
FOUNDRY_AGENT_NAME=AF-UW-RiskApetite
USE_AZURE_CLI_AUTH=false

AZURE_TENANT_ID=<tu-tenant-id>
AZURE_CLIENT_ID=<tu-client-id>
AZURE_CLIENT_SECRET=<tu-client-secret>
```

```bash
chmod 600 .env
```

---

## 6. Prueba manual

```bash
cd ~/apps/streamlit-risk-appetite-json
source .venv/bin/activate
streamlit run app.py --server.port 8502 --server.address 0.0.0.0 --server.headless true
```

Abre en el navegador:

```
http://10.72.64.196:8502
```

Detén con `Ctrl+C` y continúa con el servicio systemd.

---

## 7. Servicio systemd (arranque automático)

```bash
sudo nano /etc/systemd/system/risk-appetite-streamlit.service
```

Contenido:

```ini
[Unit]
Description=Risk Appetite Streamlit (Metal JSON Intake)
After=network.target

[Service]
Type=simple
User=azureuser
Group=azureuser
WorkingDirectory=/home/azureuser/apps/streamlit-risk-appetite-json
EnvironmentFile=/home/azureuser/apps/streamlit-risk-appetite-json/.env
ExecStart=/home/azureuser/apps/streamlit-risk-appetite-json/.venv/bin/streamlit run app.py --server.port 8502 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable risk-appetite-streamlit
sudo systemctl start risk-appetite-streamlit
sudo systemctl status risk-appetite-streamlit
```

Logs:

```bash
journalctl -u risk-appetite-streamlit -f
```

---

## 8. Actualizar la app (re-deploy)

En tu PC:

```powershell
cd C:\Users\FedericoMartinez\Desktop\Repos\auto-validator-riskappetite
$KEY = "$env:USERPROFILE\.ssh\vault-keys\AI_UAT.pem"

scp -i $KEY -r `
  streamlit-risk-appetite-json\app.py `
  streamlit-risk-appetite-json\requirements.txt `
  streamlit-risk-appetite-json\src `
  streamlit-risk-appetite-json\scripts `
  azureuser@10.72.64.196:/home/azureuser/apps/streamlit-risk-appetite-json/
```

En la VM:

```bash
cd ~/apps/streamlit-risk-appetite-json
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart risk-appetite-streamlit
sudo systemctl status risk-appetite-streamlit
```

---

## 9. Comandos útiles

| Acción | Comando |
|--------|---------|
| Ver estado | `sudo systemctl status risk-appetite-streamlit` |
| Reiniciar | `sudo systemctl restart risk-appetite-streamlit` |
| Detener | `sudo systemctl stop risk-appetite-streamlit` |
| Logs | `journalctl -u risk-appetite-streamlit -n 100 --no-pager` |

---

## 10. Acceso externo (NSG Azure)

La VM expone IP pública (ej. `20.228.231.195`). El ping puede funcionar pero el puerto **8502** queda bloqueado hasta crear regla NSG.

Quien tenga permisos de red en Azure:

```bash
# Sustituir <RESOURCE_GROUP> y <NSG_NAME> (preguntar a infra o ver en Portal → VM → Networking → Network security group)
az network nsg rule create \
  -g <RESOURCE_GROUP> \
  --nsg-name <NSG_NAME> \
  -n Allow-Streamlit-8502 \
  --priority 310 \
  --direction Inbound \
  --access Allow \
  --protocol Tcp \
  --destination-port-ranges 8502 \
  --source-address-prefixes Internet \
  --destination-address-prefixes '*'
```

Probar desde tu PC:

```powershell
powershell -File streamlit-risk-appetite-json\deploy\test-connectivity.ps1
```

URL externa:

```
http://20.228.231.195:8502
```

---

## URL final

```
http://10.72.64.196:8502
```
