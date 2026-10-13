# Smart Home Tray — Project Status

## Estado atual

- **Fase:** 1 — Backend Local-First.
- **Objetivo:** backend Python independente para controle LAN Tuya, com contratos prontos para integração futura via Tauri.
- **Progresso:** PR #1 mergeada em `develop` no commit `9e6df6c`. Etapa C1 implementada e testada localmente com mocks; PR #2 aberta para `develop`. Os jobs CI do commit de código `ed43395` passaram; a atualização documental deste checkpoint dispara nova execução. Nenhuma validação em dispositivo real foi feita. CLI, JSON Lines, RGB/HSV e controles contínuos seguem planejados.
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
| Normalização de falhas de inicialização do TuyaAdapter | TESTADO | `backend/src/smart_home_tray/tuya_adapter.py`; testes com factory que lança timeout, OSError, exceção genérica e BackendError com causa sensível |
| CI pytest/compileall em Windows para PRs em develop/main (Python 3.12/3.14) | TESTADO | PR #2: os dois jobs da matriz passaram |
| CLI, JSON Lines, conversões RGB/HSV e comandos contínuos | PLANEJADO | Etapas posteriores à C1 |

## Arquivos relevantes

- Modelos: `backend/src/smart_home_tray/models.py`.
- Configuração: `backend/src/smart_home_tray/config.py` e `backend/config.example.toml`.
- Adapter: `backend/src/smart_home_tray/tuya_adapter.py`.
- DeviceManager: `backend/src/smart_home_tray/device_manager.py`.
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

## Decisões técnicas

Ver [DECISIONS.md](DECISIONS.md). A arquitetura aprovada está descrita em [architecture.md](architecture.md) e [contracts.md](contracts.md).

## Problemas conhecidos e riscos

- O equipamento de escritório Tuya 3.3 retorna erro 904 e permanece fora do caminho crítico do MVP.
- Não há validação física automatizada; capacidades e faixas precisam permanecer identificadas como não validadas até evidência correspondente.
- Atualização de IP é explícita via `update_address`; descoberta automática LAN não foi implementada.
- A matriz Python 3.12/3.14 passou remotamente no commit `ed43395`; Python 3.12 não foi executado localmente.
- A versão mínima declarada é Python 3.12; a execução deste checkpoint foi em Python 3.14.3. A versão 3.12 ainda não foi executada localmente.
- PyInstaller e empacotamento ainda não foram testados; compatibilidade futura foi documentada a partir da documentação oficial, não validada por build.

## Pendências arquiteturais

- Nenhuma decisão adicional à aprovação arquitetural registrada.
- Descoberta e atualização dinâmica de IP serão implementadas na etapa futura do `DeviceManager`.
- Armazenamento protegido por usuário do Windows é requisito futuro; nesta fase, as chaves são lidas de variáveis de ambiente referenciadas pelo TOML externo.

## Git

- **Estado:** repositório Git existente; sem merge automático.
- **Branch base atualizada:** `develop` fast-forward até `9e6df6c` (merge da PR #1); base de desenvolvimento não é `main`.
- **Branch de trabalho:** `feature/device-manager-core`, criada em `9e6df6c`.
- **Commits desta etapa:** `f9d0898` (adapter) e `ed43395` (DeviceManager/CI/docs), mais o commit final do status deste checkpoint.
- **Último commit:** HEAD da branch `feature/device-manager-core`, atualização do checkpoint C1.
- **Arquivos não commitados:** nenhum após o commit final; nenhum arquivo contendo credenciais foi incluído.
- **PR #1:** mergeada em `develop` no commit `9e6df6c`.
- **PR #2:** https://github.com/SCAPUTO88/smart-home-tray/pull/2, aberta de `feature/device-manager-core` para `develop`; sem merge.

## Próximos passos

1. Verificar a conclusão da matriz CI Python 3.12/3.14 e revisar eventuais falhas na PR #2.
2. Aguardar revisão e merge manual da PR #2; não mesclar automaticamente.
3. Após revisão/merge, planejar a próxima etapa sem antecipar CLI, protocolo JSON Lines, RGB/HSV ou controles contínuos.
