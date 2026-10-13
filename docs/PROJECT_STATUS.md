# Smart Home Tray — Project Status

## Estado atual

- **Fase:** 1 — Backend Local-First.
- **Objetivo:** backend Python independente para controle LAN Tuya, com contratos prontos para integração futura via Tauri.
- **Progresso:** Etapas A e B implementadas; correções CR-01 a CR-03 do Code Review 01 implementadas e verificadas com mocks. PR #1 foi aprovada arquiteturalmente com observações não bloqueantes e está aberta para merge manual em `develop`. DeviceManager, CLI e JSON Lines ainda não iniciados.
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
| DeviceManager, CLI, JSON Lines, conversões RGB/HSV e sincronização | PLANEJADO | Próxima etapa após revisão deste checkpoint |

## Arquivos relevantes

- Modelos: `backend/src/smart_home_tray/models.py`.
- Configuração: `backend/src/smart_home_tray/config.py` e `backend/config.example.toml`.
- Adapter: `backend/src/smart_home_tray/tuya_adapter.py`.
- Testes: `backend/tests/test_models.py`, `backend/tests/test_config.py` e `backend/tests/test_tuya_adapter.py`.
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
- **PR #1:** aberta de `fix/checkpoint-01-review` para `develop`; revisão arquitetural aprovada com observações não bloqueantes. Não mesclada. Checks automáticos ainda não configurados.
- **Ambiente:** dependências foram instaladas inicialmente no Python 3.14 existente para validar a instalação; a suíte final foi repetida em `backend/.venv`, que será o ambiente de desenvolvimento daqui em diante.

## Decisões técnicas

Ver [DECISIONS.md](DECISIONS.md). A arquitetura aprovada está descrita em [architecture.md](architecture.md) e [contracts.md](contracts.md).

## Problemas conhecidos e riscos

- O equipamento de escritório Tuya 3.3 retorna erro 904 e permanece fora do caminho crítico do MVP.
- Não há validação física automatizada; capacidades e faixas precisam permanecer identificadas como não validadas até evidência correspondente.
- A versão mínima declarada é Python 3.12; a execução deste checkpoint foi em Python 3.14.3. A versão 3.12 ainda não foi executada localmente.
- PyInstaller e empacotamento ainda não foram testados; compatibilidade futura foi documentada a partir da documentação oficial, não validada por build.
- Normalizar exceções durante a inicialização do `TuyaAdapter` (pendência técnica; não implementada neste checkpoint).
- Criar GitHub Actions para executar `pytest` automaticamente nas PRs (pendência técnica; não implementada neste checkpoint).

## Pendências arquiteturais

- Nenhuma decisão adicional à aprovação arquitetural registrada.
- Descoberta e atualização dinâmica de IP serão implementadas na etapa futura do `DeviceManager`.
- Armazenamento protegido por usuário do Windows é requisito futuro; nesta fase, as chaves são lidas de variáveis de ambiente referenciadas pelo TOML externo.

## Git

- **Estado:** repositório Git existente; sem merge automático.
- **Branch:** `fix/checkpoint-01-review`, criada a partir de `develop` (que contém o commit inicial `d2794d3`).
- **Commit inicial:** `d2794d3` (`initial commit`).
- **Commit das correções:** `fd9ab2b` (`fix: address checkpoint 01 review findings`).
- **Último commit:** HEAD da branch `fix/checkpoint-01-review`, incluindo o registro deste checkpoint.
- **Arquivos não commitados:** nenhum após o commit final do checkpoint.
- **PR:** #1 aberta com base `develop`; estado aberto, aprovada para merge manual e sem merge automático.

## Próximos passos

1. Fazer merge manual da PR #1 em `develop`, conforme o processo do repositório.
2. Em checkpoint posterior, normalizar exceções da inicialização do `TuyaAdapter`.
3. Adicionar GitHub Actions para executar a suíte `pytest` nas PRs.
4. Após o merge e autorização/revisão do próximo checkpoint, implementar `DeviceManager` com serialização, coalescing, estados, polling e redescoberta simples de IP.
5. Depois implementar parsing de estado e conversão/serialização RGB/HSV, CLI e protocolo JSON Lines sobre o mesmo manager.
