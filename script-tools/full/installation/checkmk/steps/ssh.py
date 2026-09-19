from __future__ import annotations

import re
from pathlib import Path

from lib.common import backup_file, command_exists, log_header, log_info, log_success, log_warn, run as run_cmd, run_stdin
from lib.config import InstallerConfig


def _set_sshd_option(sshd_config: Path, key: str, value: str) -> None:
    key_re = re.compile(rf"^\s*#?\s*{re.escape(key)}\s+.*$", re.IGNORECASE)
    lines = sshd_config.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    replaced = False
    out: list[str] = []
    for line in lines:
        if key_re.match(line):
            out.append(f"{key} {value}\n")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append(f"\n{key} {value}\n")
    sshd_config.write_text("".join(out), encoding="utf-8")


def _set_sshd_option_if_active(path: Path, key: str, value: str) -> bool:
    """Same as _set_sshd_option, but only touches the file if `key` is already active
    (non-commented) there. Used for /etc/ssh/sshd_config.d/*.conf drop-ins: on Ubuntu these
    are Include'd near the top of sshd_config, so a live directive there (e.g. cloud-init's
    PasswordAuthentication yes) silently overrides what we set in the main file below."""
    key_re = re.compile(rf"^\s*#?\s*{re.escape(key)}\s+.*$", re.IGNORECASE)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if not any(key_re.match(line) and not line.lstrip().startswith("#") for line in lines):
        return False
    out: list[str] = []
    for line in lines:
        if key_re.match(line) and not line.lstrip().startswith("#"):
            out.append(f"{key} {value}\n")
        else:
            out.append(line)
    path.write_text("".join(out), encoding="utf-8")
    return True


def _dropin_files(sshd_config: Path) -> list[Path]:
    d = sshd_config.parent / "sshd_config.d"
    return sorted(d.glob("*.conf")) if d.is_dir() else []


def _dropin_has_active_key(path: Path, key: str) -> bool:
    key_re = re.compile(rf"^\s*#?\s*{re.escape(key)}\s+.*$", re.IGNORECASE)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return any(key_re.match(line) and not line.lstrip().startswith("#") for line in lines)


def _has_authorized_keys() -> bool:
    candidates = [Path("/root/.ssh/authorized_keys")]
    home_root = Path("/home")
    if home_root.is_dir():
        candidates.extend(home_root.glob("*/.ssh/authorized_keys"))
    return any(p.is_file() and p.stat().st_size > 0 for p in candidates)


def run_step(cfg: InstallerConfig) -> None:
    log_header("10-SSH")
    log_info("Configuring SSH...")

    sshd_config = Path("/etc/ssh/sshd_config")
    if not sshd_config.exists():
        raise RuntimeError("/etc/ssh/sshd_config not found")

    backup = backup_file(sshd_config)
    log_info(f"Backup created: {backup}")

    password_auth = "no"
    if not _has_authorized_keys():
        log_warn("No SSH authorized_keys found for root or any user under /home.")
        log_warn("Keeping PasswordAuthentication yes to avoid locking yourself out.")
        log_warn("Add a public key (e.g. ssh-copy-id) then re-run bootstrap/verify to disable password login.")
        password_auth = "yes"

    settings = {
        "Port": str(cfg.ssh_port),
        "PermitRootLogin": cfg.permit_root_login,
        "PasswordAuthentication": password_auth,
        "PubkeyAuthentication": "yes",
        "X11Forwarding": "no",
        "ClientAliveInterval": str(cfg.client_alive_interval),
        "ClientAliveCountMax": str(cfg.client_alive_countmax),
        "LoginGraceTime": str(cfg.login_grace_time),
    }
    for key, value in settings.items():
        _set_sshd_option(sshd_config, key, value)

    # Ubuntu Includes /etc/ssh/sshd_config.d/*.conf near the top of sshd_config, so an active
    # directive there (e.g. cloud-init's 50-cloud-init.conf) takes precedence over what we just
    # set above. Align any drop-in that already defines one of our keys, so there's no ambiguity.
    for dropin in _dropin_files(sshd_config):
        if any(_dropin_has_active_key(dropin, key) for key in settings):
            backup_file(dropin)
            for key, value in settings.items():
                _set_sshd_option_if_active(dropin, key, value)
            log_info(f"Aligned conflicting directive(s) in drop-in: {dropin}")

    if cfg.root_password and not cfg.root_password.upper().startswith("INSERISCI_"):
        log_info("Setting root password (value not shown)...")
        run_stdin(["chpasswd"], f"root:{cfg.root_password}\n", check=True)
    elif cfg.root_password:
        log_warn("ROOT_PASSWORD looks like a placeholder; skipping root password change.")

    if command_exists("systemctl"):
        run_cmd(["systemctl", "restart", "sshd"], check=False)
        run_cmd(["systemctl", "restart", "ssh"], check=False)

    log_success("SSH configured")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
