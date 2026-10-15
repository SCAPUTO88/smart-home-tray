# Refinamento: recuperação de IP por descoberta LAN

**Estado:** proposta técnica para revisão. Nenhuma decisão arquitetural deste documento foi aprovada e nenhuma parte está implementada.

## Problema e objetivo

Após queda de energia e renovação DHCP, o IPv4 de dispositivos Tuya mudou enquanto Device IDs e Local Keys permaneceram válidos. O TOML continuou apontando para endereços antigos, causando falha de leitura. A homologação recuperou a operação atualizando o arquivo TOML manualmente após descoberta com TinyTuya.

O objetivo é permitir reencontrar um dispositivo LAN já cadastrado a partir de seu Device ID, mantendo identidade, capacidades e credenciais. A descoberta deve ser local, limitada, apenas de leitura, isolada por dispositivo e nunca deve enviar comandos de iluminação.

## Arquitetura existente relevante

- `DeviceManager` usa Device ID como chave estável do catálogo, mantém um lock por dispositivo e cria adapters sob demanda. `update_address(device_id, address)` atualiza o endereço em memória sob o lock, descarta o adapter para reconstrução posterior, preserva valores/intenção e invalida conhecimento confirmado até novo readback.
- `TuyaAdapter` encapsula TinyTuya e normaliza erros; sua fábrica pode ser substituída por fake. A configuração carrega o TOML e resolve a Local Key pelo ambiente. Não se deve copiar essa chave para o scanner, logs, DTOs, erros ou frontend.
- `protocol.py` aceita comandos por allowlist e atualmente não possui operação de descoberta. Escritas seguem pelo `CommandScheduler`; este tem FIFO por Device ID e workers independentes. As leituras/refreshes REAL iniciados por `TauriDeviceController` podem concorrer com resultados assíncronos e respeitam precedência por revisão/sequência.
- Rust é dono do subprocesso e do modo (`MOCK` padrão, `FIXTURE` sem rede, `REAL` sob opt-in). A WebView só chama handlers Tauri fixos e tipados; não pode escolher processos, caminhos, argumentos ou mensagens JSONL arbitrárias.
- A documentação de arquitetura e contratos descreve explicitamente que não há descoberta automática atualmente.

## Abordagens consideradas

| Abordagem | Vantagem | Custo / risco |
| --- | --- | --- |
| Repetir tentativa no IP salvo | Simples; não faz broadcast. | Não encontra um endereço DHCP novo; inútil para o caso observado. |
| Descoberta UDP TinyTuya na LAN | Usa anúncio local com Device ID/IP/versão; sem Tuya Cloud e sem varrer todas as combinações TCP. TinyTuya expõe `find_device(dev_id)` e `deviceScan()`. | Depende de broadcasts, firewall, interfaces/sub-redes e suporte do firmware; o anúncio pode estar ausente ou não confiável como prova de identidade. |
| Varredura de sub-rede por TCP/porta | Pode encontrar dispositivos sem broadcast. | Custo e tempo crescem com interfaces e tamanho da sub-rede; aumenta tráfego e risco operacional; não recomendada como caminho normal. |

**Proposta recomendada para implementação futura:** usar a API de descoberta LAN do TinyTuya para obter candidatos por Device ID, sem cloud; considerar cada pacote UDP apenas uma pista. Para cada candidato único, tentar uma consulta `status` estritamente de leitura usando o Device ID, Local Key, protocolo e timeout já configurados. Aceitar o IP somente se a validação de identidade e a resposta do status forem suficientes, conforme a seção seguinte. Não implementar varredura de sub-rede TCP nesta feature.

TinyTuya documenta `find_device(dev_id=...)`, `deviceScan()` e a natureza LAN do scanner ([API](https://github.com/jasonacox/tinytuya/blob/master/API.md#find_device), [scanner](https://github.com/jasonacox/tinytuya#network-scanner)). A documentação corrente pode divergir da versão fixada pelo projeto; antes da implementação, conferir a API efetivamente instalada (TinyTuya 1.20.0 registrada no último handoff) e fixar essa compatibilidade em teste. Não depender da saída textual/CLI do scanner.

## Identificação e aceitação do novo endereço

1. A consulta parte de um Device ID já conhecido no catálogo; não cria nem pareia dispositivos novos.
2. Descoberta devolve candidatos com ID reportado, IP, versão e metadados disponíveis. Filtrar para correspondência exata do Device ID configurado; ignorar candidatos de outros IDs. Resposta UDP isolada nunca altera a configuração.
3. Validar IP como IPv4 LAN utilizável e rejeitar endereço inválido, multicast, unspecified, loopback ou broadcast. Não persistir nem publicar MAC.
4. Criar conexão candidata somente no backend, com os dados privados já configurados para aquele Device ID. Executar um `status` sem nenhuma escrita DPS. Verificar sucesso semântico conforme contrato do Adapter e consistência dos DPS suportados configurados. A resposta esperada de status e a identidade reportada pelo scanner devem corresponder ao mesmo cadastro.
5. **Ponto a fechar antes de implementação:** o protocolo TinyTuya/status disponível nesta versão precisa confirmar se fornece prova confiável de que o endpoint respondeu como o Device ID esperado. Um status bem formado por si só pode não vincular criptograficamente a resposta ao ID; erro ou ausência de ID esperado deve resultar em rejeição, nunca relaxamento silencioso da validação. A validação não deve interpretar 904 como identidade confirmada nem atribuir sua causa.
6. Com um único candidato validado, aplicar `update_address()` (ou equivalente transacional interno) sob lock e descartar o adapter antigo. Em seguida, uma leitura normal atualiza o estado; a resposta de descoberta não inventa estado observado.
7. Com mais de um candidato validado, não escolher por ordem ou proximidade: retornar resultado ambíguo e manter o IP atual. Sem candidato validado, manter o endereço e estado; reportar offline/erro de descoberta genérico conforme o contrato a definir.

Capabilities e Local Key continuam associados ao cadastro por Device ID. O processo só atualiza o IPv4 em memória. Nenhuma Local Key entra nos argumentos de Rust/Tauri, payload JSONL, mensagens públicas, exceptions, logs ou interface.

## Gatilhos e frequência

| Gatilho | Comportamento possível | Avaliação |
| --- | --- | --- |
| Startup REAL | Tentar uma leitura direta no IP configurado; para falha elegível, disparar no máximo uma descoberta dirigida por ID durante a inicialização. Limitar duração total do catálogo e não serializar o bootstrap de todos os dispositivos sem limite. | Ajuda retomada após DHCP, mas pode atrasar abertura, multiplicar broadcasts e complicar a UX quando vários dispositivos estão offline. Não repetir em todo restart sem cooldown. |
| Falha de leitura | Para `DEVICE_OFFLINE`/`TIMEOUT` em leitura normal, tentar uma descoberta limitada uma vez e repetir status somente após validar e trocar IP. | Recupera mudanças transparentemente; falsos positivos de falha podem causar scan inesperado e atraso. Não disparar por 904/`DEVICE_ERROR`, `AUTH_FAILED` ou falhas de parsing que não indiquem IP obsoleto. |
| Refresh manual | Um refresh do usuário tenta endereço conhecido; se falhar por transporte, uma descoberta única pode preceder uma leitura de status. | UX previsível e custo sob demanda, mas mistura refresh de estado com operação de descoberta mais demorada. |
| Recuperação explicitamente solicitada | Ação dedicada “redescobrir endereço” no app/CLI; resultado mostra encontrado, ambíguo, não encontrado ou validação falhou. | Intenção explícita e melhor diagnóstico. Exige novo comando/contrato e UX explícitos; recomendada como primeira entrega. |

**Sequência proposta:** PR inicial adiciona uma operação explícita e dirigida por Device ID na CLI e na bridge REAL tipada; MOCK/FIXTURE retornam resultado sintético, sem scanner. Não adicionar polling, scan periódico ou retry infinito. Considerar um único retry automático após `DEVICE_OFFLINE` somente em PR posterior, com limite/cooldown medidos e UX aprovada. Startup REAL continua fazendo o readback atual; não deve scanear todos os dispositivos por padrão na primeira versão.

## Isolamento, comandos e readbacks

- Descoberta e validação usam o lock já existente daquele Device ID, ou uma coordenação equivalente com semântica demonstrada. Enquanto ocorre, leitura/escrita do mesmo dispositivo aguarda; dispositivos diferentes continuam progredindo.
- A verificação não entra no `CommandScheduler` como comando de luz e não chama métodos de escrita. Se for exposta no IPC, é um comando de recuperação separado, com payload mínimo `{deviceId}` e resultado tipado. Não aceitar endereço fornecido pela WebView.
- `update_address()` roda dentro de uma seção crítica por dispositivo. Proteger também contra resultado atrasado: antes da troca, confirmar que o endereço/configuração não mudou desde o início da busca (geração/versionamento ou lock mantido) e que não há leitura/comando concorrente capaz de tornar o candidato obsoleto.
- Não substituir nem cancelar comandos pendentes. A opção recomendada é a operação aguardar o lock do mesmo dispositivo; se a integração com o scheduler não garantir essa ordem, rejeitar recuperação enquanto houver comando pendente. Comandos de outras lâmpadas nunca devem ser bloqueados por um lock global de descoberta.
- Estado retornado de validação é somente prova de conectividade/identidade, não confirmação de iluminação. O readback normal posterior decide `quality` e `knowledge`; mudanças de IP não atualizam sequência de comando no frontend nem invalidam respostas válidas de outro dispositivo.
- A busca pode descobrir vários dispositivos em um scan compartilhado, mas o primeiro incremento pode filtrar apenas o ID solicitado. Não manter cache global sem política de expiração e invalidação.

## Tempo, interfaces e tentativas

- Estabelecer orçamento explícito por operação: uma janela curta/finita de escuta, timeout e no máximo um teste de status por candidato, com teto de candidatos e prazo total. Valores concretos devem ser medidos contra a API TinyTuya compatível e submetidos a revisão; não herdar defaults de scan interativo que escutam por muitos segundos sem avaliar impacto.
- Enumerar interfaces/broadcasts uma única vez por tentativa. Na primeira versão, usar somente os broadcasts/interfaces enumerados pela TinyTuya compatível; limitar a execução concorrente de scans a um por processo e deduplicar candidatos por Device ID/IP.
- Tratar interface sem bind, VPN, Wi-Fi desligado, sub-rede isolada e firewall como falhas parciais. Registrar contagem/categoria genérica, sem despejar payloads nem dados sensíveis.
- No máximo uma tentativa por ação explícita; eventual política automática posterior deve ter cooldown por Device ID, limite global e cancelamento no encerramento do app.

## Persistência de endereço

**Alternativas:** (a) manter apenas em memória; simples e não modifica configuração do usuário, mas após reiniciar é necessário redescobrir novamente; (b) gravar TOML automaticamente; reduz redescobertas, mas dá ao processo efeito colateral sobre arquivo de configuração, exige política de backup/atomicidade/permissão e pode sobrescrever edição do usuário; (c) guardar override em arquivo local separado, adicionando precedência e suporte de lifecycle/migração.

**Proposta:** primeiro release mantém endereço atualizado somente na memória. Não reescreve TOML nem introduz arquivo de override até haver requisito e decisão explícita de persistência. No próximo startup, repete-se a ação de recuperação quando necessário. O trade-off é custo de nova busca após restart, em troca de configuração previsível e nenhuma escrita de disco não solicitada.

## MOCK, FIXTURE e fronteira de segurança

- Discovery deve ser uma dependência injetável (por exemplo, interface/provider em backend) e ter fake determinístico nos testes Python. Nenhum teste padrão importa/invoca sockets reais ou chama a API scanner real.
- FIXTURE implementa o novo contrato com respostas estáticas de sucesso, ausência, ambiguidade e erro; não instala/importa TinyTuya nem acessa LAN. MOCK usa estado sintético no controller.
- Tauri expõe apenas operação tipada sem endereço arbitrário ou detalhe TinyTuya. Rust continua selecionando subprocesso e modo; WebView não envia JSONL genérico nem caminho/configuração/segredo.
- REAL permanece gated pelos opt-ins existentes. A execução física posterior exige autorização explícita do mantenedor, fora da suíte automatizada.
- Normalizar erros com códigos públicos já existentes ou aprovar previamente novo código. Nunca incluir Local Key, Device ID não redigido em logs, MAC, bytes UDP, `repr` TinyTuya ou exceção original.

## Riscos e decisões em aberto

1. **Validação real de identidade:** confirmar no TinyTuya 1.20.0 como correlacionar anúncio e resposta de status com o Device ID sob a Local Key configurada; não aceitar apenas um DPS que pareça válido.
2. **Cobertura de protocolo:** broadcasts e discovery request podem variar por versão Tuya, firmware, Wi-Fi/VLAN e Windows firewall; um dispositivo legítimo pode não anunciar.
3. **Custo de scan:** várias interfaces/VPNs podem aumentar tempo e gerar duplicatas; requer limites testáveis.
4. **Interação single-instance e clientes concorrentes:** a homologação mostrou hipótese de interferência entre clientes para Fita LED, ainda não comprovada. Descobrir e validar com o mesmo processo reduz novos clientes, mas não prova ausência de disputa com aplicativos externos.
5. **Concorrência e consistência:** discovery não deve alterar o endereço entre emissão e execução de operação nem deixar readback antigo sobrescrever o novo estado.
6. **Persistência:** apenas memória significa repetição após restart; persistência automática permanece fora do escopo proposto.
7. **Diagnóstico:** 904 significa payload inesperado e não deve iniciar redescoberta automaticamente, já que não comprova endereço antigo.

Antes de implementação, obter aprovação do desenho, confirmar a API instalada e semântica de identidade, escolher valores de timeout/cooldown e decidir o contrato de resultado/erros. Nenhuma escolha deste documento é uma decisão arquitetural adotada.

## Testes automatizados propostos

Todos os testes devem ser determinísticos e não abrir sockets reais:

- Encontrar um candidato exato, validar por status read-only e atualizar só o endereço; assertar Device ID, capacidades, estado pendente e credenciais preservadas e adapter antigo descartado.
- Pacote UDP com ID diferente, IP inválido, anúncio duplicado ou candidato cujo status falha/malforma não muda o endereço.
- Nenhum candidato, timeout, falha de interface, múltiplos candidatos validados e erros TinyTuya normalizados; demais dispositivos continuam utilizáveis.
- Provar que o fake de validação só chama `status`, nunca `set_value`/escritas.
- Locks: recuperação disputa com leitura, comando ativo e `update_address()` concorrente; mesma lâmpada serializa e outra lâmpada conclui sem esperar o scan.
- Simular mudança concorrente de endereço/geração e confirmar que resposta atrasada não sobrescreve a configuração atual.
- Protocolo: allowlist/schema, correlação requestId, timeout/cancelamento/shutdown e respostas sem credencial, endereço, MAC ou payload de scanner.
- Rust: handler Tauri fixo, payload tipado apenas com `deviceId`, operação limitada ao modo permitido e normalização de erros.
- FIXTURE/MOCK: cenários de sucesso, não encontrado, ambíguo e erro; afirmar que nenhuma dependência scanner/rede é chamada.
- Frontend: estado pending/success/ambiguous/not-found/error, prevenção de resultado obsoleto por revisão, isolamento entre dispositivos e sem expor dados privados.
- Verificar como regressão que startup e refresh comuns não acionam discovery além da política escolhida e que não existe polling/retry ilimitado.

## Critérios de aceite propostos

- Um dispositivo cadastrado cujo IPv4 mudou pode ser localizado pelo Device ID sem Tuya Cloud; Device ID, capacidades e referência à credencial ficam inalterados.
- O novo endereço só é aceito após validação adequada de identidade pelo scanner e por status LAN read-only; broadcast sozinho não basta.
- Ausência, ambiguidade, timeout e dispositivo offline terminam dentro de orçamento definido, preservam endereço conhecido e não comprometem outros dispositivos.
- A descoberta não envia comandos de iluminação e não confirma estado de iluminação.
- Nenhuma Local Key aparece em logs, erros, JSONL, Tauri DTOs ou frontend.
- Testes automatizados usam apenas mocks/fakes/fixtures; sem LAN doméstica, equipamentos ou cloud.
- A descoberta não é contínua; gatilho e rate limit são explícitos, e testes provam o limite.
- Homologação REAL ocorre somente depois de autorização explícita do mantenedor.

## Divisão sugerida em PRs

1. **PR A — investigação/contrato backend:** confirmar TinyTuya 1.20.0 e identidade verificável; definir provider injetável, tipos de resultado, orçamento e testes fake do backend. Sem UI e sem auto-recovery.
2. **PR B — integração backend/CLI/JSONL:** operação explícita por Device ID, isolamento por lock, validação read-only, atualização de IP em memória e erros/resultados públicos seguros; fixtures e testes de concorrência/protocolo.
3. **PR C — bridge Tauri e fixtures:** comando fixo tipado, seleção estrita de modo, fixture estático sem rede, testes Rust de sucesso/falha e fronteira de segurança.
4. **PR D — UX de recuperação manual:** ação explícita, estados tipados e resultado isolado por dispositivo; testes UI para resultado atrasado e seleção alternada.
5. **PR E opcional — retry limitado após falha:** somente após métricas/revisão da recuperação manual; política, timeout e cooldown documentados, testes da ausência de loop e autorização separada para eventual homologação REAL.

## Resumo para revisão arquitetural

O plano recomenda recuperação explicitamente solicitada no primeiro incremento, scanner UDP TinyTuya apenas para candidatos, validação read-only no endpoint com os dados já associados ao Device ID, troca sob coordenação por dispositivo e endereço atualizado somente em memória. Não recomenda startup scan global, polling, varredura TCP de sub-rede nem persistência automática. A principal questão técnica pendente é provar que a versão TinyTuya instalada consegue vincular a resposta validada ao Device ID pretendido, e não somente devolver status plausível.
