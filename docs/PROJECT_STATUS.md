# Smart Home Tray — Project Status

## Estado atual

- **Fase:** 2 — F2C.2 CR-28/29/30 corrigidas e validadas localmente na branch feature/real-mode-readiness; PR #21 aguarda revisão do delta. Modo REAL não validado com equipamentos.
- **Objetivo:** Backend local-first para dispositivos LAN e prototipo frontend React/Tauri F2A com dispositivos exclusivamente simulados.
- **Progresso:** PR #17 (F2B, CR-16–19) integrada em origin/develop no merge 893e1ca. F2C.1 implementa a ponte tipada Tauri ↔ Python com MOCK por padrão, FIXTURE JSONL sem rede e REAL somente por opt-in controlado pelo processo Rust. A validação automatizada desta entrega foi concluída; nenhuma lâmpada física foi acessada. F2B teve uma limitação de UX manual em posicionamento multi-monitor, registrada como CR-20.
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
| CR-07/CR-08: HSV atual obrigatório para brilho colorido; qualidade coerente após rejeição explícita | TESTADO | Regressões em `backend/tests/test_device_manager.py`; suíte completa desta revisão: 123 passed |
| Scheduler de comandos contínuos com coalescing, barreiras discretas e FIFO por dispositivo | TESTADO | `backend/src/smart_home_tray/command_scheduler.py`; 17 testes determinísticos em `backend/tests/test_command_scheduler.py` |
| Lifecycle explícito e Futures sem confirmação no enqueue | TESTADO | `start()`/`stop()`; teste integrado com DeviceManager fake confirma que estado só muda após readback |
| CR-09: stop() solicitado em callback evita join da própria thread e mantém retorno booleano correto | TESTADO | Regressão em `backend/tests/test_command_scheduler.py`; callback cancela fila, operação em andamento conclui e stop externo posterior aguarda término |
| Validação física de controles C2A | PLANEJADO | Nenhum dispositivo real acessado |
| Normalização de falhas de inicialização do TuyaAdapter | TESTADO | `backend/src/smart_home_tray/tuya_adapter.py`; testes com factory que lança timeout, OSError, exceção genérica e BackendError com causa sensível |
| CI pytest/compileall em Windows para PRs em develop/main (Python 3.12/3.14) | TESTADO | PR #2: os dois jobs da matriz passaram |
| CLI `argparse` para catálogo, status e controles explícitos | IMPLEMENTADO | `backend/src/smart_home_tray/cli.py`; entrypoint em `backend/pyproject.toml` |
| Protocolo JSON Lines limitado, validado e correlacionado | TESTADO | `backend/src/smart_home_tray/protocol.py`; testes com streams em memória em `backend/tests/test_protocol.py` |
| Comandos IPC encaminhados ao CommandScheduler; status em executor limitado | TESTADO | Protocolo usa métodos normalizados e mantém leitura de stdin independente de Futures |
| CLI/IPC listam via allowlist e stdout `serve` contém apenas JSONL | TESTADO | `device_status_to_public_dict`; writer único e testes de validação/saída |
| CR-10: list/get/status fora da thread de stdin e inicialização lazy sem locks LAN | TESTADO | `DeviceManager.list_device_ids()` e regressões com locks/Event em `test_protocol.py` |
| CR-11: erros inesperados da CLI são genéricos, sem traceback ou texto de exceção | TESTADO | Regressões para inicialização, status e Future de escrita em `test_cli.py` |
| CR-12: leituras aceitas pendentes no executor são drenadas após EOF | TESTADO | Executor limitado a um worker; primeira leitura bloqueada por Event e segunda confirmada executada/resposta terminal em `test_protocol.py` |

## Arquivos relevantes

- Modelos: `backend/src/smart_home_tray/models.py`.
- Configuração: `backend/src/smart_home_tray/config.py` e `backend/config.example.toml`.
- Adapter: `backend/src/smart_home_tray/tuya_adapter.py`.
- DeviceManager: `backend/src/smart_home_tray/device_manager.py`.
- Codec: `backend/src/smart_home_tray/color.py`.
- Scheduler: `backend/src/smart_home_tray/command_scheduler.py`.
- CLI e protocolo: `backend/src/smart_home_tray/cli.py`, `backend/src/smart_home_tray/protocol.py` e entrypoint `smart-home-tray` em `backend/pyproject.toml`.
- Testes: `backend/tests/test_models.py`, `backend/tests/test_config.py`, `backend/tests/test_tuya_adapter.py` e `backend/tests/test_device_manager.py`.
- Testes de scheduler/IPC/CLI: `backend/tests/test_command_scheduler.py`, `backend/tests/test_protocol.py` e `backend/tests/test_cli.py`.
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
- **CI PR #6 antes desta revisão:** conforme checkpoint informado, 116 testes passaram em Windows/Python 3.12 e 3.14. Esse resultado antecede as correções CR-07/CR-08.
- **Code Review C2A CR-07/CR-08:** testes focados `test_color.py` + `test_device_manager.py` — **83 passed**; suíte completa — **123 passed**; `compileall -q backend\src backend\tests` e `git diff --check` sem erros. Execução local Python 3.14; CI atualizado aguarda push manual. Testes somente com fakes/mocks; nenhum dispositivo físico acessado.
- **Etapa C2B:** testes focados `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_command_scheduler.py -q` — **17 passed**; suíte completa — **140 passed**; `compileall` e `git diff --check` sem erros. Execução local Python 3.14; testes somente com fakes/mocks, sem rede ou hardware.
- **Code Review C2B CR-09:** regressão reproduziu `RuntimeError: cannot join current thread` antes da correção; testes focados após correção — **18 passed**; suíte completa — **141 passed**; `compileall -q backend\src backend\tests` e `git diff --check` sem erros. Execução local Python 3.14, somente fakes/mocks; nenhum hardware acessado.
- **Etapa D — testes focados:** `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_protocol.py backend\tests\test_cli.py -q` — **28 passed** em Python 3.14.3; somente streams em memória e fakes.
- **Etapa D — suíte completa:** `backend\.venv\Scripts\python.exe -m pytest backend\tests -q` — **169 passed**; `compileall -q backend\src backend\tests` e `git diff --check` concluídos sem erros. Inspeção textual encontrou somente placeholders de teste existentes/explicitamente fictícios; nenhum segredo real ou configuração local foi adicionada. Nenhum hardware, cloud ou rede doméstica acessado.
- **CR-10/CR-11 — testes focados:** `rtk py -m pytest backend/tests/test_protocol.py backend/tests/test_cli.py -q` — **35 passed** em Python 3.14.3; somente fakes, locks/Event e streams em memória.
- **CR-10/CR-11 — suíte completa:** `rtk py -m pytest backend/tests -q` — **176 passed** em Python 3.14.3; `rtk py -m compileall -q backend/src backend/tests` e `rtk git diff --check` concluídos sem erros. Busca nos arquivos alterados não encontrou IPs privados nem valores com aparência de Local Key; identificadores sensíveis de regressão são explicitamente fictícios. Sem acesso a hardware/rede/cloud.
- **CR-12 — focados:** `rtk py -m pytest backend/tests/test_protocol.py backend/tests/test_cli.py -q` — **36 passed** em Python 3.14.3.
- **CR-12 — suíte completa:** `rtk py -m pytest backend/tests -q` — **177 passed**; `rtk py -m compileall -q backend/src backend/tests` e `rtk git diff --check` passaram. Python 3.12 não está instalado/disponível neste ambiente; o CI atualizado deverá validar essa versão. Inspeção das alterações não encontrou credenciais; somente mocks e endereços reservados de teste, sem hardware/rede/cloud.

## Decisões técnicas

Ver [DECISIONS.md](DECISIONS.md). A arquitetura aprovada está descrita em [architecture.md](architecture.md) e [contracts.md](contracts.md).

## Problemas conhecidos e riscos

- O equipamento de escritório Tuya 3.3 retorna erro 904 e permanece fora do caminho crítico do MVP.
- Não há validação física automatizada; capacidades e faixas precisam permanecer identificadas como não validadas até evidência correspondente.
- Atualização de IP é explícita via `update_address`; descoberta automática LAN não foi implementada.
- A matriz Python 3.12/3.14 passou remotamente no commit `ed43395`; Python 3.12 não foi executado localmente.
- As correções CR-07/CR-08 ainda não foram enviadas à PR #6; os commits locais aguardam push manual e novos checks de CI.
- A versão mínima declarada é Python 3.12; a execução deste checkpoint foi em Python 3.14.3. A versão 3.12 ainda não foi executada localmente.
- PyInstaller e empacotamento ainda não foram testados; compatibilidade futura foi documentada a partir da documentação oficial, não validada por build.

## Pendências arquiteturais

- Nenhuma decisão adicional à aprovação arquitetural registrada.
- Descoberta e atualização dinâmica de IP serão implementadas na etapa futura do `DeviceManager`.
- Armazenamento protegido por usuário do Windows é requisito futuro; nesta fase, as chaves são lidas de variáveis de ambiente referenciadas pelo TOML externo.

## Git

- Estado: feature/desktop-ui-prototype estava limpa e igual a origin/feature/desktop-ui-prototype antes de CR-13/CR-14; correcoes desta revisao estao locais e ainda sem commit/push/merge.
- Base: origin/develop em fb9081f, que ja inclui a Etapa D/PR #11.
- Branch de trabalho: feature/desktop-ui-prototype, criada diretamente da base remota.
- PR #13 publicada para develop; nao direcionar a main. A branch local e a remota estavam iguais em 2e6add7 no inicio desta revisao.
- Commits incrementais CR-13/CR-14 serao listados ao concluir este checkpoint local.
## Proximos passos

1. Revisao manual das telas pelo mantenedor, pois nao havia navegador automatizavel disponivel neste ambiente.
2. Validar compilacao Tauri depois de instalar Rust/Cargo e Microsoft C++ Build Tools.
3. Concluir a revisao arquitetural de CR-13/CR-14 e, depois da aprovacao do mantenedor, publicar os commits locais na branch da PR #13 direcionada a develop.

## Revisão de código F2A.1 — CR-15

- PR #16 foi publicada na branch feature/realistic-lighting-visuals; o mantenedor realizou revisão visual manual da gravação, aprovou o refinamento da lâmpada e identificou emissão residual branca na fita LED após Power OFF.
- Causa visual: cápsulas quase brancas e ponto interno com opacidade mínima de 16% continuavam visíveis como emissores mesmo com intensidade normalizada zero.
- Correção local CR-15: cápsulas de LEDs agora usam acabamento escuro metálico; ponto emissor usa a cor RGB já normalizada por HSV/Value e desaparece com opacidade zero quando desligado. Reflexos do difusor, specular, trilha e circuito seguem materiais visíveis sem emissão ativa. A legenda passa a dizer “Desligada” sem zerar o valor mantido no slider.
- Testes frontend adicionados para desligamento e preservação do corpo físico, cor HSV em intensidade total e legenda sem alterar o percentual configurado. Os testes DOM/CSS validam estado e estrutura, mas não substituem nova inspeção visual da gravação após CR-15.
- Verificações após CR-15: typecheck e lint aprovados; 46 testes frontend passaram; build Vite e git diff --check aprovados. Sem alterações no backend, nos contratos, no scheduler ou na reconciliação. Hardware e LAN não foram acessados.

## Checkpoint F2A - prototipo visual interativo

- Estado: interface React/TypeScript demonstravel no navegador, camada Tauri 2 preparada e todos os dispositivos exclusivamente simulados.
- Base Git: branch feature/desktop-ui-prototype derivada de origin/develop fb9081f (Etapa D ja integrada).
- Dependencias: Node 24.14.1, npm 11.11.0, Vite 8.3.4, React 19, Tailwind v4, Motion, Lucide, Vitest e Testing Library; npm ci instalou 132 pacotes e reportou zero vulnerabilidades.
- Verificacoes frontend: typecheck, Oxlint, 32 testes em 4 arquivos e build Vite passaram nesta revisao.
- Verificacao backend: backend/tests -q passou com 177 testes; nenhum arquivo Python do backend foi alterado.
- Tauri: scaffold/configuracao Tauri 2 presente. Rust/Cargo nao estao instalados; a compilacao nativa nao foi executada. O workflow CI frontend nao compila Rust.
- Inspecao visual: npm run dev serviu o app, mas CUA nao encontrou navegador e a sessao nao tinha js_repl/Playwright; nao foi possivel gerar screenshots. Revisao visual manual ainda recomendada.
- Hardware, backend runtime, LAN, cloud e credenciais: nenhum foi acessado.
- Fase 2 continua aberta; este checkpoint nao marca a fase como concluida.

## Code review F2A — CR-13/CR-14

- Estado: correcoes locais na branch feature/desktop-ui-prototype; PR #13 publicada e com destino develop. Sem push ou merge nesta revisao.
- CR-13: removido o sequenciamento global por dispositivo. O mock reconcilia cada campo (e canal HSV) com a intencao mais recente daquele campo; a sessao faz merge seletivo do readback e compoe preview a partir do estado confirmado com pedidos ainda pendentes. Hue+power, hue+saturacao, HSV+intensidade, modo+brilho branco e operacoes pendentes em dois dispositivos cobertos por regressao.
- CR-14: pending mostra preview solicitado. Sucesso usa readback retornado para os campos aceitos; cancelamento/DEVICE_ERROR volta aos valores confirmados e mostra feedback terminal; DEVICE_OFFLINE preserva valores conhecidos, marca estado offline e invalida respostas em voo. Estado `unknown` nao se torna `confirmed` artificialmente. Resposta antiga nao substitui intencao ou feedback mais recente.
- Contrato futuro: Branco/RGB continua sendo abstracao visual; JSON Lines nao tem comando autonomo de modo. Adapter futuro precisa traduzir a selecao em operacao de iluminacao suportada, sem inventar comando IPC. Nenhum adapter Tauri/JSON Lines ou scheduler frontend foi implementado.
- Testes adicionados em `desktop/src/features/devices/useLightingSession.test.tsx`, `desktop/src/mock/MockDeviceController.test.ts` e `desktop/src/app/App.test.tsx`. Typecheck, Oxlint, 32 testes frontend, build Vite e `rtk py -m pytest backend/tests -q` (177 passed) passaram.
- A validacao continua exclusivamente simulada; nenhuma lampada, runtime backend de controle, LAN ou cloud foi acessada. Revisao visual manual e compilacao nativa Tauri permanecem pendentes.


## F2A.1 — polimento visual realista

- Estado: PR #16 (F2A.1 / CR-15) integrada em `origin/develop` pelo merge `e307e69`. O mantenedor aprovou a lâmpada e validou visualmente a correção final da fita.
- `DeviceArtwork` desenha lâmpada com envelope de vidro em gradientes SVG, emissor, reflexos especulares recortados, base metálica e IDs SVG isolados por instância. A fita usa trilha dimensional, emissores individuais sob difusor translúcido e reflexão ambiente.
- Cor e intensidade vêm apenas de `DeviceState` da prévia: HSV controla RGB, Value/brilho controla emissão e power off zera a emissão. Temperatura visual interpola âmbar, neutro e azulado. A direção do controle de temperatura Tuya continua sem validação física.
- Glow usa camadas de gradientes radiais e transições de cor/opacidade; não há filtros blur animados. `prefers-reduced-motion` reduz transições CSS e animações existentes via MotionConfig. O acento do cartão segue a cor e intensidade da prévia.
- Verificações: typecheck, lint, 44 testes frontend, build Vite e `git diff --check` passaram. Nenhum dispositivo, backend runtime, LAN ou cloud foi acessado.
- Limitação do checkpoint visual original: não havia janela de navegador para screenshots automatizadas. Depois, o mantenedor revisou manualmente a gravação, aprovou a lâmpada e confirmou visualmente a correção CR-15 da fita antes da integração da PR #16 em e307e69.
# Smart Home Tray — Project Status

## Checkpoint F2B — PR #17 integrada

- **Integração:** PR #17 foi integrada à develop no merge commit 893e1ca0cdccf2398dcef89b381878419037b608, descendente da base da F2A.1.
- **Escopo integrado:** tray nativo, ciclo de vida do popup, instância única, arraste pelo cabeçalho, geometria para quatro bordas da taskbar e tamanho lógico ajustado ao DPI.
- **CI registrado na revisão da PR:** frontend Node 24, backend Python 3.12/3.14, cargo fmt, cargo check, cargo test e build sem bundle aprovados conforme checks publicados na PR. A revisão CR-17 adicionou testes sintéticos para clique simples/duplo; eles não substituem validação do tray nativo.
- **Validação manual:** mantenedor confirmou inicialização/renderização nativa e apontou que o popup pode ficar distante do tray em configuração multi-monitor. A limitação permanece no backlog como CR-20. O arraste e os eventos nativos dependem de confirmação manual no Windows.
- **Histórico corrigido:** as alterações CR-17 foram publicadas na PR antes do merge. Não há commit local CR-17 pendente na branch desta etapa.
## Resumo técnico F2B

Rust/Tauri mantém tray/menu, visibilidade/foco/saída e encaminha uma segunda instância para a janela existente. React conserva controles e estado da sessão; `src/platform` oferece detecção Tauri, ocultação e arraste. `tauri-plugin-positioner` recebe eventos; a geometria em pixels físicos seleciona o monitor, infere a borda da taskbar e posiciona na `Monitor::work_area()`. A preferência de 420 × 720 pixels lógicos converte por DPI e é restaurada ao reabrir em monitor maior. Posição manual não muda enquanto visível.

O job Windows/MSVC fica separado do job Node. Nesta revisão, cargo fmt/check, 17 testes Rust (incluindo os testes sintéticos CR-17), 53 testes frontend, typecheck/lint/build Vite e build Tauri sem bundle passaram. Testes unitários não simulam eventos nativos; interação manual de tray/arraste e monitores continua pendente. Sem ocultação automática por perda de foco.

## Estado anterior

- PR #16 (F2A.1 / CR-15): integrada em `origin/develop` no merge commit `e307e69`; validação visual manual do mantenedor aprovou a lâmpada e confirmou a correção final da Fita LED.
- A interface navegável F2A continua em MOCK no navegador. F2C.1 adiciona transporte fixture e caminho REAL protegido por opt-in no aplicativo Tauri, sem testes físicos.

## Checkpoint F2C.1 — concluída e integrada

- **Branch/base:** feature/tauri-python-bridge, baseada no merge PR #17 893e1ca. O worktree original e suas alterações locais foram preservados; a cópia isolada de implementação está em .worktrees/f2c1-tauri-python-bridge/.
- **Arquitetura:** Rust possui o supervisor de subprocesso e comandos Tauri tipados. A WebView não fornece executável, argumentos, caminho de TOML, variáveis de ambiente ou comandos JSONL arbitrários. O controller converte o DTO público allowlisted para o modelo visual e mantém valores ausentes em qualidade desconhecida.
- **Modos:** navegador e Tauri padrão usam MOCK. FIXTURE executa smart_home_tray.fixture, sem TinyTuya/rede. REAL usa o CLI existente e exige SMART_HOME_TRAY_BACKEND_MODE=real, SMART_HOME_TRAY_ALLOW_REAL=1 e caminho TOML absoluto em SMART_HOME_TRAY_CONFIG; nenhum teste real foi executado. Falha explícita não troca para mock.
- **Protocolo:** JSON Lines existente, envelope sem campo ok, correlação requestId, respostas fora de ordem, limite 65.536 bytes, stdout de protocolo e stderr drenado sem eco. O processo fica vivo quando a janela é ocultada e encerra no evento real de saída do app.
- **Backlog:** CR-20, refinamento do posicionamento multi-monitor; fita LED flexível parcialmente enrolada com difusor COB contínuo. Ambos estão registrados sem implementação nesta etapa.
- **Validação executada:** typecheck, lint, build Vite e 66 testes frontend aprovados; cargo fmt, cargo check --locked e cargo test --locked aprovados (21 testes); build Tauri Windows --no-bundle aprovado; pytest backend/tests com Python 3.14.3 (180 testes) e compileall aprovados. O Cargo avisou colisão de nome PDB bin/lib, mas o build concluiu.
- **Validação manual:** o mantenedor aprovou a revisão arquitetural e validou manualmente o fluxo Tauri/FIXTURE no Windows. O fixture comprova subprocesso/protocolo, sem dispositivos reais.
- **Integração:** PR #19 foi mergeada em develop e PR #20 levou a mesma entrega à main. REAL continuou sem ativação física; revisão arquitetural obrigatória antes do primeiro teste com equipamentos.

## Revisão F2C.1 CR-21 / CR-22 / CR-23 — integrada nas PRs #19/#20

- **Base revisada:** PR #19, head revisado 3d794107; correcoes locais na branch feature/tauri-python-bridge. Este clone usa um origin local, portanto a PR foi identificada pelo head informado e consultada no GitHub sem alterar a PR.
- **CR-21:** em modo REAL opt-in, a hidratacao obtem devices.list e faz device.status por dispositivo; uma falha nao bloqueia os demais. Campos nulos/incompletos continuam unknown, e a interface desabilita os controles que exigiriam estado confirmado. MOCK e FIXTURE nao fazem esse readback inicial. Sem polling.
- **CR-22:** respostas de comando nao substituem um readback mais recente; a base confirmada so avanca com estado completo e confirmado. Intencoes HSV completas pendentes preservam a composicao dos canais entre respostas fora de ordem ou cancelamento. Falhas nao alteram a ultima base confirmada e o estado e isolado por dispositivo.
- **CR-23:** failed e pending agora sao protegidos por um unico estado sincronizado; registro concorrente apos falha retorna erro terminal. SMART_HOME_TRAY_BACKEND_MODE ausente continua MOCK e valor desconhecido e rejeitado. Opt-ins de REAL permanecem obrigatorios.
- **Validacao local:** frontend typecheck/lint, 74 testes, build Vite; Rust fmt/check/test (24 testes); build Tauri Windows --no-bundle; backend pytest (180 testes) e compileall passaram. Os testes IPC usam somente fixture e dados fake; nenhum hardware/LAN foi acessado. A revisão e correções foram incluídas nas PRs #19/#20, integradas em develop/main.
- **Limitacao:** falta validacao manual de UI no modo REAL opt-in; nao foi feita ativacao com dispositivos. A posicao multi-monitor CR-20 e o redesign flexivel COB continuam backlog.


## Checkpoint F2C.2 — Real Mode Readiness

- Branch/worktree: feature/real-mode-readiness em .worktrees/real-mode-readiness, baseada na develop que contém o merge F2C.1 #19/#20.
- Adicionado knowledge aditivo por campo ao snapshot público no backend: observed/stale/unknown para power, workMode, whiteBrightness, colorTemperature, hsv, colorValue e scene. O metadado é calculado com DPS validado, sem alterar quality global ou confirmação de escrita.
- Mapper/controlador frontend agora carregam knowledge e compõem HSV somente com base observada; controles passaram a habilitar por campo/operação. A UI ganhou refresh manual, sem polling; refresh durante escrita é bloqueado e respostas obsoletas são descartadas.
- Bridge Rust verifica o caminho TOML REAL como arquivo existente e valida funcionalidade do subprocesso por devices.list antes de marcar o bridge disponível. A saída continua normalizada.
- Validação executada no worktree: frontend typecheck, lint, build Vite e 82 testes; backend pytest 182 testes e compileall; Rust fmt, check e 24 testes; build Tauri Windows sem bundle. O detalhamento final consta no handoff desta branch.
- Nenhum hardware ou modo REAL foi acionado. O subprocesso REAL só valida configuração via arquivo absoluto existente e handshake devices.list, que não consulta LAN.

## Revisão F2C.2 CR-28 / CR-29 / CR-30 — correções locais para PR #21

- **CR-28:** merge de readback agora atualiza knowledge somente para os campos aceitos pela precedência por campo. HSV e colorValue avançam juntos; refresh bem-sucedido recupera knowledge stale/unknown. Testes cobrem stale/observed, coerência HSV e isolamento de knowledge de operações independentes.
- **CR-29:** sessão e controller descartam efeitos de erros de refresh/comando quando já houve uma operação ou snapshot mais recente aplicável. A precedência usa revisões por dispositivo; falhas atuais continuam marcando offline, sem afetar outros dispositivos.
- **CR-30:** controller separa sequência emitida, conjunto de operações pendentes, resultado terminal da maior sequência e sequência/revisão do último snapshot aplicado. Um readback válido de A ainda pode ser aplicado quando B falhou; intenções sem confirmação são removidas e não viram base HSV.
- **Regressões:** 9 testes novos entre `TauriDeviceController.test.ts` e `useLightingSession.test.tsx`; os casos RED foram observados antes das correções. Suíte frontend completa: 91 testes aprovados.
- **Validação:** frontend typecheck, lint, 91 testes e build Vite aprovados; Rust fmt/check/test (24 testes) aprovados; build Tauri Windows `--no-bundle` aprovado; backend pytest (182 testes) e compileall aprovados; `git diff --check` aprovado.
- **Ajuste do harness:** Vitest usou config temporário sem o plugin Tailwind, config loader nativo e pool de threads porque o carregamento padrão tentou subprocessos bloqueados pelo shell (`spawn EPERM`). O build Vite/Tauri foi concluído com `--configLoader native`; o build Tauri usou override local do `beforeBuildCommand`, sem alterar configuração versionada.
- **Estado de integração:** correções locais ainda não publicadas nem mergeadas; PR #21 precisa receber o delta e passar nova revisão. Nenhum modo REAL, hardware, LAN doméstica ou cloud foi acessado; testes usam bridge fake, controladores deferred, MOCK/FIXTURE e subprocessos artificiais.
