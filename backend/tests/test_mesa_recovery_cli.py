from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from smart_home_tray import cli


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'socket', Mock(side_effect=AssertionError('network forbidden')))


@pytest.mark.parametrize('args', [
    ['list'], ['status', '--device', 'x'], ['power', '--device', 'x', '--on'],
    ['white-brightness', '--device', 'x', '--percent', '50'],
    ['color-temperature', '--device', 'x', '--percent', '50'],
    ['color-brightness', '--device', 'x', '--percent', '50'],
    ['hsv', '--device', 'x', '--hue', '0', '--saturation', '0', '--value', '0'], ['serve'],
])
def test_legacy_requires_config(args, monkeypatch):
    load = Mock()
    monkeypatch.setattr(cli, 'load_config', load)
    with pytest.raises(SystemExit):
        cli.main(args)
    load.assert_not_called()


@pytest.mark.parametrize('args', [
    ['list'], ['status', '--device', 'x'], ['power', '--device', 'x', '--on'],
    ['white-brightness', '--device', 'x', '--percent', '50'],
    ['color-temperature', '--device', 'x', '--percent', '50'],
    ['color-brightness', '--device', 'x', '--percent', '50'],
    ['hsv', '--device', 'x', '--hue', '0', '--saturation', '0', '--value', '0'], ['serve'],
])
def test_legacy_config_reaches_loader(args, monkeypatch):
    load = Mock(side_effect=ValueError('synthetic'))
    monkeypatch.setattr(cli, 'load_config', load)
    assert cli.main(['--config', 'synthetic.toml', *args]) == 2
    load.assert_called_once_with('synthetic.toml')


@pytest.mark.parametrize('args', [['--config', 'x', 'recover-luz-mesa'], ['--config', '', 'recover-luz-mesa'], ['recover-luz-mesa', '--config', 'x']])
def test_recovery_rejects_config(args, monkeypatch):
    load = Mock()
    monkeypatch.setattr(cli, 'load_config', load)
    with pytest.raises(SystemExit):
        cli.main(args)
    load.assert_not_called()


def test_recovery_dispatches_before_generic_load(monkeypatch):
    from smart_home_tray import mesa_recovery_cli
    run = Mock(return_value=7)
    monkeypatch.setattr(mesa_recovery_cli, 'run_mesa_recovery', run)
    monkeypatch.setattr(cli, 'load_config', Mock(side_effect=AssertionError()))
    monkeypatch.setattr(cli, 'DeviceManager', Mock(side_effect=AssertionError()))
    assert cli.main(['recover-luz-mesa']) == 7
    run.assert_called_once()


class Console:
    def __init__(self, *answers):
        self.answers = iter(answers)
    def read(self, deadline):
        answer = next(self.answers)
        if isinstance(answer, BaseException):
            raise answer
        return answer


@pytest.fixture
def setup_recovery(tmp_path):
    from smart_home_tray.recovery import PreparationStatus, ConfirmationStatus, ReadbackStatus
    path = tmp_path / 'synthetic.toml'
    path.write_text('synthetic')
    target = SimpleNamespace(name='Luz Mesa', device_id='synthetic-private-id', protocol_version=3.5)
    proposal = SimpleNamespace(token='synthetic-private-token', candidate_address='192.0.2.1', expires_at=60.0)
    service = Mock()
    service.prepare_internal.return_value = SimpleNamespace(status=PreparationStatus.PROPOSAL_READY_INTERNAL, proposal=proposal)
    service.confirm_internal.return_value = SimpleNamespace(status=ConfirmationStatus.ADOPTED, readback_status=ReadbackStatus.SUCCEEDED, readback=object())
    service.close.return_value = True
    scheduler = Mock()
    scheduler.stop.return_value = True
    deps = SimpleNamespace(load=Mock(return_value=SimpleNamespace(devices=(target,))), build=Mock(return_value=(service, scheduler)), clock=Mock(return_value=0.0), console=Console('PREPARAR LUZ MESA', 'CONFIRMAR LUZ MESA'))
    env = {'SMART_HOME_TRAY_BACKEND_MODE':'real', 'SMART_HOME_TRAY_ALLOW_REAL':'1', 'SMART_HOME_TRAY_CONFIG':str(path)}
    stream = Mock()
    stream.isatty.return_value = True
    return env, deps, service, scheduler, stream


def test_success_is_private_and_staged(setup_recovery):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    env, deps, service, scheduler, stream = setup_recovery
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) == 0
    service.prepare_internal.assert_called_once_with('synthetic-private-id', scheduler)
    service.confirm_internal.assert_called_once_with('synthetic-private-token', scheduler)
    service.close.assert_called_once()
    output = ''.join(str(call.args[0]) for call in stream.write.call_args_list)
    assert 'ADOPTED' in output and 'SUCCEEDED' in output
    assert 'synthetic-private' not in output


@pytest.mark.parametrize('answers', [('',), ('CONFIRMAR LUZ MESA',), ('PREPARAR LUZ MESA', ''), ('PREPARAR LUZ MESA', EOFError()), ('PREPARAR LUZ MESA', KeyboardInterrupt())])
def test_decline_or_interruption_never_confirms(setup_recovery, answers):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    env, deps, service, scheduler, stream = setup_recovery
    deps.console = Console(*answers)
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    service.confirm_internal.assert_not_called()
    if len(answers) == 1:
        service.prepare_internal.assert_not_called()
    service.close.assert_called_once()


@pytest.mark.parametrize('change', ['mode', 'optin', 'relative', 'console', 'missing', 'duplicate', 'protocol'])
def test_gates_fail_before_service(setup_recovery, change):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    env, deps, service, scheduler, stream = setup_recovery
    if change == 'mode': env['SMART_HOME_TRAY_BACKEND_MODE'] = 'mock'
    if change == 'optin': env['SMART_HOME_TRAY_ALLOW_REAL'] = '0'
    if change == 'relative': env['SMART_HOME_TRAY_CONFIG'] = 'relative'
    if change == 'console': stream.isatty.return_value = False
    if change == 'missing': deps.load.return_value.devices = ()
    if change == 'duplicate': deps.load.return_value.devices *= 2
    if change == 'protocol': deps.load.return_value.devices[0].protocol_version = 3.3
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    deps.build.assert_not_called()


@pytest.mark.parametrize('missing_value', [True, False])
def test_missing_or_nonexistent_config_rejected_before_loading(setup_recovery, tmp_path, missing_value):
    import socket
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    env, deps, service, scheduler, stream = setup_recovery
    if missing_value:
        del env['SMART_HOME_TRAY_CONFIG']
    else:
        env['SMART_HOME_TRAY_CONFIG'] = str(tmp_path / 'does-not-exist.toml')
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    deps.load.assert_not_called()
    deps.build.assert_not_called()
    service.prepare_internal.assert_not_called()
    socket.socket.assert_not_called()


@pytest.mark.parametrize('device_id', ['', '   '])
def test_blank_mesa_id_rejected_before_service(setup_recovery, device_id):
    import socket
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    env, deps, service, scheduler, stream = setup_recovery
    deps.load.return_value.devices[0].device_id = device_id
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    deps.build.assert_not_called()
    service.prepare_internal.assert_not_called()
    socket.socket.assert_not_called()


def test_expired_before_confirmation(setup_recovery):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    env, deps, service, scheduler, stream = setup_recovery
    deps.clock.return_value = 60.0
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    service.confirm_internal.assert_not_called()
    service.close.assert_called_once()


@pytest.mark.parametrize('status', ['AMBIGUOUS', 'NOT_FOUND', 'TIMEOUT', 'VALIDATION_FAILED', 'PROTOCOL_NOT_ELIGIBLE'])
def test_prepare_failure_reports_status_and_never_confirms(setup_recovery, status):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    from smart_home_tray.recovery import PreparationStatus
    env, deps, service, scheduler, stream = setup_recovery
    service.prepare_internal.return_value = SimpleNamespace(status=PreparationStatus[status], proposal=None)
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    service.confirm_internal.assert_not_called()
    assert status in ''.join(str(c.args[0]) for c in stream.write.call_args_list)


@pytest.mark.parametrize('status,snapshot', [('FAILED', None), ('SUPERSEDED', None), ('SUCCEEDED', None)])
def test_adoption_readback_incomplete(setup_recovery, status, snapshot):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    from smart_home_tray.recovery import ReadbackStatus
    env, deps, service, scheduler, stream = setup_recovery
    service.confirm_internal.return_value.readback_status = ReadbackStatus[status]
    service.confirm_internal.return_value.readback = snapshot
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    output = ''.join(str(c.args[0]) for c in stream.write.call_args_list)
    assert 'ADOPTED' in output and status in output
    service.confirm_internal.assert_called_once()


def test_load_error_is_sanitized(setup_recovery):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    env, deps, service, scheduler, stream = setup_recovery
    deps.load.side_effect = ValueError('secret example')
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    deps.build.assert_not_called()
    assert 'secret example' not in ''.join(str(c.args[0]) for c in stream.write.call_args_list)


def test_cleanup_failure_does_not_leak_exception(setup_recovery):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    env, deps, service, scheduler, stream = setup_recovery
    service.close.side_effect = ValueError('private cleanup data')
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    scheduler.stop.assert_called_once()
    assert 'private cleanup data' not in ''.join(str(c.args[0]) for c in stream.write.call_args_list)


def test_recovery_parser_does_not_echo_invalid_input(capsys):
    with pytest.raises(SystemExit):
        cli.main(['recover-luz-mesa', '--config', 'private-argument-marker'])
    assert 'private-argument-marker' not in capsys.readouterr().err


def test_dependency_prints_are_suppressed(setup_recovery, capsys):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    env, deps, service, scheduler, stream = setup_recovery
    original = service.prepare_internal.return_value
    def noisy(*args):
        print('private-third-party-marker')
        return original
    service.prepare_internal.side_effect = noisy
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) == 0
    assert 'private-third-party-marker' not in capsys.readouterr().out


@pytest.mark.parametrize('answer', [None, 'CONFIRMAR LUZ MESA'])
def test_expiry_during_review_never_confirms(setup_recovery, answer):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    env, deps, service, scheduler, stream = setup_recovery
    class ExpiringConsole:
        def read(self, deadline):
            if deadline is None:
                return 'PREPARAR LUZ MESA'
            deps.clock.return_value = deadline
            return answer
    deps.console = ExpiringConsole()
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    service.confirm_internal.assert_not_called()
    service.close.assert_called_once()


@pytest.mark.parametrize("stage", ["STAGE_COORDINATION", "STAGE_LISTENER", "STAGE_INTERFACES", "STAGE_SEND", "STAGE_RECEIVE", "STAGE_LIMIT"])
def test_discovery_failure_cli_displays_only_closed_stage(setup_recovery, stage):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    from smart_home_tray.recovery import PreparationResult, PreparationStatus, RecoveryFailure
    env, deps, service, scheduler, stream = setup_recovery
    service.prepare_internal.return_value = PreparationResult(PreparationStatus.DISCOVERY_FAILED, failure=RecoveryFailure[stage])
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    output = "".join(str(c.args[0]) for c in stream.write.call_args_list)
    assert stage in output
    assert "synthetic-private" not in output
    service.confirm_internal.assert_not_called()


@pytest.mark.parametrize("category", ["PROVIDER_ERROR", "INVALID_ANNOUNCEMENT", "INVALID_RESULT", "COORDINATION_ERROR"])
def test_discovery_other_closed_failures_are_reported(setup_recovery, category):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    from smart_home_tray.recovery import PreparationResult, PreparationStatus, RecoveryFailure
    env, deps, service, scheduler, stream = setup_recovery
    service.prepare_internal.return_value = PreparationResult(PreparationStatus.DISCOVERY_FAILED, failure=RecoveryFailure[category])
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    output = "".join(str(c.args[0]) for c in stream.write.call_args_list)
    assert category in output
    assert "synthetic-private" not in output
    service.confirm_internal.assert_not_called()


def test_catalog_failure_category_is_reported(setup_recovery):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    from smart_home_tray.recovery import PreparationResult, PreparationStatus, RecoveryFailure
    env, deps, service, scheduler, stream = setup_recovery
    service.prepare_internal.return_value = PreparationResult(PreparationStatus.CATALOG_FAILED, failure=RecoveryFailure.CATALOG_ERROR)
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    assert "CATALOG_ERROR" in "".join(str(c.args[0]) for c in stream.write.call_args_list)
    service.confirm_internal.assert_not_called()


def test_untrusted_failure_is_not_rendered(setup_recovery):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    from smart_home_tray.recovery import PreparationStatus
    env, deps, service, scheduler, stream = setup_recovery
    service.prepare_internal.return_value = SimpleNamespace(status=PreparationStatus.DISCOVERY_FAILED, proposal=None, failure="private-marker")
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    assert "private-marker" not in "".join(str(c.args[0]) for c in stream.write.call_args_list)
    service.confirm_internal.assert_not_called()


@pytest.mark.parametrize("category", ["STAGE_RECEIVE_WAIT", "STAGE_RECEIVE_EXCEPTION", "STAGE_RECEIVE_RETIRED"])
def test_specific_receive_failure_does_not_confirm(setup_recovery, category):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    from smart_home_tray.recovery import PreparationResult, PreparationStatus, RecoveryFailure
    env, deps, service, scheduler, stream = setup_recovery
    service.prepare_internal.return_value = PreparationResult(PreparationStatus.DISCOVERY_FAILED, failure=RecoveryFailure[category])
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    output = "".join(str(c.args[0]) for c in stream.write.call_args_list)
    assert category in output
    assert "synthetic-private" not in output
    service.confirm_internal.assert_not_called()


def test_wait_os_diagnostic_is_sanitized_and_never_confirms(setup_recovery):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    from smart_home_tray.discovery import WaitDiagnostic, WaitFailureKind
    from smart_home_tray.recovery import PreparationResult, PreparationStatus, RecoveryFailure
    env, deps, service, scheduler, stream = setup_recovery
    service.prepare_internal.return_value = PreparationResult(PreparationStatus.DISCOVERY_FAILED, failure=RecoveryFailure.STAGE_RECEIVE_WAIT, wait_diagnostic=WaitDiagnostic(WaitFailureKind.OS_ERROR, errno=22, winerror=10038))
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    output = "".join(str(call.args[0]) for call in stream.write.call_args_list)
    assert "STAGE_RECEIVE_WAIT" in output and "OS_ERROR" in output
    assert "errno=22" in output and "winerror=10038" in output
    assert "synthetic-private" not in output
    service.confirm_internal.assert_not_called()


def test_wait_diagnostic_untrusted_object_is_not_printed(setup_recovery):
    from smart_home_tray.mesa_recovery_cli import run_mesa_recovery
    from smart_home_tray.recovery import PreparationStatus, RecoveryFailure
    env, deps, service, scheduler, stream = setup_recovery
    service.prepare_internal.return_value = SimpleNamespace(status=PreparationStatus.DISCOVERY_FAILED, proposal=None, failure=RecoveryFailure.STAGE_RECEIVE_WAIT, wait_diagnostic=SimpleNamespace(kind="private-marker", errno="private-marker", winerror="private-marker"))
    assert run_mesa_recovery(environ=env, stdin=stream, stdout=stream, dependencies=deps) != 0
    assert "private-marker" not in "".join(str(c.args[0]) for c in stream.write.call_args_list)
    service.confirm_internal.assert_not_called()
