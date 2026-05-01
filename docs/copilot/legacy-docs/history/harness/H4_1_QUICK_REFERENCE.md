# H4.1 Integration - Quick Reference Guide

## CLI Usage Examples

### Check Autopilot Status
```bash
python recovery_cli.py autopilot status
```
Output:
```
Autopilot Status
├─ State: DISABLED
├─ Is Enabled: False
├─ Is Emergency Stopped: False
└─ Current Policy: None
```

### Enable Autopilot with Conservative Policy
```bash
python recovery_cli.py autopilot enable --policy conservative --reason "Starting recovery operations"
```
Output:
```
✓ Autopilot enabled with policy 'conservative'
  Policy ID: conservative-2026-04-11T10:30:45.123456Z
  Operator: user-id
  Reason: Starting recovery operations
```

### Show Available Policies
```bash
python recovery_cli.py autopilot policy show
```
Output:
```
=== Available Autopilot Policies ===

Policy: Conservative - High Confidence Only
  ID: conservative-2026-04-11T10:30:45.123456Z
  Status: ENABLED
  Confidence Threshold: 90%
  Max Concurrent: 1
  Emergency Stop Enabled: True
  Operator Override Enabled: True

Policy: Standard - Balanced Safety and Responsiveness
  ...

Policy: Permissive - Development/Test Only
  ...
```

### Change Active Policy
```bash
python recovery_cli.py autopilot policy set --policy standard --reason "Upgrading to standard"
```

### Emergency Stop (Incident Response)
```bash
python recovery_cli.py autopilot emergency-stop --reason "Critical incident detected"
```

### Disable Autopilot
```bash
python recovery_cli.py autopilot disable --reason "Operations complete"
```

---

## REST API Examples

### Health Check
```bash
curl http://localhost:8000/recovery/health
```

### Get Recovery Stack Health
```bash
curl http://localhost:8000/recovery/health
```

### Get Autopilot Status
```bash
curl http://localhost:8000/recovery/autopilot/status | jq
```
Response:
```json
{
  "state": "DISABLED",
  "is_enabled": false,
  "is_emergency_stopped": false,
  "current_policy": null,
  "last_state_change": "2026-04-11T10:30:45.123456Z"
}
```

### List Available Policies
```bash
curl http://localhost:8000/recovery/autopilot/policies | jq
```

### Enable Autopilot via API
```bash
curl -X POST http://localhost:8000/recovery/autopilot/enable \
  -H "Content-Type: application/json" \
  -d '{
    "policy": "conservative",
    "reason": "API-initiated enable"
  }' | jq
```

### Set Policy via API
```bash
curl -X POST http://localhost:8000/recovery/autopilot/policy/set \
  -H "Content-Type: application/json" \
  -d '{
    "policy": "standard",
    "reason": "Upgrading policy"
  }' | jq
```

### Emergency Stop via API
```bash
curl -X POST http://localhost:8000/recovery/autopilot/emergency-stop \
  -H "Content-Type: application/json" \
  -d '{"reason": "Incident response"}' | jq
```

### Get Event History
```bash
curl http://localhost:8000/recovery/events?limit=10 | jq
```

### Get Events for Specific Job
```bash
curl http://localhost:8000/recovery/events?job_id=job-123&limit=50 | jq
```

### Export Prometheus Metrics
```bash
curl http://localhost:8000/recovery/metrics
```
Output:
```
# HELP recovery_http_requests_total Total HTTP requests
# TYPE recovery_http_requests_total counter
recovery_http_requests_total{method="GET",path="/recovery/autopilot/status"} 42.0

# HELP recovery_recommendations_generated Total recommendations generated
# TYPE recovery_recommendations_generated counter
recovery_recommendations_generated 156.0
...
```

---

## Policy Descriptions

### Conservative (90% confidence threshold)
- **When to use**: Production environments, critical systems
- **Max concurrent actions**: 1
- **Characteristics**: Requires very high confidence, single-threaded, safest
- **Use case**: Database backups, critical infrastructure recovery

### Standard (80% confidence threshold)
- **When to use**: Normal operations, typical recovery scenarios
- **Max concurrent actions**: 3
- **Characteristics**: Balanced safety and speed, moderate parallelism
- **Use case**: Default for most recovery tasks

### Permissive (70% confidence threshold)
- **When to use**: Development/test environments, non-critical systems
- **Max concurrent actions**: 5
- **Characteristics**: Lower confidence bar, more aggressive parallelism
- **Use case**: Testing, staging environments, rapid prototyping

---

## State Machine

```
DISABLED
   ↓ enable()
ENABLED ←→ EMERGENCY_STOPPED
   ↓          ↑
disable()  emergency_resume()
   ↓          
DISABLED

emergency_stop() can be called from:
- ENABLED → EMERGENCY_STOPPED
- DISABLED → EMERGENCY_STOPPED (prevents re-enabling)
```

---

## Troubleshooting

### Autopilot Won't Enable
```bash
# Check current status
python recovery_cli.py autopilot status

# Try with explicit reason
python recovery_cli.py autopilot enable --policy conservative --reason "Manual enable"
```

### Policy Set Fails
```bash
# First ensure autopilot is enabled
python recovery_cli.py autopilot status

# If disabled, enable first
python recovery_cli.py autopilot enable --policy conservative

# Then set policy
python recovery_cli.py autopilot policy set --policy standard
```

### Emergency Stop Won't Resume
```bash
# Check status
python recovery_cli.py autopilot status

# Resume with reason
python recovery_cli.py autopilot emergency-resume --reason "Incident resolved"
```

### No Events Appearing
```bash
# Verify events are being recorded
curl http://localhost:8000/recovery/events | jq 'length'

# Check with job filter
curl http://localhost:8000/recovery/events?job_id=job-123 | jq
```

---

## Monitoring

### Check Metrics Regularly
```bash
# Every 30 seconds
watch -n 30 'curl -s http://localhost:8000/recovery/metrics | grep recovery'

# Or with tail
while true; do curl -s http://localhost:8000/recovery/metrics; sleep 30; done
```

### Event Count Monitoring
```bash
# Get recent events
curl http://localhost:8000/recovery/events?limit=5 | jq '.[] | .timestamp'

# Count events by type
curl http://localhost:8000/recovery/events | jq 'group_by(.event_type) | map({type: .[0].event_type, count: length})'
```

---

## Integration Points

### Environment Variables
- `RECOVERY_OPERATOR_ID` - User/system ID performing the operation (required for audit trail)

### API Server Startup
```bash
# Development
python recovery_api.py

# Production (with uvicorn)
uvicorn recovery_api:app --host 0.0.0.0 --port 8000 --workers 4
```

### CLI Integration
- All autopilot commands integrated into `recovery_cli.py`
- Accessible as: `python recovery_cli.py autopilot <command>`
- Supports tab-completion if configured

### Event Streaming
- All state changes emit canonical events
- Events stored in `CanonicalEventStore`
- Queryable via REST API at `/recovery/events`

---

## Performance Notes

- **Response Time**: All endpoints respond in <100ms
- **Concurrent Limit**: Default max 5 concurrent autonomous actions (configurable per policy)
- **Event Storage**: In-memory with optional SQLite persistence
- **Metrics**: Zero-copy Prometheus text format (~1KB per endpoint)

---

## Security Notes

- **Operator Tracking**: All operations recorded with operator ID for audit
- **Emergency Stop**: Immediate (no state machine transitions needed)
- **Policy Validation**: All policy inputs validated server-side
- **Event Immutability**: Canonical events are append-only
- **No Secrets**: Metrics and events contain no credentials or secrets

