# Decisões técnicas e de processo

## Aprovadas

### D-001 — Backend Python local-first com TinyTuya

- **Estado:** aprovada.
- **Decisão:** Python + TinyTuya para comunicação LAN; React/TypeScript, Tauri 2 e sidecar ficam para fases futuras.
- **Motivo:** usar uma biblioteca existente para o protocolo Tuya e manter o backend independente do frontend.
- **Trade-off:** a integração depende dos contratos LAN e das limitações específicas de cada firmware; não há telemetria cloud em runtime.

### D-002 — Modelos e serialização com biblioteca padrão

- **Estado:** aprovada.
- **Decisão:** dataclasses, enums e serialização padrão; pytest somente como dependência de desenvolvimento.
- **Motivo:** reduzir dependências e manter modelos fáceis de testar.
- **Trade-off:** validação e conversão de configuração ficam explícitas no projeto.

### D-003 — Identidade pelo Device ID; IP é mutável

- **Estado:** aprovada.
- **Decisão:** Device ID é chave persistente; endereço IP é dado de conexão atualizável.
- **Motivo:** DHCP pode alterar o endereço sem alterar a identidade do dispositivo.
- **Trade-off:** redescoberta LAN terá de associar o resultado ao Device ID.

### D-004 — Capacidades e DPS declarados por dispositivo

- **Estado:** aprovada.
- **Decisão:** cada dispositivo declara mapeamento DPS e capacidades derivadas; não há mapeamento global de DPS.
- **Motivo:** a semântica e os recursos variam entre modelos.
- **Trade-off:** é necessária configuração inicial por dispositivo e a configuração não equivale a validação física.

### D-005 — Credenciais externas ao repositório

- **Estado:** aprovada.
- **Decisão:** TOML externo referencia nomes de variáveis de ambiente que contêm Local Keys; nenhuma credencial será versionada, logada ou exposta via IPC.
- **Motivo:** separar segredos da configuração versionável e manter o segredo fora do frontend.
- **Trade-off:** o ambiente de desenvolvimento precisa definir essas variáveis; armazenamento Windows protegido fica para fase futura.

### D-006 — JSON Lines como contrato futuro de sidecar

- **Estado:** aprovada.
- **Decisão:** uma mensagem JSON por linha com `requestId`; stdout fica reservado a mensagens de protocolo e diagnósticos usam stderr.
- **Motivo:** permitir integração simples entre Rust e o processo Python.
- **Trade-off:** framing exige que respostas sejam completas por linha; segredos nunca fazem parte do payload.

### D-007 — Execução em duas etapas com checkpoint

- **Estado:** aprovada.
- **Decisão:** implementar fundação e models/config/adapter, executar testes e parar para revisão antes de DeviceManager, CLI e protocolo.
- **Motivo:** permitir revisão arquitetural após a primeira fatia funcional.
- **Trade-off:** o backend não estará executável como produto completo nesse primeiro checkpoint.

### D-008 — Sem inicialização automática do Git

- **Estado:** aprovada.
- **Decisão:** não criar repositório, branch ou commits sem autorização explícita.
- **Motivo:** preservar o estado inicial solicitado.
- **Trade-off:** o trabalho atual não terá isolamento por worktree nem revisão baseada em diff/commit.

### D-009 — Compatibilidade Python 3.12 a 3.14

- **Estado:** aprovada para a fundação da Fase 1.
- **Decisão:** declarar `>=3.12,<3.15`; usar Python 3.14 disponível no ambiente para validação e manter 3.12 como versão mínima planejada.
- **Motivo:** TinyTuya publica wheel universal Python 3 e tem matriz de testes documentada até 3.12; PyInstaller atual documenta suporte a Python 3.8+ e adicionou suporte 3.14.
- **Trade-off:** este checkpoint valida o runtime instalado (3.14), não executa a matriz completa nem prova o empacotamento PyInstaller.
- **Referências:** [TinyTuya no PyPI](https://pypi.org/project/tinytuya/), [matriz do projeto TinyTuya](https://github.com/jasonacox/tinytuya/blob/master/AGENTS.md), [documentação PyInstaller](https://www.pyinstaller.org/en/stable/) e [changelog](https://pyinstaller.org/en/latest/CHANGES.html).

### D-010 — Scheduler contínuo com worker por dispositivo

- **Estado:** aprovado para a Etapa C2B.
- **Decisão:** adicionar `CommandScheduler` separado do DeviceManager. Após `start()`, há um worker por dispositivo; uma `Condition` compartilhada protege filas mas nunca é mantida durante operações LAN. Filas são FIFO por dispositivo. Apenas o último comando contínuo do mesmo tipo no segmento final pode ser substituído. A janela é fixa de 150 ms a partir da primeira intenção do segmento; atualizações repetidas não a reiniciam. Comandos contínuos também respeitam no mínimo 150 ms entre seus inícios, salvo quando um comando discreto antecipa uma intenção anterior. Power é FIFO discreto e antecipa a execução de controles anteriores ainda pendentes.
- **Resultados e ciclo de vida:** cada submissão retorna `Future[DeviceStatus]`; substituição e shutdown cancelam Futures ainda não iniciados. O Future de comando iniciado só termina com resposta do DeviceManager ou erro. `stop(timeout_seconds=10)` fecha novas submissões, cancela fila pendente e aguarda operações iniciadas até o timeout; retorna `False` se alguma ainda executa, permitindo novo `stop()` para aguardar seu encerramento.
- **Motivo:** combinar cadência previsível, entrega periódica durante arraste, ordem entre controles incompatíveis e progresso independente por lâmpada, sem alterar a API LAN síncrona do DeviceManager.
- **Trade-offs:** número de workers é proporcional ao catálogo de dispositivos; comandos podem esperar pelo fim de uma operação LAN mais longa e callbacks de Future executam no worker que publica o resultado. Não há restart após shutdown. O limite de espera do shutdown não interrompe comandos iniciados.

### D-011 — Contrato IPC JSON Lines e encerramento terminal

- **Estado:** aprovada para a Etapa D.
- **Decisão:** usar `COMMAND_CANCELED` para Futures substituídos ou cancelados; aceitar somente `requestId` string não vazio de até 128 caracteres e rejeitar IDs duplicados enquanto ativos; responder erros de ID com `requestId: null`; limitar linhas de entrada a 65.536 bytes UTF-8 e drenar o excedente até LF. JSON não finito é inválido. Toda requisição aceita deve receber resposta terminal; no EOF cancelam-se comandos enfileirados, operações já iniciadas terminam sem interrupção e o writer drena as respostas. Callbacks somente enfileiram eventos; um writer dedicado serializa stdout.
- **Motivo:** manter framing previsível e limitado, evitar crescimento ilimitado de IDs, impedir mistura de respostas concorrentes e garantir correlação durante comandos assíncronos e shutdown.
- **Trade-offs:** IDs deixam de ser retidos depois da resposta escrita, podendo ser reutilizados após conclusão; respostas de operações independentes podem terminar fora da ordem de recebimento; shutdown aguarda operações LAN já iniciadas conforme timeouts existentes. Uma quebra do pipe do processo hospedeiro impede entrega, embora o servidor ainda finalize o processamento local.


### D-012 — Fronteira de controle visual e mock da F2A

- **Estado:** aprovada para a Etapa F2A.
- **Decisão:** criar `desktop/` como frontend React/TypeScript independente, servível por Vite no navegador e preparado para Tauri 2. UI e sessão dependem da interface normalizada `DeviceController`; nesta etapa sua única implementação é `MockDeviceController`. O adapter Tauri/JSON Lines, scheduler de comandos, persistência e acesso físico ficam para fases seguintes.
- **Motivo:** demonstrar interação, animação e feedback antes de introduzir o processo nativo e a comunicação com dispositivos; manter credenciais e estruturas privadas fora do frontend.
- **Trade-offs:** o subconjunto tipado é mantido no frontend e precisará ser mapeado explicitamente ao contrato público JSON Lines. Os cenários assíncronos e estados confirmados são simulados, não são evidência de hardware. O protótipo ainda depende das ferramentas Rust/C++ para compilar como desktop.

### D-013 — Reconciliação visual por campo e rollback de prévia

- **Estado:** aplicada no code review F2A (CR-13/CR-14), mantendo D-012 e o contrato backend inalterados.
- **Decisão:** o mock e a sessão acompanham a precedência de intenção por dispositivo e por campo; HSV é reconciliado por canal. Respostas assíncronas só mesclam valores dos campos ainda pertencentes àquela operação. A prévia aplica patches pendentes sobre o último estado confirmado. Cancelamento/erro restaura a prévia dos campos afetados; offline invalida operações pendentes e mantém os valores conhecidos com qualidade offline. Estado desconhecido não é promovido a confirmado sem readback que o confirme.
- **Motivo:** preservar comandos independentes e evitar que um resultado atrasado ou uma falha pareça uma atualização confirmada.
- **Trade-offs:** o modelo visual acompanha intenções por campo sem ordenar ou agendar comandos no frontend. A integração JSON Lines futura deve usar respostas de readback do backend e continuar delegando ordenação/coalescing ao `CommandScheduler` Python. O seletor visual Branco/RGB precisará ser traduzido para uma operação de iluminação suportada; o protocolo não possui comando autônomo de modo.


### D-014 — Renderização de iluminação material na F2A.1

- **Estado:** aprovada para F2A.1.
- **Decisão:** representar lâmpada e fita com SVG/CSS em camadas. A lâmpada usa gradientes de vidro/metal, reflexos especulares estáticos e emissor interno; a fita usa emissores discretos sob difusor translúcido. Halo e ambiente usam gradientes radiais cuja cor e opacidade derivam exclusivamente do estado normalizado de prévia. Temperatura visual usa três âncoras: âmbar, neutra e azulada; power off zera todas as camadas emissivas.
- **Motivo:** aumentar materialidade e leitura de luz sem adicionar runtime 3D ou alterar arquitetura de controle.
- **Trade-offs:** SVG e gradientes mantêm o custo baixo e permitem emissão colorida; gradientes ainda repintam quando a cor muda. Para preservar fluidez, blur não é animado, não há loop contínuo, e `prefers-reduced-motion` reduz transições. A escala visual de temperatura não confirma a orientação física Tuya e exige validação no equipamento.

## F2B — Tray como proprietário do ciclo de vida do popup

**Estado:** adotada para a etapa F2B.

**Decisão:** tray, menu, instância única, posição, foco, ocultação e saída são controlados por Rust/Tauri. A janela inicia oculta e continua viva quando ocultada; fechar a janela equivale a ocultar. O menu **Sair** é o encerramento explícito. React recebe ações mínimas de hide e startDragging, somente no Tauri; o navegador não usa APIs nativas.

**Posicionamento:** encaminhar eventos pelo plugin `tauri-plugin-positioner`, usar o retângulo físico do tray, os limites do monitor e `Monitor::work_area()` para inferir o lado da taskbar. O popup fica 10 px físicos na direção oposta à barra, e posição/tamanho são limitados à work area. O tamanho lógico de 420 × 720 converte pelo scale factor do monitor a cada abertura, permitindo restauração após monitores menores. Só reposiciona quando oculto. O plugin limita à resolução total, não desconta taskbar; a geometria local complementa isso. Single instance continua registrada primeiro.

**Trade-offs:** a janela frameless e sem taskbar parece painel de bandeja e reduz controles nativos; por isso o botão acessível de ocultar, cursor de arraste no cabeçalho e menu Sair são explícitos. Estado React só persiste no processo aberto; não há persistência em disco. A janela não fecha ao perder foco para evitar interrupções em menus/seleção. Tray event rect já é físico e usa conversão 1.0; scale factor é aplicado somente ao tamanho lógico preferencial. Taskbar auto-hide pode não criar diferença na work area; a orientação então depende da âncora disponível. Layouts/DPI ainda precisam de inspeção manual no Windows.

**Segurança e escopo:** capabilities limitadas a `core:window:allow-hide` e `core:window:allow-start-dragging`, CSP mantida, sem `withGlobalTauri`, shell, filesystem ou comandos de iluminação. A UI segue no `MockDeviceController`, sem backend Python, JSON Lines ou dispositivos.

### D-015 — Ponte nativa tipada e modos explícitos

- **Estado:** aprovada para F2C.1.
- **Decisão:** Rust é proprietário do subprocesso e do modo de integração. MOCK é padrão; FIXTURE usa um módulo Python determinístico; REAL requer modo explícito, opt-in independente e caminho de configuração vindo somente do ambiente do processo Rust. React acessa operações nativas por handlers Tauri fixos e tipados, sem transporte JSONL genérico.
- **Motivo:** manter a fronteira DeviceController, preservar o contrato JSON Lines existente e impedir que a WebView selecione processos, caminhos ou credenciais.
- **Trade-offs:** há um processo Python externo por sessão Tauri e o modo REAL depende de runtime/configuração instalados. O processo fixture duplica respostas públicas simples para validação sem dispositivos. JSONL continua em stdout; stderr é drenado sem eco. Falhas são normalizadas sem detalhes brutos.
- **Confirmação:** respostas result só são lidas como readback; valores ausentes mantêm qualidade unknown. A composição HSV consulta estado público e intenções pendentes. CommandScheduler continua sendo o único scheduler. REAL permanece sem validação física nesta etapa.


### D-016 — Conhecimento de estado por campo e refresh manual (F2C.2)

- **Estado:** aprovada para F2C.2.
- **Decisão:** anexar ao snapshot LightState um mapa tipado de conhecimento por campo (observed/stale/unknown), derivado exclusivamente da leitura validada de DPS. Valores nullable e quality global permanecem; knowledge não representa confirmação de escrita. Leitura parcial pode atualizar um campo enquanto preserva os demais como stale.
- **Refresh:** uma ação explícita consulta somente device.status do dispositivo selecionado; não há polling ou retry automático. Refresh é bloqueado durante escrita pendente para manter a ordem do readback, e respostas obsoletas/desmontadas não alteram a sessão.
- **Trade-off:** campos stale continuam visíveis como última observação, mas seus controles ficam bloqueados até novo readback válido. A UI não usa defaults de apresentação como observação física.

### D-017 — Precedência de comandos e snapshots na F2C.2

- **Estado:** adotada para as correções CR-28/CR-29/CR-30/CR-31 da PR #21; revisão do delta pendente.
- **Decisão:** manter por dispositivo sequência de comandos emitidos e última sequência aplicada, IDs pendentes, revisão de snapshot confirmado, revisões de refresh e revisão de estado alterado por erro. Readbacks de comando são ordenados pela sequência emitida/aplicada; revisão de snapshot não invalida outro readback de comando mais recente. Erros de transporte só mudam conexão se nenhuma atualização posterior já mudou o estado. Refresh obsoleto não altera valores nem conexão. Readbacks válidos de operações anteriores ainda podem ser usados se operações posteriores falharem. Não armazenar resultado terminal redundante: cada Promise já entrega o resultado ao solicitante.
- **Motivo:** emissão não equivale a confirmação. Um comando mais novo pode falhar depois que um anterior confirmou valores diferentes da intenção; o snapshot confirmado deve prevalecer, sem preservar intenção terminal como se ainda estivesse pendente.
- **Trade-offs:** o controller mantém contadores distintos para ordem de comando, snapshots, refresh e mutações de estado por dispositivo, alinhados à precedência da sessão React. Isso não agenda nem reordena comandos; o `CommandScheduler` Python continua sendo o único scheduler de execução.
