import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"

def start_fixture():
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(SRC)}
    return subprocess.Popen([sys.executable, "-u", "-m", "smart_home_tray.fixture"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

def send(process, request):
    process.stdin.write(json.dumps(request).encode() + b"\n")
    process.stdin.flush()
    return json.loads(process.stdout.readline())

def test_fixture_lists_public_devices_without_private_or_physical_fields():
    process = start_fixture()
    try:
        result = send(process, {"requestId":"list-1", "command":"devices.list", "payload":{}})
        assert result["requestId"] == "list-1"
        devices = result["result"]["devices"]
        assert {item["deviceId"] for item in devices} >= {"fixture-desk-lamp", "fixture-led-strip", "fixture-tuya35", "fixture-tuya33"}
        assert next(item for item in devices if item["deviceId"] == "fixture-tuya35")["protocolVersion"] == 3.5
        assert next(item for item in devices if item["deviceId"] == "fixture-tuya33")["protocolVersion"] == 3.3
        assert devices[0]["state"]["knowledge"]["hsv"] == "observed"
        assert devices[0]["state"]["knowledge"]["colorValue"] == devices[0]["state"]["knowledge"]["hsv"]
        assert all("localKey" not in item and "dps" not in item for item in devices)
    finally:
        process.stdin.close()
        assert process.wait(timeout=3) == 0

def test_fixture_supports_existing_hsv_and_power_commands():
    process = start_fixture()
    try:
        result = send(process, {"requestId":"hsv-1", "command":"device.hsv", "payload":{"deviceId":"fixture-led-strip","hue":245,"saturation":80,"value":22}})
        assert result["result"]["state"]["hsv"] == {"hue":245,"saturation":80,"value":22}
        power = send(process, {"requestId":"power-1", "command":"device.power", "payload":{"deviceId":"fixture-led-strip","enabled":False}})
        assert power["result"]["state"]["power"] is False
    finally:
        process.stdin.close()
        assert process.wait(timeout=3) == 0

def test_fixture_recovery_prepare_confirm_and_replay_in_same_process():
    process = start_fixture()
    try:
        prepared = send(process, {"requestId":"prepare", "command":"recovery.prepare", "payload":{"deviceId":"fixture-tuya35"}})
        result = prepared["result"]
        assert prepared["requestId"] == "prepare"
        assert result["status"] == "PROPOSAL_READY"
        assert len(result["proposalId"]) == 43
        assert all(character.isalnum() or character in "-_" for character in result["proposalId"])
        assert result["candidateIp"] == "198.51.100.35"
        assert result["ttlSeconds"] == 60

        confirmed = send(process, {"requestId":"confirm", "command":"recovery.confirm", "payload":{"proposalId":result["proposalId"]}})
        replay = send(process, {"requestId":"replay", "command":"recovery.confirm", "payload":{"proposalId":result["proposalId"]}})
        assert confirmed["requestId"] == "confirm"
        assert confirmed["result"]["recovery"]["status"] == "ADOPTED"
        assert confirmed["result"]["readback"]["status"] == "SUCCEEDED"
        assert confirmed["result"]["readback"]["device"]["deviceId"] == "fixture-tuya35"
        assert confirmed["result"]["readback"]["device"]["address"] == "198.51.100.35"
        catalog = send(process, {"requestId":"after-confirm", "command":"devices.list", "payload":{}})["result"]["devices"]
        assert next(item for item in catalog if item["deviceId"] == "fixture-tuya35")["address"] == "198.51.100.35"
        assert replay["requestId"] == "replay"
        assert replay["result"] == {"recovery":{"status":"PROPOSAL_EXPIRED"}}
    finally:
        process.stdin.close()
        assert process.wait(timeout=3) == 0

def test_recovery_fixture_uses_injected_monotonic_clock_for_expiry():
    from smart_home_tray.fixture import RecoveryFixture

    now = [100.0]
    recovery = RecoveryFixture(monotonic=lambda: now[0])
    proposal = recovery.prepare("fixture-tuya35")["result"]
    now[0] += 60.0
    assert recovery.confirm(proposal["proposalId"]) == {"result":{"recovery":{"status":"PROPOSAL_EXPIRED"}}}


def test_recovery_busy_admission_does_not_consume_pending_proposal():
    import threading
    from smart_home_tray.fixture import RecoveryFixture

    now = [100.0]
    slot = threading.Lock()
    recovery = RecoveryFixture(monotonic=lambda: now[0], active_slot=slot)
    proposal = recovery.prepare("fixture-tuya35")["result"]["proposalId"]

    assert slot.acquire(blocking=False)
    try:
        assert recovery.confirm(proposal) == {"result":{"recovery":{"status":"BUSY"}}}
    finally:
        slot.release()

    now[0] += 1.0
    assert recovery.confirm(proposal)["result"]["recovery"]["status"] == "ADOPTED"
    assert recovery.confirm(proposal) == {"result":{"recovery":{"status":"PROPOSAL_EXPIRED"}}}


def test_recovery_fixture_enforces_pending_proposal_limits_and_releases_capacity():
    from smart_home_tray.fixture import RecoveryFixture

    now = [20.0]
    recovery = RecoveryFixture(monotonic=lambda: now[0])
    first = recovery.prepare("fixture-tuya35")["result"]["proposalId"]
    assert recovery.prepare("fixture-tuya35") == {"result":{"status":"BUSY"}}

    device_ids = [
        "fixture-tuya35-alt",
        "fixture-recovery-readback-failed",
        "fixture-recovery-readback-superseded",
    ]
    proposals = [recovery.prepare(device_id)["result"]["proposalId"] for device_id in device_ids]
    fifth = recovery.prepare("fixture-recovery-capacity")
    assert fifth == {"result":{"status":"BUSY"}}

    assert recovery.confirm(first)["result"]["recovery"]["status"] == "ADOPTED"
    new_proposal = recovery.prepare("fixture-recovery-capacity")["result"]["proposalId"]
    assert recovery.confirm(first) == {"result":{"recovery":{"status":"PROPOSAL_EXPIRED"}}}
    assert all(recovery.confirm(token)["result"]["recovery"]["status"] == "ADOPTED" for token in proposals)
    assert recovery.confirm(new_proposal)["result"]["recovery"]["status"] == "ADOPTED"

    pending = recovery.prepare("fixture-tuya35")["result"]["proposalId"]
    now[0] += 60.0
    assert recovery.prepare("fixture-tuya35")["result"]["status"] == "PROPOSAL_READY"
    assert recovery.confirm(pending) == {"result":{"recovery":{"status":"PROPOSAL_EXPIRED"}}}

    for device_id in device_ids[:3]:
        assert recovery.prepare(device_id)["result"]["status"] == "PROPOSAL_READY"
    assert recovery.prepare("fixture-recovery-capacity") == {"result":{"status":"BUSY"}}
    now[0] += 60.0
    assert recovery.prepare("fixture-recovery-capacity")["result"]["status"] == "PROPOSAL_READY"


def test_pending_human_proposals_do_not_hold_global_recovery_slot():
    import threading
    from smart_home_tray.fixture import RecoveryFixture

    slot = threading.Lock()
    recovery = RecoveryFixture(monotonic=lambda: 0.0, active_slot=slot)
    first = recovery.prepare("fixture-tuya35")["result"]["proposalId"]
    second = recovery.prepare("fixture-tuya35-alt")["result"]["proposalId"]
    assert first != second
    assert slot.acquire(blocking=False)
    slot.release()

def test_recovery_fixture_has_deterministic_domain_and_readback_outcomes():
    from smart_home_tray.fixture import RecoveryFixture

    recovery = RecoveryFixture(monotonic=lambda: 10.0)
    for device_id, status in [
        ("fixture-tuya33", "PROTOCOL_NOT_ELIGIBLE"),
        ("fixture-recovery-ambiguous", "AMBIGUOUS"),
        ("fixture-recovery-not-found", "NOT_FOUND"),
        ("fixture-recovery-auth-failed", "AUTH_FAILED"),
        ("fixture-recovery-transport-failed", "TRANSPORT_FAILED"),
        ("fixture-recovery-busy", "BUSY"),
        ("fixture-recovery-config-changed", "CONFIG_CHANGED"),
        ("fixture-recovery-timeout", "TIMEOUT"),
        ("unknown-device", "DEVICE_NOT_FOUND"),
    ]:
        assert recovery.prepare(device_id) == {"result":{"status":status}}

    for device_id, readback in [
        ("fixture-tuya35", "SUCCEEDED"),
        ("fixture-recovery-readback-failed", "FAILED"),
        ("fixture-recovery-readback-superseded", "SUPERSEDED"),
    ]:
        proposal = recovery.prepare(device_id)["result"]["proposalId"]
        result = recovery.confirm(proposal)["result"]
        assert result["recovery"]["status"] == "ADOPTED"
        assert result["readback"]["status"] == readback
        assert next(item for item in recovery.catalog() if item["deviceId"] == device_id)["address"].startswith("198.51.100.")

    for device_id, status in [
        ("fixture-recovery-confirm-auth-failed", "AUTH_FAILED"),
        ("fixture-recovery-confirm-transport-failed", "TRANSPORT_FAILED"),
        ("fixture-recovery-confirm-config-changed", "CONFIG_CHANGED"),
        ("fixture-recovery-confirm-timeout", "TIMEOUT"),
    ]:
        proposal = recovery.prepare(device_id)["result"]["proposalId"]
        assert recovery.confirm(proposal) == {"result":{"recovery":{"status":status}}}

def test_recovery_fixture_isolates_proposals_and_never_serializes_private_data():
    from smart_home_tray.fixture import RecoveryFixture

    recovery = RecoveryFixture(monotonic=lambda: 10.0)
    first = recovery.prepare("fixture-tuya35")["result"]["proposalId"]
    second = recovery.prepare("fixture-tuya35-alt")["result"]["proposalId"]
    assert first != second
    assert recovery.confirm(first)["result"]["readback"]["device"]["deviceId"] == "fixture-tuya35"
    assert recovery.confirm(second)["result"]["readback"]["device"]["deviceId"] == "fixture-tuya35-alt"
    serialized = json.dumps({"first":first, "second":second, "devices": recovery.catalog()})
    for private in ("localKey", "owner", "binding", "dps", "traceback"):
        assert private not in serialized

def test_fixture_recovery_rejects_extra_fields_and_unknown_tokens_as_domain_expired():
    from smart_home_tray.fixture import RecoveryFixture

    recovery = RecoveryFixture(monotonic=lambda: 10.0)
    assert recovery.confirm("A" * 43) == {"result":{"recovery":{"status":"PROPOSAL_EXPIRED"}}}
    assert recovery.prepare("") == {"result":{"status":"INVALID_INPUT"}}
    process = start_fixture()
    try:
        response = send(process, {"requestId":"extra", "command":"recovery.prepare", "payload":{"deviceId":"fixture-tuya35", "candidateIp":"192.0.2.2"}})
        assert response["requestId"] == "extra"
        assert response["error"]["code"] == "INVALID_INPUT"
        invalid_token = send(process, {"requestId":"bad-token", "command":"recovery.confirm", "payload":{"proposalId":"bad"}})
        assert invalid_token["requestId"] == "bad-token"
        assert invalid_token["error"]["code"] == "INVALID_INPUT"
    finally:
        process.stdin.close()
        assert process.wait(timeout=3) == 0

def test_recovery_fixture_rejects_new_operations_while_global_slot_is_active():
    import threading
    from smart_home_tray.fixture import RecoveryFixture

    slot = threading.Lock()
    recovery = RecoveryFixture(monotonic=lambda: 10.0, active_slot=slot)
    assert slot.acquire(blocking=False)
    try:
        assert recovery.prepare("fixture-tuya35") == {"result":{"status":"BUSY"}}
        assert recovery.confirm("A" * 43) == {"result":{"recovery":{"status":"BUSY"}}}
    finally:
        slot.release()
    assert recovery.prepare("fixture-tuya35")["result"]["status"] == "PROPOSAL_READY"
