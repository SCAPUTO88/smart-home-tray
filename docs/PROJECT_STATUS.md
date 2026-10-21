# Smart Home Tray — Project Status

## CR-49.1 — lifecycle da sessão corrigido (2026-10-20)

- **Decisão aprovada:** `ApplicationSessionHost`, persistente acima da árvore visual durante o runtime ativo, mantém DeviceIntegration/controller, hook da sessão, propostas/confirm em andamento, RecoveryPresentation e os checkpoints causais já existentes. A UI pode desmontar/remontar sem recatalogar ou reinicializar estado transacional. D-020 registra limites e trade-offs; D-015–D-019 permanecem inalteradas.
- **Implementação:** bootstrap padrão guarda a Promise de resolução no host; `useLightingSession` guarda uma única Promise de `controller.list()` por identidade de controller e não limpa propostas no cleanup do efeito. Hosts keyados pela identidade de integração/controller isolam injeções. `main.tsx` monta o host dentro do StrictMode, acima de `LightingApp`.
- **Regressões A–J:** proposta confirmável após remount; ADOPTED/FAILED e ADOPTED/SUCCEEDED durante desmontagem com Device ID original; indeterminate sem retry; expiração sem renovar TTL; intenção de iluminação pendente; troca de seleção; StrictMode para integração injetada e padrão; catálogo/checkpoints sem reinicialização; e isolamento de integrações. Promises deferred e relógio injetado; sem sleeps/rede.
- **Verificações locais:** `npm test` — 213 testes em 17 arquivos passaram; `npm run typecheck`, `npm run lint`, `npm run build` (2.350 módulos) e `git diff --check` passaram. Nenhum teste acessou LAN/hardware/cloud.
- **Limites/riscos:** estado somente em memória e válido enquanto o runtime raiz está ativo; reload/destruição da WebView, encerramento do aplicativo ou reinício Python não preservam mapas de proposta/checkpoint. Um runtime novo inicia conservadoramente e não afirma cancelamento, adoção ou rollback do resultado anterior. Nenhum backend, Rust/JSONL, contrato LightingDevice, D-015–D-019, mecanismo de adoção ou lógica de reconciliação foi alterado.
- **Publicação:** branch existente `feature/f2e-d4c-recovery-ui`, PR #49 existente. Não abrir outra PR nem fazer merge. Publicar o head corrigido, conferir CI e parar para code review.

## Estado atual

### Checkpoint F2E.D.4.C — 2026-10-20 (histórico pré-CR-49.1)

- **Base:** worktree isolada `D:/Projetos/smart-home-tray/.worktrees/f2e-d4c-recovery-ui`, branch `feature/f2e-d4c-recovery-ui`, base `b5f09a2f4cadcdb8240b827ae5b72ad24020a257`. Após fetch, esse merge da PR #48 é ancestral de `origin/develop`. A branch local `develop` antiga foi preservada; demais worktrees intactas.
- **Fluxo implementado:** `ApplicationSessionHost` resolve `DeviceIntegration` e mantém iluminação/recuperação acima da árvore visual. Prop `controller` permanece compatível; prop `integration` permite integração em testes. Painel expansível compacto/dark, elegibilidade consultiva, prepare explícito, candidato não editável, aviso de confiança, adoção em memória e confirm somente com proposalId. Nenhum fetch/invoke/reconciliação física no componente.
- **Apresentação:** estados idle, preparing, proposal-ready, confirming, adopted, failed, expired, ambiguous, busy e indeterminate; mensagens públicas sanitizadas. ADOPTED distingue os quatro resultados de readback. Indeterminate não permite repetir confirm/preparar e oferece refresh manual; ocultar resultado não remove a incerteza. BUSY permite somente repetição explícita, preservando deadline/token.
- **TTL/UX:** deadline por performance.now(), atualização local a cada 250 ms, rechecagem em focus/pageshow/visibilitychange e no clique, bloqueio com <= 2 s, cleanup de intervalo/listeners. Nenhum polling. Escape seguro e retorno de foco; confirmação recebe foco no título; mensagens aria-live, contador silencioso, botões nativos e foco visível. Scroll da janela preservado, sem modal nem animações novas.
- **Testes/checks pré-CR-49.1:** D.4.C tinha 202 testes em 16 arquivos e build de 2.347 módulos. A suíte atual após CR-49.1 tem 213 testes em 17 arquivos; veja o checkpoint no início deste documento.
- **Camadas exercitadas:** componentes com fakes/deferred/relógio injetado; UI + hook + controllers reais de TypeScript com bridge falso; browser MOCK e Tauri MOCK em memória (somente bridge_info no segundo); modo FIXTURE com invokes fixos falsos. Não foi exercitado E2E React → handlers Rust → processo Python FIXTURE nesta sessão. Sem LAN, hardware, ambiente REAL, novos subprocessos ou sockets nos testes de UI. Build não é homologação física.
- **Achado de review corrigido pela CR-49.1:** remontagem completa da UI recriava integração/sessão, relistava catálogo, invalidava checkpoints e descartava proposta ativa. D-020 aprova o host persistente por runtime ativo e as regressões A–J cobrem o remount durante prepare/confirm.
- **Riscos pendentes:** inspeção visual nativa/assistiva e E2E FIXTURE ainda não executados; consulte os limites de runtime no checkpoint CR-49.1 acima. Publicar e conferir CI na PR #49 existente, sem merge, depois parar para code review.

- **Fase:** 2 — F2D.1 (Luz Mesa) e F2D.2 (Fita LED) homologadas manualmente pelo mantenedor em modo REAL; F2D.3 (Luz Escritório) pendente de investigação ou substituição. PRs #19–22 integradas em `develop` e `main` (conforme handoff do mantenedor). PR #44 está aberta com desenho documental F2E.D.4.0; não há implementação D.4.
- **Objetivo:** Backend local-first para dispositivos LAN e frontend React/Tauri com MOCK por padrão, FIXTURE sem rede e modo REAL local sob opt-in.
- **Progresso:** PRs #19–22 integraram F2C.1/F2C.2, incluindo knowledge por campo, refresh manual e CR-28–31. PR #43 integrou F2E.D.3.B; PR #44 publica o refinamento documental D.4.0 e aguarda merge/review corretivo CR-44. A validação automatizada de CI e a homologação física manual são evidências distintas: Luz Mesa e Fita LED passaram pelos controles registrados abaixo; a Luz Escritório segue pendente. Uma mudança de DHCP durante a homologação motivou o refinamento proposto em `docs/LAN_IP_REDISCOVERY_PLAN.md`. Nenhuma credencial ou endereço doméstico é registrado aqui. F2B teve uma limitação de UX manual em posicionamento multi-monitor, registrada como CR-20.
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
| Validação física de controles | TESTADO parcialmente | F2D.1 Luz Mesa e F2D.2 Fita LED homologadas manualmente em modo REAL pelo mantenedor; F2D.3 Luz Escritório pendente. Ver resultados detalhados no checkpoint F2D abaixo. |
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
- **CR-30:** controller separa sequência emitida, conjunto de operações pendentes e sequência/revisão do último snapshot aplicado. Um readback válido de A ainda pode ser aplicado quando B falhou; intenções sem confirmação são removidas e não viram base HSV.
- **Regressões:** 9 testes novos entre `TauriDeviceController.test.ts` e `useLightingSession.test.tsx`; os casos RED foram observados antes das correções. Suíte frontend completa: 91 testes aprovados.
- **Validação:** frontend typecheck, lint, 91 testes e build Vite aprovados; Rust fmt/check/test (24 testes) aprovados; build Tauri Windows `--no-bundle` aprovado; backend pytest (182 testes) e compileall aprovados; `git diff --check` aprovado.
- **Ajuste do harness:** Vitest usou config temporário sem o plugin Tailwind, config loader nativo e pool de threads porque o carregamento padrão tentou subprocessos bloqueados pelo shell (`spawn EPERM`). O build Vite/Tauri foi concluído com `--configLoader native`; o build Tauri usou override local do `beforeBuildCommand`, sem alterar configuração versionada.
- **Estado de integração:** correções locais ainda não publicadas nem mergeadas; PR #21 precisa receber o delta e passar nova revisão. Nenhum modo REAL, hardware, LAN doméstica ou cloud foi acessado; testes usam bridge fake, controladores deferred, MOCK/FIXTURE e subprocessos artificiais.

## Revisão F2C.2 CR-31 — precedência de readbacks

- **Causa:** o controller exigia que a revisão global do snapshot permanecesse igual desde a emissão para aplicar um comando. Quando A confirmava antes de B, A incrementava essa revisão e fazia B ser descartado mesmo sendo a operação emitida mais recentemente.
- **Correção:** respostas de comandos são ordenadas por sequência emitida versus última sequência de comando aplicada. A revisão do snapshot continua avançando para proteger refreshes, mas não invalida um comando B posterior enquanto aguarda readback. B emitido por último substitui A se ambos confirmarem; A ainda pode confirmar após falha de B.
- **Estado redundante:** removido `terminalResult`, que só armazenava resultado já entregue pela Promise e não participava das decisões de precedência. O conjunto de comandos pendentes e a base confirmada mantêm suas responsabilidades próprias.
- **Regressão RED/GREEN:** teste deferred A(hue=210) e B(saturation=25), com A resolvendo antes de B, falhava porque C enviava saturation=70. Após a correção, C envia `{ hue: 210, saturation: 25, value: 30 }`.
- **Validação CR-31:** typecheck, lint, 92 testes frontend e build Vite aprovados; `git diff --check` aprovado. Vitest e build usaram o config loader nativo; nenhum arquivo Rust/backend mudou neste delta.
- **Integração:** correção local na branch `feature/real-mode-readiness`, após revisão de CR-28/29/30 no commit `14f11c4`; sem push/merge. Modo REAL e acesso físico permanecem desativados.

## Checkpoint F2D — homologação REAL manual (2026-10-15)

Este checkpoint registra resultados físicos relatados e confirmados manualmente pelo mantenedor no Windows, com TOML externo e Local Keys obtidas do ambiente. Não confundir com os testes automatizados de CI das PRs #19–22, que usam mocks/fixtures e não acessam equipamentos. A homologação ocorreu após a integração F2C.1/F2C.2; os checkpoints anteriores permanecem como registro do que era conhecido e validado à época.

### F2D.1 — Luz Mesa: homologada

- Dispositivo físico Tuya 3.5. Leitura real via CLI e Tauri confirmou online, qualidade `confirmed` e `observed` nos campos suportados.
- O mantenedor confirmou fisicamente liga/desliga, RGB, modo branco, brilho, temperatura e controles de cor.

### F2D.2 — Fita LED: homologada

- Dispositivo físico Tuya 3.5. Leitura LAN e controles reais de power, matiz, saturação e intensidade RGB foram validados.
- Brilho branco e temperatura independentes permanecem ausentes/`unknown`, conforme as capacidades declaradas do dispositivo.
- O mantenedor confirmou operação simultânea com a Luz Mesa, sem interferência observada nos controles, incluindo alternância da seleção e atualização de estado. Isto registra o comportamento observado nesta sessão, não uma garantia geral de ausência de concorrência.

### F2D.3 — Luz Escritório: pendente

- Dispositivo Tuya 3.3 identificado pela descoberta LAN. A leitura TinyTuya retornou `DEVICE_ERROR` associado ao erro 904 (`Unexpected Payload from Device`).
- O equipamento também apresentou comportamento físico intermitente de desligar e religar. A homologação foi adiada até investigação ou substituição.
- Causa não determinada: não há evidência suficiente para atribuir definitivamente o erro 904 à Local Key, ao protocolo, ao hardware ou para declarar defeito físico comprovado.

### Ocorrências e resolução durante a homologação

1. TinyTuya estava ausente do ambiente Python inicialmente usado; instalar as dependências do backend resolveu essa etapa.
2. Um script PowerShell concatenava várias Local Keys por tratamento incorreto de array JSON. O script foi corrigido e as chaves conferidas individualmente sem imprimir seus valores.
3. Os endereços dos equipamentos mudaram após queda de energia e renovação DHCP. O mantenedor descobriu os endereços atuais com TinyTuya e corrigiu manualmente o TOML externo.
4. Uma instância MOCK continuava ativa devido ao single-instance do Tauri. Encerrá-la pelo tray e reiniciar o aplicativo em REAL resolveu.
5. A Fita LED teve falhas `DEVICE_OFFLINE` intermitentes; leituras diretas funcionaram e uma leitura CLI teve sucesso após isolamento/encerramento de outros clientes. Concorrência de conexão é hipótese diagnóstica ainda não verificada, não causa comprovada.

### Evidência e lacunas

- **Automatizada:** CI das PRs integradas #19–22 cobriu os contratos com testes automatizados em mocks, fakes e fixtures. Essa evidência não valida rede doméstica, dispositivos físicos, recuperação de desconexões ou descoberta automática.
- **Manual física:** resultados de Luz Mesa e Fita LED acima foram executados e confirmados pelo mantenedor; Luz Escritório não foi homologada.
- **Hipóteses em aberto:** concorrência de clientes pode estar relacionada às falhas intermitentes da Fita LED, mas ainda não foi isolada como causa. A origem do erro 904 da Luz Escritório também permanece indeterminada.
- **Lacunas:** não há validação de recuperação automática após desconexão/mudança de IP, nem garantia de reconexão sem ação manual. Descoberta LAN por IP está em refinamento; homologação REAL futura de qualquer alteração dependerá de autorização explícita do mantenedor.

## Planejamento — redescoberta de IP LAN

`docs/LAN_IP_REDISCOVERY_PLAN.md` propõe uma feature para reencontrar dispositivos cadastrados após mudança de IPv4 DHCP. É refinamento, não decisão aprovada nem implementação. O documento compara gatilhos, validação de identidade, concorrência, persistência e testes isolados.

## Checkpoint F2E.A — investigação e contratos de descoberta LAN (2026-10-15)

- **Investigado:** TinyTuya instalada 1.20.0 por leitura local do pacote, sem executar scanner/status/conexão. `find_device()` faz descoberta UDP síncrona, não aceita timeout, retorna um único resultado/sentinela e pode carregar incidentalmente `devices.json`; o scanner usa 18 s padrão, enumera broadcasts IPv4 disponíveis e pode perder dispositivos que não anunciam ou estejam atrás de interfaces/VLAN/firewall incompatíveis.
- **Identidade:** anúncio `gwId` é pista não autenticada pela Local Key. Status com DPS válidos não prova identidade. TinyTuya 3.4/3.5 autentica sessão/frame com Local Key, porém o código não demonstra vínculo criptográfico da resposta ao Device ID esperado; 3.3 não usa HMAC no enquadramento tradicional. Aceitação automática de IP permanece bloqueada.
- **Implementado:** documentação da investigação e contratos propostos em `docs/F2E_A_DISCOVERY_INVESTIGATION.md`. Nenhum tipo executável, provider, mudança de endereço ou integração foi implementado; arquitetura ainda depende de revisão do mantenedor.
- **Testado:** nenhum teste Python executado, pois código Python não foi alterado. A investigação foi estática; sem leitura de configuração privada e sem uso de scanner, sockets, LAN, dispositivos ou cloud. Verificações documentais serão registradas após execução.
- **Próximo passo histórico:** revisão arquitetural da PR #25 refinou a separação entre candidatos e adoção; o checkpoint seguinte é F2E.B abaixo. A política de identidade continua pendente somente para validação/adoção de endereço.

## Checkpoint F2E.B — núcleo de descoberta LAN (2026-10-15)

- **Implementado:** `backend/src/smart_home_tray/discovery.py` define anúncios/candidatos imutáveis, `DiscoveryProvider` injetável, resultados `not_found`/`candidates`/`ambiguous`/`failed` e códigos de falha genéricos. Processamento puro exige Device ID textual exato, normaliza IPv4, rejeita unspecified/loopback/multicast/limited broadcast, preserva todos os IPs distintos e agrega versões anunciadas conflitantes. IPv4 privado/global não é tratado como prova de LAN ou identidade.
- **Isolamento:** provider fake só nos testes. Nenhum provider TinyTuya real, scanner, socket, status, `DeviceManager`, `TuyaAdapter`, `update_address()`, escrita DPS, integração ou fluxo de produção foi adicionado. Nada persistido ou conectado ao startup/REAL.
- **Identidade:** candidatos permanecem não verificados. Falha, lote malformado do ID solicitado ou ausência retorna resultado tipado sem payload/exceção sensível; IPs múltiplos resultam em ambiguidade sem seleção. Modelo de confiança 3.5/3.3 continua proposta não aprovada; aceitação automática de IP permanece fora desta PR.
- **Testado:** `rtk py -m pytest backend/tests/test_discovery.py -q` — 27 passed; `rtk py -m pytest backend/tests -q` — 209 passed em Python 3.14; `rtk py -m compileall -q backend/src backend/tests` passou; `rtk git diff --check` passou.
- **Segurança/escopo:** somente identificadores sintéticos e endereços reservados nos testes. Nenhuma Local Key, configuração privada, `devices.json`, snapshot, LAN, hardware, cloud ou modo REAL foi acessado.
- **F2E.C:** revisar provider TinyTuya sem acesso incidental a arquivos privados, timeout/cancelamento/limites e preservação de candidatos. Aprovar separadamente política de identidade/aceitação por protocolo; se não houver decisão, F2E.C pode apenas observar candidatos, sem alterar IP.

## Checkpoint F2E.C — provider LAN UDP (2026-10-16)

- **Implementado:** `backend/src/smart_home_tray/lan_discovery.py` adiciona `TinyTuyaLanDiscoveryProvider`, compatível com `DiscoveryProvider`, usando `tinytuya.decrypt_udp()` e primitivas de frame do TinyTuya 1.20.0. O código aceita anúncios 3.3/3.5, decodifica somente Device ID e versão e sempre usa IPv4 de origem como endereço. Solicitações UDP de descoberta para 3.5 usam sockets próprios com fechamento garantido.
- **Limites:** teto por operação de 3 s (ou o timeout menor do chamador), até 256 pacotes recebidos, até 64 endereços candidatos distintos e uma operação concorrente por processo. Duplicatas são mantidas até o limite de pacotes para normalização F2E.B. A deadline monotônica é verificada durante enumeração, bind e recepção; não há thread de trabalho. Até três listeners IPv4 são tentados (6666/6667/7000); bind parcial continua quando resta listener, falha total é genérica, falha de um adaptador não impede tentar os demais. Socket e parser não registram dados de pacotes.
- **Isolamento e identidade:** não usa `find_device()`, `deviceScan()`, `scanner.devices()`, carregamento de arquivo, `Device`, status, escrita, cloud ou `DeviceManager`. Não usa o fallback TinyTuya que tenta um socket UDP para endereço público durante consulta de rota; enumera somente broadcasts explícitos via `psutil`/`netifaces` opcionais. Sem essas interfaces, permanece em escuta passiva e não solicita anúncios 3.5. Não lê configuração privada nem adota endereço. Anúncios não autenticados continuam apenas candidatos e IDs concorrentes em IPs distintos chegam ao pipeline F2E.B sem seleção.
- **Testado:** `rtk py -m pytest backend/tests/test_lan_discovery.py -q` — 20 passed; `rtk py -m pytest backend/tests -q` — 229 passed; `rtk py -m compileall -q backend/src backend/tests` e `rtk git diff --check` passaram em Python 3.14.3, com sockets, interfaces e relógio fakes e fixtures 3.3/3.5 sintéticas. Python 3.12 ainda depende do CI.
- **Limitações:** sem `psutil`/`netifaces` ou com firewall, VLAN, isolamento Wi-Fi e dispositivos sem anúncio, o scan pode não encontrar equipamentos; sem interfaces enumeráveis, anúncios 3.5 que exijam pedido ativo podem não aparecer. Chamadas síncronas de sistema para criar/bind/fechar sockets e enumerar interfaces não podem ser interrompidas no meio; o código verifica a deadline entre elas, sem criar worker órfão.
- **Decisões pendentes:** política de identidade e adoção automática permanece sem aprovação. `DECISIONS.md` não foi alterado. Validação REAL depende de autorização explícita; este checkpoint não executou tráfego de rede.
- **Resumo para revisão arquitetural:** provider observador, UDP-only, timeout e limites finitos no fluxo controlado, parser TinyTuya 1.20.0 isolado, sem arquivo privado nem sessão TCP; todos os endereços são não verificados. Revisar o teto de 3 s, limite de interfaces/portas e suporte por versão antes de qualquer integração operacional.

## Revisão CR-29 — correções do provider F2E.C (2026-10-17)

- **Timeout:** qualquer janela de escuta concluída sem anúncio retorna coleção vazia e normaliza para `NOT_FOUND`, seja 0,2 s, 1 s, o teto de 3 s ou valor superior. Se a inicialização consumir todo o budget antes de começar a escuta, retorna `TIMEOUT`; falha do `select`/listeners permanece erro de provider.
- **Coleta truncada:** atingir limite de 256 datagramas ou 64 endereços distintos agora lança erro genérico de provider e descarta a coleção parcial, que F2E.B normaliza como `FAILED`. Isso evita apresentar o primeiro IP como resultado conclusivo.
- **Interfaces/dependência:** o backend anteriormente só declarava TinyTuya; seus requisitos instalados eram `requests`, `colorama` e `cryptography`, não `psutil`/`netifaces`. `psutil>=7,<8` foi declarado como dependência de runtime. A enumeração considera interfaces IPv4 ativas, preserva adaptadores com broadcast repetido e valida broadcast contra IPv4 local + netmask. Não usa probe de rota ou endereço externo. Até 64 registros são examinados e no máximo 16 sockets de transmissão são abertos (além dos três listeners fixos).
- **Windows e adaptadores:** `psutil.net_if_addrs()`/`net_if_stats()` fornecem endereços, máscaras e estado em Windows; CI executa backend no Windows para Python 3.12 e 3.14. VPNs em túnel ponto-a-ponto sem broadcast não recebem pedido ativo; interfaces down são ignoradas. Adaptadores acima do teto podem não ser consultados. Nenhuma validação REAL de interfaces ocorreu.
- **Recepção:** três falhas consecutivas de `recvfrom()` aposentam o listener. Outros listeners continuam ativos; falha de todos gera erro operacional. O teste de readiness contínua confirma aposentadoria após três ciclos sem depender de avanço artificial do relógio.
- **CR-29.6/29.7:** expiração durante bind de transmissão agora retorna o par de flags esperado e, se não houve janela de escuta, normaliza para `TIMEOUT`. Falha de qualquer transmissão ou aposentadoria de listener agora invalida a coleta inteira, inclusive quando outros listeners já coletaram um candidato. Listeners saudáveis seguem ativos até o fim da janela, mas resultados parciais não são expostos.
- **Frames:** adicionada fixture sintética 3.3 em 55AA com retcode e CRC; permanece cobertura do payload legado cifrado, 6699/3.5 e ambiguidade de múltiplos IPs.
- **Verificacao:** Python 3.14.3; testes focados (	est_discovery.py + 	est_recovery.py) — 50 passed; suite backend — 267 passed; compileall e git diff --check passaram. Testes com providers fakes; sem acesso a LAN, dispositivos ou cloud. Python 3.12 depende do CI.
- **Trade-offs remanescentes:** `psutil` inclui uma dependência binária de runtime, instalada pelo `pip install -e "backend[dev]"` do CI; em troca, interfaces são enumeradas sem fallback externo. A coleta limitada falha fechada mesmo se os anúncios já vistos forem válidos. Identidade e adoção de IP seguem sem aprovação.

## F2E.D.0 — refinamento de confiança e recuperação manual (2026-10-17)

- **Base:** branch `feature/f2e-d0-trust-policy` em `develop`, após integração da F2E.B/F2E.C pela PR #29.
- **Decisão registrada:** D-018 formaliza somente a política aprovada pelo mantenedor: adoção manual em Tuya 3.5 após leitura read-only aceita sob a Local Key cadastrada e confirmação explícita; isso indica posse da chave, não identidade criptográfica independente do Device ID. 3.3 não adota endereço; UDP isolado nunca autoriza; ambiguidades não escolhem automaticamente; recuperação automática e persistência TOML estão proibidas.
- **Refinamento CR-31:** `docs/F2E_D_RECOVERY_ARCHITECTURE.md` descreve trust model, fluxo prepare/confirm, resultados seguros, orçamento recomendado ainda pendente, transação sob locks, fronteira JSONL/Tauri e PRs D.1–D.4 com critérios de aceite. D.1 somente coleta/normaliza candidatos não verificados; não emite `PROPOSAL_READY` nem token. Pedido de adoção 3.3 é rejeitado antes do scan; descoberta diagnóstica permanece separada. O alvo de 9 s cobre trabalho ativo prepare+confirm, sem espera humana e sem garantia rígida; pior caso dos tetos atuais chega a 10,5 s antes do overhead. Ambiguidade, limites, TTL, timeouts e barreira FIFO seguem defaults para aprovação, não decisões.
- **Código:** nenhuma funcionalidade foi implementada. `DeviceManager.update_address()` continua sendo a única operação existente para substituir endereço em memória; não há geração de config, propostas/tokens, validator temporário nem comando de recuperação. A PR D.0 não altera runtime.
- **Verificação:** revisão documental e inspeção estática de `DeviceManager`, `TuyaAdapter`, `CommandScheduler`, JSONL, F2E.B/C e documentos relacionados. Nenhuma suíte foi executada porque não houve alteração de código. Nenhum TOML privado, Local Key, LAN, dispositivo ou cloud foi acessado.
- **Pendências antes de D.1:** aprovar defaults arquiteturais; medir timeout/lifecycle TinyTuya e definir alocação coerente do alvo 9 s (duas validações + um readback podem somar 7,5 s, além dos 3 s UDP); confirmar ambiguidade bloqueante, teto UDP 3 s, até 2,5 s por validação, duas validações sem retry, slot ativo unitário liberado entre prepare/confirm, quatro propostas por processo, uma por ID, TTL 60 s, revisão + revalidação no confirm, resultados separados `ADOPTED`/readback e barreira FIFO tipada sem callbacks. Esses pontos não alteram D-018.
- **Próximo incremento proposto:** iniciar F2E.D.1 somente depois da revisão deste desenho e aprovação dos pontos de bloqueio. D.1 deve definir contratos/orquestração com provider fake, sem status/TCP, adoção de endereço ou UI.

## Checkpoint F2E.D.1 — orquestração interna de recuperação manual (2026-10-17)

- **Implementado:** `backend/src/smart_home_tray/recovery.py` define DTOs internos tipados sem estado de autenticação/proposta e `RecoveryService.discover_for_recovery()`. A elegibilidade consulta um catálogo estreito; protocolo diferente de 3.5 e ID ausente são recusados antes do provider. Cada chamada elegível usa `discover_candidates()` uma vez, com timeout limitado a 3 s, preservando ausência, candidato único não verificado, ambiguidades e falhas normalizadas de F2E.B.
- **Concorrência:** um lock global compartilhado entre instâncias limita a uma descoberta de recuperação ativa por processo e retorna `BUSY` sem fila. O lock é liberado em `finally`; o catálogo usa leituras públicas curtas do `DeviceManager`, sem manter seu lock durante UDP. Sem worker, polling ou retry.
- **Limites de segurança:** D.1 não abre TCP, chama `status`, acessa Local Keys/configuração privada, escreve DPS, cria proposalId/token ou chama `DeviceManager.update_address()`. Apenas Device ID, IPv4 e versões anunciadas atravessam o DTO candidato; erros não carregam exceções originais. Candidatos permanecem não verificados.
- **Decisões:** D-018 e D-019 foram registradas em `docs/DECISIONS.md`. D-019 registra defaults aprovados para etapas futuras, não implementados na D.1; o timeout efetivo do TinyTuya para validação TCP segue sujeito a verificação.
- **Testes locais:** Python 3.14.3; testes focados F2B/C/D.1 (`rtk py -m pytest backend/tests/test_discovery.py backend/tests/test_lan_discovery.py backend/tests/test_recovery.py -q`) — 80 passed; suíte completa (`rtk py -m pytest backend/tests -q`) — 262 passed; `rtk py -m compileall -q backend/src backend/tests` e `rtk git diff --check` passaram. Testes usam providers/catalogs fakes, sem rede real, sessões de dispositivo ou cloud. Python 3.12 depende do CI.
- **Sincronização da base:** a branch, inicialmente baseada em 3261831 (PR #29), incorporou origin/develop 2e2d414 (PR #31) por merge, sem rebase; os documentos D.0 normativos foram preservados.
- **Limitações:** esta branch não integra protocolo JSON Lines, CLI, Tauri ou UI. Não há validação read-only, token, TTL, barreira FIFO ou adoção nesta etapa. A compatibilidade Python 3.12 ainda depende do CI; localmente foi validado Python 3.14.3.
- **Resumo para revisão arquitetural:** a D.1 só fornece classificação de anúncios não autenticados. Protocolo 3.3 é recusado antes do scanner para o fluxo de adoção; protocolo 3.5 ainda não é autenticado nesta etapa. Slot global evita scans simultâneos sem bloquear o catálogo ou outros dispositivos durante UDP. Nenhum endereço ou estado do dispositivo é alterado.


### Revisão CR-33.1 — compatibilidade da versão anunciada (2026-10-17)

- **Correção:** após normalização F2E.B, candidato único só permanece CANDIDATE_UNVERIFIED se anunciar exatamente a única versão distinta 3.5, compatível com o protocolo cadastrado. Claim somente 3.3, versão ausente/desconhecida ou claims conflitantes no mesmo IP retornam PROTOCOL_NOT_ELIGIBLE, sem candidato.
- **Ambiguidade e confiança:** resultados AMBIGUOUS são preservados antes da checagem e nenhum IP é selecionado. Versão UDP é uma claim não confiável, sem valor de autenticação/identidade. Não foi introduzida validação TCP, proposta/token ou adoção.
- **Verificação:** testes focados, suíte backend, compileall e git diff --check executados localmente; nenhum acesso a LAN, dispositivo ou cloud.

## F2E.D.2 — auditoria técnica e desenho pendente (2026-10-18)

- **Base e escopo:** branch `feature/f2e-d2-validation`, criada de `origin/develop` em `c2d79f3` (PR #33), no worktree isolado `.worktrees/f2e-d2-validation`. Esse checkpoint registra a auditoria documental antes da implementação D.2.A.
- **Entregável:** [F2E_D2_VALIDATION_AUDIT.md](F2E_D2_VALIDATION_AUDIT.md) reúne fontes versionados, interfaces propostas, ordem de locks, diagramas, lifecycle de propostas, matriz de testes fakes e plano D.2.A/D.2.B. D-018/D-019 e o documento normativo D.0 foram preservados.
- **Auditoria:** TinyTuya instalado 1.20.0, Python 3.14.3, crypto pyca/cryptography com GCM. Três fontes críticos coincidem por SHA-256 com o commit público `8512d8364a9d0e351bbec2597bafa17595545b13` e com RECORD. Um retorno DPS do adapter atual não demonstra sozinho autenticação de resposta: recepção aceita 55AA sem gate de crc_good; DEBUG criptográfico escolhe IV fixo quando recebe iv=True. Retries/deadlines e persist=False também não satisfazem automaticamente os requisitos de validação/cleanup.
- **Proposta para revisão:** adapter read-only 3.5 dedicado com helpers TinyTuya, transporte com deadline e limites, frames 6699 autenticados, parser semântico puro, lease privada por dispositivo, barreira FIFO tipada, revisão de configuração e store interno limitado. Nenhum resultado propõe identidade independente; D.3 continua responsável por confirmação pública, adoção e readback.
- **Pendências:** aprovar abordagem, matriz de versões, limites adicionais, alocação dos budgets, política IPv4/VPN, lifecycle e tratamento de logs/relay. Não foi alterada a faixa de dependências nem registrada nova decisão aprovada. Meta de 9 s não é garantia; os sub-limites existentes somam 10,5 s antes de overhead.
- **Verificação desta execução:** inspeção estática de código/testes, comparação de fontes públicos e revisão documental; `git diff --check`, whitespace e links locais do novo documento passaram. Backend, D-018/D-019 e documento normativo D.0 sem alteração. Sem testes runtime ou compileall, pois não houve alteração funcional. Nenhum socket de dispositivo, autenticação real, arquivo privado ou Tuya Cloud foi acessado. Testes criptográficos/fakes e CI Python 3.12/3.14 descritos no plano ainda devem ser implementados/executados após aprovação.
- **Próximo passo naquele checkpoint:** revisão arquitetural do desenho antes de iniciar D.2.A; não houve commit, push, PR ou merge.

## F2E.D.2.A — transporte read-only autenticado isolado (2026-10-18)

- **Implementado:** tuya35_readonly.py fornece um cliente dedicado sem instanciar TinyTuya Device: gate de versão exata 1.20.0, preflight da chave de 16 bytes/protocolo/claim/endereço, uma conexão TCP 6668, handshake 3.5 com HMAC de desafio, frames 6699 com GCM válido, um único DP_QUERY_NEW e fechamento obrigatório antes de retornar DPS. Retcode e comando de status precisam ser sucesso/allowlist; 55AA, resposta truncada, tag/HMAC/replay inválidos falham fechados.
- **Limites:** deadline monotônica cumulativa limitada a 2,5 s; oito frames totais, 12 KiB de entrada+saída e payload de até 1.440 bytes. Timeout recalculado antes de connect/send/recepção de cada fragmento. IVs de saída explícitos pela entropia do sistema, distintos na sessão mesmo com loggers TinyTuya em DEBUG. Não há retry, reconexão, segundo query, status(), escrita DPS, cloud ou descoberta incidental.
- **Interfaces e parser:** recovery_validation.py retorna somente status tipado e fase genérica. dps_observation.py centraliza interpretação pura de DPS e passou a ser usada também pelo DeviceManager, preservando a aplicação atual de estado e pendências. DPS brutos são transitórios e não entram em resultados.
- **Rede e dependências:** dependências não foram alteradas; backend/pyproject.toml continua com tinytuya>=1.20,<2. Só o cliente novo habilita TinyTuya exatamente 1.20.0 e GCM disponível; outras versões falham antes do socket sem afetar adapters existentes. Interface IPv4 vem de psutil local, sem probe externo. Só RFC1918 em subnet ativa elegível (/8 a /30) é aceita; /31 e /32 são excluídas. Adaptadores VPN com sub-rede privada até /30 ainda podem passar pelo critério e requerem revisão de política.
- **Confiança:** KEY_AUTHENTICATED_READ é evidência limitada de leitura em sessão autenticada sob a chave cadastrada, não comprova identidade independente nem vínculo criptográfico ao Device ID. Nenhuma proposta/token, coordenação D.2.B, mudança de endereço, persistência, integração pública ou estado físico é produzido.
- **Testes locais:** Python 3.14.3; focados (transporte, validador e parser) — 48 passed; suíte backend — 315 passed; compileall e git diff --check passaram. Fixtures sintéticas, interfaces/socket/relógio fakes; sem LAN, hardware, cloud, arquivos de credenciais ou autenticação real. Python 3.12 permanece para CI.
- **Limitações:** deadline cobre connect/send/recv com timeout do socket e é conferida após cleanup, mas não consegue interromper um travamento nativo do sistema em close(). Não há cancelamento concorrente do socket nesta etapa. Python não garante zeroização de bytes imutáveis. Nenhum firmware/hardware real foi homologado; a identidade independente permanece fora do alcance do protocolo aprovado.
- **Decisões:** D-018 e D-019 não foram modificadas. A fixação global da faixa TinyTuya não foi adotada: o gate local evita afetar o backend existente, ao custo de não validar em instalações com versão diferente de 1.20.0 até auditoria futura.
- **Resumo para revisão arquitetural:** D.2.A valida uma sessão 3.5 read-only e exige autenticação GCM/HMAC, DPS reconhecido e cleanup observado. O resultado é transitório e reduzido; ainda não existe proposta ou caminho de adoção. Revisar o tratamento de VPNs privadas e a limitação de cleanup nativo antes de D.2.B.

## Revisão CR-35.1 — limite de enumeração de interfaces (2026-10-18)

- **Correção:** `tuya35_readonly.py` limita a 64 registros IPv4 elegíveis tanto na materialização do provider padrão quanto ao consumir qualquer provider injetado. A 65ª entrada causa falha tipada e descarta a coleção inteira; nenhum subconjunto é validado. A deadline é verificada imediatamente antes e após a enumeração e antes de abrir socket.
- **Limitação:** a checagem pós-chamada detecta expiração durante a enumeração, mas não interrompe uma chamada síncrona nativa que fique bloqueada. Não se promete cancelamento desse tipo de chamada.
- **Regressões:** provider injetado sintético com 65 registros e provider padrão com `psutil` sintético excedente; ambos verificam rejeição sem acesso à rede/socket. A autenticação e o contrato de leitura permanecem iguais.
- **Verificação CR-35.1:** Python 3.14.3; `rtk py -m pytest backend/tests/test_tuya35_readonly.py -q` — 43 passed; `rtk py -m pytest backend/tests -q` — 317 passed; `rtk py -m compileall -q backend/src backend/tests` e `rtk git diff --check` passaram. Testes usam provider/`psutil` sintéticos e socket fake; sem LAN REAL, hardware, cloud ou credenciais.
- **Resumo para revisão arquitetural:** enumeradores agora têm teto explícito e rejeição integral em excesso; deadline protege a abertura de socket, com a ressalva de que chamada nativa bloqueante não é interrompível.

## F2E.D.2.B.1 — coordenação e concorrência (2026-10-19)

- **Base:** branch `feature/f2e-d2b-coordination` em `8b2c6ef`, merge da PR #35 sobre `origin/develop`. A PR #35 permanece fora deste checkpoint funcional.
- **Commit local:** `cf685f9` (`feat: coordinate recovery validation safely`); sem push ou merge.
- **Implementado:** revisão privada de configuração por Device ID, incremento em cada `update_address()` bem-sucedido (inclusive mesmo IP), snapshot privado redigido e lease com deadline. A validação sob lease usa configuração atual e `CandidateValidator` sem modificar status, adapter ativo, pending, knowledge ou caches de leitura.
- **Scheduler/coordenação:** novo item interno `VALIDATE_RECOVERY` discreto, imediato e não coalescível; Condition não cobre lease/I/O. Recuperação usa a mesma trava global de D.1 sem chamá-la recursivamente e mantém o slot até conclusão real da Future. Shutdown cancela fila, mas operação ativa continua dona do worker/lease até terminar; `stop()` sinaliza timeout por `False`.
- **Fora de escopo:** ProposalStore, token, TTL, confirmação pública, JSONL/UI, adoção e mudança de endereço por recovery não foram criados. Não houve rede, cloud ou dispositivo físico.
- **Cobertura nova:** revisão same-IP e A→B→A, rejeição de revisão antiga antes do validator, invariância do estado do manager, request de validação não coalescido, progresso de outro Device ID e shutdown durante I/O fake.
- **Verificação:** focados (`test_device_manager`, `test_command_scheduler`, `test_recovery`, `test_recovery_validation`) — 105 passed; suíte backend — 327 passed; `compileall` e `git diff --check` passaram. Testes novos usam fakes, Event/barriers e nenhum hardware/rede.
- **Resumo para revisão arquitetural:** B.1 introduz revisão/lease por ID, barreira tipada e coordenação na trava global existente. Revisar o lifecycle `close()` (retorno `False` enquanto I/O drena) e a limitação de cancelamento do transporte síncrono antes de B.2; B.1 não adiciona proposta nem superfície pública.

### Correções CR-37.1 e CR-37.2 — PR #37

- **CR-37.1:** descoberta repete a checagem de lifecycle depois de adquirir o slot global. A admissão é linearizada sob o mutex curto; ele é liberado antes do provider/I/O. Regressão determinística pausa a aquisição do slot, deixa `close()` concluir e confirma que o provider não é chamado.
- **CR-37.2:** o coordenador espera Futures em intervalos limitados pelo deadline. Se a validação ainda está pendente, `cancel()` impede que ela comece e o resultado é `TIMEOUT`. Se já iniciou, cancelamento falha e o coordenador drena a operação real antes de soltar slot; conclusão após deadline resulta em `TIMEOUT`. Cancelamento pelo shutdown resulta em `CLOSED`. O fechamento do serviço também cancela trabalho pendente e aguarda o trabalho iniciado.
- **Interleavings:** regressões cobrem timeout na FIFO, validação iniciada com retenção do slot, shutdown concorrente e progresso do outro Device ID.
- **Verificação:** focados — 109 passed; backend — 331 passed (327 anteriores + 4 regressões novas); `compileall` e `git diff --check` passaram. Sem LAN REAL, hardware ou cloud.
- **Resumo para revisão:** o lifecycle pós-admissão impede descoberta após fechamento concluído; o timeout não abandona I/O nem libera o slot cedo. Compatibilidade FIFO e locks não reentrantes preservados.

## F2E.D.2.B.2 — ProposalStore e prepare interno (2026-10-19)

- **Base:** branch `feature/f2e-d2b-proposal-store` criada de `origin/develop` no merge commit `708044f` da PR #37.
- **Store:** criado `recovery_proposals.py`, compartilhado no processo, com limite quatro/um por ID, TTL monotônico de 60 s, tokens derivados de 32 bytes de entropia, índice SHA-256, lookup, claim atômico, replay bloqueado, expiração, colisão fail-closed e invalidação no shutdown.
- **Composição:** `prepare_internal()` mantém o slot global por snapshot, D.1, barreira FIFO, validação e publicação. A publicação acontece no handler fixo durante a lease; `update_address()` invalida revisões antigas na ordem ID → store. Deadline, cancelamento, fechamento, revisão obsoleta, falha de autenticação e cleanup não publicam proposta. Nenhuma confirmação/adopção pública ou mudança de endereço foi criada.
- **Regressões:** cobertura de capacidade, duplicata por ID, TTL, claim/replay concorrente, colisão, shutdown, expiração durante validação iniciada, revisão alterada durante UDP/FIFO/validação, falha de autenticação/cleanup, progresso de outro ID e invariância do estado do manager.
- **Verificação:** bateria focada de recovery, manager, scheduler, descoberta, transporte e parser — 237 passed; suíte backend — 352 passed; `rtk py -m compileall -q backend/src backend/tests` e `rtk git diff --check` passaram.
- **Segurança/escopo:** todos os testes usam stores/relógios/fakes e Events. Sem LAN REAL, hardware, cloud, credenciais, JSONL, UI, TOML ou adoção.
- **Resumo para revisão arquitetural:** o token interno só nasce após leitura autenticada e cleanup bem-sucedidos, enquanto a configuração ainda está leaseada. Revisar compartilhamento/encerramento do store e a fronteira do claim interno; sem confirmação pública nesta etapa.

## CR-39.1/39.2 — lifecycle e coleta tardia de propostas (2026-10-19)

- **Correção:** resultados coletados após TIMEOUT/CLOSED removem apenas o digest da proposta exata retornada pela Future. A remoção verifica a existência desse digest e não interfere em uma proposta mais recente para o mesmo Device ID.
- **Ownership:** `ProposalStore` permanece compartilhado e sem fechamento global parcial. Cada registro guarda owner privado; `RecoveryService.close()` invalida somente propostas dessa instância, preservando operações e tokens de outras instâncias ativas.
- **Regressões:** clock fake para expiração entre publicação e coleta; teste de retração sem apagar token mais novo; duas instâncias concorrentes com validação bloqueada por Events; expiração de owner e manutenção de propostas de outra instância.
- **Verificação:** testes focados `test_recovery_proposals.py` e `test_recovery_prepare.py` — 25 passed; suíte backend — 356 passed; compileall e diff-check aprovados.
- **Resumo para revisão arquitetural:** fechamento é por instância, pois não há lifecycle global da aplicação neste store; a coleta tardia é compensada por remoção exata e idempotente. Nenhuma adoção ou confirmação pública foi adicionada.

## F2E.D.3.A — confirmação interna e adoção atômica (2026-10-19)

- **Base/worktree:** `feature/f2e-d3a-adoption`, criada em worktree dedicado a partir de `origin/develop` no merge `abab02c` da PR #39. Implementação permanece local e sem commit/push/merge para revisão.
- **Contrato:** `confirm_internal()` aceita apenas token. O claim verifica owner sob mutex antes de consumir e carrega `expires_at` original. A admissão revalida lifecycle após o slot global; `CONFIRM_RECOVERY` é uma barreira FIFO tipada, discreta e sem coalescing.
- **Adoção:** uma lease compara revisão/endereço/protocolo/TTL/deadline/shutdown, executa segunda validação read-only 3.5, fecha adapter pelo `TuyaAdapter.close()` e faz commit sob lock ID → lifecycle. O helper incrementa revisão uma vez e preserva identidade/configuração privada/capacidades/pending; `update_address()` lineariza pelo mesmo lock.
- **Readback:** a lease é liberada antes do readback normal, que readquire o lock e confere a revisão do commit antes de I/O. Readback `SUCCEEDED`, `FAILED` ou `SUPERSEDED` permanece separado de `ADOPTED`; após commit, deadline/shutdown/falha não revertem adoção.
- **Cleanup:** TinyTuya 1.20.0 recebe `persist=False`; o adapter encapsula o socket exposto, torna falha sanitizada e inutiliza instância em cleanup parcial. Não há garantia de prazo rígido contra travamento nativo/kernel nem promessa de rollback físico; cleanup incerto aborta commit.
- **Regressões:** ownership/replay concorrente, validade original de TTL, expiração em fila e durante validação, deadline pendente/iniciado, lifecycle após slot, A→B→A, shutdown antes/depois do commit, alteração entre commit/readback, falha de auth/cleanup/readback, FIFO e progresso independente, invalidação de knowledge e preservação de pending.
- **Verificação:** suite focada — 148 passed; backend — 379 passed; `rtk py -m compileall -q backend/src backend/tests` passou; `rtk git diff --check` passou (aviso Git LF→CRLF no documento novo).
- **Escopo:** sem JSONL/IPC/Tauri/UI, TOML, escrita DPS, cloud, LAN real ou hardware. D-018/D-019 preservados.
- **Resumo para code review:** revisar atomicidade do claim/commit, cleanup observável e readback condicionado à revisão. Sem commit funcional até aprovação do review.

## F2E.D.3.B — integração JSON Lines (2026-10-19)

- **Base/worktree:** branch isolada `feature/f2e-d3b-jsonl`, sobre `origin/develop` em `c8bf7ce` (merge da PR #41).
- **Integração:** `serve` instancia `RecoveryService`, catálogo do `DeviceManager` e provider TinyTuya sem iniciar descoberta até `recovery.prepare`. `recovery.prepare` aceita somente `{deviceId}`; `recovery.confirm`, somente `{proposalId}`. Os dois executam no executor limitado, preservando requestId, writer único, concorrência e respostas terminais.
- **Fronteira pública:** serializers explícitos permitem status estáveis; prepare de sucesso retorna proposalId, IP candidato e TTL restante. Confirm separa `ADOPTED` do status de readback. Credenciais, owner, binding, DPS, exceções e traceback não são serializados.
- **Lifecycle e cobertura:** EOF fecha a instância, invalida propostas próprias, cancela estágios pendentes pelos contratos existentes e drena executor/writer para respostas aceitas. Regressões cobrem contratos JSONL, status de falha, ordem de conclusão, shutdown e dados sensíveis; os testes internos cobrem replay/expiração/owner, ambiguidade, autenticação e readback falho após adoção.
- **Verificação:** focados (`test_protocol.py`, `test_cli.py`, `test_recovery.py`, `test_recovery_prepare.py`, `test_recovery_confirm.py`) — **109 passed**; suíte backend — **391 passed**; `python -m compileall -q src tests` e `git diff --check` concluídos sem erros. Somente fakes/streams em memória; sem LAN, cloud ou hardware.
- **Escopo preservado:** sem Tauri/React, recuperação automática, TOML, escrita DPS ou acesso a hardware.
- **Resumo para revisão arquitetural:** a composição D.3.A agora está exposta somente por dois comandos JSONL fixos. Confirmar sobretudo os nomes/campos dos status públicos e o encerramento do serviço antes da integração Tauri.

### CR-43.1 — integração end-to-end prepare/confirm/replay

- Adicionado teste numa única sessão JSONL usando `RecoveryService`, `ProposalStore`, `DeviceManager` e `CommandScheduler` reais, com provider, validator e adapter fake. O teste lê o token da resposta prepare, espera cada resposta terminal antes do próximo comando, confirma adoção em memória, valida replay bloqueado e `ADOPTED` com readback `FAILED`.
- `JsonLinesServer` aceita clock monotônico injetável e o serializer de prepare usa esse mesmo clock para calcular TTL. O teste fixa o clock em valor não relacionado ao relógio real e verifica TTL restante de 60 segundos.
- A saída da regressão verifica os três requestIds, exatamente três respostas e um único thread escritor. EOF só ocorre após a resposta do replay.
- **Verificação CR-43.1:** testes focados (`test_protocol.py`, `test_recovery_prepare.py`, `test_recovery_confirm.py`) — **77 passed**; suíte backend — **392 passed**; `compileall` e `git diff --check` passaram. Commit publicado na branch rastreada pela PR #43; sem merge.

## F2E.D.4.0 — desenho documental e CR-44 (2026-10-19)

- **PR/branch:** PR #44 foi integrada à `develop` no merge `30255af5b1cd99179751710a675315168dc923e3`; o commit de desenho `5fe23ce` e as correções CR-44 permanecem no histórico da PR. O checkpoint foi atualizado após a integração.
- **Entregável:** [F2E_D4_TAURI_UX_DESIGN.md](F2E_D4_TAURI_UX_DESIGN.md) documenta contratos reais de `recovery.prepare`/`recovery.confirm`, statuses de domínio/transporte, bridge Rust, DTOs TypeScript, invalidação/reconciliação de estado, state machine/UX, MOCK/FIXTURE e plano D.4.A–D.4.C.
- **CR-44.1:** corrigida a formatação que armazenava separadores literais barra+n: arquivo convertido para Markdown multilinha com newline final. Estrutura, tabelas e diagramas preservados para renderização GFM.
- **CR-44.2:** `ttlSeconds` agora é descrito como finito `>= 0`; zero desabilita confirmação; margem visual de 2 s aprovada; nunca estender TTL; backend segue autoridade e a margem não altera o protocolo.
- **CR-44.3:** protocolo detalhado para invalidar `knownPublic`/`confirmedBase` por Device ID após `ADOPTED`, preservar valores históricos marcados stale, reconciliar snapshots e rejeitar respostas atrasadas/fora de ordem com comandos/refreshes concorrentes. Valores não observados não habilitam controles que dependem de baseline observado.
- **CR-44.4:** timeout de domínio em `result` separado do `error.code=TIMEOUT` do envelope e do timeout local de 30 s. Como bridge não distingue as duas últimas origens, timeout após enviar confirm é indeterminado sem evidência terminal inequívoca de domínio; sem retry automático, cancelamento fictício ou falha definitiva.
- **CR-44.5/decisões:** registradas no desenho as cinco decisões indicadas no review (controller separado; elegibilidade do catálogo público em DTO sem comando JSONL; TTL/margem 2 s; perfil FIXTURE 3.5 sintético com IPs reservados e identificação clara; readback `SUCCEEDED` sem `device` defensivo, nunca confirmação visual, backend fora do escopo). D-015 a D-019 não foram alteradas.
- **Estado:** D.4.0 foi exclusivamente documental; nenhum handler, componente ou lógica funcional integrou a PR #44. A PR foi integrada em `30255af`; a implementação funcional começa no checkpoint D.4.A abaixo.
- **Verificação:** contratos conferidos em `protocol.py`, `recovery.py`, `device_manager.py`, `bridge.rs`, `TauriDeviceController.ts` e `useLightingSession.ts`. GitHub Markdown API em modo GFM renderizou o documento com título, seis tabelas e dois blocos Mermaid; três links locais foram resolvidos, fences/tabelas/newline final foram validados e `git diff --check` passou. Nenhum teste funcional, compileall, acesso a dispositivo/LAN doméstica, cloud ou credencial foi usado.
- **Checkpoint para novo review:** correções documentais prontas; revisar principalmente guards de revisão/estado observado e semântica conservadora dos timeouts.

## F2E.D.4.A — bridge Rust/Tauri e FIXTURE determinística (2026-10-20)

- **Base/branch:** `feature/f2e-d4a-tauri-fixture`, criada isoladamente sobre `origin/develop` após a integração da PR #44 (`30255af5b1cd99179751710a675315168dc923e3`).
- **Implementação:** registrados somente `bridge_recovery_prepare(deviceId)` e `bridge_recovery_confirm(proposalId)`, usando o `BridgeClient` e subprocesso existentes. Os pedidos JSONL têm payloads fixos; respostas usam DTOs/enums com status allowlisted, campos estritos, candidato IPv4 e TTL finito `>= 0`. Readback permanece irmão e independente de `ADOPTED`; `SUCCEEDED` sem `device` é aceito defensivamente.
- **FIXTURE:** adicionados perfis sintéticos fixos Tuya 3.5/3.3 com IPs TEST-NET reservados para documentação, cenários de domínio/readback, expiração e replay, e isolamento por dispositivo. Estado de adoção fica somente em memória do processo. A fixture não abre sockets, não importa TinyTuya e não acessa LAN, cloud ou hardware. Correlação fora de ordem é exercitada por subprocesso de teste controlado, sem atraso artificial.
- **Arquivos:** `desktop/src-tauri/src/bridge.rs`, `desktop/src-tauri/src/lib.rs`, `backend/src/smart_home_tray/fixture.py`, `backend/tests/test_fixture.py`, `docs/contracts.md`, `docs/architecture.md` e este checkpoint.
- **Semântica preservada:** timeout local de 30 s encerra a espera do bridge, não cancela o backend e pode preceder uma adoção; não há retry automático. MOCK/FIXTURE/REAL, processo único e correlação `requestId` continuam usando a arquitetura existente.
- **Verificações:** Rust `cargo fmt --check` e `cargo test` — **28 passed**; Python focados (`test_fixture.py`, `test_protocol.py`) — **53 passed**; suíte backend — **398 passed**; `python -m compileall -q backend/src backend/tests` passou. Nenhum teste acessou dispositivo real.
- **Limites:** sem React/UX, `ManualRecoveryController`, polling, recuperação automática, escrita TOML/DPS, adoção 3.3 ou homologação física/REAL. A FIXTURE é simulação determinística, não evidência de compatibilidade física.
- **Riscos para D.4.B:** adaptar DTOs Tauri à capability `ManualRecoveryController`; expor elegibilidade somente via catálogo público dedicado; representar timeout de confirm como `indeterminate`; reconciliar readback por Device ID sem sobrescrever comandos/refreshes mais novos.
- **PR/estado:** [PR #46](https://github.com/SCAPUTO88/smart-home-tray/pull/46), direcionada a `develop`, publicada sem merge; branch `feature/f2e-d4a-tauri-fixture`. Commits de implementação `a07a883` e cobertura corretiva `6604c62`; checkpoint desta publicação segue nesta branch.
- **Review interno:** nenhuma issue crítica/importante; cobertura de prepare `TIMEOUT` foi adicionada após apontamento menor e passou novamente.
- **Checkpoint:** entrega publicada e parada para code review humano. Não iniciar D.4.B sem revisão.

### CR-46.1–CR-46.3 — admissão e propostas na FIXTURE (2026-10-20)

- **Base/branch:** correções sobre o head `90d2c3a` da branch `feature/f2e-d4a-tauri-fixture`, PR #46 para `develop`.
- **CR-46.1:** a fixture tenta adquirir o slot global antes de olhar/consumir a proposta. BUSY pré-admissão preserva token e TTL; teste injeta relógio monotônico e lock, libera o slot e confirma antes de expirar, seguido de replay bloqueado.
- **CR-46.2:** FIXTURE mantém no máximo uma proposta por Device ID e quatro por instância/processo, TTL monotônico original de 60 segundos; purge expirado e claim liberam capacidade. Prepare repetido retorna BUSY sem renovar proposta. Não há armazenamento de segredo nem réplica interna de RecoveryService/ProposalStore.
- **CR-46.3:** prepare e confirm disputam um slot global não enfileirável. O slot é liberado no retorno de prepare, portanto propostas esperando confirmação humana não bloqueiam outra operação. Testes de admissão usam lock injetado; o teste Rust de correlação agora usa subprocesso falso que envia duas respostas em ordem inversa, sem depender de atrasos da fixture. Removidos os perfis e sleeps artificiais usados para ordenar respostas.
- **Arquivos alterados:** `backend/src/smart_home_tray/fixture.py`, `backend/tests/test_fixture.py`, `desktop/src-tauri/src/bridge.rs` (somente testes), `docs/contracts.md` e este checkpoint. Código de produção Rust/JSONL, handlers, MOCK/REAL e D-015 a D-019 não foram alterados.
- **Verificações locais:** `pytest backend/tests/test_fixture.py` — 11 passed; suíte backend — **400 passed**; `python -m compileall -q src tests` passou; `cargo fmt --check` passou; `cargo test` — **28 passed**; `git diff --check` passou.
- **CI da PR antes da correção:** head anterior tinha Frontend e Python 3.12/3.14 aprovados, mas Tauri/Rust Windows falhou. A leitura do log de artifacts expirou por falha TLS no host de logs; causa exata não confirmada. Conferir os checks do novo head depois do push.
- **Limites/riscos:** concorrência, TTL e resultados são simulação local determinística; não demonstram comportamento TinyTuya nem homologação REAL/física. Nenhuma rede, LAN, cloud, credencial ou hardware foi acessado. O slot não modela duração real: serve apenas para admissão não enfileirável.
- **Estado:** CR-46.1–46.3 publicada na PR #46 no commit `d1edb65`, sem merge. O teste de correlação não depende de temporização da fixture.

### CR-46.4 — timeout do teste de resposta tardia (2026-10-20)

- **Causa:** o teste usava 100 ms também na segunda chamada. O subprocesso aguarda essa chamada para emitir primeiro a resposta atrasada do request que expirou e depois a resposta do request atual; o limite curto fazia a segunda chamada expirar em runners Windows.
- **Correção:** mantém 100 ms na primeira requisição, que expira enquanto o subprocesso aguarda a segunda. Depois, o timeout exclusivamente do cliente de teste é aumentado para 5 s. O subprocesso envia explicitamente a resposta tardia primeiro e a resposta atual em seguida. O teste verifica `TIMEOUT` na primeira chamada e que a segunda recebe `{"current":true}`, provando que a resposta tardia não foi entregue a ela e que o subprocesso não foi cancelado.
- **Escopo:** somente teste Rust em `bridge.rs` e este checkpoint; `BridgeClient` de produção e timeout real de 30 s permanecem inalterados. PR #46 permanece sem merge e D.4.B não foi iniciada.
- **Verificações locais:** teste corrigido executado **3 vezes**, cada execução com 1 passed; `cargo fmt --check` passou; `cargo test --locked` — **28 passed**; `git diff --check` passou.
- **CI:** conferir o job Tauri/Rust Windows MSVC do novo head após publicação. A falha confirmada do head `d1edb65` foi `bridge_timeout_does_not_cancel_backend_or_misroute_late_response`, com 27 passed e 1 failed por timeout da segunda chamada.
- **Checkpoint:** correção publicada para novo code review; sem merge.

## F2E.D.4.B — ManualRecoveryController e reconciliação TypeScript (2026-10-20)

- **Base/branch:** `feature/f2e-d4b-recovery-controller`, worktree isolado criado sobre `origin/develop` no merge `752ac4a942a44c0ab2960b33c3e6e5d8ebe373f2` (PR #46 integrada). A branch anterior D.4.A permaneceu intacta.
- **Capability:** adicionados `ManualRecoveryController` e adaptador Tauri tipado para apenas `bridge_recovery_prepare({ deviceId })` e `bridge_recovery_confirm({ proposalId })`. DTOs são discriminados pelos statuses do backend, rejeitam campos desconhecidos e aceitam somente dados públicos allowlisted. Confirmação ambígua retorna `indeterminate`; não há retry automático.
- **Plataformas/elegibilidade:** MOCK usa somente memória; FIXTURE e REAL resolvem pelos invokes fixos existentes e gates atuais, sem subprocesso adicional. Elegibilidade consultiva deriva do catálogo público carregado (3.5 elegível; outras versões válidas inelegíveis; dado ausente/desconhecido permanece UNKNOWN), sem inserir endereço ou protocolo em `LightingDevice`.
- **Reconciliação:** `TauriDeviceController` invalida `confirmedBase` e knowledge observado após adoção, preserva valores históricos como stale e aceita readback somente para o mesmo Device ID e quando catálogo, revisão, comandos e refreshes ainda são compatíveis. `useLightingSession` captura ID/revisões, não troca seleção nem aplica resposta a outro dispositivo, preserva operações de outras IDs e ignora conclusões tardias após unmount. ADOPTED com readback FAILED, SUPERSEDED ou SUCCEEDED sem snapshot deixa conhecimento stale; refresh posterior continua explícito.
- **MOCK:** adicionada simulação determinística 3.5/3.3 com propostas em memória, TTL pelo relógio injetável, single use e resultados de adoção/readback configuráveis por doubles locais. Sem rede, sockets, TinyTuya ou hardware.
- **Arquivos:** capability e contratos em `desktop/src/features/recovery/`; reconciliação/session em `desktop/src/features/devices/TauriDeviceController.ts` e `useLightingSession.ts`; resolução da integração em `desktop/src/features/devices/platformController.ts`; simulação em `desktop/src/mock/`. Decisões D-015 a D-019 não foram modificadas.
- **Verificações locais:** `npm test` — **128 testes aprovados em 14 arquivos**; `npm run typecheck` passou; `npm run lint` passou; `npm run build` passou (2345 módulos transformados). Nenhum teste usou LAN, cloud, credenciais ou hardware.
- **Limitações/riscos para revisão:** a confirmação remota pode adotar após o timeout local, portanto o frontend comunica resultado indeterminado e só invalida a base visual; reabertura/relistagem posterior depende de refresh explícito. Elegibilidade é apenas consultiva. Build e MOCK não constituem homologação REAL/física.
- **Estado:** implementação D.4.B publicada para review em [PR #48](https://github.com/SCAPUTO88/smart-home-tray/pull/48), commit `1bd80669eabad74eaf86715510545c8b9b10f692`, direcionada a `develop`. A branch remota foi criada e acompanha a branch local; a API GraphQL do GitHub recusou conexão ao tentar consultar checks/head final. Não houve merge e D.4.C não foi iniciada.

### CR-48.1–CR-48.2 — barreira causal da reconciliação (2026-10-20)

- **Causa-raiz:** `reconcileRecovery()` descartava a invalidação quando revisões de snapshot/estado mudavam durante `confirm`. Além disso, sequência maior de comando/refresh emitido antes do resultado era confundida com evidência física posterior; respostas tardias podiam repor knowledge observado e `confirmedBase`. O hook repetia a mesma suposição com `appliedRevision` e floors próprios, podendo deixar `confirmed` visual observado mesmo após a invalidação do controller.
- **Estratégia:** controller mantém uma época causal por Device ID, distinta dos contadores D-017 de emissão/aplicação e da geração de recuperação. `ADOPTED` ou resultado indeterminado avança a época e sempre invalida observações atuais; um readback `SUCCEEDED` do próprio backend é aplicado como observação autoritativa, se tiver o Device ID alvo. Operações iniciadas antes dessa barreira não podem restaurar baseline quando terminam; atualizam apenas o conhecimento afetado para stale (refresh invalida o snapshot todo). Uma operação aplicada depois da barreira pode prevalecer. A sessão React não replica épocas/floors: aplica o estado reconciliado do controller por Device ID e mantém intents pendentes/previews até as Promises terminarem.
- **Geração/ordem:** a barreira rejeita replay do checkpoint e resultado de geração de recuperação já superada. Uma confirmação anterior ainda pode reconciliar se uma geração mais nova apenas começou, mas não concluiu; a resposta terminal mais nova passa a prevalecer quando chegar. Mudança de catálogo invalida checkpoints antigos.
- **Regressões determinísticas:** comando iniciado durante confirm e concluído antes de `ADOPTED`; comando iniciado antes e concluído depois; refresh iniciado antes e depois do checkpoint e concluído após a adoção; `ADOPTED` com readback `SUCCEEDED`, `FAILED`, `SUPERSEDED` ou `SUCCEEDED` sem `device`; resultado indeterminado; refresh explícito posterior; duas gerações de recuperação; isolamento de dois dispositivos; estado interno/baseline do controller e estado visual `confirmed`, `preview`, `knowledge` e `pendingOperations`. Respostas usam deferred promises, sem sleeps.
- **Verificações:** `npm test` — **139 testes aprovados em 14 arquivos**; `npm run typecheck`, `npm run lint`, `npm run build` e `git diff --check` passaram. Após publicar o head, `gh run list` mostrou novas execuções Backend tests `39371710904` e Desktop frontend and Windows shell `39371711077` em andamento; consultas de status detalhado foram recusadas pelo proxy, portanto resultado final de CI não confirmado.
- **Limitações/riscos residuais:** operações locais já enviadas não podem ser canceladas; as que cruzam a barreira deixam a observação afetada stale e exigem refresh explícito para restabelecer conhecimento. Um refresh posterior iniciado enquanto ainda há outra operação pré-barreira em curso pode ser rejeitado pelas proteções D-017 e exigir nova tentativa explícita. Nenhum backend, protocolo JSONL, decisão D-015–D-019, UI D.4.C ou caminho REAL foi alterado/testado.
- **Estado:** correção publicada na PR #48, commit `efae7e1` (`fix: preserve causal recovery invalidation`), na branch existente. Push normal, sem rebase forçado/force-push; sem merge. Aguardando conclusão/verificação do CI e novo code review.

### CR-48.3–CR-48.4 — efeitos de modo e readback autoritativo (2026-10-20)

- **CR-48.3 causa:** comandos de brilho branco, temperatura e HSV passam por `_set_control_unlocked()`, que pode escrever `work_mode` antes do DPS principal. Uma resposta que atravessou a barreira causal invalidava só o campo DPS; assim, `workMode` do readback de recuperação permanecia falsamente observado. `set_power()` escreve apenas o DPS de energia e não tem esse efeito de modo.
- **Correção:** ao concluir um comando pré-barreira sem observação posterior que prevaleça, invalidar `workMode` junto com `whiteBrightness`, `colorTemperature`, ou `hsv` e `colorValue`. Power continua invalidando somente `power`. A projeção React aplica o estado/knowledge de `mode` retornado pelo controller para esses comandos, respeitando uma intenção de modo posterior; valores mantêm seu histórico, mas ficam stale.
- **CR-48.4 causa:** o refresh de leitura iniciado antes da barreira podia terminar depois de `ADOPTED + SUCCEEDED` e seu ramo causal chamava `invalidateCurrent`, degradando e removendo `confirmedBase` do snapshot confiável recém-retornado pela recuperação.
- **Correção:** qualquer resposta de refresh que atravesse a época causal é descartada; retorna-se o estado atual do controller. Se a recuperação trouxe readback `SUCCEEDED` com device, ele permanece autoritativo. Se não trouxe readback (FAILED, SUPERSEDED, SUCCEEDED sem device ou indeterminate), o estado atual já foi invalidado e a resposta antiga não o revalida. Comandos continuam tratados separadamente porque podem mutar o dispositivo após o readback.
- **Regressões determinísticas:** para comandos atrasados de `whiteBrightness`, `colorTemperature`, HSV e power, os testes verificam knowledge interno, preservação de campos independentes e estado stale do modo; testes do hook verificam `confirmed`, `preview`, `knowledge` e conclusão das operações. Refresh anterior resolvido após readback sucedido mantém valores, knowledge observado e baseline do controller/UI; FAILED continua stale. Os testes usam deferred promises, sem sleeps.
- **Verificação local:** as regressões focadas passaram (**42 testes**), a suíte Vitest passou (**148 testes em 14 arquivos**), `npm run typecheck`, `npm run lint`, `npm run build` e `git diff --check` passaram. Neste ambiente Windows restrito, Vitest/build foram executados com pool `threads` e preload temporário que suprime somente a consulta auxiliar `net use` do Vite; nenhum arquivo temporário permanece no produto.
- **Limites:** sem backend, contrato JSONL, D.4.C, LAN, cloud, credenciais ou hardware. CI remoto do novo head deve ser conferido após o push; o CI verde informado pela revisão refere-se ao head anterior.
- **Estado:** alterações locais não commitadas na branch existente da PR #48; `git add` foi bloqueado pelo ambiente porque o índice do worktree fica em `D:/Projetos/smart-home-tray/.git/worktrees/f2e-d4b-recovery-controller`, fora da raiz gravável. Nenhum lock foi deixado e nenhum workaround de escrita externa foi usado. Commit, push e CI do novo head permanecem pendentes; sem merge/force-push e sem iniciar D.4.C. Parar para novo code review após publicação.
