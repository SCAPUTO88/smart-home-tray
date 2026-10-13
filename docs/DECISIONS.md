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
