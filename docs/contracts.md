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
| `devices.list` | `{}` | `{ "devices": [DeviceStatus público, ...] }`, sem LAN |
| `device.get` | `{ "deviceId": string }` | `DeviceStatus` do catálogo, sem LAN |
| `device.status` | `{ "deviceId": string }` | `DeviceStatus` após leitura LAN |
| `device.power` | `{ "deviceId": string, "enabled": boolean }` | `DeviceStatus` após readback confirmado |
| `device.whiteBrightness` | `{ "deviceId": string, "percent": 0..100 }` | `DeviceStatus` após readback confirmado |
| `device.colorTemperature` | `{ "deviceId": string, "percent": 0..100 }` | `DeviceStatus` após readback confirmado |
| `device.hsv` | `{ "deviceId": string, "hue": 0..360, "saturation": 0..100, "value": 0..100 }` | `DeviceStatus` após readback confirmado |
| `device.colorBrightness` | `{ "deviceId": string, "percent": 0..100 }` | `DeviceStatus` após readback confirmado |

Números devem ser finitos; booleanos não contam como números. Objetos payload são allowlists exatas, sem chaves de credenciais ou escrita DPS genérica. Escritas passam pelo `CommandScheduler`; power é discreto e controles contínuos mantêm o coalescing de 150 ms. Uma resposta pode terminar fora da ordem de recebimento devido a operações assíncronas independentes; FIFO por dispositivo continua sob responsabilidade do scheduler. Enqueue não confirma estado: sucesso só é emitido após o DeviceManager concluir readback válido.

Substituição pelo coalescing ou cancelamento de comandos ainda não iniciados no shutdown termina com `COMMAND_CANCELED`. O código distingue apenas cancelamento conhecido; mensagem é genérica e segura. Uma operação LAN iniciada não é interrompida. Ao receber EOF, o servidor para novas submissões, fecha o scheduler cancelando fila pendente e aguarda operações iniciadas e leituras em andamento; então drena as respostas terminais do writer e encerra. O tempo de shutdown depende dos timeouts das operações. O writer é único, serializa e faz flush a cada linha; callbacks de Future apenas põem um evento em fila. stdout é reservado ao protocolo em `serve`; diagnósticos vão para stderr.

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
