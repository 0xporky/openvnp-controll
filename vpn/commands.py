import socket
from dataclasses import dataclass, field
from pathlib import Path

from vpn import do_api
from vpn.config import (
    DNS_DOMAIN,
    DNS_HOSTNAME,
    DNS_SUBDOMAIN,
    DO_REGION,
    DO_SIZE,
    DROPLET_NAME,
    DROPLET_TAG,
    SNAPSHOT_PREFIX,
    SSH_KEY_FINGERPRINT,
    VPN_PORT,
    VPN_PROTO,
)
from vpn.ssh import (
    download_file,
    ensure_openvpn_running,
    generate_client_config,
    install_openvpn,
    wait_for_ssh,
)


@dataclass
class VpnUpResult:
    status: str  # "ready", "already_running", "error"
    ip: str = ""
    dns: str = ""
    message: str = ""


@dataclass
class VpnDownResult:
    status: str  # "destroyed", "not_running", "error"
    message: str = ""


@dataclass
class SnapshotInfo:
    id: str
    name: str
    size_gb: float
    created_at: str


@dataclass
class VpnStatusResult:
    running: bool
    ip: str = ""
    droplet_id: int = 0
    droplet_name: str = ""
    region: str = ""
    dns: str = ""
    dns_status: str = ""  # "ok", "stale", "not_resolving"
    dns_resolved_ip: str = ""
    snapshots: list[SnapshotInfo] = field(default_factory=list)


@dataclass
class VpnSetupResult:
    status: str  # "ready", "already_exists", "error"
    snapshot_name: str = ""
    clients_generated: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class VpnCleanupResult:
    deleted_droplets: int = 0
    deleted_snapshots: int = 0
    message: str = ""


def _resolve_dns(hostname: str) -> str | None:
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        if results:
            return results[0][4][0]
    except socket.gaierror:
        pass
    return None


async def _find_latest_snapshot() -> dict | None:
    snapshots = await do_api.list_snapshots()
    matching = [s for s in snapshots if s["name"].startswith(SNAPSHOT_PREFIX)]
    if not matching:
        return None
    return matching[-1]


async def _get_snapshots_info() -> list[SnapshotInfo]:
    snapshots = await do_api.list_snapshots()
    matching = [s for s in snapshots if s["name"].startswith(SNAPSHOT_PREFIX)]
    return [
        SnapshotInfo(
            id=s["id"],
            name=s["name"],
            size_gb=s["size_gigabytes"],
            created_at=s["created_at"],
        )
        for s in matching
    ]


async def vpn_setup(client_names: list[str] | None = None, on_progress=None) -> VpnSetupResult:
    """Initial setup: create droplet, install OpenVPN, generate clients, snapshot, destroy."""
    from datetime import datetime, timezone
    from pathlib import Path

    # Check if snapshot already exists
    existing = await _find_latest_snapshot()
    if existing:
        return VpnSetupResult(
            status="already_exists",
            snapshot_name=existing["name"],
            message=f"Snapshot '{existing['name']}' already exists. Run cleanup first to re-setup.",
        )

    if client_names is None:
        client_names = ["default"]

    if on_progress:
        await on_progress("Creating temporary droplet for setup...")

    # Create from base Ubuntu image
    droplet = await do_api.create_droplet_from_image(
        name=f"{DROPLET_NAME}-setup",
        region=DO_REGION,
        size=DO_SIZE,
        image="ubuntu-24-04-x64",
        ssh_keys=[SSH_KEY_FINGERPRINT],
        tags=[DROPLET_TAG],
    )
    droplet_id = droplet["id"]

    try:
        if on_progress:
            await on_progress("Waiting for droplet to become active...")

        droplet = await do_api.wait_for_active(droplet_id)
        ip = do_api.get_droplet_ip(droplet) or ""

        if on_progress:
            await on_progress(f"Droplet active at {ip}. Waiting for SSH...")

        ssh_ready = await wait_for_ssh(ip, on_progress=on_progress)
        if not ssh_ready:
            return VpnSetupResult(
                status="error",
                message=f"SSH not reachable at {ip} after 5 minutes. Check that SSH key fingerprint matches and the droplet is accessible.",
            )

        if on_progress:
            await on_progress("Installing OpenVPN (this takes a few minutes)...")

        success, output = await install_openvpn(ip, VPN_PORT, VPN_PROTO, on_progress=on_progress)
        if not success:
            return VpnSetupResult(
                status="error",
                message=f"OpenVPN installation failed:\n{output[-500:]}",
            )

        # Generate client configs
        clients_dir = Path(__file__).resolve().parent.parent / "clients"
        clients_dir.mkdir(exist_ok=True)
        generated = []

        for name in client_names:
            if on_progress:
                await on_progress(f"Generating client config: {name}...")

            ok, remote_path = await generate_client_config(ip, name, DNS_HOSTNAME, VPN_PORT, VPN_PROTO)
            if not ok:
                if on_progress:
                    await on_progress(f"Warning: failed to generate {name}: {remote_path}")
                continue

            ovpn_data = await download_file(ip, remote_path)
            local_path = clients_dir / f"{name}.ovpn"
            local_path.write_bytes(ovpn_data)
            generated.append(name)

        if on_progress:
            await on_progress("Shutting down droplet for snapshot...")

        # Graceful shutdown before snapshot
        action_id = await do_api.shutdown_droplet(droplet_id)
        await do_api.wait_for_action(droplet_id, action_id, timeout=120)

        # Create snapshot
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        snapshot_name = f"{SNAPSHOT_PREFIX}-{ts}"

        if on_progress:
            await on_progress(f"Creating snapshot '{snapshot_name}' (this takes a few minutes)...")

        action_id = await do_api.snapshot_droplet(droplet_id, snapshot_name)
        await do_api.wait_for_action(droplet_id, action_id, timeout=600)

        if on_progress:
            await on_progress("Snapshot created. Destroying temporary droplet...")

        # Destroy the setup droplet
        await do_api.delete_droplet(droplet_id)

        return VpnSetupResult(
            status="ready",
            snapshot_name=snapshot_name,
            clients_generated=generated,
            message=f"Setup complete. Snapshot: {snapshot_name}. Clients: {', '.join(generated)}.",
        )

    except Exception as e:
        # Clean up on failure
        try:
            await do_api.delete_droplet(droplet_id)
        except Exception:
            pass
        return VpnSetupResult(
            status="error",
            message=f"Setup failed: {e}. Temporary droplet was cleaned up.",
        )


async def vpn_up(on_progress=None) -> VpnUpResult:
    # Check if already running
    droplets = await do_api.list_droplets(DROPLET_TAG)
    if droplets:
        ip = do_api.get_droplet_ip(droplets[0]) or ""
        return VpnUpResult(status="already_running", ip=ip, dns=DNS_HOSTNAME)

    # Find latest snapshot
    snapshot = await _find_latest_snapshot()
    if not snapshot:
        return VpnUpResult(
            status="error",
            message=f"No snapshot found with prefix '{SNAPSHOT_PREFIX}'. Run setup first.",
        )

    if on_progress:
        await on_progress(f"Creating droplet from snapshot {snapshot['name']}...")

    # Create droplet
    droplet = await do_api.create_droplet(
        name=DROPLET_NAME,
        region=DO_REGION,
        size=DO_SIZE,
        image=int(snapshot["id"]),
        ssh_keys=[SSH_KEY_FINGERPRINT],
        tags=[DROPLET_TAG],
    )
    droplet_id = droplet["id"]

    if on_progress:
        await on_progress("Waiting for droplet to become active...")

    # Wait for active
    try:
        droplet = await do_api.wait_for_active(droplet_id)
    except TimeoutError:
        return VpnUpResult(status="error", message="Droplet did not become active in time.")

    ip = do_api.get_droplet_ip(droplet) or ""

    # Update DNS to point to the new IP
    if on_progress:
        await on_progress(f"Droplet active at {ip}. Updating DNS ({DNS_HOSTNAME} → {ip})...")

    try:
        await do_api.upsert_dns_a_record(DNS_DOMAIN, DNS_SUBDOMAIN, ip)
    except Exception as e:
        return VpnUpResult(
            status="error",
            ip=ip,
            dns=DNS_HOSTNAME,
            message=f"DNS update failed: {e}. You may need to update {DNS_HOSTNAME} manually.",
        )

    if on_progress:
        await on_progress("DNS updated. Waiting for SSH...")

    # Wait for SSH and verify OpenVPN
    ssh_ready = await wait_for_ssh(ip, on_progress=on_progress)
    if not ssh_ready:
        return VpnUpResult(
            status="error",
            ip=ip,
            dns=DNS_HOSTNAME,
            message=f"SSH not reachable at {ip} after 5 minutes.",
        )

    if on_progress:
        await on_progress("SSH ready. Verifying OpenVPN...")

    vpn_ok, diag = await ensure_openvpn_running(ip, port=VPN_PORT)
    if not vpn_ok:
        return VpnUpResult(
            status="error",
            ip=ip,
            dns=DNS_HOSTNAME,
            message=f"OpenVPN not listening on port {VPN_PORT} after multiple restarts.\n\n{diag}",
        )

    return VpnUpResult(status="ready", ip=ip, dns=DNS_HOSTNAME)


async def vpn_down() -> VpnDownResult:
    droplets = await do_api.list_droplets(DROPLET_TAG)
    if not droplets:
        return VpnDownResult(status="not_running", message="No running VPN droplet found.")

    droplet = droplets[0]
    droplet_id = droplet["id"]
    ip = do_api.get_droplet_ip(droplet) or "unknown"

    await do_api.delete_droplet(droplet_id)
    return VpnDownResult(
        status="destroyed",
        message=f"Droplet {droplet_id} ({ip}) destroyed. Snapshot preserved.",
    )


async def vpn_status() -> VpnStatusResult:
    droplets = await do_api.list_droplets(DROPLET_TAG)
    snapshots = await _get_snapshots_info()

    if not droplets:
        return VpnStatusResult(running=False, snapshots=snapshots)

    droplet = droplets[0]
    ip = do_api.get_droplet_ip(droplet) or ""

    resolved_ip = _resolve_dns(DNS_HOSTNAME)
    if resolved_ip == ip:
        dns_status = "ok"
    elif resolved_ip:
        dns_status = "stale"
    else:
        dns_status = "not_resolving"

    return VpnStatusResult(
        running=True,
        ip=ip,
        droplet_id=droplet["id"],
        droplet_name=droplet["name"],
        region=droplet["region"]["slug"],
        dns=DNS_HOSTNAME,
        dns_status=dns_status,
        dns_resolved_ip=resolved_ip or "",
        snapshots=snapshots,
    )


async def vpn_cleanup(on_progress=None) -> VpnCleanupResult:
    deleted_droplets = 0
    deleted_snapshots = 0

    # Delete all tagged droplets
    droplets = await do_api.list_droplets(DROPLET_TAG)
    for d in droplets:
        if on_progress:
            await on_progress(f"Deleting droplet {d['id']}...")
        await do_api.delete_droplet(d["id"])
        deleted_droplets += 1

    # Delete all matching snapshots
    snapshots = await do_api.list_snapshots()
    for s in snapshots:
        if s["name"].startswith(SNAPSHOT_PREFIX):
            if on_progress:
                await on_progress(f"Deleting snapshot {s['name']}...")
            await do_api.delete_snapshot(s["id"])
            deleted_snapshots += 1

    return VpnCleanupResult(
        deleted_droplets=deleted_droplets,
        deleted_snapshots=deleted_snapshots,
        message=f"Deleted {deleted_droplets} droplet(s) and {deleted_snapshots} snapshot(s).",
    )
