#!/usr/bin/env python3
# M@il
# Bulk: yes
# CheckMK notification script - sends HTML email with real IP and FRP tunnel detection.
# Version: 1.0.0

import os
import sys
import subprocess
from urllib.parse import quote

VERSION = "1.0.0"

# === CONFIG ===
CMK_URL = os.environ.get("CMK_URL", "https://<your-checkmk-server>/monitoring")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "checkmk@example.com")
# ==============


def get_color(state):
    """Get color for state badge."""
    state_upper = state.upper()
    if state_upper in ["OK", "UP"]:
        return "#13d389"
    elif state_upper in ["WARNING", "WARN"]:
        return "#ffd700"
    elif state_upper in ["CRITICAL", "CRIT", "DOWN"]:
        return "#ff5151"
    else:
        return "#ff9800"


def get_label(state):
    """Get abbreviated label for state."""
    state_upper = state.upper()
    if state_upper == "WARNING":
        return "WARN"
    elif state_upper == "CRITICAL":
        return "CRIT"
    elif state_upper == "UNKNOWN":
        return "UNKN"
    else:
        return state_upper


def main():
    # Get CheckMK environment variables
    to_email = os.getenv("NOTIFY_CONTACTEMAIL", "root@localhost")
    hostname = os.getenv("NOTIFY_HOSTNAME", "Unknown")
    site = os.getenv("NOTIFY_OMD_SITE", "monitoring")
    date = os.getenv("NOTIFY_SHORTDATETIME", "")
    
    # Real IP or fallback
    host_address = os.getenv("NOTIFY_HOSTADDRESS", "N/A")
    real_ip = os.getenv("NOTIFY_HOSTLABEL_real_ip", host_address)
    frp = os.getenv("NOTIFY_HOSTLABEL_frp_tunnel", "no")
    
    # Service or Host notification?
    service_desc = os.getenv("NOTIFY_SERVICEDESC")
    
    if service_desc:
        # Service notification
        old_state = os.getenv("NOTIFY_PREVIOUSSERVICEHARDSHORTSTATE", "OK")
        new_state = os.getenv("NOTIFY_SERVICESHORTSTATE", "UNKNOWN")
        output = os.getenv("NOTIFY_SERVICEOUTPUT", "N/A")
        long_output = os.getenv("NOTIFY_LONGSERVICEOUTPUT", "")
        service = service_desc
        subject = f"Checkmk: {hostname}/{service} {new_state}"
    else:
        # Host notification
        old_state = os.getenv("NOTIFY_PREVIOUSHOSTHARDSHORTSTATE", "UP")
        new_state = os.getenv("NOTIFY_HOSTSHORTSTATE", "DOWN")
        output = os.getenv("NOTIFY_HOSTOUTPUT", "N/A")
        long_output = os.getenv("NOTIFY_LONGHOSTOUTPUT", "")
        service = "Host Check"
        subject = f"Checkmk: {hostname} {new_state}"
    
    # Replace IP on output
    if host_address and host_address != real_ip:
        output = output.replace(host_address, real_ip)
        long_output = long_output.replace(host_address, real_ip)
    
    # Combine outputs
    full_output = output
    if long_output:
        full_output += "<br>" + long_output.replace("\n", "<br>")
    
    # Colors and labels
    old_color = get_color(old_state)
    new_color = get_color(new_state)
    old_label = get_label(old_state)
    new_label = get_label(new_state)
    
    # FRP info row
    frp_row = ""
    if frp == "yes":
        frp_row = f'<tr><td>FRP Tunnel:</td><td><span style="color:#00d4aa;font-weight:600"> Active</span> (Real IP: {real_ip})</td></tr>'
    
    # CheckMK links
    cmk_url = CMK_URL.rstrip("/")
    h_enc = quote(hostname)
    srv_enc = quote(service)
    
    if service != "Host Check":
        srv_link = f"{cmk_url}/check_mk/view.py?view_name=service&host={h_enc}&service={srv_enc}"
    else:
        srv_link = f"{cmk_url}/check_mk/view.py?view_name=host&host={h_enc}"
    
    host_link = f"{cmk_url}/check_mk/view.py?view_name=host&host={h_enc}"
    
    # Output for summary (single line)
    output_summary = output.replace("\n", "<br>")
    
    # Build email
    email_content = f"""To: {to_email}
From: {FROM_EMAIL}
Subject: {subject}
Content-Type: text/html; charset=UTF-8
MIME Version: 1.0

<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px}}
.container{{max-width:650px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1);border:2px solid #e0e0e0}}
.header{{background:#f8f9fa;padding:20px;display:flex;align-items:center;gap:10px;border-bottom:2px solid #d0d0d0}}
.logo-icon{{width:24px;height:24px;background:#00d4aa;border-radius:4px;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:14px}}
.logo-text{{color:#00d4aa;font-size:18px;font-weight:600}}
.status-bar{{background:linear-gradient(90deg,{old_color} 0%,{old_color} 48%,#666 48%,#666 52%,{new_color} 52%,{new_color} 100%);height:6px;border-bottom:1px solid rgba(0,0,0,.15)}}
.content{{padding:30px}}
.event-row{{background:#f8f9fa;padding:15px 20px;border-radius:6px;margin-bottom:20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;border:1px solid #e0e0e0}}
.event-label{{color:#666;font-size:14px;font-weight:500}}
.event-value{{color:#333;font-size:14px;word-break:break-word}}
.state-badge{{padding:6px 14px;border-radius:4px;font-weight:600;font-size:13px;color:#fff;background-color:{new_color};white-space:nowrap}}
.section-title{{color:#999;font-size:18px;font-weight:600;margin:20px 0 15px}}
.info-table{{width:100%;border-collapse:collapse;margin-bottom:25px}}
.info-table td{{padding:10px 0;border-bottom:1px solid #e0e0e0;word-break:break-word}}
.info-table td:first-child{{color:#333;font-weight:600;width:140px}}
.info-table td:last-child{{color:#666}}
.service-details{{background:linear-gradient(135deg,#fafafa 0%,#f5f5f5 100%);padding:20px;border-radius:8px;border:1px solid {new_color};border-left:6px solid {new_color};margin-top:15px;overflow-x:auto;box-shadow:0 2px 4px rgba(0,0,0,.05)}}
.service-details pre{{margin:0;white-space:pre-wrap;word-wrap:break-word;font-family:'Courier New',monospace;font-size:13px;color:#333;line-height:1.6}}
.footer{{background:#f8f8f8;padding:20px;text-align:center;color:#666;font-size:13px}}
.buttons{{margin-top:15px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap}}
.btn{{display:inline-block;padding:12px 24px;background:{new_color};color:#fff;text-decoration:none;border-radius:4px;font-weight:600;font-size:14px;min-width:120px;border:2px solid #000;transition:filter 0.2s}}
.btn:hover{{filter:brightness(0.85)}}
@media(max-width:600px){{
body{{padding:10px}}
.content{{padding:15px}}
.header{{padding:15px}}
.event-row{{padding:12px 15px;flex-direction:column;align-items:flex-start}}
.info-table td:first-child{{width:100px;font-size:13px}}
.info-table td:last-child{{font-size:13px}}
.section-title{{font-size:16px}}
.btn{{width:100%;min-width:auto;padding:14px 20px;font-size:15px}}
.buttons{{gap:8px}}
}}
</style></head>
<body>
<div class="container">
<div class="header"><div class="logo-icon"></div><span class="logo-text">checkmk</span></div>
<div class="status-bar"></div>
<div class="content">
<div class="event-row"><span class="event-label">Event:</span><div><span class="state-badge" style="background:{old_color}">{old_label}</span> → <span class="state-badge">{new_label}</span></div></div>
<div class="event-row"><span class="event-label">Service:</span><span class="event-value">{service}</span></div>
<div class="event-row"><span class="event-label">Host:</span><span class="event-value">{hostname}</span></div>
<h2 class="section-title"> Event overview</h2>
<table class="info-table">
<tr><td>Event date:</td><td>{date}</td></tr>
<tr><td>Address:</td><td>{real_ip}</td></tr>
{frp_row}
<tr><td>Site:</td><td>{site}</td></tr>
<tr><td>Summary:</td><td>{output_summary}</td></tr>
</table>
<h2 class="section-title"> Service details:</h2>
<div class="service-details"><pre>{full_output}</pre></div>
</div>
<div class="footer">Sent by Checkmk<div class="buttons"><a href="{srv_link}" class="btn">Service</a><a href="{host_link}" class="btn">Host</a></div></div>
</div>
</body>
</html>"""
    
    # Send via sendmail
    try:
        proc = subprocess.run(
            ["/usr/sbin/sendmail", "-t"],
            input=email_content.encode("utf-8"),
            timeout=30
        )
        return proc.returncode
    except subprocess.TimeoutExpired:
        print("ERROR: sendmail timeout", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("ERROR: sendmail not found", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
