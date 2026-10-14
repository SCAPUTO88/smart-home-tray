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
