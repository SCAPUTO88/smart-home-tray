# Contratos internos e IPC futuro

## Modelos internos

- `DeviceConfig`: `device_id`, nome, endereço atual, versão Tuya, timeout, `DPSMap` e segredo privado não exibido em `repr`.
- `DPSMap`: índices opcionais de `power`, `work_mode`, `white_brightness`, `white_temperature`, `hsv` e `scene`; capacidades são derivadas da presença dos índices e dos limites necessários.
- `LightState`: valores normalizados e modo atual, com qualidade `confirmed`, `pending`, `offline` ou `unknown`. Brilho branco e intensidade HSV são campos distintos.
- `DeviceStatus`: identidade, nome, endereço atual, protocolo, capacidades e estado de conexão; nunca inclui Local Key.
- `BackendError`: código padronizado e mensagem segura sem credenciais ou chave local.

## Operações do adapter

- `read_status() -> dict[str, object]`: consulta status por LAN e retorna apenas o mapa `dps` validado.
- `write_dps(dps_index: int, value: object) -> None`: envia uma escrita DPS individual; checa o retorno e converte erros TinyTuya em `BackendError`.

## Erros

| Código | Uso |
| --- | --- |
| `TIMEOUT` | Timeout ao conectar ou receber resposta. |
| `DEVICE_OFFLINE` | Dispositivo inalcançável, resposta vazia ou falha de socket. |
| `AUTH_FAILED` | TinyTuya identifica chave/protocolo inválido (ex.: erro 914). |
| `INVALID_INPUT` | Configuração, DPS ou payload fora do contrato. |
| `UNSUPPORTED_CAPABILITY` | Operação solicita capacidade ausente no mapa do dispositivo. |
| `DEVICE_ERROR` | Erro do equipamento não mapeado para os códigos acima. |

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
