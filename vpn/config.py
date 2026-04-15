import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        print(f"ERROR: {name} is not set. Copy .env.example to .env and fill in your values.")
        sys.exit(1)
    return value


# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "0"))

# DigitalOcean
DO_TOKEN = _require("DO_TOKEN")
DO_REGION = os.getenv("DO_REGION", "ams3")
DO_SIZE = os.getenv("DO_SIZE", "s-1vcpu-1gb")
SSH_KEY_FINGERPRINT = _require("SSH_KEY_FINGERPRINT")
SSH_PRIVATE_KEY_PATH = os.getenv("SSH_PRIVATE_KEY_PATH", "~/.ssh/id_rsa")

# Naming
SNAPSHOT_PREFIX = os.getenv("SNAPSHOT_PREFIX", "openvpn-server")
DROPLET_TAG = os.getenv("DROPLET_TAG", "openvpn")
DROPLET_NAME = os.getenv("DROPLET_NAME", "openvpn-server")

# DNS
DNS_DOMAIN = _require("DNS_DOMAIN")
DNS_SUBDOMAIN = os.getenv("DNS_SUBDOMAIN", "vpn")

# OpenVPN
VPN_PORT = os.getenv("VPN_PORT", "443")
VPN_PROTO = os.getenv("VPN_PROTO", "tcp")

DNS_HOSTNAME = f"{DNS_SUBDOMAIN}.{DNS_DOMAIN}"
