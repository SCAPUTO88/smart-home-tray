"""Restricted, interactive Luz Mesa recovery; no JSON or device controls."""

from __future__ import annotations

import ipaddress
import contextlib
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from .config import load_config
from .recovery import ConfirmationStatus, PreparationStatus, ReadbackStatus


class _WindowsConsole:
    def read(self, deadline):
        import msvcrt

        # Discard type-ahead so an earlier response cannot authorize this stage.
        while msvcrt.kbhit():
            msvcrt.getwch()
        chars = []
        while deadline is None or time.monotonic() < deadline:
            if not msvcrt.kbhit():
                time.sleep(0.05)
                continue
            char = msvcrt.getwch()
            if char in ('\x03', '\x1a'):
                raise EOFError
            if char in ('\r', '\n'):
                return ''.join(chars)
            if char == '\b':
                if chars:
                    chars.pop()
            elif char in ('\x00', '\xe0'):
                msvcrt.getwch()
            elif char.isprintable() and len(chars) < 128:
                chars.append(char)
        return None


def _build(config):
    from .command_scheduler import CommandScheduler
    from .device_manager import DeviceManager
    from .lan_discovery import TinyTuyaLanDiscoveryProvider
    from .recovery import DeviceManagerRecoveryCatalog, RecoveryService

    manager = DeviceManager(config)
    scheduler = CommandScheduler(manager)
    service = RecoveryService(catalog=DeviceManagerRecoveryCatalog(manager), provider=TinyTuyaLanDiscoveryProvider())
    return service, scheduler


class _CleanupError(Exception):
    pass


class _DiscardOutput:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def run_mesa_recovery(*, environ=None, stdin=None, stdout=None, dependencies=None) -> int:
    try:
        return _run_mesa_recovery(environ=environ, stdin=stdin, stdout=stdout, dependencies=dependencies)
    except _CleanupError:
        print('Encerramento incompleto; não repita automaticamente.', file=sys.stdout if stdout is None else stdout)
        return 2


def _run_mesa_recovery(*, environ, stdin, stdout, dependencies) -> int:
    env = os.environ if environ is None else environ
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    deps = dependencies or SimpleNamespace(load=load_config, build=_build, clock=time.monotonic, console=_WindowsConsole())

    def say(message):
        print(message, file=stdout, flush=True)

    def quiet(function, *args, **kwargs):
        with contextlib.redirect_stdout(_DiscardOutput()), contextlib.redirect_stderr(_DiscardOutput()):
            return function(*args, **kwargs)

    service = scheduler = None
    try:
        say('A configuração exige as variáveis de Local Key de todos os dispositivos cadastrados.')
        path = env.get('SMART_HOME_TRAY_CONFIG', '')
        if (env.get('SMART_HOME_TRAY_BACKEND_MODE') != 'real' or env.get('SMART_HOME_TRAY_ALLOW_REAL') != '1'
                or not path or not Path(path).is_absolute() or not Path(path).is_file()
                or not stdin.isatty() or not stdout.isatty()):
            say('Gates REAL ou console inválidos; encerrado.')
            return 2
        config = quiet(deps.load, path)
        matches = [item for item in config.devices if item.name == 'Luz Mesa']
        if (len(matches) != 1 or not isinstance(matches[0].device_id, str)
                or not matches[0].device_id.strip() or isinstance(matches[0].protocol_version, bool)
                or matches[0].protocol_version != 3.5):
            say('Luz Mesa não é única ou não é elegível para Tuya 3.5.')
            return 2
        service, scheduler = quiet(deps.build, config)
        say('Luz Mesa · Tuya 3.5. Preparar inicia descoberta UDP e possível leitura TCP autenticada.')
        say('Digite PREPARAR LUZ MESA para autorizar; a entrada não é exibida.')
        if deps.console.read(None) != 'PREPARAR LUZ MESA':
            say('Preparação não autorizada.')
            return 2
        quiet(scheduler.start)
        result = quiet(service.prepare_internal, matches[0].device_id, scheduler)
        if result.status is not PreparationStatus.PROPOSAL_READY_INTERNAL or result.proposal is None:
            label = result.status.name if isinstance(result.status, PreparationStatus) else 'UNKNOWN'
            say(f'Preparação: {label}. Pare e revise o resultado.')
            return 2
        proposal = result.proposal
        candidate = ipaddress.IPv4Address(proposal.candidate_address)
        remaining = max(0, proposal.expires_at - deps.clock())
        if remaining <= 0:
            say('Proposta expirada.')
            return 2
        say(f'Luz Mesa · Tuya 3.5 · IPv4 candidato: {candidate} · tempo estimado: {remaining:.1f} s')
        say('A resposta demonstra posse da chave, não identidade física independente.')
        say('A adoção é apenas neste processo, não persiste no TOML e não é transferida ao desktop.')
        say('Revise e digite CONFIRMAR LUZ MESA para autorizar; a entrada não é exibida.')
        answer = deps.console.read(proposal.expires_at)
        if answer != 'CONFIRMAR LUZ MESA' or deps.clock() >= proposal.expires_at:
            say('Confirmação não autorizada ou proposta expirada.')
            return 2
        outcome = quiet(service.confirm_internal, proposal.token, scheduler)
        if outcome.status is not ConfirmationStatus.ADOPTED:
            say('Confirmação não concluída; não repita automaticamente.')
            return 2
        say('ADOPTED: endereço adotado em memória.')
        status = outcome.readback_status
        label = status.value.upper() if isinstance(status, ReadbackStatus) else 'UNKNOWN'
        say(f'Readback: {label}')
        if status is not ReadbackStatus.SUCCEEDED or outcome.readback is None:
            say('Readback incompleto; pare. A adoção pode ter ocorrido.')
            return 2
        return 0
    except (Exception, KeyboardInterrupt):
        say('Operação interrompida ou falhou; resultado pode ser desconhecido. Não repita automaticamente.')
        return 2
    finally:
        cleanup_failed = False
        if service is not None:
            try:
                quiet(service.close, timeout_seconds=0.0)
            except Exception:
                cleanup_failed = True
        if scheduler is not None:
            try:
                while not quiet(scheduler.stop, timeout_seconds=10.0):
                    pass
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise _CleanupError from None
