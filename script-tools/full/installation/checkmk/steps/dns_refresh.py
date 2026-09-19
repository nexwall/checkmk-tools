from __future__ import annotations

from pathlib import Path

from lib.common import backup_file, log_header, log_info, log_success, log_warn, run as run_cmd
from lib.config import InstallerConfig

_CRON_FILE_NAME = "dns-refresh"
_CRON_CONTENT = """\
# Refresh DNS cache every 30 seconds, reload CheckMK config every 5 minutes.
# Needed for DHCP hosts that can change IP address.
* * * * * cmk --update-dns-cache > /dev/null 2>&1
* * * * * sleep 30 && cmk --update-dns-cache > /dev/null 2>&1
*/5 * * * * cmk -R > /dev/null 2>&1"""


def run(cfg: InstallerConfig) -> None:
    log_header("72-DNS-REFRESH-CRON")

    cron_dir = Path("/omd/sites") / cfg.site_name / "etc" / "cron.d"
    cron_file = cron_dir / _CRON_FILE_NAME

    if not cron_dir.exists():
        log_warn(f"OMD cron directory not found: {cron_dir}. CheckMK site '{cfg.site_name}' might not be installed yet. Skip.")
        return

    if cron_file.exists():
        backup_file(cron_file)

    log_info(f"Writing DNS refresh cron: {cron_file}")
    cron_file.write_text(_CRON_CONTENT, encoding="utf-8")

    log_info("Reloading OMD crontab ...")
    run_cmd(["su", "-", cfg.site_name, "-c", "omd reload crontab"], check=False)

    log_success(f"DNS refresh cron installed (every 5 min: cmk --update-dns-cache ; cmk -R)")
