# Arquitetura aprovada — Smart Home Tray

## Escopo

Backend local-first executável como processo independente. A operação em runtime usa a rede local e não requer API cloud, assinatura ou servidor remoto. O prototipo React/TypeScript com Vite e Tauri 2 da Etapa F2A esta implementado em desktop/; o adapter nativo e a integracao com o backend continuam planejados para etapas seguintes.

## Componentes

| Componente | Responsabilidade | Dependências |
| --- | --- | --- |
| `models.py` | Modelos de dispositivo, capacidades, estado, mapeamentos DPS e erros tipados. | Biblioteca padrão |
| `config.py` | Ler TOML externo, validar campos, resolver referências a variáveis de ambiente. | `tomllib`, models |
| `tuya_adapter.py` | Construir cliente TinyTuya, ler status LAN e escrever DPS. | TinyTuya, models |
| `device_manager.py` | Identidade persistente por Device ID, endereço mutável, coordenação de estado, timeout, reconexão e falhas isoladas. | Adapter, config, models |
| `command_scheduler.py` | Submissão assíncrona de operações normalizadas, coalescing de controles contínuos e ordenação discreta por dispositivo. | DeviceManager, biblioteca padrão (`threading`, `concurrent.futures`) |
| `color.py` | Conversão RGB/HSV e serialização/validação HSV16 dos valores de cor Tuya. | Biblioteca padrão, `colorsys` |
| `protocol.py` | Ler requests e escrever responses JSON Lines com framing limitado, validação e correlação assíncrona. | DeviceManager, CommandScheduler, models, biblioteca padrão |
| `cli.py` | Interface de diagnóstico e comandos explicitamente invocados pelo usuário. | config, DeviceManager, CommandScheduler, protocol |

`DeviceManager` cria o catálogo por `Device ID`, mantém estado público sem configuração privada e instancia adapters sob demanda. Cada dispositivo tem seu próprio lock; polling é opt-in via `start_polling()` e encerra com `stop_polling()`. `poll_once()` permite uma sincronização explícita sem thread. O intervalo padrão é 15 segundos. `update_address()` atualiza o IP e descarta o adapter para reconstruí-lo na próxima operação; não há descoberta automática nesta etapa. `list_device_ids()` expõe uma tupla lock-free das identidades do catálogo, cuja associação de IDs é imutável após a construção; alterações de endereço não mudam essa associação.

O CLI e o protocolo usam o mesmo DeviceManager. O frontend não recebe credenciais nem acessa TinyTuya diretamente.

## Fluxo de comunicação

1. `config.py` lê o arquivo TOML local e obtém Local Keys por nomes de variáveis de ambiente.
2. O DeviceManager mantém o cadastro por Device ID e usa o IP atual apenas para conectar/redescobrir.
3. O Adapter cria a sessão TinyTuya para protocolo e timeout configurados e faz operações LAN.
4. O Adapter converte falhas e respostas inválidas em erros estruturados e seguros. Uma escrita aceita não confirma estado físico; o DeviceManager faz leitura posterior antes de atualizar estado confirmado, pendente ou offline.
5. CLI e protocolo encaminham comandos normalizados ao DeviceManager; no IPC, escritas passam pelo CommandScheduler e respostas não carregam configuração privada.

O manager lê somente os DPS configurados de cada equipamento. Power exige booleano, escreve no DPS mapeado e só confirma a intenção após leitura que reporte o valor solicitado. Leituras divergentes atualizam o último valor observado, mas mantêm a intenção em `pending`; uma leitura posterior correspondente resolve a intenção. Na Etapa C2A, o mesmo princípio é aplicado por campo às intenções de iluminação, sem confundir confirmação de power e cor. DPS ausentes ou inválidos preservam valores anteriormente observados e não resolvem pendências. Resposta inválida degrada a qualidade para `unknown` sem converter automaticamente a conexão em offline; falha de transporte marca offline. `update_address()` preserva os valores conhecidos e eventuais intenções pendentes, mas invalida a confirmação até uma leitura no novo endereço. Falhas em um dispositivo não interrompem os demais.

## Estado, capacidades e sincronização

Capacidades são específicas por dispositivo e derivadas dos DPS declarados. `Luz Mesa` usa DPS 22 para brilho branco, DPS 23 para temperatura, DPS 24 para HSV e DPS 25 para cenas; a `Fita LED` usa Value do HSV em DPS 24 para intensidade colorida e não declara DPS de brilho branco ou temperatura. Os campos normalizados de brilho branco e intensidade HSV permanecem separados. Percentuais de brilho e temperatura usam `ValueRange`; capacidade declarada não significa validação física.

O codec C2A segue o formato HSV16 documentado pelo TinyTuya 1.20.0 (`HHHHSSSSVVVV`; hue 0–360, saturation/value 0–1000). O modo é escrito antes do valor dependente quando o DPS de modo está configurado e a última leitura indica modo diferente. Sem mapeamento de modo, não há alternância presumida. Comandos não ligam o dispositivo automaticamente. Uma troca de modo aceita seguida de falha no DPS de valor é uma falha parcial: não se faz rollback físico; o estado é atualizado por leitura de melhor esforço e a intenção incerta permanece pendente. Não há debounce nesta etapa.

Escritas são serializadas por dispositivo, preservando a ordem de comandos dependentes. Polling começa em 15 segundos e não se sobrepõe a escrita no mesmo dispositivo. Depois de comandos, o estado é relido antes de ser considerado confirmado. O scheduler C2B adiciona coalescing para controles contínuos na camada acima do DeviceManager.

### CommandScheduler (Etapa C2B)

O scheduler é uma camada opcional e explicitamente iniciada por `start()`; o construtor não cria threads. Ele consulta o catálogo público do DeviceManager e cria um worker por Device ID. Uma `Condition` compartilhada coordena filas FIFO independentes; o lock é liberado antes de qualquer chamada síncrona ao DeviceManager. Assim, dispositivos diferentes progridem em paralelo, enquanto o DeviceManager continua coordenando cada comando com polling pelo lock local.

Para cada dispositivo, uma intenção contínua fica elegível 150 ms após a primeira submissão do segmento; novas submissões do mesmo tipo substituem somente a intenção ainda não iniciada no final da fila e não reiniciam o prazo. A cadência limita inícios contínuos a pelo menos 150 ms, exceto quando uma barreira discreta antecipa a intenção precedente. Isso produz atualizações periódicas em um arraste longo, com atraso efetivo limitado pela duração da operação LAN em andamento. Controles incompatíveis — incluindo HSV e brilho colorido, apesar do DPS 24 compartilhado — são barreiras e preservam sua ordem.

Power é discreto e nunca sofre coalescing nem espera sua própria janela. Ao chegar, antecipa os controles contínuos anteriores ainda pendentes, mantendo-os antes do power na FIFO; comandos posteriores permanecem depois dele. O scheduler não combina valores HSV nem chama TuyaAdapter diretamente.

Cada API `submit_*` retorna `Future[DeviceStatus]`: enquanto aguarda, o Future não modifica nem confirma `LightState`; o resultado só é entregue após o método normalizado do DeviceManager completar sua leitura de confirmação. Um comando substituído tem Future cancelado; uma falha é propagada pelo Future preservando `BackendError`. Callbacks de Future executam sincronamente na thread que publica a conclusão e podem atrasar aquele worker e o shutdown. `stop(timeout_seconds=10)` fecha submissões, cancela comandos ainda na fila e deixa operações iniciadas terminarem. Retorna `False` se algum worker ainda está ativo no limite; também não tenta juntar a própria thread quando chamado de um callback. Uma chamada posterior de outra thread pode aguardar o encerramento. Shutdown não reinicia o scheduler e nunca cancela uma escrita iniciada.

### CLI e JSON Lines (Etapa D)

`cli.py` implementa entrypoint `argparse`; `list` e `--help` não acessam LAN. `status` e comandos de controle só acessam equipamentos quando solicitados explicitamente. O modo `serve` não inicia polling. `protocol.py` lê uma linha limitada a 65.536 bytes UTF-8 e valida os campos por allowlist; excedentes são descartados até LF e rejeitados sem derrubar o processo. `requestId` precisa ser string não vazia de até 128 caracteres e é mantido em memória somente enquanto a resposta está pendente; IDs ativos duplicados recebem erro com ID nulo.

O dispatcher envia escritas normalizadas ao CommandScheduler. `device.status`, `device.get` e `devices.list` usam executor limitado, portanto a thread de stdin não espera locks do DeviceManager. A inicialização lazy do scheduler consulta apenas `list_device_ids()` e não espera locks LAN; assim, uma primeira escrita para outro dispositivo ainda pode ser recebida enquanto uma operação está bloqueada em um dispositivo. Um writer dedicado é o único que produz stdout JSONL, com UTF-8 e flush por mensagem; stderr recebe diagnósticos. Callbacks de Future somente enfileiram o resultado, sem I/O. As respostas são correlacionadas por requestId, mas operações independentes podem concluir fora da ordem recebida. FIFO por dispositivo e confirmação por readback continuam nas camadas existentes. No EOF, novas entradas param, o scheduler cancela escritas ainda não iniciadas e deixa as iniciadas terminarem; o executor aguarda todas as leituras aceitas, inclusive consultas ainda na fila interna do executor. As respostas terminais são drenadas antes de encerrar o writer. O ciclo de espera respeita timeout por operação; duração total depende do timeout LAN e da quantidade de operações ativas.

## Erros e isolamento

Erros padronizados incluem `TIMEOUT`, `DEVICE_OFFLINE`, `AUTH_FAILED`, `INVALID_INPUT`, `UNSUPPORTED_CAPABILITY`, `DEVICE_ERROR` e `COMMAND_CANCELED`. Uma falha de dispositivo não interrompe consultas dos demais. Retornos Tuya inesperados recebem erro seguro e não expõem a chave nem dados brutos sensíveis. O erro 904 da Luz escritório permanece não crítico para o MVP.

## Segurança e limites

- Runtime somente LAN; APIs de cloud/wizard da TinyTuya não são chamadas pelo backend.
- Configuração real é externa e ignorada pelo Git. O exemplo contém placeholders e nomes de variáveis de ambiente.
- Local Keys não aparecem em stdout IPC, respostas, logs, repr dos modelos ou testes.
- A futura camada pública usa somente `device_status_to_public_dict`, com allowlist explícita; configurações privadas nunca são serializadas genericamente.
- Armazenamento protegido por usuário do Windows será tratado na fase de empacotamento.
- Testes padrão usam mocks; não executam comandos físicos.

## Desenvolvimento no Windows

No PowerShell, a partir do repositório:

```powershell
py -3.14 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
Copy-Item backend\config.example.toml backend\config.toml
```

Defina as variáveis de ambiente declaradas em `local_key_env` antes de iniciar o backend. O exemplo não contém credenciais. CLI/sidecar, comandos, framing e lifecycle estão detalhados em [contracts.md](contracts.md). Para executar, use `backend\.venv\Scripts\smart-home-tray.exe --config backend\config.toml list` ou `backend\.venv\Scripts\python.exe -m smart_home_tray.cli --config backend\config.toml serve`.


## Fase 2, Etapa F2A — protótipo visual

`desktop/` contém a interface React/TypeScript servida e compilada por Vite. A configuração Tauri 2 aponta para o mesmo `dev` e `dist`, com janela compacta; o frontend não importa APIs nativas, portanto também executa no navegador. Tailwind v4 é ligado pelo plugin oficial do Vite; Motion cobre transições de layout e CSS cuida de sliders, iluminação e estados simples.

A UI depende dos modelos normalizados em `desktop/src/features/devices/types.ts` e da interface `DeviceController`. Nesta etapa, somente `MockDeviceController` fornece o catálogo: `mock-desk-lamp` e `mock-led-strip`. Os modelos expõem identidade, capabilities, conexão, estado, qualidade e HSV normalizado. Capacidades de branco/temperatura existem só na Luz Mesa. Nenhum ID, capability ou valor de mock prova compatibilidade física.

`useLightingSession` mantém por dispositivo o patch solicitado, a prévia imediata, operações pendentes, estado confirmado e resultado/erro. A precedência é rastreada por campo, incluindo cada canal HSV, para que uma resposta atrasada só atualize campos cuja intenção ainda seja aquela operação; o readback completo é mesclado nesse subconjunto, sem restaurar valores antigos de campos independentes. A prévia é composta do último estado confirmado com as intenções ainda pendentes. Cancelamento e erro descartam a prévia otimista dos campos afetados; offline também invalida operações em andamento e preserva os valores conhecidos com qualidade offline. Qualidade `unknown` nunca vira `confirmed` somente pelo aceite do comando. Os componentes visuais não importam detalhes de mock. A futura implementação Tauri será um adapter da interface de controle para os comandos JSON Lines da Etapa D, sem mover scheduler/coalescing para o frontend.

O seletor visual Branco/RGB é uma abstração de apresentação. O protocolo JSON Lines não expõe uma operação pública isolada de troca de modo; o adapter futuro deverá traduzir essa seleção junto com uma operação de iluminação suportada, sem criar um comando IPC inexistente.

Testes automáticos usam Vitest, jsdom e React Testing Library. O workflow `.github/workflows/desktop-tests.yml` valida frontend isoladamente em Windows/Node 24. Nesta etapa a configuração Rust foi gerada, mas a compilação Tauri depende de Rust/Cargo e C++ Build Tools; nenhum equipamento físico, backend Python, LAN ou serviço cloud foi acessado.


### Representação visual F2A.1

O protótipo mantém a fronteira visual da F2A: `DeviceArtwork` recebe o dispositivo selecionado e o `DeviceState` de prévia, sem importar controladores ou detalhes de reconciliação. Gradientes e clip paths SVG descrevem vidro, reflexos e base metálica da lâmpada; CSS posiciona camadas radiais de glow e estrutura a fita com PCB, emissores e difusor. Cor e intensidade derivam de HSV/Value ou temperatura/brilho branco normalizados; power off define intensidade visual zero. Temperatura é representada visualmente como quente em 0, neutra em 50 e fria em 100, sem afirmar que a orientação corresponde ao hardware Tuya.

A representação usa gradientes, clip paths, opacidade e transições CSS. Não há WebGL, loop de animação de renderização nem blur animado; filtros de desfoque não são usados nas camadas dinâmicas. `prefers-reduced-motion` reduz transições CSS e o `MotionConfig` respeita a preferência do sistema. Isso limita repaints às mudanças de estado e mantém o custo proporcional à arte visível. A revisão depende de navegador manual; testes DOM não validam fidelidade de renderização.

## Fase 2, Etapa F2B — desktop Windows e system tray

A composição mantém a fronteira da F2A: React/Vite e `MockDeviceController` são proprietários da UI e do estado visual. Rust/Tauri é proprietário do tray, menu nativo, janela, posicionamento, foco, single instance e encerramento explícito. A F2B não inicia backend, sidecar ou scheduler e não abre JSON Lines, LAN ou cloud.

O app registra `tauri-plugin-single-instance` primeiro; uma segunda invocação reutiliza a janela da primeira instância. O setup cria um ícone Tauri com tooltip e menu nativo Abrir/Sair. Clique esquerdo só alterna visibilidade em `MouseButtonState::Up`; o evento é encaminhado uma vez ao positioner, e DoubleClick/MouseDown não disparam uma segunda ação. A janela é criada oculta, sem decoração, sem fullscreen, sem taskbar e sem always-on-top. CloseRequested vira hide para preservar o WebView; somente Sair marca encerramento explícito e chama `app.exit`.

A camada `desktop/src/platform` detecta `isTauri()` e expõe somente `getCurrentWindow().hide()`. O botão de ocultação é acessível e não aparece no navegador. A capability concede apenas `core:window:allow-hide`; `withGlobalTauri` permanece desativado e CSP existente foi preservada.

O plugin oficial `tauri-plugin-positioner` recebe os eventos para manter a posição do tray. Para respeitar taskbar, o app seleciona o monitor pela âncora física do tray, lê `Monitor::work_area()`, limita o tamanho e calcula uma posição dentro dessa área. O cálculo puro em `src-tauri/src/positioning.rs` preserva coordenadas negativas de monitores e tem fallback na área útil primária. O plugin `move_window_constrained` considera a resolução total, não a work area, por isso não é usado como limite final. Tauri e o tray reportam medidas físicas; tamanhos lógicos iniciais da configuração são convertidos pelo runtime antes da aplicação do clamp. A validação em DPI e múltiplos monitores ainda depende de Windows real.

A perda de foco não oculta automaticamente o popup nesta fase. Essa opção pode conflitar com menus contextuais e controles nativos e será reavaliada depois da validação manual. O frontend tem scroll vertical em janelas baixas e reduz a arte para não exigir uma altura mínima fixa.

O workflow desktop mantém Node 24 e adiciona um job Windows/MSVC com Rust estável e cache para formatação, checagem, testes Rust e build Tauri sem bundle. Um `npm run build` só valida Vite e não serve como evidência do app nativo. F2B não inclui integração real, persistência, inicialização com Windows, assinatura, update ou publicação; integração JSON Lines permanece na F2C.
