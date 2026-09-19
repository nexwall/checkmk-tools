#!/usr/bin/env python3
"""install_frpc.py - Standalone FRPC Installer

Quick installation and configuration of FRPC (Fast Reverse Proxy Client).
Supports Linux (systemd) and OpenWrt (procd).

Usage:
    install_frpc.py [options]

Options:
    --uninstall Remove FRPC

Env Vars:
    FRP_VERSION FRPC version (e.g. 0.64.0)

Version: 1.0.0"""

import sys
import os
import shutil
import tarfile
import tempfile
import platform
import urllib.request
from pathlib import Path

# --- Configuration ---
DEFAULT_FRP_VER = "0.64.0"

class Console:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    NC = '\033[0m'
    
    @staticmethod
    def log(msg): print(f"[INFO] {msg}")
    @staticmethod
    def error(msg): print(f"{Console.RED}[ERROR] {msg}{Console.NC}"); sys.exit(1)
    @staticmethod
    def success(msg): print(f"{Console.GREEN}[OK] {msg}{Console.NC}")

def http_get(url, dest):
    try:
        with urllib.request.urlopen(url) as response, open(dest, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        Console.error(f"Download error: {e}")

def run_cmd(cmd):
    if os.system(" ".join(cmd)) != 0: return False
    return True

class FRPCInstaller:
    def __init__(self):
        self.version = os.environ.get("FRP_VERSION", DEFAULT_FRP_VER)
        self.os_type = "openwrt" if Path("/etc/openwrt_release").exists() else "linux"
        
    def install(self):
        Console.log(f"Installazione FRPC {self.version} ({self.os_type})...")
        
        arch = platform.machine()
        if arch == "x86_64": arch = "amd64"
        elif arch in ["aarch64", "arm64"]: arch = "arm64"
        
        url = f"https://github.com/fatedier/frp/releases/download/v{self.version}/frp_{self.version}_linux_{arch}.tar.gz"
        tmp_dir = Path(tempfile.mkdtemp())
        tar_path = tmp_dir / "frp.tgz"
        
        Console.log(f"Download: {url}")
        http_get(url, tar_path)
        
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=tmp_dir)
            
        bin_found = list(tmp_dir.rglob("frpc"))
        if not bin_found: Console.error("Binario non trovato")
        
        shutil.copy2(bin_found[0], "/usr/local/bin/frpc")
        os.chmod("/usr/local/bin/frpc", 0o755)
        shutil.rmtree(tmp_dir)
        
        self.configure()
        
    def configure(self):
        hostname = platform.node()
        print("\nConfigurazione:")
        host = input(f"Nome host [{hostname}]: ").strip() or hostname
        server = input("FRP server address: ").strip() or os.environ.get("FRP_SERVER", "")
        port = input("Porta remota: ").strip()
        token = input("Token: ").strip()
        
        if not port or not token: Console.error("Dati mancanti")
        
        Path("/etc/frp").mkdir(exist_ok=True)
        config = f"""[common]
server_addr = "{server}"
server_port = 7000
auth.method = "token"
auth.token = "{token}"
tls.enable = true
log.to = "/var/log/frpc.log"
log.level = "info"

[{host}]
type = "tcp"
local_ip = "127.0.0.1"
local_port = 6556
remote_port = {port}"""
        with open("/etc/frp/frpc.toml", "w") as f: f.write(config)
        
        if self.os_type == "openwrt":
            init = """#!/bin/sh /etc/rc.common
START=99
STOP=10
USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command /usr/local/bin/frpc -c /etc/frp/frpc.toml
    procd_set_param respawn
    procd_close_instance
}"""
            with open("/etc/init.d/frpc", "w") as f: f.write(init)
            os.chmod("/etc/init.d/frpc", 0o755)
            run_cmd(["/etc/init.d/frpc", "enable"])
            run_cmd(["/etc/init.d/frpc", "restart"])
        else:
            service = """[Unit]
Description=FRP Client Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frpc -c /etc/frp/frpc.toml
Restart=on-failure
RestartSec=5s
User=root

[Install]
WantedBy=multi-user.target"""
            with open("/etc/systemd/system/frpc.service", "w") as f: f.write(service)
            run_cmd(["systemctl", "daemon-reload"])
            run_cmd(["systemctl", "enable", "--now", "frpc"])
            
        Console.success("FRPC Installato e Avviato")

    def uninstall(self):
        Console.log("Disinstallazione...")
        if self.os_type == "openwrt":
            run_cmd(["/etc/init.d/frpc", "stop"])
            run_cmd(["/etc/init.d/frpc", "disable"])
            if Path("/etc/init.d/frpc").exists(): os.remove("/etc/init.d/frpc")
        else:
            run_cmd(["systemctl", "disable", "--now", "frpc"])
            if Path("/etc/systemd/system/frpc.service").exists(): os.remove("/etc/systemd/system/frpc.service")
            run_cmd(["systemctl", "daemon-reload"])
            
        if Path("/usr/local/bin/frpc").exists(): os.remove("/usr/local/bin/frpc")
        if Path("/etc/frp").exists(): shutil.rmtree("/etc/frp")
        Console.success("Disinstallato")

def main():
    if os.geteuid() != 0: Console.error("Serve root")
    
    installer = FRPCInstaller()
    if "--uninstall" in sys.argv:
        installer.uninstall()
    else:
        installer.install()

if __name__ == "__main__":
    main()
