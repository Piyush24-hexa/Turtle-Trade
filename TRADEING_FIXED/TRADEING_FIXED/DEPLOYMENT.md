# ☁️ Oracle Cloud Free Tier Deployment Guide

> Host your trading bot 24/7 for **FREE** — Oracle gives you an ARM instance forever.

---

## Why Oracle Cloud Free Tier?

- ✅ **Free forever** (not a trial)
- ✅ 4 OCPU + 24GB RAM (ARM instance — way more than we need)
- ✅ Perfect for Python bots
- ✅ Located in India (Mumbai region = low latency to NSE)

---

## Step 1: Create Oracle Cloud Account

1. Go to https://www.oracle.com/cloud/free/
2. Sign up (requires credit card for verification — **not charged**)
3. Choose **India South (Mumbai)** or **India West (Hyderabad)** region

---

## Step 2: Create a Free ARM Instance

1. **Compute** → Instances → **Create Instance**
2. **Image**: Oracle Linux 8 (or Ubuntu 22.04)
3. **Shape**: Select `VM.Standard.A1.Flex` (ARM) → set **1 OCPU, 6GB RAM**
4. **SSH Key**: Generate and download (you'll need this to connect)
5. Click **Create**

Wait 2-3 minutes for instance to start.

---

## Step 3: Connect via SSH

```bash
# Windows: use PuTTY or Windows Terminal
ssh -i your_key.pem opc@<YOUR_INSTANCE_IP>
```

---

## Step 4: Install Python & Bot

```bash
# Update system
sudo yum update -y  # Oracle Linux
# OR: sudo apt update && sudo apt upgrade -y  # Ubuntu

# Install Python 3.11
sudo yum install python3.11 python3.11-pip -y

# Upload your bot files (from Windows)
# Run this on YOUR WINDOWS machine:
scp -i your_key.pem -r e:\TRADEING\ opc@<IP>:~/trading_bot/

# Back on cloud server:
cd ~/trading_bot
pip3.11 install -r requirements.txt
pip3.11 install flask flask-cors
```

---

## Step 5: Configure API Keys on Cloud

Create `.env` file on cloud (don't put keys in source files):

```bash
cat > .env << 'EOF'
TELEGRAM_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
ANGEL_API_KEY=your_key_here
ANGEL_CLIENT_ID=your_client_id_here
ANGEL_PASSWORD=your_password_here
ANGEL_TOTP_SECRET=your_totp_here
EOF
```

Load env vars in the bot:
```bash
export $(cat .env | xargs)
```

---

## Step 6: Run as Background Service (systemd)

```bash
sudo nano /etc/systemd/system/tradingbot.service
```

Paste:
```ini
[Unit]
Description=NSE Trading Bot
After=network.target

[Service]
Type=simple
User=opc
WorkingDirectory=/home/opc/trading_bot
EnvironmentFile=/home/opc/trading_bot/.env
ExecStart=/usr/bin/python3.11 main.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tradingbot
sudo systemctl start tradingbot

# Check status
sudo systemctl status tradingbot

# View live logs
sudo journalctl -u tradingbot -f
```

---

## Step 7: Open Firewall for Dashboard API

```bash
# Oracle Cloud console → Networking → Security Lists → Add Ingress Rule
# Source CIDR: 0.0.0.0/0
# Port: 5001

# Also open OS firewall:
sudo firewall-cmd --add-port=5001/tcp --permanent
sudo firewall-cmd --reload

# Start dashboard API as service too
sudo nano /etc/systemd/system/tradingapi.service
```

```ini
[Unit]
Description=Trading Bot Dashboard API
After=network.target

[Service]
Type=simple
User=opc
WorkingDirectory=/home/opc/trading_bot
EnvironmentFile=/home/opc/trading_bot/.env
ExecStart=/usr/bin/python3.11 api_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable tradingapi
sudo systemctl start tradingapi
```

---

## Step 8: Update Dashboard to Point to Cloud

In `dashboard/dashboard.js`, change:
```js
const API_BASE = 'http://YOUR_ORACLE_IP:5001';
```

---

## Useful Commands

```bash
# View bot logs
sudo journalctl -u tradingbot -n 50

# Restart bot
sudo systemctl restart tradingbot

# Stop bot
sudo systemctl stop tradingbot

# Deploy new code
scp -i key.pem -r e:\TRADEING\*.py opc@<IP>:~/trading_bot/
sudo systemctl restart tradingbot
```

---

## Cost Summary

| Service | Cost |
|---------|------|
| Oracle Cloud ARM | **₹0** (free forever) |
| Angel One API | **₹0** (free real-time) |
| Yahoo Finance | **₹0** |
| Telegram | **₹0** |
| **Total** | **₹0/month** |

Your ₹1,500/month budget → goes into trading capital! 🎉
