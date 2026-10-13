# Smart Home Tray — Project Status

## Estado atual

- **Fase:** 1 — Backend Local-First.
- **Objetivo:** backend Python independente para controle LAN Tuya, com contratos prontos para integração futura via Tauri.
- **Progresso:** PR #1 mergeada em `develop` no commit `9e6df6c`; PR #2 (Etapa C1) mergeada em `develop` no commit `2224d2b`; Code Review 02 mergeada em `develop` no commit `1d96db2`. Etapa C2A está implementada e em validação local na branch `feature/advanced-lighting-controls`; nenhum push foi feito, conforme instrução do mantenedor. Nenhuma validação física foi executada nesta etapa.
- **Legenda:** PLANEJADO = ainda sem implementação; IMPLEMENTADO = presente no código; TESTADO = executado com evidência; BLOQUEADO = impedido por uma dependência ou limitação confirmada.

## Implementações

| Item | Estado | Evidência |
| --- | --- | --- |
| Estrutura, instruções do projeto e documentação inicial | IMPLEMENTADO | `AGENTS.md`, `docs/`, `.gitignore`, `backend/pyproject.toml`, `backend/config.example.toml` |
| Modelos de dispositivo, capacidades, estado e erros | TESTADO | `backend/src/smart_home_tray/models.py`; testes de capacidades, intervalos, validação e ocultação de chave |
| Leitura de configuração TOML externa e resolução de Local Key pelo ambiente | TESTADO | `backend/src/smart_home_tray/config.py`; testes de carregamento, chave ausente, IDs duplicados e DPS inválido |
| Adapter LAN TinyTuya para status e escrita DPS | TESTADO | `backend/src/smart_home_tray/tuya_adapter.py`; testes com fábrica e dispositivo simulados |
| Conversão pública explícita por allowlist | TESTADO | `device_status_to_public_dict` em `models.py`; teste de campos permitidos e ausência de Local Key |
| Mapeamento seguro TinyTuya 903/904/907/914 e fallback | TESTADO | Testes de erro no `test_tuya_adapter.py`; mensagens brutas não são propagadas |
| Semântica da escrita e validação de retorno TinyTuya | TESTADO | `write_dps` aceita null ACK sem confirmar estado e rejeita respostas inválidas; testes com mocks |
| DeviceManager: catálogo por ID, estado, leitura LAN, energia com readback, locks por dispositivo e polling explícito | TESTADO | `backend/src/smart_home_tray/device_manager.py`; suíte unitária com fakes/mocks |
| CR-05/CR-06: intenção pendente só resolvida por leitura correspondente; falha de leitura degrada qualidade sem classificar `DEVICE_ERROR` como offline | TESTADO | `backend/src/smart_home_tray/device_manager.py`; regressões em `backend/tests/test_device_manager.py` |
| Troca de endereço invalida confirmação, preserva valor/intenção e reconstrói adapter | TESTADO | `update_address()`; casos de estado confirmado e pendente em `test_device_manager.py` |
| Codec HSV16 Tuya e conversão RGB ↔ HSV | IMPLEMENTADO | `backend/src/smart_home_tray/color.py`; testes em `backend/tests/test_color.py` |
| Leitura normalizada de brilho branco, temperatura, HSV, cena e work mode por DPS configurado | IMPLEMENTADO | `DeviceManager._read_state_unlocked()`; testes unitários com fakes |
| Comandos normalizados de brilho branco, temperatura, HSV e brilho colorido | IMPLEMENTADO | Métodos explícitos em `device_manager.py`; readback/pendências por campo com mocks |
| Validação física de controles C2A | PLANEJADO | Nenhum dispositivo real acessado |
| Normalização de falhas de inicialização do TuyaAdapter | TESTADO | `backend/src/smart_home_tray/tuya_adapter.py`; testes com factory que lança timeout, OSError, exceção genérica e BackendError com causa sensível |
| CI pytest/compileall em Windows para PRs em develop/main (Python 3.12/3.14) | TESTADO | PR #2: os dois jobs da matriz passaram |
| CLI, JSON Lines, conversões RGB/HSV e comandos contínuos | PLANEJADO | Etapas posteriores à C1 |

## Arquivos relevantes

- Modelos: `backend/src/smart_home_tray/models.py`.
- Configuração: `backend/src/smart_home_tray/config.py` e `backend/config.example.toml`.
- Adapter: `backend/src/smart_home_tray/tuya_adapter.py`.
- DeviceManager: `backend/src/smart_home_tray/device_manager.py`.
- Codec: `backend/src/smart_home_tray/color.py`.
- Testes: `backend/tests/test_models.py`, `backend/tests/test_config.py`, `backend/tests/test_tuya_adapter.py` e `backend/tests/test_device_manager.py`.
- CI: `.github/workflows/backend-tests.yml`.
- Contratos e arquitetura: `docs/contracts.md` e `docs/architecture.md`.

## Testes

- **Executado:** `backend\.venv\Scripts\python.exe -m pytest backend/tests -q` na raiz — **21 passed**.
- **Executado:** `backend\.venv\Scripts\python.exe -m compileall -q backend/src backend/tests` — concluído sem erros.
- **Executado:** análise TOML de `backend/config.example.toml` com `tomllib` — válida.
- **Compatibilidade observada:** Python 3.14.3, TinyTuya 1.20.0; API `Device` e `set_value` conferidas por introspecção. Testes de comunicação usam mocks.
- **Falhas durante desenvolvimento:** testes RED falharam inicialmente pela ausência dos módulos, como esperado; uma expectativa de capitalização da mensagem de ID duplicado falhou e foi corrigida; os casos de timeout não finito inicialmente revelaram validação ausente, que foi implementada. A suíte final passou.
- **Code Review 01:** testes focados `backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_models.py backend\\tests\\test_tuya_adapter.py -q` — **32 passed**; suíte completa `backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests -q` — **36 passed**; `compileall` — sem erros; `git diff --check` — sem erros.
- **Dispositivos físicos:** nenhum acessado ou alterado.
- **PyInstaller:** não instalado; nenhum empacotamento foi executado.
- **PR #1:** mergeada em `develop` no commit `9e6df6c`; revisão arquitetural aprovada com observações não bloqueantes.
- **Ambiente:** dependências foram instaladas inicialmente no Python 3.14 existente para validar a instalação; a suíte final foi repetida em `backend/.venv`, que será o ambiente de desenvolvimento daqui em diante.

- **Etapa C1:** `backend\.venv\Scripts\python.exe -m pytest backend\tests -q` — **55 passed**; `backend\.venv\Scripts\python.exe -m compileall -q backend\src backend\tests` — sem erros; `git diff --check` — sem erros. Execução local em Python 3.14.3. Nenhum dispositivo físico acessado.
- **GitHub Actions:** jobs Windows Python 3.12 e 3.14 da PR #2 passaram no commit `ed43395`; o status-only commit deste checkpoint também dispara nova execução.
- **Code Review 02:** `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_device_manager.py -q` — **25 passed**; suíte completa `backend\.venv\Scripts\python.exe -m pytest backend\tests -q` — **65 passed**; `compileall` e `git diff --check` concluídos sem erros. Inspeção das alterações não encontrou credenciais; apenas o placeholder de teste `unit-test-key-not-real`. Nenhum dispositivo físico acessado.
- **Etapa C2A:** testes focados `test_device_manager.py` + `test_color.py` — **76 passed**; suíte completa — **116 passed**; `compileall` e `git diff --check` concluídos sem erros. Testes usam somente mocks/fakes; nenhum hardware foi acessado. Inspeção final de credenciais e commits locais são os próximos passos.

## Decisões técnicas

Ver [DECISIONS.md](DECISIONS.md). A arquitetura aprovada está descrita em [architecture.md](architecture.md) e [contracts.md](contracts.md).

## Problemas conhecidos e riscos

- O equipamento de escritório Tuya 3.3 retorna erro 904 e permanece fora do caminho crítico do MVP.
- Não há validação física automatizada; capacidades e faixas precisam permanecer identificadas como não validadas até evidência correspondente.
- Atualização de IP é explícita via `update_address`; descoberta automática LAN não foi implementada.
- A matriz Python 3.12/3.14 passou remotamente no commit `ed43395`; Python 3.12 não foi executado localmente.
- A correção CR-05/CR-06 ainda não foi enviada: sem push manual não há PR nem execução de CI para este branch.
- A versão mínima declarada é Python 3.12; a execução deste checkpoint foi em Python 3.14.3. A versão 3.12 ainda não foi executada localmente.
- PyInstaller e empacotamento ainda não foram testados; compatibilidade futura foi documentada a partir da documentação oficial, não validada por build.

## Pendências arquiteturais

- Nenhuma decisão adicional à aprovação arquitetural registrada.
- Descoberta e atualização dinâmica de IP serão implementadas na etapa futura do `DeviceManager`.
- Armazenamento protegido por usuário do Windows é requisito futuro; nesta fase, as chaves são lidas de variáveis de ambiente referenciadas pelo TOML externo.

## Git

- **Estado:** repositório Git existente; sem merge automático.
- **Branch base atualizada:** `develop` em `1d96db2` (merge Code Review 02); base de desenvolvimento não é `main`.
- **Branch de trabalho:** `feature/advanced-lighting-controls`, criada a partir de `1d96db2`.
- **Commits C2A:** `5dd0c74` (codec HSV16 e testes) e `9593803` (controles normalizados, regressões e documentação).
- **Último commit:** `docs: finalize C2A status` (HEAD; hash do próprio checkpoint omitido para evitar autorreferência).
- **Arquivos não commitados:** nenhum; sem credenciais versionadas.
- **PR #1:** mergeada em `develop` no commit `9e6df6c`.
- **PR #2:** https://github.com/SCAPUTO88/smart-home-tray/pull/2, mergeada em `develop` no commit `2224d2b`.
- **Code Review 02:** PR mergeada em `develop` no commit `1d96db2`.
- **PR C2A:** ainda não existe; push será manual pelo mantenedor após os commits locais.

## Próximos passos

1. Finalizar `compileall`, `git diff --check`, revisão de segurança e validação dos testes C2A.
2. Criar commits locais claros; o mantenedor fará push manual e abrirá PR para `develop`, então aguardar CI Windows/Python 3.12/3.14.
3. Aguardar revisão arquitetural da C2A; não iniciar C2B automaticamente.
