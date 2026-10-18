"""Fresh exact-owned-UUID state proof, independent of shutdown exit codes."""
import json
import uuid
import process_scope


def clean_command(row):
    return (type(row.get('exit_code')) is int and row['exit_code'] == 0
            and row.get('failure_type') is None and row.get('primary_error') is None
            and not row.get('cleanup_errors'))


def observed_state(row, device):
    if not clean_command(row):
        raise ValueError('simulator state query failed or writer unresolved')
    raw = row.get('stdout')
    if not isinstance(raw, str) or len(raw.encode()) > 1024 * 1024:
        raise ValueError('invalid simulator state query size')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('duplicate state JSON key')
            result[key] = value
        return result
    data = json.loads(raw, object_pairs_hook=unique)
    groups = data.get('devices') if isinstance(data, dict) else None
    if not isinstance(groups, dict) or not all(isinstance(g, list) for g in groups.values()):
        raise ValueError('invalid simulator device inventory')
    flat = [d for group in groups.values() for d in group]
    if not all(isinstance(d, dict) and isinstance(d.get('udid'), str) for d in flat):
        raise ValueError('invalid simulator device row')
    matches = [d for d in flat if d['udid'].lower() == device.lower()]
    if len(matches) != 1 or matches[0].get('state') not in ['Shutdown', 'Booted']:
        raise ValueError('exact owned simulator state unavailable')
    return matches[0]['state']


def confirm_shutdown(command, device, owned_boot):
    if owned_boot is not True or not isinstance(device, str) or str(uuid.UUID(device)) != device.lower():
        raise ValueError('exclusively owned canonical simulator UUID required')
    result = {'schema': 'p1-owned-simulator-shutdown-v1', 'device': device,
              'owned_boot': True, 'observed_shutdown': False, 'command_failed': False,
              'receipts': [], 'admissionEligible': False}
    def invoke(phase, *argv):
        try: row = command(*argv, timeout=15, cleanup=True, receipt=True)
        except Exception as error:
            row = {'exit_code': None, 'failure_type': type(error).__name__,
                   'primary_error': process_scope.error_info(error), 'cleanup_errors': []}
        result['receipts'].append({'phase': phase, 'command': row})
        if not clean_command(row): result['command_failed'] = True
        return row
    def query(phase):
        row = invoke(phase, 'xcrun', 'simctl', 'list', 'devices', '--json')
        try:
            state = observed_state(row, device)
            result['receipts'][-1]['observed_state'] = state
            process_scope.emit_diagnostic('owned-simulator-state', device=device, stage=phase, state=state)
            return state
        except Exception as error:
            result['command_failed'] = True
            result['receipts'][-1]['state_error'] = process_scope.error_info(error)
            process_scope.emit_diagnostic('owned-simulator-state-failure', device=device, stage=phase, error=process_scope.error_info(error))
            return None
    state = query('before')
    if state == 'Shutdown':
        result['observed_shutdown'] = True
    elif state == 'Booted' or (state is None and result['receipts'][-1]['command'].get('writer_settled') is True
                             and (result['receipts'][-1]['command'].get('primary_error') or {}).get('type') == 'TimeoutExpired'):
        # Exclusive ownership predates boot. Only a settled timed-out query
        # permits this fallback. Retain its failure despite later Shutdown.
        invoke('shutdown', 'xcrun', 'simctl', 'shutdown', device)
        # A fresh state query can prove simulator quiescence, but cannot erase
        # a shutdown command failure or discharge any host process writer.
        result['observed_shutdown'] = query('after') == 'Shutdown'
    return result
