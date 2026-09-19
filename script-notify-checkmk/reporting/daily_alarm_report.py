#!/usr/bin/env python3
"""Report giornaliero allarmi ricorrenti."""
import sys, os, subprocess
sys.path.insert(0, '/omd/sites/monitoring/local/share/check_mk/notifications')
from analyze_notification_recurrence import parse_notifications, analyze_recurrences, format_dur

SITE = 'monitoring'
FROM_EMAIL = 'srv-monitoring-us@nethesis.it'
TO_EMAIL = os.environ.get('DAILY_REPORT_TO_EMAIL', 'root@localhost')
W = 78  # larghezza box titolo

def send_email(subject, body):
    msg = f"From: {FROM_EMAIL}\nTo: {TO_EMAIL}\nSubject: {subject}\nContent-Type: text/plain; charset=UTF-8\n\n{body}"
    try:
        subprocess.run(["/usr/sbin/sendmail", "-t"], input=msg.encode("utf-8"), timeout=30)
        return True
    except:
        return False

def main():
    events = parse_notifications(SITE)
    rows, total = analyze_recurrences(events)

    flaps = [r for r in rows if r[1] > 3]
    rics = [r for r in rows if 1 <= r[1] <= 3]
    certas = [r for r in rows if r[7] and r[1] < 1]

    now = __import__('datetime').datetime.now().strftime('%d/%m/%Y alle %H:%M')

    lines = []
    lines.append("")
    lines.append("=" * W)
    lines.append("  " + "REPORT ALLARMI RICORRENTI".center(W - 4) + "  ")
    lines.append("  " + "".center(W - 4) + "  ")
    lines.append("  " + now.center(W - 4) + "  ")
    lines.append("=" * W)
    lines.append("")
    lines.append("")
    lines.append("Buongiorno, di seguito il report giornaliero degli allarmi ricorrenti.")
    lines.append("")

    if flaps:
        lines.append(f"  🔴 ALLARMI FREQUENTI (>3 volte/giorno)")
        lines.append("  Potrebbe esserci un problema tecnico da verificare.")
        lines.append("")
        for r in flaps:
            lines.append(f"  \u26a0 {r[3]:22s} {r[4]:12s} {r[1]:.0f} volte/giorno  (dura {format_dur(r[2])})")
        lines.append("")

    if rics:
        lines.append(f"  \U0001f7e1 ALLARMI SALTUARI (1-3 volte/giorno)")
        lines.append("  Potrebbero essere causati da cali di rete momentanei.")
        lines.append("")
        for r in rics:
            lines.append(f"  \u26a1 {r[3]:22s} {r[4]:12s} {r[1]:.0f} volte/giorno  (dura {format_dur(r[2])})")
        lines.append("")

    if certas:
        lines.append(f"  \U0001f7e2 POSSIBILI SPEGNIMENTI PROGRAMMATI")
        lines.append("  Host con comportamenti sistematici")
        lines.append("")
        for r in certas:
            dur_h = r[2] / 3600
            lines.append(f"  \u23f1 {r[3]:22s} spento {r[5]} -> acceso {r[6]}  ({dur_h:.0f} ore)")
        lines.append("")

    lines.append("-" * W)
    lines.append(f"  Totale: {len(rows)} pattern | Prossimo report: domani alle 18:00")
    lines.append("=" * W)

    body = "\n".join(lines)
    print(body)

    subject = f"[Checkmk] Report Allarmi Ricorrenti - {__import__('datetime').datetime.now().strftime('%d/%m/%Y')}"
    ok = send_email(subject, body)
    print(f"\nEmail inviata a {TO_EMAIL}" if ok else "\nERRORE invio email")

if __name__ == '__main__':
    main()
