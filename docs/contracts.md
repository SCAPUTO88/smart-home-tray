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

Mapeamento documentado da TinyTuya: 903 → `INVALID_INPUT` (valor fora do intervalo); 904 → `DEVICE_ERROR` (payload inesperado, diagnóstico fixo e seguro); 907 → `UNSUPPORTED_CAPABILITY`; 914 → `AUTH_FAILED` (mensagem neutra sobre parâmetros de autenticação, sem afirmar se a causa foi chave ou protocolo). Códigos desconhecidos usam `DEVICE_ERROR`. Mensagens brutas de resposta/exceção não são repassadas.

## Valores de cor

`HSVColor` público usa hue em graus 0–360 e saturation/value em percentual 0–100. O codec `color.py` usa a convenção HSV16 do TinyTuya 1.20.0: três inteiros hexadecimais de quatro dígitos (`HHHHSSSSVVVV`), hue 0–360 e S/V 0–1000. S/V são truncados para décimos de percentual na codificação; o decoder rejeita tamanho, caracteres e componentes fora do intervalo. RGB usa canais 0–255. A convenção foi verificada no código versionado do TinyTuya, mas a equivalência física pode variar por firmware e não foi validada nesta etapa.

O percentual do DPS de temperatura é uma normalização matemática dos limites físicos configurados; não há inversão nem afirmação sobre mais quente/frio sem validação específica do equipamento.

## Configuração externa

TOML define `version = 1`, array `devices`, identidade, endereço, protocolo, timeout, `local_key_env`, tabela `[devices.dps]` e limites físicos. O nome em `local_key_env` é lido do ambiente; o valor não é serializado de volta nem incluído em erros. `config.example.toml` contém somente placeholders.

## JSON Lines futuro

Uma linha JSON por mensagem, UTF-8. Requisição:

```json
{"requestId":"req-1","command":"device.status","payload":{"deviceId":"<id>"}}
```

Sucesso:

```json
{"requestId":"req-1","result":{"deviceId":"<id>","online":true}}
```

Erro:

```json
{"requestId":"req-1","error":{"code":"DEVICE_OFFLINE","message":"Device is unreachable"}}
```

O processo sidecar reserva stdout para essas mensagens; logs e diagnósticos vão para stderr. `requestId` é ecoado sem alteração. `payload` não aceita credenciais e responses não incluem Local Keys. `INVALID_INPUT` cobre JSON inválido, campos ausentes ou tipos incorretos.
