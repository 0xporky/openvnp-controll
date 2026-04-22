# OpenVPN Droplet Controller

On-demand OpenVPN server on DigitalOcean. Spin up when you need it, tear down when you don't. Pay only for the hours you use (~$1/mo instead of $6/mo).

Control via CLI or Telegram bot from your phone.

## How it works

1. **One-time setup** creates a droplet, installs OpenVPN, generates client configs, and saves a snapshot
2. **Daily use**: create a droplet from the snapshot — VPN is ready in ~60 seconds
3. **DNS auto-updates** on every boot so your clients always connect to the right IP
4. Clients are configured once and never need changing

## Cost breakdown

| Item | Cost |
|------|------|
| `.xyz` domain | ~$1/year (~$0.08/mo) |
| Snapshot (~1GB) | ~$0.05/mo |
| Droplet (2 hrs/day) | ~$0.54/mo |
| DO DNS hosting | Free |
| **Total** | **~$0.70/mo** |

## Prerequisites

- A **domain name** (e.g. a `.xyz` domain for ~$1/year from Porkbun or Namecheap)
- A **DigitalOcean account** with an API token
- An **SSH key** added to your DO account
- **Python 3.11+**

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/openvnp-controll.git
cd openvnp-controll

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate    # Linux/macOS
venv\Scripts\activate       # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your config
cp .env.example .env
# Edit .env with your values (API token, domain, SSH key, etc.)
```

## Configuration

Copy `.env.example` to `.env` and set these values:

| Variable | Description |
|----------|-------------|
| `DO_TOKEN` | DigitalOcean API token |
| `DO_REGION` | Droplet region (default: `ams3`) |
| `DO_SIZE` | Droplet size (default: `s-1vcpu-1gb`) |
| `SSH_KEY_FINGERPRINT` | Your SSH key fingerprint from DO |
| `SSH_PRIVATE_KEY_PATH` | Path to your SSH private key (default: `~/.ssh/id_rsa`) |
| `DNS_DOMAIN` | Your domain (e.g. `myvpn.xyz`) |
| `DNS_SUBDOMAIN` | VPN subdomain (default: `vpn` → `vpn.myvpn.xyz`) |
| `SNAPSHOT_PREFIX` | Snapshot name prefix (default: `openvpn-server`) |
| `DROPLET_TAG` | Tag to identify VPN droplets (default: `openvpn`) |
| `DROPLET_NAME` | Droplet name (default: `openvpn-server`) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather (for bot only) |
| `TELEGRAM_USER_ID` | Your Telegram user ID (for bot only) |

## Domain setup

1. Buy a cheap domain (e.g. `myvpn.xyz` for ~$1/year)
2. At your registrar, change the **nameservers** to:
   - `ns1.digitalocean.com`
   - `ns2.digitalocean.com`
   - `ns3.digitalocean.com`
3. Put the domain name in `.env` (`DNS_DOMAIN=myvpn.xyz`)
4. The scripts handle DNS record creation and updates automatically

## Interactive Menu

The easiest way to use the controller. Navigate with arrow keys and press Enter to select:

```bash
python menu.py
```

Available options:

| Option | Description |
|--------|-------------|
| Setup | Install OpenVPN, generate clients, create snapshot |
| Start VPN | Create droplet from snapshot |
| Start VPN (timed) | Create droplet, auto-destroy after 1-12 hours |
| Stop VPN | Destroy the running droplet (snapshot preserved) |
| Status | Show VPN status, DNS, and snapshots |
| Cleanup | Delete ALL droplets and snapshots |
| Start Bot | Run the Telegram bot |
| Quit | Exit the menu |

Controls: **↑↓** navigate, **Enter** select, **q** or **Esc** quit.

## CLI Usage

```bash
# One-time setup (install OpenVPN, generate client configs, snapshot)
python cli.py setup
python cli.py setup --clients phone laptop tablet   # custom client names

# Start the VPN
python cli.py up

# Start the VPN for a bounded session (1-12h), then auto-destroy
python cli.py up-timed                       # prompts for hours + region
python cli.py up-timed --hours 3             # non-interactive; process blocks for 3h
# Ctrl+C cancels the timer but leaves the droplet running — use `down` to destroy it.

# Check status
python cli.py status

# Stop the VPN
python cli.py down

# Delete everything (snapshots + droplets) — stops all costs
python cli.py cleanup

# Start the Telegram bot
python cli.py bot
```

## Telegram Bot Setup

The bot lets you start, stop, and check your VPN from your phone.

### 1. Create a bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token into `.env` as `TELEGRAM_BOT_TOKEN`

### 2. Get your user ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. It replies with your user ID
3. Copy it into `.env` as `TELEGRAM_USER_ID`

### 3. Start the bot

```bash
python cli.py bot
```

### 4. Use it

Open your bot in Telegram and use these commands:

| Command | Description |
|---------|-------------|
| `/start` | Show available commands |
| `/up` | Start VPN (create droplet from snapshot) |
| `/up_timed` | Start VPN for 1-12 hours, then auto-destroy |
| `/down` | Stop VPN (destroy droplet) |
| `/status` | Show VPN status, IP, DNS, and snapshots |
| `/cleanup` | Delete all droplets and snapshots (with confirmation) |

Only your Telegram account (matching `TELEGRAM_USER_ID`) can control the bot. All other users are ignored.

## Security

- **No web interface** — server is managed exclusively via SSH
- **Firewall** — only SSH (22/tcp) and OpenVPN (1194/udp) ports are open
- **SSH hardened** — password login disabled, key-only authentication
- `.env` contains your API token — **never commit it** (it's gitignored)
- `clients/` contains VPN private keys — **never commit them** (gitignored)
- The DO API token is stored on the droplet (in `/etc/vpn-dns/token`) for DNS updates — it's included in the snapshot
- Telegram bot only responds to your user ID — unauthorized users are silently ignored
