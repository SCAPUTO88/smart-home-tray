# Arquitetura aprovada — Smart Home Tray

## Escopo

Backend local-first executável como processo independente. A operação em runtime usa a rede local e não requer API cloud, assinatura ou servidor remoto. React/TypeScript, Tauri 2, o intermediário Rust e o empacotamento Python são fases futuras.

## Componentes

| Componente | Responsabilidade | Dependências |
| --- | --- | --- |
| `models.py` | Modelos de dispositivo, capacidades, estado, mapeamentos DPS e erros tipados. | Biblioteca padrão |
| `config.py` | Ler TOML externo, validar campos, resolver referências a variáveis de ambiente. | `tomllib`, models |
| `tuya_adapter.py` | Construir cliente TinyTuya, ler status LAN e escrever DPS. | TinyTuya, models |
| `device_manager.py` | Identidade persistente por Device ID, endereço mutável, coordenação de estado, timeout, reconexão e falhas isoladas. | Adapter, config, models |
| `color.py` | Conversão RGB/HSV e serialização/validação HSV16 dos valores de cor Tuya. | Biblioteca padrão, `colorsys` |
| `protocol.py` | Ler requests e escrever responses JSON Lines sem imprimir logs em stdout. | DeviceManager, models, JSON |
| `cli.py` | Interface de diagnóstico e comandos explicitamente invocados pelo usuário. | DeviceManager |

`DeviceManager` cria o catálogo por `Device ID`, mantém estado público sem configuração privada e instancia adapters sob demanda. Cada dispositivo tem seu próprio lock; polling é opt-in via `start_polling()` e encerra com `stop_polling()`. `poll_once()` permite uma sincronização explícita sem thread. O intervalo padrão é 15 segundos. `update_address()` atualiza o IP e descarta o adapter para reconstruí-lo na próxima operação; não há descoberta automática nesta etapa.

O CLI e o protocolo futuro usam o mesmo DeviceManager. O frontend não recebe credenciais nem acessa TinyTuya diretamente.

## Fluxo de comunicação

1. `config.py` lê o arquivo TOML local e obtém Local Keys por nomes de variáveis de ambiente.
2. O DeviceManager mantém o cadastro por Device ID e usa o IP atual apenas para conectar/redescobrir.
3. O Adapter cria a sessão TinyTuya para protocolo e timeout configurados e faz operações LAN.
4. O Adapter converte falhas e respostas inválidas em erros estruturados e seguros. Uma escrita aceita não confirma estado físico; o DeviceManager faz leitura posterior antes de atualizar estado confirmado, pendente ou offline.
5. CLI ou protocolo encaminham comandos normalizados ao manager; respostas não carregam configuração privada.

O manager lê somente os DPS configurados de cada equipamento. Power exige booleano, escreve no DPS mapeado e só confirma a intenção após leitura que reporte o valor solicitado. Leituras divergentes atualizam o último valor observado, mas mantêm a intenção em `pending`; uma leitura posterior correspondente resolve a intenção. Na Etapa C2A, o mesmo princípio é aplicado por campo às intenções de iluminação, sem confundir confirmação de power e cor. DPS ausentes ou inválidos preservam valores anteriormente observados e não resolvem pendências. Resposta inválida degrada a qualidade para `unknown` sem converter automaticamente a conexão em offline; falha de transporte marca offline. `update_address()` preserva os valores conhecidos e eventuais intenções pendentes, mas invalida a confirmação até uma leitura no novo endereço. Falhas em um dispositivo não interrompem os demais.

## Estado, capacidades e sincronização

Capacidades são específicas por dispositivo e derivadas dos DPS declarados. `Luz Mesa` usa DPS 22 para brilho branco, DPS 23 para temperatura, DPS 24 para HSV e DPS 25 para cenas; a `Fita LED` usa Value do HSV em DPS 24 para intensidade colorida e não declara DPS de brilho branco ou temperatura. Os campos normalizados de brilho branco e intensidade HSV permanecem separados. Percentuais de brilho e temperatura usam `ValueRange`; capacidade declarada não significa validação física.

O codec C2A segue o formato HSV16 documentado pelo TinyTuya 1.20.0 (`HHHHSSSSVVVV`; hue 0–360, saturation/value 0–1000). O modo é escrito antes do valor dependente quando o DPS de modo está configurado e a última leitura indica modo diferente. Sem mapeamento de modo, não há alternância presumida. Comandos não ligam o dispositivo automaticamente. Uma troca de modo aceita seguida de falha no DPS de valor é uma falha parcial: não se faz rollback físico; o estado é atualizado por leitura de melhor esforço e a intenção incerta permanece pendente. Não há debounce nesta etapa.

Escritas são serializadas por dispositivo, preservando a ordem de comandos dependentes. Polling começa em 15 segundos e não se sobrepõe a escrita no mesmo dispositivo. Depois de comandos, o estado é relido antes de ser considerado confirmado. Coalescing de 150 ms para controles contínuos permanece planejado para etapa futura; não está implementado.

## Erros e isolamento

Erros padronizados incluem `TIMEOUT`, `DEVICE_OFFLINE`, `AUTH_FAILED`, `INVALID_INPUT` e `UNSUPPORTED_CAPABILITY`. Uma falha de dispositivo não interrompe consultas dos demais. Retornos Tuya inesperados recebem erro seguro e não expõem a chave nem dados brutos sensíveis. O erro 904 da Luz escritório permanece não crítico para o MVP.

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

Defina as variáveis de ambiente declaradas em `local_key_env` antes de iniciar o backend. O exemplo não contém credenciais. Os comandos de CLI e sidecar serão documentados quando esses módulos forem implementados.
