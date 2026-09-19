# check_dns_resolution.py

## Description
Test local server DNS resolution (127.0.0.1) on NethSecurity 8.8, checking speed and reliability.

## Features
- Test resolution of public domains (google.com, cloudflare.com, dns.google)
- Sends a raw UDP DNS query directly to 127.0.0.1:53 (local dnsmasq) - not the system resolver, which may be configured with a different server entirely
- Measure average response time in milliseconds
- Threshold: WARNING if > 500ms, CRITICAL if > 1000ms or no response

## States
- **OK (0)**: All tests OK and time < 500ms
- **WARNING (1)**: Some tests failed or time > 500ms (but < 1000ms)
- **CRITICAL (2)**: All tests failed or time > 1000ms

## Output CheckMK
```
0 DNS.Resolution response_time=45ms;500;1000|successful=3|failed=0|total=3 Test: 3/3 OK, avg time: 45ms - OK
```

## Performance Data
- `response_time`: Average response time with threshold
- `successful`: Number of successful tests
- `failed`: Number of failed tests
- `total`: Total number of tests

## Requirements
- Python 3 (raw DNS query via stdlib `socket`/`struct`, no external DNS library needed)
- dnsmasq or other DNS resolver listening on 127.0.0.1:53
- Internet access to resolve public domains

## Installation
```bash
cp check_dns_resolution.py /usr/lib/check_mk_agent/local/check_dns_resolution
chmod +x /usr/lib/check_mk_agent/local/check_dns_resolution
```

## Manual testing
```bash
python3 /opt/checkmk-tools/script-check-nsec8/full/check_dns_resolution.py
```

## Notes
- Test on public domains to verify complete chain (local → upstream)
- Slow DNS can indicate:
  - Upstream DNS overloaded or slow
  - WAN connectivity issues
  - dnsmasq overloaded (many queries)
- Failures can indicate:
  - dnsmasq not running
  - Upstream DNS unreachable
  - WAN problems
