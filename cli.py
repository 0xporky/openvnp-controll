import argparse
import asyncio
import sys


def cmd_setup(clients: list[str]):
    from vpn.commands import vpn_setup

    async def run():
        print("=== VPN Setup ===")
        print(f"Clients to generate: {', '.join(clients)}")
        print()

        async def on_progress(text: str):
            print(text)

        result = await vpn_setup(client_names=clients, on_progress=on_progress)
        if result.status == "ready":
            print(f"\nSetup complete!")
            print(f"  Snapshot: {result.snapshot_name}")
            print(f"  Clients:  {', '.join(result.clients_generated)}")
            print(f"\nClient configs saved to ./clients/")
            print(f"Run 'python cli.py up' to start the VPN.")
        elif result.status == "already_exists":
            print(f"\n{result.message}")
        else:
            print(f"\nERROR: {result.message}")
            sys.exit(1)

    asyncio.run(run())


def cmd_up():
    from vpn.commands import vpn_up

    async def run():
        print("=== VPN Up ===")

        async def on_progress(text: str):
            print(text)

        result = await vpn_up(on_progress=on_progress)
        if result.status == "ready":
            print(f"\nVPN is ready!")
            print(f"  IP:  {result.ip}")
            print(f"  DNS: {result.dns}")
            print(f"\nDNS will auto-update shortly. You can connect now.")
        elif result.status == "already_running":
            print(f"VPN is already running at {result.ip}")
            print(f"DNS: {result.dns}")
        else:
            print(f"ERROR: {result.message}")
            sys.exit(1)

    asyncio.run(run())


def cmd_down():
    from vpn.commands import vpn_down, vpn_status

    async def run():
        print("=== VPN Down ===")
        status = await vpn_status()
        if not status.running:
            print("No running VPN droplet found.")
            return

        print(f"Found VPN droplet: ID={status.droplet_id} IP={status.ip}")
        reply = input("Destroy this droplet? (y/N) ").strip()
        if reply.lower() != "y":
            print("Cancelled.")
            return

        result = await vpn_down()
        print(result.message)

    asyncio.run(run())


def cmd_status():
    from vpn.commands import vpn_status

    async def run():
        print("=== VPN Status ===\n")
        result = await vpn_status()

        if result.running:
            print(f"Status:  RUNNING")
            print(f"IP:      {result.ip}")
            print(f"DNS:     {result.dns}")
            print(f"Region:  {result.region}")
            print()

            if result.dns_status == "ok":
                print(f"DNS:     OK ({result.dns_resolved_ip})")
            elif result.dns_status == "stale":
                print(f"DNS:     STALE (resolves to {result.dns_resolved_ip}, droplet is {result.ip})")
            else:
                print("DNS:     NOT RESOLVING")
        else:
            print("Status:  STOPPED (no droplet running)")

        print()
        if result.snapshots:
            print("Snapshots:")
            for s in result.snapshots:
                print(f"  {s.id}  {s.name}  {s.size_gb}GB  {s.created_at}")
        else:
            print("No snapshots found. Run setup first.")

    asyncio.run(run())


def cmd_cleanup():
    from vpn.commands import vpn_cleanup

    async def run():
        print("=== VPN Cleanup ===")
        reply = input("Delete ALL droplets and snapshots? This cannot be undone. (y/N) ").strip()
        if reply.lower() != "y":
            print("Cancelled.")
            return

        async def on_progress(text: str):
            print(text)

        result = await vpn_cleanup(on_progress=on_progress)
        print(result.message)

    asyncio.run(run())


def cmd_clear_clients():
    from pathlib import Path

    clients_dir = Path(__file__).resolve().parent / "clients"
    if not clients_dir.exists():
        print("No clients/ directory found.")
        return

    ovpn_files = list(clients_dir.glob("*.ovpn"))
    if not ovpn_files:
        print("No .ovpn files found in clients/.")
        return

    print(f"Found {len(ovpn_files)} client config(s):")
    for f in ovpn_files:
        print(f"  {f.name}")

    reply = input("\nDelete all local client configs? (y/N) ").strip()
    if reply.lower() != "y":
        print("Cancelled.")
        return

    for f in ovpn_files:
        f.unlink()
    print(f"Deleted {len(ovpn_files)} client config(s).")


def cmd_bot():
    from bot.main import run_bot
    run_bot()


def main():
    parser = argparse.ArgumentParser(description="OpenVPN Droplet Controller")
    sub = parser.add_subparsers(dest="command")

    setup_parser = sub.add_parser("setup", help="Initial setup: create droplet, install OpenVPN, snapshot")
    setup_parser.add_argument(
        "--clients", nargs="+", default=["phone", "laptop", "tablet"],
        help="Client names to generate .ovpn configs for (default: phone laptop tablet)",
    )
    sub.add_parser("up", help="Start VPN (create droplet from snapshot)")
    sub.add_parser("down", help="Stop VPN (destroy droplet)")
    sub.add_parser("status", help="Show VPN status")
    sub.add_parser("cleanup", help="Delete all droplets and snapshots")
    sub.add_parser("clear-clients", help="Delete local .ovpn client configs")
    sub.add_parser("bot", help="Start the Telegram bot")

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup(args.clients)
        return

    commands = {
        "up": cmd_up,
        "down": cmd_down,
        "status": cmd_status,
        "cleanup": cmd_cleanup,
        "clear-clients": cmd_clear_clients,
        "bot": cmd_bot,
    }

    if args.command in commands:
        commands[args.command]()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
