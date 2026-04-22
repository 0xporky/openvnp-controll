# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

On-demand OpenVPN server on DigitalOcean. One-time setup creates a droplet, installs OpenVPN, generates `.ovpn` client configs, snapshots it, then destroys the droplet. Daily use creates a cheap droplet from that snapshot (~60s boot). DNS auto-updates so client configs never need changing. Control via CLI, interactive menu, or Telegram bot.

## Commands

```bash
# Install dependencies (Python 3.11+, use a venv)
pip install -r requirements.txt

# Interactive menu (arrow keys + Enter)
python menu.py

# CLI commands
python cli.py setup                          # one-time: install OpenVPN, gen clients, snapshot
python cli.py setup --clients phone laptop   # custom client names
python cli.py up                             # create droplet from snapshot
python cli.py up-timed                       # create droplet, auto-destroy after 1-12h (blocks)
python cli.py up-timed --hours 3 --region ams3
python cli.py down                           # destroy droplet (snapshot preserved)
python cli.py status                         # show status, DNS, snapshots
python cli.py cleanup                        # delete ALL droplets and snapshots
python cli.py clear-clients                  # delete local .ovpn files
python cli.py bot                            # start Telegram bot

# Syntax check (no test suite exists)
python -c "import ast; [ast.parse(open(f).read()) for f in ('cli.py','menu.py','bot/main.py')]"
python -c "import ast; [ast.parse(open(f'vpn/{f}').read()) for f in ('commands.py','do_api.py','ssh.py','config.py')]"
```

## Architecture

Three entry points share the same backend:

- **`menu.py`** — interactive terminal menu (arrow-key navigation via raw `tty`/`termios`). Delegates to `cli.py` subcommands via `subprocess`.
- **`cli.py`** — argparse CLI. Each subcommand calls async functions from `vpn/commands.py` via `asyncio.run()`.
- **`bot/main.py`** — Telegram bot using `python-telegram-bot`. Calls the same `vpn/commands.py` functions directly (already async). Auth is a simple user-ID check decorator.

Backend (`vpn/`):

- **`vpn/config.py`** — loads `.env` via `python-dotenv`, exports all config constants. Required vars (`DO_TOKEN`, `SSH_KEY_FINGERPRINT`, `DNS_DOMAIN`) exit with an error if missing.
- **`vpn/do_api.py`** — async DigitalOcean REST API wrapper using `httpx`. Handles droplets, snapshots, actions (shutdown, snapshot, wait-for-active).
- **`vpn/ssh.py`** — SSH operations via `paramiko` (wrapped in `asyncio.to_thread`). Contains the OpenVPN install script and client config generation as bash heredoc templates with `%%PLACEHOLDER%%` substitution.
- **`vpn/commands.py`** — orchestration layer. Each operation (setup, up, down, status, cleanup) is an async function returning a typed dataclass result. `on_progress` callbacks let callers (CLI/bot) report intermediate status.

Key pattern: all VPN operations return dataclass results (e.g. `VpnUpResult`, `VpnStatusResult`) with a `status` field. Callers switch on `status` to display appropriate output.

## Configuration

Copy `.env.example` to `.env`. Required: `DO_TOKEN`, `SSH_KEY_FINGERPRINT`, `DNS_DOMAIN`. The domain's nameservers must point to `ns1/ns2/ns3.digitalocean.com`. Telegram vars are only needed for the bot.

## Sensitive paths (gitignored, never commit)

- `.env` — API tokens
- `clients/` — `.ovpn` private keys
