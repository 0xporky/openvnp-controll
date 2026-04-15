import asyncio
import base64
import os
from pathlib import Path

import paramiko

from vpn.config import SSH_PRIVATE_KEY_PATH


def _get_key() -> paramiko.PKey:
    key_path = Path(os.path.expanduser(SSH_PRIVATE_KEY_PATH))
    if not key_path.exists():
        raise FileNotFoundError(f"SSH key not found: {key_path}")
    # Try loading key directly (works for unencrypted keys)
    for key_class in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return key_class.from_private_key_file(str(key_path))
        except (paramiko.SSHException, ValueError):
            continue
    # Key is likely passphrase-protected — try ssh-agent
    try:
        agent = paramiko.Agent()
        agent_keys = agent.get_keys()
        if agent_keys:
            return agent_keys[0]
    except Exception:
        pass
    raise paramiko.SSHException(
        f"Could not load SSH key from {key_path}. "
        f"If the key is passphrase-protected, add it to ssh-agent: ssh-add {key_path}"
    )


def _ssh_exec(ip: str, command: str) -> tuple[int, str]:
    key = _get_key()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username="root", pkey=key, timeout=10)
        _, stdout, stderr = client.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode().strip()
        return exit_code, output
    finally:
        client.close()


async def wait_for_ssh(ip: str, timeout: int = 300, on_progress=None) -> bool:
    elapsed = 0
    interval = 5
    while elapsed < timeout:
        try:
            exit_code, _ = await asyncio.to_thread(_ssh_exec, ip, "echo ok")
            if exit_code == 0:
                return True
        except Exception as e:
            if on_progress:
                await on_progress(f"Waiting for SSH... ({elapsed}s, {type(e).__name__})")
        await asyncio.sleep(interval)
        elapsed += interval
    return False


async def run_script(ip: str, script: str, timeout: int = 600, on_output=None) -> tuple[int, str]:
    """Encode script as base64, decode on remote, execute. Streams output via channel recv."""
    def _run():
        key = _get_key()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(ip, username="root", pkey=key, timeout=10)
            # Base64-encode the script so it travels as a single safe string
            # No stdin piping, no SFTP — avoids all input conflicts
            encoded = base64.b64encode(script.encode()).decode()
            command = f"echo '{encoded}' | base64 -d > /tmp/_vpn_script.sh && bash /tmp/_vpn_script.sh"
            channel = client.get_transport().open_session()
            channel.settimeout(timeout)
            channel.exec_command(command)

            # Read stdout in chunks, split into lines for streaming
            buf = ""
            output_lines = []
            while True:
                if channel.exit_status_ready() and not channel.recv_ready():
                    break
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode(errors="replace")
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        output_lines.append(line)
                        if on_output:
                            on_output(line)
                else:
                    import time
                    time.sleep(0.1)
            # Flush remaining buffer
            if buf.strip():
                output_lines.append(buf.strip())
                if on_output:
                    on_output(buf.strip())

            exit_code = channel.recv_exit_status()
            # Read stderr
            err_buf = ""
            while channel.recv_stderr_ready():
                err_buf += channel.recv_stderr(4096).decode(errors="replace")

            output = "\n".join(output_lines)
            return exit_code, f"{output}\n{err_buf}".strip()
        finally:
            client.close()
    return await asyncio.to_thread(_run)


async def download_file(ip: str, remote_path: str) -> bytes:
    """Download a file from the remote server via SFTP."""
    def _download():
        key = _get_key()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(ip, username="root", pkey=key, timeout=10)
            sftp = client.open_sftp()
            with sftp.open(remote_path, "rb") as f:
                return f.read()
        finally:
            client.close()
    return await asyncio.to_thread(_download)


async def list_remote_files(ip: str, directory: str) -> list[str]:
    """List files in a remote directory."""
    exit_code, output = await asyncio.to_thread(
        _ssh_exec, ip, f"ls -1 {directory}"
    )
    if exit_code != 0:
        return []
    return [f for f in output.split("\n") if f.strip()]


_INSTALL_SCRIPT_TEMPLATE = r"""
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "[1/8] Stopping automatic updates and clearing apt locks..."
# Stop and disable all automatic update services
systemctl kill --signal=SIGKILL unattended-upgrades.service 2>/dev/null || true
systemctl stop apt-daily.service apt-daily-upgrade.service 2>/dev/null || true
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service 2>/dev/null || true
# Force-kill any apt/dpkg processes
killall -9 unattended-upgr unattended-upgrade apt-get dpkg apt 2>/dev/null || true
sleep 3
# Remove all lock files and fix any interrupted dpkg state
rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/lib/apt/lists/lock /var/cache/apt/archives/lock
dpkg --configure -a 2>/dev/null || true
echo "  Locks clear."

echo "[2/8] Installing packages (openvpn, easy-rsa, iptables-persistent)..."
# Pre-seed debconf so iptables-persistent doesn't prompt
echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections
apt-get update -qq
apt-get install -y -qq openvpn easy-rsa iptables-persistent > /dev/null
echo "  Packages installed."

echo "[3/8] Setting up Easy-RSA PKI..."
EASYRSA_DIR=/etc/openvpn/easy-rsa
mkdir -p "$EASYRSA_DIR"
cp -r /usr/share/easy-rsa/* "$EASYRSA_DIR/"
cd "$EASYRSA_DIR"

cat > vars << 'VARS'
set_var EASYRSA_BATCH     "yes"
set_var EASYRSA_REQ_CN    "OpenVPN-CA"
set_var EASYRSA_ALGO      ec
set_var EASYRSA_CURVE     secp384r1
set_var EASYRSA_DIGEST    "sha384"
VARS

echo "[4/8] Generating certificates and keys..."
echo "  init-pki..."
./easyrsa init-pki
echo "  build-ca..."
./easyrsa build-ca nopass
echo "  gen-req server..."
./easyrsa gen-req server nopass
echo "  sign-req server..."
./easyrsa sign-req server server
echo "  gen-dh (this may take a moment)..."
./easyrsa gen-dh
echo "  gen tls-auth key..."
openvpn --genkey secret /etc/openvpn/ta.key
echo "  Certificates and keys ready."

echo "[5/8] Writing server config..."
cat > /etc/openvpn/server/server.conf << SCONF
port %%PORT%%
proto %%PROTO%%
dev tun
ca /etc/openvpn/easy-rsa/pki/ca.crt
cert /etc/openvpn/easy-rsa/pki/issued/server.crt
key /etc/openvpn/easy-rsa/pki/private/server.key
dh /etc/openvpn/easy-rsa/pki/dh.pem
tls-auth /etc/openvpn/ta.key 0
cipher AES-256-GCM
auth SHA384
server 10.8.0.0 255.255.255.0
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 1.1.1.1"
push "dhcp-option DNS 8.8.8.8"
keepalive 10 120
persist-key
persist-tun
user nobody
group nogroup
status /var/log/openvpn-status.log
verb 3
SCONF

echo "[6/8] Enabling IP forwarding..."
sed -i 's/#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/' /etc/sysctl.conf
sysctl -p
echo "  IP forwarding enabled."

echo "[7/8] Configuring NAT / iptables..."
IFACE=$(ip route show default | awk '/default/ {print $5}')
echo "  Default interface: $IFACE"
iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o "$IFACE" -j MASQUERADE
iptables -A FORWARD -i tun0 -o "$IFACE" -j ACCEPT
iptables -A FORWARD -i "$IFACE" -o tun0 -m state --state RELATED,ESTABLISHED -j ACCEPT
netfilter-persistent save
echo "  NAT rules saved."

mkdir -p /etc/openvpn/clients

echo "[8/8] Starting OpenVPN service..."
systemctl enable openvpn-server@server
systemctl start openvpn-server@server

echo "OPENVPN_SETUP_DONE"
"""


def _build_install_script(port: str, proto: str) -> str:
    return _INSTALL_SCRIPT_TEMPLATE.replace("%%PORT%%", port).replace("%%PROTO%%", proto)



_CLIENT_GEN_TEMPLATE = r"""
set -euo pipefail
cd /etc/openvpn/easy-rsa

# Generate client key pair
./easyrsa gen-req %%CLIENT%% nopass
./easyrsa sign-req client %%CLIENT%%

# Build .ovpn
CA=$(cat pki/ca.crt)
CERT=$(openssl x509 -in pki/issued/%%CLIENT%%.crt)
KEY=$(cat pki/private/%%CLIENT%%.key)
TA=$(cat /etc/openvpn/ta.key)

cat > /etc/openvpn/clients/%%CLIENT%%.ovpn << OVPN
client
dev tun
proto %%PROTO%%
remote %%HOST%% %%PORT%%
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-GCM
auth SHA384
key-direction 1
verb 3
<ca>
$CA
</ca>
<cert>
$CERT
</cert>
<key>
$KEY
</key>
<tls-auth>
$TA
</tls-auth>
OVPN

echo "/etc/openvpn/clients/%%CLIENT%%.ovpn"
"""


def _build_client_gen_script(client_name: str, dns_hostname: str, port: str, proto: str) -> str:
    return (_CLIENT_GEN_TEMPLATE
            .replace("%%CLIENT%%", client_name)
            .replace("%%HOST%%", dns_hostname)
            .replace("%%PORT%%", port)
            .replace("%%PROTO%%", proto))


async def install_openvpn(ip: str, port: str, proto: str, on_progress=None) -> tuple[bool, str]:
    """Install and configure OpenVPN on a droplet. Returns (success, output)."""
    script = _build_install_script(port, proto)
    loop = asyncio.get_running_loop()

    def _on_line(line: str):
        if on_progress and line.strip():
            asyncio.run_coroutine_threadsafe(on_progress(f"  {line}"), loop)

    exit_code, output = await run_script(ip, script, timeout=600, on_output=_on_line)
    success = exit_code == 0 and "OPENVPN_SETUP_DONE" in output
    return success, output


async def generate_client_config(ip: str, client_name: str, dns_hostname: str, port: str, proto: str) -> tuple[bool, str]:
    """Generate a client .ovpn file on the server. Returns (success, remote_path)."""
    script = _build_client_gen_script(client_name, dns_hostname, port, proto)
    exit_code, output = await run_script(ip, script, timeout=120)
    if exit_code != 0:
        return False, output
    remote_path = f"/etc/openvpn/clients/{client_name}.ovpn"
    return True, remote_path


async def ensure_openvpn_running(ip: str, port: str = "443", retries: int = 5) -> tuple[bool, str]:
    """Ensure OpenVPN is running AND listening on the expected port.
    Returns (success, diagnostic_info)."""
    for i in range(retries):
        try:
            # Check if port is actually listening — this is what matters
            exit_code, output = await asyncio.to_thread(
                _ssh_exec, ip, f"ss -tlnp | grep :{port}"
            )
            if exit_code == 0 and output.strip():
                return True, "OpenVPN listening"

            # Port not listening — check service status and try to fix
            _, svc_status = await asyncio.to_thread(
                _ssh_exec, ip, "systemctl status openvpn-server@server 2>&1 || true"
            )

            # Restart the service
            await asyncio.to_thread(
                _ssh_exec, ip, "systemctl restart openvpn-server@server"
            )
            await asyncio.sleep(3)

            # Check port again after restart
            exit_code, output = await asyncio.to_thread(
                _ssh_exec, ip, f"ss -tlnp | grep :{port}"
            )
            if exit_code == 0 and output.strip():
                return True, "OpenVPN listening after restart"

        except Exception:
            pass

        if i < retries - 1:
            await asyncio.sleep(5)

    # All retries failed — gather diagnostics
    diag_lines = []
    try:
        _, svc = await asyncio.to_thread(
            _ssh_exec, ip, "systemctl status openvpn-server@server 2>&1 || true"
        )
        diag_lines.append(f"Service status:\n{svc}")
        _, journal = await asyncio.to_thread(
            _ssh_exec, ip, "journalctl -u openvpn-server@server --no-pager -n 30 2>&1 || true"
        )
        diag_lines.append(f"Journal:\n{journal}")
        _, conf = await asyncio.to_thread(
            _ssh_exec, ip, "ls -la /etc/openvpn/server/ 2>&1 && head -5 /etc/openvpn/server/server.conf 2>&1 || true"
        )
        diag_lines.append(f"Config:\n{conf}")
    except Exception as e:
        diag_lines.append(f"Diagnostic collection failed: {e}")

    return False, "\n".join(diag_lines)
