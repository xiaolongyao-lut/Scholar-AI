# Harness Recovery Framework - Quick Reference Guide

## System Components

| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| Execution Engine | `recovery_execution_engine.py` | Execute recovery actions | ✓ Active |
| Console | `recovery_console.py` | User interface | ✓ Active |
| API Endpoints | `recovery_api_endpoints.py` | HTTP interface | ✓ Active |
| Event Store | `canonical_event_store.py` | Event persistence | ✓ Active |
| Memory Store | `memory_fact_store.py` | Fact storage | ✓ Active |
| Policies | `memory_policy.py` | Policy enforcement | ✓ Active |
| Protocols | `harness_protocols.py` | Data definitions | ✓ Active |
| Persistence | `harness_persistence_adapter.py` | Backend adapter | ✓ Active |

---

## Common Operations

### 1. Execute a Recovery Action

```python
from recovery_execution_engine import RecoveryExecutionEngine
from harness_protocols import RecoveryAction, RecoveryActionType, InspectionContext

# Create action
action = RecoveryAction(
    action_id="action_001",
    action_type=RecoveryActionType.REBUILD_WAKEUP,
    context=InspectionContext(session_id="sess_123"),
    parameters={"session_id": "sess_123"}
)

# Execute
result = engine.execute_action(action)
print(f"Status: {result.status}")
print(f"Output: {result.output}")
```

### 2. Query Recovery Status

```bash
curl http://localhost:8000/recovery/status
```

Response:
```json
{
  "status": "operational",
  "actions_executed": 1520,
  "success_rate": 99.7,
  "last_recovery": "2025-03-15T10:30:00Z",
  "memory_usage": "45MB"
}
```

### 3. Inspect Session State

```bash
curl http://localhost:8000/recovery/sessions/sess_123
```

Response:
```json
{
  "session_id": "sess_123",
  "created": "2025-03-15T09:00:00Z",
  "fact_count": 245,
  "namespaces": ["execution", "skill", "resource"],
  "last_update": "2025-03-15T10:30:00Z"
}
```

### 4. Use Recovery Console

```bash
python
>>> from recovery_console import RecoveryConsole
>>> console = RecoveryConsole()
>>> console.parse_command("recover session sess_123")
>>> console.parse_command("replay job job_456")
>>> console.parse_command("inspect state")
```

---

## Policy Management

### Apply a Retention Policy
```python
from memory_policy import MemoryRetentionPolicy

policy = MemoryRetentionPolicy(
    namespace="execution",
    max_age_days=30,
    max_entries=10000
)
framework.apply_policy(policy)
```

### Apply an Eviction Policy
```python
from memory_policy import MemoryEvictionPolicy

policy = MemoryEvictionPolicy(
    trigger="memory_threshold",
    threshold_percent=80,
    action="evict_lru",
    priority="low"
)
framework.apply_policy(policy)
```

---

## Troubleshooting

### Issue: Recovery action fails

**Solution**:
1. Check that session_id exists
2. Verify event store connectivity
3. Review error logs in console
4. Check memory policy constraints

### Issue: Memory usage high

**Solution**:
1. Enable compression policy
2. Increase retention age thresholds
3. Trigger garbage collection
4. Archive old events

### Issue: API endpoint not responding

**Solution**:
1. Check service is running
2. Verify network connectivity
3. Check firewall rules
4. Review API logs

---

## Monitoring

### Key Metrics to Track

- **Recovery Success Rate**: Target > 99%
- **Average Recovery Time**: Target < 100ms
- **Memory Usage**: Monitor growth
- **Event Store Size**: Archive when > 1GB
- **Policy Violations**: Investigate immediately

### Health Check Script
```bash
python
>>> from recovery_execution_engine import RecoveryExecutionEngine
>>> engine.health_check()
# Returns dictionary with health status
```

---

## Configuration

### Set Memory Policies

```python
# Maximum 50MB for execution namespace
framework.set_namespace_limit("execution", 50 * 1024 * 1024)

# Archive events older than 30 days
framework.set_retention_policy("events", 30 * 24 * 3600)

# Compress memory facts
framework.enable_compression("facts")
```

### Configure Persistence

```python
# Use file-based persistence
adapter.configure_backend("file", {
    "path": "/var/recovery/state",
    "sync_interval": 5000  # milliseconds
})

# Or use database persistence
adapter.configure_backend("sqlite", {
    "path": "/var/recovery/state.db"
})
```

---

## Emergency Recovery

### Full System Recovery
```bash
python
>>> from recovery_console import RecoveryConsole
>>> console = RecoveryConsole()
>>> console.parse_command("full_recovery all_sessions")
```

### Specific Session Recovery
```bash
python
>>> console.parse_command("recover session sess_123 --full")
```

### State Verification
```bash
python
>>> from recovery_execution_engine import RecoveryExecutionEngine
>>> result = engine.verify_state("sess_123")
>>> print(result)  # Consistency check results
```

---

## Performance Tips

1. **Batch Operations**: Process multiple recoveries together
2. **Use Compression**: Enable for large datasets
3. **Archive Events**: Keep active store under 500MB
4. **Tune Policies**: Adjust based on usage patterns
5. **Monitor Metrics**: Early warning detection

---

## Support Contacts

- **Documentation**: See PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md
- **Issues**: Create GitHub issues with detailed logs
- **Features**: Submit enhancement requests
- **Security**: Report via security@contact

---

*Quick Reference v1.0 - Phase G*
