from __future__ import annotations

import datetime as _dt
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


VERSION = "1.0.48"


class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    NC = "\033[0m"


def now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def log_header(message: str) -> None:
    print("")
    print(f"{Colors.CYAN}========================================{Colors.NC}")
    print(f"{Colors.CYAN}  {message}{Colors.NC}")
    print(f"{Colors.CYAN}========================================{Colors.NC}")
    print("")


def log_info(message: str) -> None:
    print(f"{Colors.BLUE}[INFO]{Colors.NC} {message}")


def log_success(message: str) -> None:
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {message}")


def log_warn(message: str) -> None:
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {message}")


def log_error(message: str) -> None:
    print(f"{Colors.RED}[ERROR]{Colors.NC} {message}")


def require_root() -> None:
    if os.name != "posix":
        raise SystemExit("This installer must run on Linux (Ubuntu).")
    if os.geteuid() != 0:
        raise SystemExit("This command must be run as root (use sudo).")


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("DEBIAN_FRONTEND", "noninteractive")
    env.setdefault("NEEDRESTART_MODE", "a")
    env.setdefault("APT_LISTCHANGES_FRONTEND", "none")
    return env


@dataclass(frozen=True)
class RunResult:
    returncode: int


def _with_progress_fancy(cmd: list[str]) -> list[str]:
    """Ask apt/apt-get for a real percentage progress bar (harmless on
    non-install subcommands too, e.g. update/purge/autoremove) whenever it's
    attached to a real terminal. Applied centrally here so every step
    benefits without repeating the flag at each apt-get call site."""
    if not cmd or cmd[0] not in ("apt-get", "apt"):
        return cmd
    if "Dpkg::Progress-Fancy=1" in cmd:
        return cmd
    return [cmd[0], "-o", "Dpkg::Progress-Fancy=1", *cmd[1:]]


def run(cmd: list[str], *, check: bool = True) -> RunResult:
    """Run cmd, inheriting stdout/stderr so its own output (including apt's
    real Dpkg::Progress-Fancy percentage bar) still streams live.

    A custom elapsed-time ticker was tried twice (2026-08-03) to reassure
    during phases that sit at the same file-count percentage for a long
    time - both attempts (with and without a leading newline) produced a
    garbled cascade of output, because the ticker thread and the child
    process are two independent, uncoordinated writers to the same
    terminal: the OS can interleave their writes at the byte level no
    matter how carefully either side formats its own output. Properly
    fixing that would mean capturing the child's stdout ourselves and
    proxying it through a single writer - real effort for a cosmetic
    problem. Dropped in favor of relying solely on Dpkg::Progress-Fancy,
    which is safe by construction: apt is the only writer during its own
    operation."""
    cmd = _with_progress_fancy(cmd)
    log_info(f"Running: {shlex.join(cmd)}")
    res = subprocess.run(cmd, env=_child_env())
    if check and res.returncode != 0:
        raise subprocess.CalledProcessError(res.returncode, cmd)
    return RunResult(returncode=res.returncode)


def run_capture(cmd: list[str], *, check: bool = True) -> str:
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_child_env())
    if check and res.returncode != 0:
        raise subprocess.CalledProcessError(res.returncode, cmd, output=res.stdout, stderr=res.stderr)
    return res.stdout.strip()


def run_stdin(cmd: list[str], input_text: str, *, check: bool = True) -> RunResult:
    """Like run(), but feeds `input_text` via stdin instead of embedding secrets in argv/shell strings.

    Use this whenever a command needs a password/secret: passing it as a CLI argument
    would leak it both to `ps`/`/proc/<pid>/cmdline` and to the "Running: ..." log line."""
    log_info(f"Running: {shlex.join(cmd)} (stdin hidden)")
    res = subprocess.run(cmd, input=input_text, text=True, env=_child_env())
    if check and res.returncode != 0:
        raise subprocess.CalledProcessError(res.returncode, cmd)
    return RunResult(returncode=res.returncode)


_BACKUP_DIR = Path("/var/backups/checkmk-installer")


def backup_file(path: Path, dest_dir: Path | None = None) -> Path:
    """Backup to file into dest_dir (default: /var/backups/checkmk-installer/).

    The backup filename encodes the original path so it never lands inside
    sensitive directories like /etc/apt/apt.conf.d/ where apt would complain."""
    if not path.exists():
        return path
    out_dir = dest_dir if dest_dir is not None else _BACKUP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    # encode full path as flat filename: /etc/apt/apt.conf.d/50foo → etc_apt_apt.conf.d_50foo.backup
    flat = str(path).lstrip("/").replace("/", "_")
    backup_path = out_dir / f"{flat}.backup"
    shutil.copy2(path, backup_path)
    return backup_path


def cleanup_backup_files(directory: Path) -> int:
    """Delete all *.backup and *.backup_* files in a directory (not recursive)."""
    count = 0
    for pattern in ("*.backup", "*.backup_*"):
        for f in directory.glob(pattern):
            try:
                f.unlink()
                count += 1
            except Exception:
                pass
    return count
