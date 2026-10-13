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
| `color.py` | Conversão RGB/HSV e serialização dos valores de cor Tuya. | Biblioteca padrão |
| `protocol.py` | Ler requests e escrever responses JSON Lines sem imprimir logs em stdout. | DeviceManager, models, JSON |
| `cli.py` | Interface de diagnóstico e comandos explicitamente invocados pelo usuário. | DeviceManager |

O CLI e o protocolo futuro usam o mesmo DeviceManager. O frontend não recebe credenciais nem acessa TinyTuya diretamente.

## Fluxo de comunicação

1. `config.py` lê o arquivo TOML local e obtém Local Keys por nomes de variáveis de ambiente.
2. O DeviceManager mantém o cadastro por Device ID e usa o IP atual apenas para conectar/redescobrir.
3. O Adapter cria a sessão TinyTuya para protocolo e timeout configurados e faz operações LAN.
4. O DeviceManager converte o retorno bruto usando o mapeamento de DPS e atualiza estado confirmado, pendente ou offline.
5. CLI ou protocolo encaminham comandos normalizados ao manager; respostas não carregam configuração privada.

## Estado, capacidades e sincronização

Capacidades são específicas por dispositivo e derivadas dos DPS declarados. `Luz Mesa` usa DPS 22 para brilho branco e DPS 23 para temperatura; a `Fita LED` usa Value do HSV em DPS 24 para intensidade RGB. Percentuais são normalizados contra os limites físicos configurados e o modo ativo. Capacidade declarada não significa validação física.

Escritas serão serializadas por dispositivo, preservando a ordem de comandos dependentes. Controles contínuos terão coalescing inicial de 150 ms com a última intenção; power e cenas são discretos e não serão coalescidos. Polling começa em 15 segundos e não se sobrepõe a escrita no mesmo dispositivo. Depois de comandos, o estado será atualizado de acordo com o tempo de resposta do equipamento.

## Erros e isolamento

Erros padronizados incluem `TIMEOUT`, `DEVICE_OFFLINE`, `AUTH_FAILED`, `INVALID_INPUT` e `UNSUPPORTED_CAPABILITY`. Uma falha de dispositivo não interrompe consultas dos demais. Retornos Tuya inesperados recebem erro seguro e não expõem a chave nem dados brutos sensíveis. O erro 904 da Luz escritório permanece não crítico para o MVP.

## Segurança e limites

- Runtime somente LAN; APIs de cloud/wizard da TinyTuya não são chamadas pelo backend.
- Configuração real é externa e ignorada pelo Git. O exemplo contém placeholders e nomes de variáveis de ambiente.
- Local Keys não aparecem em stdout IPC, respostas, logs, repr dos modelos ou testes.
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
