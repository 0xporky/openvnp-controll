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


def _prompt_region(regions, default_slug: str) -> str | None:
    """Prompt the user to pick a region. Returns the slug, or None if cancelled."""
    default_idx = 0
    for i, r in enumerate(regions):
        if r.slug == default_slug:
            default_idx = i
            break

    print("Select region:")
    for i, r in enumerate(regions):
        default_marker = "*" if i == default_idx else " "
        print(f"  {i + 1:>2}) {default_marker} {r.slug:<6}  {r.name}")

    reply = input(f"Choice [{default_idx + 1}]: ").strip()
    if not reply:
        return regions[default_idx].slug
    try:
        idx = int(reply) - 1
    except ValueError:
        return None
    if not (0 <= idx < len(regions)):
        return None
    return regions[idx].slug


def _prompt_hours(default: int = 2) -> int | None:
    """Prompt the user to pick a session duration (1-12h). Returns hours, or None if cancelled."""
    print("Select duration:")
    for h in range(1, 13):
        default_marker = "*" if h == default else " "
        print(f"  {h:>2}) {default_marker} {h}h")

    reply = input(f"Choice [{default}]: ").strip()
    if not reply:
        return default
    try:
        h = int(reply)
    except ValueError:
        return None
    if not 1 <= h <= 12:
        return None
    return h


async def _resolve_region(region: str | None) -> tuple[str | None, bool]:
    """Resolve a region slug, prompting interactively when needed.

    Returns (slug, cancelled). `slug` may be None when no snapshot exists yet;
    callers should pass it through so `vpn_up` surfaces the real error.
    """
    from vpn.commands import list_up_regions
    from vpn.config import DO_REGION

    if region is not None:
        return region, False

    regions = await list_up_regions()
    if len(regions) == 1:
        chosen = regions[0].slug
        print(f"Region: {chosen} ({regions[0].name})")
        return chosen, False
    if len(regions) > 1:
        chosen = _prompt_region(regions, DO_REGION)
        if chosen is None:
            print("Invalid choice. Cancelled.")
            return None, True
        return chosen, False
    return None, False  # no snapshots; let vpn_up raise


def cmd_up(region: str | None = None):
    from vpn.commands import vpn_up

    async def run():
        print("=== VPN Up ===")

        chosen, cancelled = await _resolve_region(region)
        if cancelled:
            return

        async def on_progress(text: str):
            print(text)

        result = await vpn_up(region=chosen, on_progress=on_progress)
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


def cmd_up_timed(hours: int | None = None, region: str | None = None):
    from datetime import datetime, timedelta

    from vpn.commands import vpn_down, vpn_up

    async def run():
        print("=== VPN Up (timed) ===")

        chosen_hours = hours
        if chosen_hours is None:
            chosen_hours = _prompt_hours()
            if chosen_hours is None:
                print("Invalid choice. Cancelled.")
                return

        chosen_region, cancelled = await _resolve_region(region)
        if cancelled:
            return

        async def on_progress(text: str):
            print(text)

        result = await vpn_up(region=chosen_region, on_progress=on_progress)

        if result.status == "already_running":
            print(
                f"VPN is already running at {result.ip}.\n"
                f"`up-timed` only tracks droplets it creates. "
                f"Run 'python cli.py down' first."
            )
            return
        if result.status != "ready":
            print(f"ERROR: {result.message}")
            sys.exit(1)

        expiry = datetime.now() + timedelta(hours=chosen_hours)
        print(f"\nVPN is ready!")
        print(f"  IP:  {result.ip}")
        print(f"  DNS: {result.dns}")
        print(
            f"\nWill auto-destroy at {expiry.strftime('%H:%M')} "
            f"(in {chosen_hours}h 0m)."
        )
        print("Press Ctrl+C to cancel the timer (droplet will persist).")

        try:
            await asyncio.sleep(chosen_hours * 3600)
        except asyncio.CancelledError:
            print(
                "\nTimer cancelled. Droplet still running — "
                "run 'python cli.py down' to destroy."
            )
            return

        print("\nTimer elapsed. Destroying droplet...")
        down_result = await vpn_down()
        print(down_result.message)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        # Message already printed inside run(); swallow so the shell exits 0.
        pass


def cmd_down():
    from vpn.commands import vpn_down, vpn_status

    async def run():
        print("=== VPN Down ===")
        status = await vpn_status()
        if not status.running:
            print("No running VPN droplet found.")
            return

        print(f"Destroying droplet: ID={status.droplet_id} IP={status.ip}")
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
    up_parser = sub.add_parser("up", help="Start VPN (create droplet from snapshot)")
    up_parser.add_argument(
        "--region", default=None,
        help="DO region slug (e.g. ams3, fra1). If omitted, you'll be prompted when multiple are available.",
    )
    up_timed_parser = sub.add_parser(
        "up-timed",
        help="Start VPN for a bounded duration (1-12h), then auto-destroy",
    )
    up_timed_parser.add_argument(
        "--hours", type=int, default=None, choices=range(1, 13), metavar="{1..12}",
        help="Session duration in hours (1-12). If omitted, you'll be prompted.",
    )
    up_timed_parser.add_argument(
        "--region", default=None,
        help="DO region slug (e.g. ams3, fra1). If omitted, you'll be prompted when multiple are available.",
    )
    sub.add_parser("down", help="Stop VPN (destroy droplet)")
    sub.add_parser("status", help="Show VPN status")
    sub.add_parser("cleanup", help="Delete all droplets and snapshots")
    sub.add_parser("clear-clients", help="Delete local .ovpn client configs")
    sub.add_parser("bot", help="Start the Telegram bot")

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup(args.clients)
        return

    if args.command == "up":
        cmd_up(region=args.region)
        return

    if args.command == "up-timed":
        cmd_up_timed(hours=args.hours, region=args.region)
        return

    commands = {
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
