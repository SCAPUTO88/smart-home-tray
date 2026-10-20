# Contratos internos e IPC futuro

## Modelos internos

- `DeviceConfig`: `device_id`, nome, endereço atual, versão Tuya, timeout, `DPSMap` e segredo privado não exibido em `repr`.
- `DPSMap`: índices opcionais de `power`, `work_mode`, `white_brightness`, `white_temperature`, `hsv` e `scene`; capacidades são derivadas da presença dos índices e dos limites necessários.
- `LightState`: valores normalizados e modo atual, com qualidade `confirmed`, `pending`, `offline` ou `unknown`. Brilho branco e intensidade HSV são campos distintos.
- `DeviceStatus`: identidade, nome, endereço atual, protocolo, capacidades e estado de conexão; nunca inclui Local Key.
- `BackendError`: código padronizado e mensagem segura sem credenciais ou chave local.

### Representação pública

`device_status_to_public_dict(DeviceStatus)` é a única conversão aprovada para expor estado pela futura camada pública/IPC. Ela constrói um dicionário por allowlist explícita de campos de identidade, capacidades e estado. Não use `dataclasses.asdict`, serializadores genéricos ou conversão de `DeviceConfig`/`AppConfig`; essas configurações podem conter Local Keys. O conversor rejeita outros tipos.

## Operações do adapter

- `read_status() -> dict[str, object]`: consulta status por LAN e retorna apenas o mapa `dps` validado.
- `write_dps(dps_index: int, value: object) -> None`: envia uma escrita DPS individual e converte erros TinyTuya em `BackendError`. Retornar sem erro significa somente que a operação TinyTuya não reportou falha; não confirma o estado físico nem atualiza estado confirmado. `None` é aceito como null ACK sem estado DPS. O `DeviceManager` deve fazer leitura posterior e só então publicar estado confirmado. Retornos não vazios devem conter um mapa DPS válido; respostas vazias ou inesperadas são `DEVICE_ERROR`.

## DeviceManager (Etapas C1 e C2A)

- `DeviceManager(AppConfig, adapter_factory=TuyaAdapter, polling_interval_seconds=15.0)`: mantém catálogo interno por Device ID e status públicos; configurações e Local Keys nunca são retornadas. Adapters são criados sob demanda e uma falha de inicialização afeta somente o dispositivo solicitado.
- `list_devices() -> tuple[DeviceStatus, ...]` e `get_device(device_id) -> DeviceStatus`: consultam catálogo; ID desconhecido ou inválido gera `BackendError(INVALID_INPUT)` com mensagem genérica.
- `read_state(device_id) -> DeviceStatus`: lê LAN e interpreta apenas DPS declarados no mapa daquele dispositivo: energia, modo, brilho branco, temperatura, HSV e cena textual. DPS ausentes ou inválidos não geram valores inventados nem descartam a última observação válida. Brilho branco e Value do HSV são campos independentes. HSV inválido é ignorado. Cena só é publicada quando é string. Um status válido sem valores interpretáveis mantém a qualidade anterior (inicialmente `unknown`). Falha de transporte marca conexão/qualidade offline preservando valores conhecidos; resposta inválida degrada a qualidade para `unknown`, preserva a conexão já conhecida e os últimos valores.
- `set_power(device_id, enabled: bool) -> DeviceStatus`: valida a capacidade por dispositivo, registra/substitui a intenção pendente, escreve no DPS mapeado e executa leitura posterior. Só retorna sucesso quando uma leitura DPS booleana feita nessa confirmação corresponde ao valor solicitado. Uma leitura divergente atualiza o último valor observado, mas mantém a intenção em `pending` e retorna `DEVICE_ERROR`; DPS ausente retorna erro de confirmação inconclusiva. Timeout de confirmação também preserva a intenção. Leitura posterior correspondente resolve a pendência; comando novo substitui a intenção anterior. Rejeição explícita restaura a intenção anterior e não é tratada como falha de leitura. Não há retry ou expiração automática. A operação não expõe escrita DPS arbitrária ao consumidor.
- `set_white_brightness(device_id, percent)` e `set_color_temperature(device_id, percent)`: validam percentual finito 0–100 e capacidade/faixa específica, convertem pelo `ValueRange` e fazem leitura posterior. Quando o modo está mapeado e diverge, escrevem primeiro `white` no DPS de modo. Sem DPS de modo, enviam diretamente o comando de capacidade declarada.
- `set_hsv(device_id, hue, saturation, value)`: valida HSV público (hue 0–360, saturation/value 0–100), serializa para HSV16 Tuya e faz leitura posterior. Quando o modo está mapeado e diverge, escreve primeiro `colour`. `set_color_brightness(device_id, percent)` usa exclusivamente HSV válido recebido na leitura LAN atual, preserva hue/saturation e modifica somente Value; um valor antigo ainda exibido em `LightState` não substitui uma observação atual ausente ou inválida, e nesses casos não há escrita.
- Comandos de iluminação dispensam escrita quando a leitura inicial válida já corresponde ao valor solicitado. Caso contrário, sucesso exige confirmação do valor e, se aplicável, do modo por leitura posterior. Divergência ou ausência de confirmação deixa a intenção específica pendente; leitura correspondente posterior resolve somente o campo correspondente. Intenções de cor/brilho não resolvem pendência de power.
- Se a troca de modo for aceita e a escrita do valor falhar, não há rollback físico automático. O manager faz uma leitura de melhor esforço para atualizar observações; intenção possivelmente aplicada permanece pendente. Uma rejeição explícita não é convertida em confirmação.
- Rejeições explícitas `INVALID_INPUT` e `UNSUPPORTED_CAPABILITY` removem somente a intenção da escrita rejeitada. Sem outras intenções pendentes, a qualidade volta ao valor existente antes da intenção (que pode ser `unknown`); com outra intenção independente, continua `pending`. A rejeição não promove estado desconhecido para `confirmed`; uma leitura válida posterior pode fazê-lo.
- `update_address(device_id, address) -> DeviceStatus`: atualiza endereço válido mantendo Device ID, descarta adapter antigo e força construção sob demanda no próximo acesso. Preserva valores conhecidos, invalida `confirmed` (qualidade passa a `unknown`) e mantém eventual intenção `pending` associada ao Device ID até uma leitura correspondente ou novo comando. Descoberta automática LAN está fora desta etapa.
- `start_polling()`, `stop_polling()`, `poll_once()`: polling não inicia no construtor; ciclo padrão de 15 segundos, encerrável explicitamente. `poll_once` executa ciclo isolado por dispositivo; locks por Device ID impedem sobreposição entre leitura/escrita no mesmo equipamento.

O construtor do `TuyaAdapter` preserva `BackendError` estruturado e normaliza outras falhas de criação do cliente para `TIMEOUT`, `DEVICE_OFFLINE` ou `DEVICE_ERROR`, sem propagar mensagem/cause bruta. Não são incluídos tracebacks nas respostas públicas.

## Erros

| Código | Uso |
| --- | --- |
| `TIMEOUT` | Timeout ao conectar ou receber resposta. |
| `DEVICE_OFFLINE` | Dispositivo inalcançável, resposta vazia ou falha de socket. |
| `AUTH_FAILED` | TinyTuya identifica chave/protocolo inválido (ex.: erro 914). |
| `INVALID_INPUT` | Configuração, DPS ou payload fora do contrato. |
| `UNSUPPORTED_CAPABILITY` | Operação solicita capacidade ausente no mapa do dispositivo. |
| `DEVICE_ERROR` | Erro do equipamento não mapeado para os códigos acima. |
| `COMMAND_CANCELED` | Comando substituído antes de iniciar ou cancelado por shutdown; mensagem genérica quando a causa específica não é confiável. |

Mapeamento documentado da TinyTuya: 903 → `INVALID_INPUT` (valor fora do intervalo); 904 → `DEVICE_ERROR` (payload inesperado, diagnóstico fixo e seguro); 907 → `UNSUPPORTED_CAPABILITY`; 914 → `AUTH_FAILED` (mensagem neutra sobre parâmetros de autenticação, sem afirmar se a causa foi chave ou protocolo). Códigos desconhecidos usam `DEVICE_ERROR`. Mensagens brutas de resposta/exceção não são repassadas.

## Valores de cor

`HSVColor` público usa hue em graus 0–360 e saturation/value em percentual 0–100. O codec `color.py` usa a convenção HSV16 do TinyTuya 1.20.0: três inteiros hexadecimais de quatro dígitos (`HHHHSSSSVVVV`), hue 0–360 e S/V 0–1000. S/V são truncados para décimos de percentual na codificação; o decoder rejeita tamanho, caracteres e componentes fora do intervalo. RGB usa canais 0–255. A convenção foi verificada no código versionado do TinyTuya, mas a equivalência física pode variar por firmware e não foi validada nesta etapa.

O percentual do DPS de temperatura é uma normalização matemática dos limites físicos configurados; não há inversão nem afirmação sobre mais quente/frio sem validação específica do equipamento.

## Configuração externa

TOML define `version = 1`, array `devices`, identidade, endereço, protocolo, timeout, `local_key_env`, tabela `[devices.dps]` e limites físicos. O nome em `local_key_env` é lido do ambiente; o valor não é serializado de volta nem incluído em erros. `config.example.toml` contém somente placeholders.

## CLI e JSON Lines

O entrypoint `smart-home-tray` (equivalente a `python -m smart_home_tray.cli`) aceita `--config <arquivo.toml>` e os subcomandos `list`, `status --device`, `power --device (--on|--off)`, `white-brightness --device --percent`, `color-temperature --device --percent`, `hsv --device --hue --saturation --value`, `color-brightness --device --percent` e `serve`. `list` somente consulta o catálogo; `status` e comandos de controle acessam LAN explicitamente. `--help` não carrega configuração nem inicia conexões. `serve` não liga polling.

O transporte `JsonLinesServer` lê e escreve bytes UTF-8: cada linha de entrada contém um objeto JSON e cada resposta ocupa exatamente uma linha JSON em stdout. Uma mensagem tem no máximo 65.536 bytes UTF-8, sem contar LF/CRLF. Linhas maiores são drenadas até o delimitador, recebem `requestId: null` e `INVALID_INPUT`; a leitura continua. JSON inválido, UTF-8 inválido, NaN e Infinity também são rejeitados.

`requestId` é obrigatório: string não vazia de até 128 caracteres. O cliente deve gerar IDs únicos durante a sessão. Duplicatas enquanto a resposta anterior ainda está em andamento recebem erro com ID nulo e não afetam a requisição original. IDs saem do conjunto ativo após a resposta terminal ser gravada, evitando retenção ilimitada. ID ausente, de tipo incorreto, vazio ou longo demais retorna `requestId: null` e `INVALID_INPUT`.

Envelope da requisição (campos extras são rejeitados):

```json
{"requestId":"req-1","command":"device.status","payload":{"deviceId":"<id>"}}
```

Sucesso usa `{"requestId":"req-1","result":...}`; erro usa `{"requestId":"req-1","error":{"code":"DEVICE_OFFLINE","message":"Device is unreachable"}}`. Para IDs inválidos, a resposta usa `requestId: null`. Status é serializado exclusivamente por `device_status_to_public_dict()`; `DeviceConfig`, `AppConfig`, DPS crus, Local Keys e exceções não são serializados.

Comandos e payloads exatos:

| Comando | Payload | Resultado |
| --- | --- | --- |
| `devices.list` | `{}` | `{ "devices": [DeviceStatus público, ...] }`, sem LAN; executado fora da thread de stdin |
| `device.get` | `{ "deviceId": string }` | `DeviceStatus` do catálogo, sem LAN; executado fora da thread de stdin |
| `device.status` | `{ "deviceId": string }` | `DeviceStatus` após leitura LAN |
| `device.power` | `{ "deviceId": string, "enabled": boolean }` | `DeviceStatus` após readback confirmado |
| `device.whiteBrightness` | `{ "deviceId": string, "percent": 0..100 }` | `DeviceStatus` após readback confirmado |
| `device.colorTemperature` | `{ "deviceId": string, "percent": 0..100 }` | `DeviceStatus` após readback confirmado |
| `device.hsv` | `{ "deviceId": string, "hue": 0..360, "saturation": 0..100, "value": 0..100 }` | `DeviceStatus` após readback confirmado |
| `device.colorBrightness` | `{ "deviceId": string, "percent": 0..100 }` | `DeviceStatus` após readback confirmado |

Números devem ser finitos; booleanos não contam como números. Objetos payload são allowlists exatas, sem chaves de credenciais ou escrita DPS genérica. Escritas passam pelo `CommandScheduler`; power é discreto e controles contínuos mantêm o coalescing de 150 ms. Uma resposta pode terminar fora da ordem de recebimento devido a operações assíncronas independentes; FIFO por dispositivo continua sob responsabilidade do scheduler. Enqueue não confirma estado: sucesso só é emitido após o DeviceManager concluir readback válido.

`device.status`, `device.get` e `devices.list` são despachados por executor limitado, sem criar uma thread por mensagem, para que a thread de stdin nunca espere locks ocupados por operações LAN. A inicialização lazy do scheduler consulta o snapshot lock-free de IDs do catálogo (`DeviceManager.list_device_ids()`), não estados públicos que precisam dos locks por dispositivo. O catálogo de IDs é imutável após construção; IPs e adapters podem mudar sem alterar a identidade.

Substituição pelo coalescing ou cancelamento de comandos ainda não iniciados no shutdown termina com `COMMAND_CANCELED`. O código distingue apenas cancelamento conhecido; mensagem é genérica e segura. Uma operação LAN iniciada não é interrompida. Ao receber EOF, o servidor para novas submissões e fecha o scheduler, que cancela sua fila de escritas ainda não iniciadas. O executor de leituras é encerrado com espera e sem cancelar Futures: consultas de catálogo/status já aceitas, inclusive as ainda aguardando um worker, são executadas e concluídas. Só então o servidor aguarda as respostas terminais, drena a fila do writer e encerra. O tempo de shutdown depende dos timeouts das operações. O writer é único, serializa e faz flush a cada linha; callbacks de Future apenas põem um evento em fila. stdout é reservado ao protocolo em `serve`; diagnósticos vão para stderr.

Erros JSON/contrato usam `INVALID_INPUT`; códigos do DeviceManager são preservados com mensagens públicas seguras. Falha inesperada vira `DEVICE_ERROR` genérico, sem traceback ou texto interno no IPC.

## CommandScheduler (Etapa C2B)

`CommandScheduler(device_manager, coalescing_window_seconds=0.150, clock=time.monotonic)` é uma camada local, opcional e sem acesso a TinyTuya/credenciais. `start()` inicia um worker por dispositivo; repetir `start()` não duplica workers. Submissão exige scheduler iniciado, ainda aberto e Device ID conhecido. ID desconhecido gera `BackendError(INVALID_INPUT)` imediatamente. Validação de argumento/capacidade ocorre no método normalizado do DeviceManager e seu `BackendError` é preservado no Future.

As APIs retornam `concurrent.futures.Future[DeviceStatus]`:

- `submit_white_brightness(device_id, percent)` → `DeviceManager.set_white_brightness`.
- `submit_color_temperature(device_id, percent)` → `DeviceManager.set_color_temperature`.
- `submit_hsv(device_id, hue, saturation, value)` → `DeviceManager.set_hsv`.
- `submit_color_brightness(device_id, percent)` → `DeviceManager.set_color_brightness`.
- `submit_power(device_id, enabled)` → `DeviceManager.set_power` (discreto).

Future pendente representa comando recebido aguardando execução e não altera `LightState`. `Future.running()` indica que começou. `result()` só retorna `DeviceStatus` depois que o DeviceManager finalizou a operação e seu readback; exceções preservam `BackendError`. Se uma intenção ainda não iniciada for substituída, o Future anterior fica cancelado (`Future.cancelled()`/`CancelledError`).

Cada dispositivo tem uma FIFO própria. Apenas controles contínuos do mesmo tipo no fim da fila são compatíveis para substituição; atualizações não reiniciam a janela iniciada na primeira submissão. O worker mantém cadência mínima de 150 ms entre inícios contínuos, assim uma interação prolongada envia o valor mais recente periodicamente sem esperar o usuário parar. Comandos diferentes são barreiras: HSV e brilho colorido não se substituem embora compartilhem DPS 24; controles branco/cor mantêm ordem e trocas de modo são executadas pelo DeviceManager.

Power sempre é enfileirado sem coalescing ou espera de janela própria. Na chegada, libera imediatamente as intenções contínuas anteriores ainda aguardando, que seguem antes de power pela FIFO; comandos que chegam depois permanecem depois de power. Uma operação já iniciada nunca é cancelada nem alterada.

`stop(timeout_seconds=10.0) -> bool` fecha novas submissões, cancela Futures de comandos ainda na fila, permite comandos iniciados terminarem e aguarda os workers até o limite. `True` indica que todos os workers encerraram; `False` indica que pelo menos um ainda está ativo. Se chamado dentro de callback de Future, não tenta executar `join()` da própria thread e retorna `False` enquanto ela não tiver encerrado; uma chamada posterior de outra thread pode completar a espera. Callbacks de Future executam sincronamente na thread publicadora, podendo atrasar o worker e o shutdown. O scheduler é de ciclo único e não reinicia após stop. Workers são explicitamente não daemon; a aplicação deve chamar `stop()` no encerramento. A duração efetiva de shutdown depende dos timeouts de rede, da operação síncrona em andamento e de callbacks.

### Coordenação interna F2E.D.2.B.1

O `DeviceManager` mantém revisão privada monotônica da configuração por Device ID. Cada `update_address()` bem-sucedido incrementa a revisão, inclusive quando o endereço recebido é igual ao atual. Snapshot/lease são contratos internos e nunca entram na conversão pública de status. A lease segura o lock do ID enquanto `CandidateValidator` usa a configuração atual; não se chama `read_state()`, adapter ativo ou qualquer método que readquira esse lock.

`CommandScheduler.submit_recovery_validation(device_id, candidate, revision, deadline)` enfileira `VALIDATE_RECOVERY`, retorno `Future[ValidationResult]`. É uma barreira imediata e discreta, sem coalescing; não é comando JSON Lines e não aceita handler/callback no payload. A coordenação de recuperação é chamada fora dos workers e mantém o slot global D.1 até a Future concluir. Shutdown cancela itens ainda enfileirados; item já iniciado mantém worker e lease até terminar, mesmo quando `stop()` retorna `False` por timeout.

`RecoveryService.close(timeout_seconds=0.0) -> bool` fecha novas validações e espera pelo slot global sem segurar mutex de lifecycle durante I/O. `False` significa que a operação continua ativa e o serviço ainda não terminou o fechamento; uma chamada posterior pode concluir a espera. Resultado de validação concluído após o fechamento é normalizado para `CLOSED`.

A espera da validação usa a deadline monotônica do request. Ao expirar, o coordenador tenta cancelar a Future: sucesso significa item ainda não iniciado e retorna `TIMEOUT`; falha significa que o worker já iniciou, então o coordenador drena a Future até a conclusão real antes de liberar o slot, e retorna `TIMEOUT` se a deadline passou. Cancelamento da Future pelo shutdown retorna `CLOSED`. Nenhuma thread é destacada para abandonar I/O.


## Consumidor frontend mock (F2A)

`desktop/src/features/devices/types.ts` define um subconjunto visual normalizado alinhado conceitualmente ao status público da Etapa D:

- `deviceId` e `name` identificam a entrada pública; `kind` e a apresentação tipada existem para a UI.
- `capabilities` informa `power`, `rgb`, `white` e `temperature`. O mock de Fita LED declara branco e temperatura como indisponíveis.
- `connection` usa `online` / `offline`. `state` mantém `enabled`, `mode`, HSV com H 0–360 e S/V 0–100%, brilhos brancos normalizados de 0–100 e `quality`.
- `DeviceController` é a fronteira consumida pela sessão. `MockDeviceController` implementa catálogo e comandos de demonstração; não chama `fetch`, sockets, backend Python, TinyTuya, LAN ou cloud.

`DeviceViewState` separa patch `requested`, `preview`, `pendingOperations`, `confirmed` e `error/status`. `LightingPatch.hsv` pode conter canais parciais para que uma atualização de matiz não carregue saturação ou Value antigos. A precedência por dispositivo e por campo (incluindo canais HSV) determina quais valores de uma resposta ainda podem atualizar `confirmed`; os outros campos do estado retornado são ignorados. A prévia aplica sobre o último confirmado somente as intenções ainda pendentes. Sucesso usa o readback retornado sem promover qualidade `unknown`; cancelamento e erro removem a prévia otimista dos campos afetados e mantêm o último confirmado. Offline invalida operações pendentes, mantém os valores conhecidos e marca conexão/qualidade offline. Respostas atrasadas de erro não substituem feedback de uma intenção mais recente. Os modos de mock success/delay/canceled/error/offline só descrevem a simulação.

O seletor visual Branco/RGB não corresponde a um comando público próprio. O adapter futuro deverá traduzir a seleção em conjunto com uma operação de iluminação suportada (como brilho branco ou HSV) e usar apenas envelopes JSON Lines existentes; não deve inventar um comando IPC de troca de modo.

Como a interface visual pode enviar um patch de um canal HSV, o adapter futuro deverá compor os três canais necessários pelo comando público `device.hsv` usando o estado normalizado mais recente e as intenções ainda pendentes, sem reintroduzir canais obsoletos.

Os tipos não incluem `DeviceConfig`, configuração TOML, DPS, endereço LAN, Local Keys ou autenticação. Não são uma serialização nova do backend: o adapter Tauri futuro terá de mapear explicitamente os envelopes JSON Lines públicos e manter a allowlist da Etapa D.

## F2E.D.0 — recuperação manual (refinamento, não contrato implementado)

D-018 aprova somente a política de confiança. Nenhuma operação JSONL/Tauri foi adicionada. O desenho em [`F2E_D_RECOVERY_ARCHITECTURE.md`](F2E_D_RECOVERY_ARCHITECTURE.md) propõe `device.recovery.prepare` com `{deviceId}` e `device.recovery.confirm` com `{proposalId}`: o cliente não envia IP. D.1 somente coleta e normaliza candidatos não verificados; não cria proposta confirmável ou token. Solicitação de adoção para protocolo cadastrado 3.3 é recusada antes do scan; descoberta diagnóstica 3.3 é uma operação separada. Em estágios posteriores, token opaco é temporário, single-use e não contém segredo; um endereço só é aplicado em memória depois de validação read-only 3.5 e confirmação explícita. `ADOPTED` e readback são resultados irmãos, mesmo quando enviados na mesma resposta. Budgets, defaults, nomes finais de comando/resultado e barreira do scheduler não estão aprovados.

## Field knowledge metadata

Every public device state includes an additive knowledge object with power, workMode, whiteBrightness, colorTemperature, hsv, colorValue, and scene. Each value is observed, stale, or unknown. The backend derives it from validated DPS readbacks and stores it in the immutable state snapshot. Nullable state values and global quality retain their existing meanings; field knowledge does not confirm pending writes. A successful partial read marks returned valid fields observed and absent or invalid previously observed fields stale. Failed reads preserve the last values and mark observed fields stale. colorValue follows the HSV DPS observation.

## Recuperação manual — D.1 interno

`RecoveryService.discover_for_recovery(device_id, *, timeout_seconds=3.0)` aceita somente um ID presente no catálogo e protocolo 3.5 para o fluxo de adoção futura. Protocolo inelegível e ID ausente são rejeitados antes do provider. Cada solicitação elegível chama o provider uma vez, com timeout limitado a 3 segundos, e preserva a normalização de `discover_candidates()`.

`RecoveryResult` distingue `candidate_unverified`, `not_found`, `ambiguous`, `timeout`, `discovery_failed`, `catalog_failed`, `device_not_found`, `protocol_not_eligible`, `busy` e `invalid_request`. Seus candidatos expõem somente Device ID, IPv4 normalizado e versões anunciadas. Para cadastro 3.5, candidato único só recebe `candidate_unverified` se a coleção normalizada de versões distintas for exatamente `("3.5",)`; versão ausente, incompatível ou conflitante retorna `protocol_not_eligible` sem candidato. Essa checagem de anúncio UDP não autentica nem verifica identidade. A classificação `ambiguous` do F2E.B é preservada sem selecionar candidatos. Não há estado autenticado/verificado, proposalId, token, credencial, MAC, payload UDP ou exceção bruta. Falha ou timeout não transporta candidatos parciais. A concorrência usa um slot global não enfileirável; nenhum lock do DeviceManager permanece adquirido durante o scan.

Este contrato é interno ao backend e não altera CLI, JSON Lines, Tauri ou frontend. Candidato único continua sendo apenas anúncio não autenticado. A D.1 não abre TCP, chama status/escrita, valida identidade, cria proposta confirmável ou atualiza endereço.

Os budgets e defaults indicados como pendentes no registro F2E.D.0 foram posteriormente aprovados em D-019 para orientar D.1–D.3. Isso não torna esses fluxos implementados: em particular, o timeout efetivo do TinyTuya para validação TCP permanece sujeito a verificação.

## Validação read-only isolada — D.2.A

Contrato interno do backend, sem rota CLI/JSONL/Tauri:

- CandidateValidator.validate(config, candidate, *, deadline) retorna somente ValidationResult(status, phase). O sucesso chama-se KEY_AUTHENTICATED_READ; significa que DPS aceito foi recebido numa sessão autenticada pela Local Key cadastrada. Não representa identidade independente nem autorização para alterar IP.
- O transporte aceita somente protocolo cadastrado 3.5 e versões anunciadas exatamente ("3.5"), TinyTuya instalado exatamente 1.20.0, chave codificável em Latin-1 com 16 bytes, GCM disponível e endereço IPv4 RFC1918 de host numa sub-rede privada ativa elegível.
- Uma operação abre no máximo um socket TCP, faz handshake e uma consulta DP_QUERY_NEW read-only. Só frames 6699 com autenticação GCM válida são aceitos. Retcode diferente/ausente, comando inesperado, 55AA, JSON duplicado/malformado, DPS sem campo reconhecido, deadline, limite ou cleanup com falha rejeitam a leitura.
- Deadline monotônica cumulativa é limitada a 2,5 s. Orçamento por operação: 8 frames, 12 KiB incluindo entrada e saída, 1.440 bytes por payload. IVs de envio são gerados explicitamente por entropia do sistema; IVs repetidos de recepção são rejeitados. Nenhum retry ou reconexão ocorre.
- Os limites de compatibilidade são locais ao cliente: backend mantém tinytuya>=1.20,<2. Uma versão diferente de 1.20.0 permanece permitida aos demais componentes, mas não habilita este validador até auditoria própria.
- DPS brutos existem somente durante a validação interna e não são copiados para ValidationResult. O parser puro compartilhado dps_observation.py reconhece somente DPS mapeados com tipos/faixas já usados pelo DeviceManager; não aplica estado, pendências, conhecimento ou readback.

Limitações do contrato: a deadline limita connect/send/recv e a verificação após close, mas não consegue interromper um travamento síncrono nativo do sistema durante cleanup. A classificação de interfaces é baseada em psutil: RFC1918, ativa, máscara até /30 e mesma sub-rede; redes VPN que atendam esses critérios também podem ser elegíveis. Nenhuma validação de firmware em hardware foi realizada.

D.2.A não cria tokens/propostas, não coordena locks, não altera DeviceManager, endereço ou TOML e não integra a orquestração D.1. Esses elementos permanecem para D.2.B/D.3 conforme o documento de arquitetura.

## Coordenação de propostas — D.2.B

`RecoveryService.prepare_internal(device_id, scheduler)` é somente backend interno. Reserva o slot global antes do snapshot, limita o prepare a 5,5 segundos, executa uma descoberta D.1 (máximo 3 segundos) sem reacquirir o slot e usa a barreira FIFO `VALIDATE_RECOVERY`. A janela da validação permanece limitada a 2,5 segundos e inclui espera na fila. O slot não é liberado enquanto uma validação iniciada ainda possui I/O; trabalho pendente pode ser cancelado e não começa tardiamente.

`PreparationResult` mantém resultados tipados de descoberta, revisão, validação, store, cancelamento e shutdown. Só `PROPOSAL_READY_INTERNAL` carrega um descritor interno; token é redigido do repr e nunca é registrado. Nenhuma falha preserva exceção bruta, configuração privada, Local Key, DPS ou pacote.

O store compartilhado mantém no máximo quatro propostas e uma por Device ID. Cada token contém 32 bytes de entropia codificados em Base64 URL-safe; a tabela usa SHA-256 do token como índice e não guarda o token. TTL é de 60 segundos monotônicos. Lookup não consome; claim consome atomicamente sob mutex, sem replay nem extensão de TTL. Colisão de entropia falha fechada. O fechamento de `RecoveryService` remove somente propostas pertencentes àquela instância; outras instâncias permanecem ativas. Uma coleta tardia após TIMEOUT/CLOSED remove somente o digest da proposta daquela operação, sem afetar uma proposta mais recente. Revisão nova invalida proposta mais antiga com ordem de locks ID → store. O store nunca adquire lock do manager e não tem shutdown global separado da aplicação.

## Confirmação interna e adoção — D.3.A

`RecoveryService.confirm_internal(token, scheduler)` aceita exclusivamente o token emitido pelo prepare. Não recebe endereço nem Device ID. Adquire o slot global de forma não bloqueante, revalida lifecycle após a aquisição e faz claim no store com owner identity. O claim compara owner sob o mutex antes de consumir e retorna internamente o TTL monotônico original. Uma instância não consome token de outra; replay e falha após claim não restauram o token.

`CommandScheduler.submit_recovery_confirmation(...)` enfileira a barreira discreta `CONFIRM_RECOVERY`, sem coalescing ou callback cliente. O handler fixo mantém o turno FIFO até readback terminal e nunca espera por Future no worker. Dentro de uma lease única do Device ID, manager compara revisão/endereço/protocolo, TTL original, deadline e lifecycle, repete validação read-only Tuya 3.5 e fecha o adapter antigo por `TuyaAdapter.close()`. Falha de cleanup impede commit e o adapter que possa ter sido parcialmente fechado permanece inutilizável; não se promete rollback físico.

O ponto de commit é a substituição do `DeviceConfig` sob lock do ID e guard de lifecycle, após rechecks imediatos de deadline, TTL, revisão, endereço, protocolo e cancelamento. A ordem de locks é ID → lifecycle; nenhuma chamada ao `update_address()` ocorre sob a lease. O commit incrementa revisão uma vez, invalida adapter/knowledge antigo e preserva Device ID, Local Key, protocolo, DPS, capacidades e pending. Um `update_address()` linearizado antes impede adoção obsoleta; um posterior é mudança nova e não reverte `ADOPTED`.

Após liberar a lease, readback normal readquire o lock pelo caminho do manager, dentro do mesmo turno FIFO, e confere a revisão do commit antes de I/O. Revisão posterior resulta em `SUPERSEDED`. O resultado contém `adoption=ADOPTED` separadamente do readback `SUCCEEDED`, `FAILED` ou `SUPERSEDED`; falha/timeout/shutdown posteriores não mudam adoção. O slot global só é liberado depois de drenar trabalho ativo. Essa confirmação continua interna ao backend; não há JSONL, IPC, Tauri, UI, TOML ou escrita DPS.

## Integração JSON Lines — D.3.B

O modo `serve` compõe `RecoveryService` com `DeviceManagerRecoveryCatalog` e `TinyTuyaLanDiscoveryProvider`. Construir o provider não inicia descoberta; cada scan só começa após um pedido válido. Os comandos são `recovery.prepare` com payload exato `{ "deviceId": "..." }` e `recovery.confirm` com `{ "proposalId": "..." }`. IP, owner, Local Key, DPS, parâmetros de conexão e campos adicionais são rejeitados ou nunca publicados.

Prepare e confirm são submetidos ao executor limitado fora das threads de leitura e escrita JSONL. `requestId` e a semântica de resposta terminal única existentes são preservados; respostas podem terminar fora da ordem de entrada. Prepare publica somente `status`, `proposalId`, `candidateIp` e `ttlSeconds` em sucesso. Confirm publica `recovery.status` separadamente de `readback.status`; readback bem-sucedido usa o serializer público allowlisted de `DeviceStatus`.

Falhas internas são convertidas a status públicos estáveis (`NOT_FOUND`, `AMBIGUOUS`, `TIMEOUT`, `TRANSPORT_FAILED`, `AUTH_FAILED`, `VALIDATION_FAILED`, `PROTOCOL_NOT_ELIGIBLE`, `PROPOSAL_EXPIRED`, `CONFIG_CHANGED`, `BUSY`, `ADOPTED` e demais terminais definidos pelo protocolo). Mensagens de exceção, traceback, dados TinyTuya e detalhes privados não entram em stdout, respostas ou diagnósticos. No EOF, a instância fecha e invalida suas propostas, cancela estágios ainda pendentes conforme os contratos internos e drena operações já iniciadas e respostas aceitas antes de parar o writer.

Os testes da integração usam recovery services/providers fakes; testes internos cobrem token expirado/replay/owner, ambiguidade, falha de autenticação, shutdown e adoção com readback falho. Nenhum teste usa LAN ou hardware real. D.3.B não adiciona Tauri/React, recuperação automática, TOML, escrita DPS ou acesso a hardware.

## Bridge Rust/Tauri de recuperação — D.4.A

O bridge registra somente os handlers tipados `bridge_recovery_prepare(deviceId)` e `bridge_recovery_confirm(proposalId)`. Eles chamam, respectivamente, `recovery.prepare` com `{deviceId}` e `recovery.confirm` com `{proposalId}` pelo `BridgeClient` existente. A WebView não escolhe endereço, Local Key, DPS, parâmetros de conexão, nome de comando ou JSONL; o bridge não cria subprocesso adicional e mantém os gates MOCK/FIXTURE/REAL.

Prepare usa enum de status allowlisted; `PROPOSAL_READY` exige token Base64URL de 43 caracteres, candidato IPv4 e TTL finito `>= 0`. Confirm usa `recovery.status` independente de `readback`: somente `ADOPTED` inclui objeto irmão de readback (`SUCCEEDED`, `FAILED` ou `SUPERSEDED`), e `SUCCEEDED` pode defensivamente não carregar `device`. Falhas de domínio não carregam readback. DTOs rejeitam campos desconhecidos e o `DeviceStatus` aninhado também é estrito.

O timeout de 30 segundos do bridge encerra a espera correlacionada e não cancela uma operação já enviada ao backend; após timeout de confirm o backend ainda pode adotar. Não há retry automático. FIXTURE expõe perfis fixos de recovery 3.5/3.3 e endereços TEST-NET reservados para documentação, sem rede, TinyTuya ou hardware; o relógio monotônico pode ser injetado no store de testes.

| Perfil FIXTURE | Resultado determinístico |
|---|---|
| `fixture-tuya35`, `fixture-tuya35-alt` | Elegível, candidato válido, adoção e readback sucedido; propostas isoladas por dispositivo. |
| `fixture-tuya33` | `PROTOCOL_NOT_ELIGIBLE`. |
| `fixture-recovery-ambiguous`, `fixture-recovery-not-found`, `fixture-recovery-auth-failed`, `fixture-recovery-transport-failed`, `fixture-recovery-busy`, `fixture-recovery-config-changed`, `fixture-recovery-timeout` | Status de recusa/falha de prepare correspondente. |
| `fixture-recovery-readback-failed`, `fixture-recovery-readback-superseded` | Adoção com readback `FAILED` ou `SUPERSEDED`. |
| `fixture-recovery-confirm-auth-failed`, `fixture-recovery-confirm-transport-failed`, `fixture-recovery-confirm-busy`, `fixture-recovery-confirm-config-changed`, `fixture-recovery-confirm-timeout` | Falha terminal de confirmação sem readback. |
| `fixture-recovery-slow` | Atraso curto e determinístico para validar correlação de respostas fora de ordem. |

Tokens desconhecidos, expirados ou já consumidos retornam `PROPOSAL_EXPIRED`. O store FIXTURE usa relógio monotônico injetável nos testes e invalida seu estado ao encerrar o processo.
