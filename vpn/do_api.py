import asyncio

import httpx

from vpn.config import DO_TOKEN

BASE_URL = "https://api.digitalocean.com/v2"
HEADERS = {
    "Authorization": f"Bearer {DO_TOKEN}",
    "Content-Type": "application/json",
}


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, headers=HEADERS, timeout=30.0)


async def list_droplets(tag: str) -> list[dict]:
    async with await _client() as client:
        resp = await client.get("/droplets", params={"tag_name": tag})
        resp.raise_for_status()
        return resp.json()["droplets"]


async def get_droplet(droplet_id: int) -> dict:
    async with await _client() as client:
        resp = await client.get(f"/droplets/{droplet_id}")
        resp.raise_for_status()
        return resp.json()["droplet"]


async def create_droplet(
    name: str,
    region: str,
    size: str,
    image: int,
    ssh_keys: list[str],
    tags: list[str],
) -> dict:
    async with await _client() as client:
        resp = await client.post(
            "/droplets",
            json={
                "name": name,
                "region": region,
                "size": size,
                "image": image,
                "ssh_keys": ssh_keys,
                "tags": tags,
            },
        )
        resp.raise_for_status()
        return resp.json()["droplet"]


async def delete_droplet(droplet_id: int) -> None:
    async with await _client() as client:
        resp = await client.delete(f"/droplets/{droplet_id}")
        resp.raise_for_status()


async def list_snapshots() -> list[dict]:
    async with await _client() as client:
        snapshots = []
        page = 1
        while True:
            resp = await client.get(
                "/snapshots",
                params={"resource_type": "droplet", "page": page, "per_page": 50},
            )
            resp.raise_for_status()
            data = resp.json()
            snapshots.extend(data["snapshots"])
            if len(snapshots) >= data["meta"]["total"]:
                break
            page += 1
        return snapshots


async def delete_snapshot(snapshot_id: int) -> None:
    async with await _client() as client:
        resp = await client.delete(f"/snapshots/{snapshot_id}")
        resp.raise_for_status()


async def create_droplet_from_image(
    name: str,
    region: str,
    size: str,
    image: str,
    ssh_keys: list[str],
    tags: list[str],
) -> dict:
    """Create a droplet from a base image slug (e.g. 'ubuntu-24-04-x64')."""
    async with await _client() as client:
        resp = await client.post(
            "/droplets",
            json={
                "name": name,
                "region": region,
                "size": size,
                "image": image,
                "ssh_keys": ssh_keys,
                "tags": tags,
            },
        )
        resp.raise_for_status()
        return resp.json()["droplet"]


async def snapshot_droplet(droplet_id: int, snapshot_name: str) -> int:
    """Request a snapshot of a droplet. Returns the action ID."""
    async with await _client() as client:
        resp = await client.post(
            f"/droplets/{droplet_id}/actions",
            json={"type": "snapshot", "name": snapshot_name},
        )
        resp.raise_for_status()
        return resp.json()["action"]["id"]


async def wait_for_action(droplet_id: int, action_id: int, timeout: int = 600) -> dict:
    """Wait for a droplet action to complete."""
    elapsed = 0
    interval = 10
    async with await _client() as client:
        while elapsed < timeout:
            resp = await client.get(f"/droplets/{droplet_id}/actions/{action_id}")
            resp.raise_for_status()
            action = resp.json()["action"]
            if action["status"] == "completed":
                return action
            if action["status"] == "errored":
                raise RuntimeError(f"Action {action_id} errored")
            await asyncio.sleep(interval)
            elapsed += interval
    raise TimeoutError(f"Action {action_id} did not complete within {timeout}s")


async def shutdown_droplet(droplet_id: int) -> int:
    """Gracefully shut down a droplet. Returns the action ID."""
    async with await _client() as client:
        resp = await client.post(
            f"/droplets/{droplet_id}/actions",
            json={"type": "shutdown"},
        )
        resp.raise_for_status()
        return resp.json()["action"]["id"]


async def wait_for_active(droplet_id: int, timeout: int = 180) -> dict:
    elapsed = 0
    interval = 5
    while elapsed < timeout:
        droplet = await get_droplet(droplet_id)
        if droplet["status"] == "active":
            return droplet
        await asyncio.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"Droplet {droplet_id} did not become active within {timeout}s")


def get_droplet_ip(droplet: dict) -> str | None:
    for net in droplet.get("networks", {}).get("v4", []):
        if net["type"] == "public":
            return net["ip_address"]
    return None


async def list_domain_records(domain: str) -> list[dict]:
    """List all DNS records for a domain."""
    async with await _client() as client:
        records = []
        page = 1
        while True:
            resp = await client.get(
                f"/domains/{domain}/records",
                params={"page": page, "per_page": 50},
            )
            resp.raise_for_status()
            data = resp.json()
            records.extend(data["domain_records"])
            if len(records) >= data["meta"]["total"]:
                break
            page += 1
        return records


async def update_domain_record(domain: str, record_id: int, data: str) -> dict:
    """Update a DNS record's data (e.g. IP address for an A record)."""
    async with await _client() as client:
        resp = await client.put(
            f"/domains/{domain}/records/{record_id}",
            json={"data": data},
        )
        resp.raise_for_status()
        return resp.json()["domain_record"]


async def create_domain_record(
    domain: str, record_type: str, name: str, data: str, ttl: int = 60
) -> dict:
    """Create a new DNS record."""
    async with await _client() as client:
        resp = await client.post(
            f"/domains/{domain}/records",
            json={"type": record_type, "name": name, "data": data, "ttl": ttl},
        )
        resp.raise_for_status()
        return resp.json()["domain_record"]


async def upsert_dns_a_record(domain: str, subdomain: str, ip: str) -> dict:
    """Create or update an A record for subdomain.domain pointing to ip."""
    records = await list_domain_records(domain)
    for r in records:
        if r["type"] == "A" and r["name"] == subdomain:
            if r["data"] == ip:
                return r  # already correct
            return await update_domain_record(domain, r["id"], ip)
    return await create_domain_record(domain, "A", subdomain, ip, ttl=60)
