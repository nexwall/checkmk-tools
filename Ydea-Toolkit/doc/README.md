# Ydea API Toolkit

Complete system for managing Ydea v2 APIs, with a focus on ticket creation and management, integration with monitoring systems, and workflow automation.

## Index

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Practical Examples](#practical-examples)
- [Monitoring Integration](#monitoring-integration)
- [Best Practices](#best-practices)

## Features

- **Automatic token management** with automatic refresh
- **Helper functions** for common ticket operations
- **Automatic retry** on 401 errors
- **Integration of monitoring systems** (Netdata, custom)
- **Duplicate prevention** via intelligent caching
- **Export data** in CSV/JSON formats
- **Structured logging** with timestamp and emoji
- **Example script** for common use cases

## Requirements

- **bash** >= 4.0
- **curls**
- **jq** (JSON parser)

### Installing dependencies

```bash
# Debian/Ubuntu
sudo apt-get install curl jq

# RHEL/CentOS/Fedora
sudo yum install curl jq

# macOS
brew install curl jq
```

## Installation

```bash
#1. Download the files
git clone <repository> ydea-toolkit
cd ydea-toolkit

#2. Make scripts executable
chmod +x ydea-toolkit.sh examples-ydea.sh ydea-monitoring-integration.sh

#3. Copy and configure credentials
cp .env.example .env
nano .env # Enter YDEA_ID and YDEA_API_KEY
```

## Configuration

### 1. Get your API credentials

1. Login to [Ydea](https://my.ydea.cloud)
2. Go to **Settings** → **My Company** → **API**
3. Copy **ID** and **API Key**

### 2. Configure the .env file

```bash
# Credentials (MANDATORY)
export YDEA_ID="your_company_id"
export YDEA_API_KEY="your_api_key"

# Optional
export YDEA_BASE_URL="https://my.ydea.cloud/app_api_v2"
export YDEA_TOKEN_FILE="${HOME}/.ydea_token.json"
export YDEA_DEBUG=0 # Set 1 for verbose debugging
```

### 3. Load the variables

```bash
source .env
```

### 4. Test the connection

```bash
./ydea-toolkit.sh login
# Expected output: Login (valid token ~1h)
```

## Usage

### Basic Commands

```bash
# Login (done automatically when needed)
./ydea-toolkit.sh login

# Ticket list
./ydea-toolkit.sh list [limit] [status]

# Ticket details
./ydea-toolkit.sh get <ticket_id>

# Search tickets
./ydea-toolkit.sh search "<query>" [limit]

# Create ticket
./ydea-toolkit.sh create "<title>" "<description>" [priority] [category_id]

# Update ticket
./ydea-toolkit.sh update <ticket_id> '<json_updates>'

# Add comment
./ydea-toolkit.sh comment <ticket_id> "<text>"

# Close ticket
./ydea-toolkit.sh close <ticket_id> "<note>"

# Category list
./ydea-toolkit.sh categories

# User list
./ydea-toolkit.sh users [limit]

# Generic API call
./ydea-toolkit.sh api <METHOD> </path> [json_body]
```

## Practical Examples

### Example 1: List of last 10 open tickets

```bash
./ydea-toolkit.sh list 10 open | jq '.data[] | {id, title, priority}'
```

Outputs:
```json
{
  "id": 12345,
  "title": "Server unreachable",
  "priority": "high"
}
...
```

### Example 2: Create ticket from script

```bash
#!/bin/bash
RESULT=$(./ydea-toolkit.sh create \
  "Backup failed on server-prod" \
  "Nightly backup was not completed. Log attached." \
  "high")

TICKET_ID=$(echo "$RESULT" | jq -r '.id')
echo "Ticket created: #$TICKET_ID"
```

### Example 3: Complete workflow

```bash
#1. Create tickets
TICKET=$(./ydea-toolkit.sh create "Scheduled maintenance" "Deploy new version")
ID=$(echo "$TICKET" | jq -r '.id')

#2. Add comment
./ydea-toolkit.sh comment "$ID" "Maintenance started at $(date)"

#3. Update Status
./ydea-toolkit.sh update "$ID" '{"status":"in_progress"}'

#4. ...perform operations...

#5. Close
./ydea-toolkit.sh close "$ID" "Maintenance completed successfully"
```

### Example 4: Daily report via email

```bash
#!/bin/bash
{
  echo "=== DAILY TICKET REPORT ==="
  echo ""
  echo "OPEN tickets:"
  ./ydea-toolkit.sh list 100 open | jq -r '.data[] | " - #\(.id): \(.title)"'
  echo ""
  echo "Tickets CLOSED TODAY:"
  ./ydea-toolkit.sh list 50 closed | jq -r '.data[] | select(.closed_at | startswith("2025-11-11")) | " - #\(.id): \(.title)"'
} | mail -s "Report Ydea $(date +%Y-%m-%d)" admin@example.com
```

### Example 5: Export to CSV

```bash
./ydea-toolkit.sh list 1000 | jq -r '
  ["ID","Title","Status","Priority","Date"] as $headers |
($headers | @csv),
  (.data[] | [.id, .title, .status, .priority, .created_at] | @csv)
' > tickets_export.csv
```

## Monitoring Integration

### Automatic Monitoring

The `ydea-monitoring-integration.sh` script automatically creates tickets when it detects problems:

```bash
# Full monitoring (CPU, RAM, Disk)
./ydea-monitoring-integration.sh monitor

# Monitor specific service
./ydea-monitoring-integration.sh service nginx
./ydea-monitoring-integration.sh service postgresql
```

### CRON configuration

```bash
# Add to crontab -e
*/5 * * * * cd /path/to/ydea-toolkit && ./ydea-monitoring-integration.sh monitor >> /var/log/ydea-monitor.log 2>&1

# Monitor critical services every minute
* * * * * cd /path/to/ydea-toolkit && ./ydea-monitoring-integration.sh service nginx >> /var/log/ydea-monitor.log 2>&1
```

### Netdata integration

1. Configure Netdata to send custom notifications:

```bash
# /etc/netdata/health_alarm_notify.conf
SEND_CUSTOM="YES"
DEFAULT_RECIPIENT_CUSTOM="ydea"

# Custom notification script
cat > /usr/local/bin/netdata-to-ydea.sh << 'EOF'
#!/bin/bash
cd /path/to/ydea-toolkit
source .env

cat << JSON | ./ydea-monitoring-integration.sh netdata-webhook
{
  "alarm": "${alarm}",
  "status": "${status}",
  "hostname": "${host}",
  "value": "${value}",
  "chart": "${chart}",
  "info": "${info}"
}
JSON
EOF

chmod +x /usr/local/bin/netdata-to-ydea.sh
```

2. Restart Netdata:

```bash
sudo systemctl restart netdata
```

### Alert from Custom Script

```bash
#!/bin/bash
# check-website.sh - Check site availability

SITE="https://example.com"
if ! curl -f -s -o /dev/null "$SITE"; then
  cd /path/to/ydea-toolkit
  source .env
  
  ./ydea-toolkit.sh create \
    "[ALERT] Site $SITE unreachable" \
    "The website is not responding. Check server and DNS." \
    "critical"
fi
```

## Sample Scripts Included

### examples-ydea.sh

Interactive script with menu demonstrating:

1. **Daily ticket report**
2. **Creation of ticket from alert**
3. **Research and update**
4. **Complete Workflow**
5. **Export CSV**

Usage:
```bash
# Interactive menu
./examples-ydea.sh --menu

# Or run individual functions
source examples-ydea.sh
example_daily_report
complete_workflow_example
```

## Best Practices

### 1. Token Management

The token is saved in `~/.ydea_token.json` and automatically renewed. You don't need to log in manually every time.

### 2. Duplicate Prevention

For automatic alerts, use the built-in cache in the monitoring script to avoid duplicate tickets:

```bash
# The cache in /tmp/ydea_tickets_cache.json tracks open alerts
# It is cleaned automatically after 24h
./ydea-monitoring-integration.sh cleanup # manual cleanup
```

### 3. Ticket Priority

Use priorities consistently:
- `critical` - Services down, dataloss
- `high` - Degraded performance, critical alerts
- `normal` - Scheduled maintenance, standard requests
- `low` - Improvements, documentation

### 4. Structured Descriptions

Use markdown in descriptions for readability:

```bash
./ydea-toolkit.sh create "Alert CPU" "
## Alert Details
- Host: server-01
- CPU: 95%
- Threshold: 80%

## Diagnostics
\`\`\`
top -bn1 | head -20
\`\`\`

## Actions
1. Test processes
2. Check log
3. Evaluate scaling
"
```

### 5. Logging

Enable debug for troubleshooting:

```bash
export YDEA_DEBUG=1
./ydea-toolkit.sh list
```

### 6. Error Handling

Always handle errors in scripts:

```bash
if RESULT=$(./ydea-toolkit.sh create "..." "..." 2>&1); then
  TICKET_ID=$(echo "$RESULT" | jq -r '.id')
  echo "Ticket #$TICKET_ID created"
else
  echo " Error: $RESULT" >&2
  # Send notification, write log, etc.
fi
```

## Security

- **Never commit** the `.env` file with credentials
- Use restrictive permissions: `chmod 600 .env`
- The file token has `644` permissions by default
- Consider using production vaults (Hashicorp Vault, AWS Secrets Manager)

## Troubleshooting

### Login fails

```bash
# Verify credentials
echo "ID: $YDEA_ID"
echo "API_KEY: ${YDEA_API_KEY:0:10}..."

# Test with direct curl
curl -X POST https://my.ydea.cloud/app_api_v2/login \
  -H "Content-Type: application/json" \
  -d "{\"id\":\"$YDEA_ID\",\"api_key\":\"$YDEA_API_KEY\"}"
```

### Token expires immediately

```bash
# Check system clock
give -u
# Must be synchronized with NTP
```

### Errors jq

```bash
# Check jq installation
jq --version

# Test parsing
echo '{"test": "value"}' | jq .
```

## Support
- **Ydea API documentation**: https://my.ydea.cloud/api/doc/v2
- **Issues**: Open an issue on GitHub
- **Email**: support@example.com

## License

MIT License - See LICENSE file

## Contributions

Contributions are welcome! Please:

1. Fork the repository
2. Create branches for features (`git checkout -b feature/new-feature`)
3. Commit changes (`git commit -am 'Added new feature'`)
4. Push to branch (`git push origin feature/new-feature`)
5. Open Pull Request

## Roadmap

- [ ] Two-way webhook support
- [ ] Web dashboard for ticket viewing
- [ ] Integration with Slack/Teams
- [ ] Default ticket templates
- [ ] Advanced reporting
- [ ] Attachment support
- [ ] Interactive CLI with autocompletion

---

**Version**: 1.0.0  
**Last update**: 2025-11-11  
**Author**: Nethesis