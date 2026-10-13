# Smart Home Tray — Project Status

## Estado atual

- **Fase:** 1 — Backend Local-First.
- **Objetivo:** backend Python independente para controle LAN Tuya, com contratos prontos para integração futura via Tauri.
- **Progresso:** Etapa A concluída; Etapa B implementada e testada com mocks. Checkpoint apresentado após models, configuração e adapter. DeviceManager, CLI e JSON Lines ainda não iniciados.
- **Legenda:** PLANEJADO = ainda sem implementação; IMPLEMENTADO = presente no código; TESTADO = executado com evidência; BLOQUEADO = impedido por uma dependência ou limitação confirmada.

## Implementações

| Item | Estado | Evidência |
| --- | --- | --- |
| Estrutura, instruções do projeto e documentação inicial | IMPLEMENTADO | `AGENTS.md`, `docs/`, `.gitignore`, `backend/pyproject.toml`, `backend/config.example.toml` |
| Modelos de dispositivo, capacidades, estado e erros | TESTADO | `backend/src/smart_home_tray/models.py`; testes de capacidades, intervalos, validação e ocultação de chave |
| Leitura de configuração TOML externa e resolução de Local Key pelo ambiente | TESTADO | `backend/src/smart_home_tray/config.py`; testes de carregamento, chave ausente, IDs duplicados e DPS inválido |
| Adapter LAN TinyTuya para status e escrita DPS | TESTADO | `backend/src/smart_home_tray/tuya_adapter.py`; testes com fábrica e dispositivo simulados |
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
- **Dispositivos físicos:** nenhum acessado ou alterado.
- **PyInstaller:** não instalado; nenhum empacotamento foi executado.
- **Ambiente:** dependências foram instaladas inicialmente no Python 3.14 existente para validar a instalação; a suíte final foi repetida em `backend/.venv`, que será o ambiente de desenvolvimento daqui em diante.

## Decisões técnicas

Ver [DECISIONS.md](DECISIONS.md). A arquitetura aprovada está descrita em [architecture.md](architecture.md) e [contracts.md](contracts.md).

## Problemas conhecidos e riscos

- O equipamento de escritório Tuya 3.3 retorna erro 904 e permanece fora do caminho crítico do MVP.
- Não há validação física automatizada; capacidades e faixas precisam permanecer identificadas como não validadas até evidência correspondente.
- A versão mínima declarada é Python 3.12; a execução deste checkpoint foi em Python 3.14.3. A versão 3.12 ainda não foi executada localmente.
- PyInstaller e empacotamento ainda não foram testados; compatibilidade futura foi documentada a partir da documentação oficial, não validada por build.

## Pendências arquiteturais

- Nenhuma decisão adicional à aprovação arquitetural registrada.
- Descoberta e atualização dinâmica de IP serão implementadas na etapa futura do `DeviceManager`.
- Armazenamento protegido por usuário do Windows é requisito futuro; nesta fase, as chaves são lidas de variáveis de ambiente referenciadas pelo TOML externo.

## Git

- **Estado:** o diretório não é um repositório Git (`git status` não encontrou `.git`).
- **Branch/último commit:** indisponíveis.
- **Arquivos não commitados:** não aplicável; Git não foi inicializado conforme instrução.

## Próximos passos

1. Revisão arquitetural deste checkpoint pelo ChatGPT.
2. Após a revisão, implementar `DeviceManager` com serialização, coalescing, estado confirmado/pendente/offline, polling e redescoberta simples de IP.
3. Implementar parsing de estado e conversão/serialização RGB/HSV respeitando o DPS específico por dispositivo.
4. Implementar CLI e protocolo JSON Lines sobre o mesmo DeviceManager.
5. Documentar e testar a integração completa antes de declarar a Fase 1 concluída.
