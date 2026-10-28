# Luz Mesa Recovery CLI Implementation Plan

> **Para execução posterior:** usar `superpowers:executing-plans` depois da revisão e aprovação deste plano. Não iniciar implementação nesta etapa.

**Goal:** Criar uma entrada interativa REAL restrita à recuperação da Luz Mesa, com duas autorizações explícitas.

**Architecture:** Uma suboperação da CLI delega a um módulo dedicado que aplica gates, seleciona o alvo e orquestra o `RecoveryService` existente. Dependências de console, relógio e serviço são substituíveis por fakes; não há entrada JSON nem comandos de controle.

**Tech Stack:** Python 3.12–3.14, pytest, console Windows, serviços existentes de recuperação.

**Spec:** `docs/superpowers/specs/2026-10-27-luz-mesa-recovery-cli-design.md`.

## Restrições globais

- Sem rede, dispositivos, configuração REAL ou segredos em testes; bloquear sockets e usar dados sintéticos e fakes.
- Sem modo não interativo, flags de autorização, JSON arbitrário, escrita DPS, comandos de iluminação, persistência de endereço, cloud ou leitura dirigida à Luz Escritório.
- Exigir modo `real`, `ALLOW_REAL=1`, configuração absoluta existente e console interativo; exigir exatamente `PREPARAR LUZ MESA` e depois `CONFIRMAR LUZ MESA`.
- Preservar comportamento de `serve` e desktop, alterações locais preexistentes e memória externa; sem commit, push ou PR sem instrução posterior.
- Não imprimir ou salvar Local Key, token, Device ID completo, TOML, outros dispositivos, entrada ou exceções brutas.

## Foco da revisão

- Nomes duplicados mesmo quando somente um tem protocolo 3.5: rejeitar ambos antes da rede — tarefa 1.
- Console redirecionado ou ausência de console real: rejeitar antes da rede — tarefa 1.
- Expiração enquanto aguarda entrada e confirmação recebida na fronteira: encerrar sem confirmar; serviço mantém autoridade final — tarefa 2.
- EOF ou Ctrl+C antes e depois da preparação: fechar e invalidar proposta, sem confirmar — tarefa 2.
- `ADOPTED` com readback falho, superado ou sem snapshot: não alegar sucesso físico nem repetir — tarefa 3.

## Arquivos e responsabilidades

- Criar `backend/src/smart_home_tray/mesa_recovery_cli.py`: gates, seleção, interação limitada e lifecycle.
- Modificar `backend/src/smart_home_tray/cli.py`: registrar e despachar apenas a nova suboperação, sem alterar o caminho `serve`.
- Criar `backend/tests/test_mesa_recovery_cli.py`: fakes de console, relógio, serviço e scheduler, com sockets bloqueados.
- Atualizar `desktop/README.md` ou documentação backend pertinente com a entrada, seus gates e limites; atualizar `docs/PROJECT_STATUS.md` e, se aplicável à decisão aprovada, `docs/DECISIONS.md`, preservando os diffs existentes.

### Tarefa 1: Gates e seleção sem rede

**Arquivos:** criar `backend/src/smart_home_tray/mesa_recovery_cli.py`; modificar `backend/src/smart_home_tray/cli.py`; criar `backend/tests/test_mesa_recovery_cli.py`.

**Interfaces:** produzir `run_mesa_recovery(*, environ, stdin, stdout, dependencies) -> int`, com dependências injetáveis para carregar configuração, relógio, console e construção do serviço. Em `cli.py`, tornar `--config` global opcional no parser; após o parsing, exigir sua presença para cada subcomando antigo e rejeitar sua presença, inclusive valor vazio, para `recover-luz-mesa`. Despachar a nova operação antes de `load_config(args.config)` e da construção genérica de `DeviceManager`; ela valida e carrega exclusivamente o caminho absoluto existente em `SMART_HOME_TRAY_CONFIG`. Preservar a posição global e o fluxo dos comandos existentes.

- [ ] Escrever testes parametrizados para todos os subcomandos antigos (`list`, `status`, `power`, `white-brightness`, `color-temperature`, `color-brightness`, `hsv` e `serve`), com seus argumentos válidos: sem `--config`, erro de argumento antes do carregamento; com `--config` global, carregador recebe exatamente o caminho informado e o despacho correspondente funciona com manager, scheduler, servidor e operações falsos, sem rede.
- [ ] Escrever testes de `recover-luz-mesa`: sem `--config` e com `SMART_HOME_TRAY_CONFIG` absoluto existente sintético, o carregador dedicado recebe exatamente esse caminho; `--config` global, inclusive vazio, e `--config` após o subcomando são rejeitados sem carregamento ou despacho. Verificar que `load_config(args.config)` e `DeviceManager` do fluxo genérico não são chamados para essa operação.
- [ ] Em todos os testes de erro de parser, gate e seleção, usar spies e bloqueio de sockets para comprovar que nenhum serviço de recuperação é criado e nenhuma rede é iniciada; erros de parser também não carregam configuração.
- [ ] Escrever testes de gates: modo ausente/incorreto, opt-in diferente de `1`, caminho relativo/inexistente, console não interativo e erro de configuração retornam erro, não criam serviço nem chamam rede; saída contém explicação genérica e não dados privados.
- [ ] Escrever testes de seleção para zero, uma e duas entradas de nome exato, inclusive duplicata com protocolo distinto; ID vazio e protocolo diferente de 3.5 falham. Verificar que outros dispositivos nunca aparecem na saída e que o aviso sobre variáveis de todas as Local Keys é exibido.
- [ ] Executar `rtk py -m pytest backend/tests/test_mesa_recovery_cli.py -q` e confirmar falhas esperadas antes da implementação, com sockets bloqueados no próprio teste.
- [ ] Implementar validação condicional do parser e despacho antecipado conforme Interfaces; depois implementar gates e seleção antes da construção de provider/scheduler. Tratar falhas sem ecoar exceções nem configuração e manter o fluxo de `serve`.
- [ ] Executar o mesmo comando e confirmar aprovação dos testes parametrizados de parser, despacho, gates e seleção, incluindo rejeição de argumentos extras da nova entrada.

### Tarefa 2: Autorizações, prazo e encerramento

**Arquivos:** modificar `backend/src/smart_home_tray/mesa_recovery_cli.py` e `backend/tests/test_mesa_recovery_cli.py`.

**Interfaces:** `run_mesa_recovery` usa console injetado com leitura interativa limitada por deadline monotônico, serviço com `prepare_internal(device_id, scheduler)` / `confirm_internal(token, scheduler)` e `close`; o relógio fake controla o prazo original da proposta.

- [ ] Escrever testes: somente frase exata de preparação chama `prepare_internal` uma vez; negativa, texto diferente, EOF ou interrupção não chamam prepare. Após proposta, só a segunda frase exata chama confirm uma vez; não reutilizar a primeira resposta.
- [ ] Escrever testes de expiração sem entrada, confirmação no limite, recusa, EOF e interrupção após proposta. Verificar zero confirmações, fechamento do serviço e invalidação da proposta do proprietário. Verificar token, ID e entrada não aparecem em saída ou erros.
- [ ] Executar os testes focados e confirmar falhas esperadas. Implementar leitura de console Windows com espera pelo deadline, sem thread abandonada; recusar redirecionamento e não confiar apenas em timeout local para validade do serviço.
- [ ] Implementar apresentação mínima, manutenção do token em memória e cleanup em `finally`, com fechamento do serviço e drenagem do scheduler existente; nunca reiniciar uma operação automaticamente.
- [ ] Executar os testes focados e confirmar aprovação, incluindo uma validação com relógio fake que expira sem pressionar Enter.

### Tarefa 3: Resultados e ausência de comandos físicos

**Arquivos:** modificar `backend/src/smart_home_tray/mesa_recovery_cli.py` e `backend/tests/test_mesa_recovery_cli.py`.

**Interfaces:** o adaptador de produção compõe `DeviceManagerRecoveryCatalog`, `TinyTuyaLanDiscoveryProvider`, `RecoveryService` e `CommandScheduler`; os testes injetam substitutos e não criam provider real.

- [ ] Escrever testes para `AMBIGUOUS`, `NOT_FOUND`, protocolo inelegível, timeout, falha de autenticação/transporte, erro de validação e exceções sanitizadas: nenhum confirma, nenhum retry e cleanup observado.
- [ ] Escrever testes de `ADOPTED` com `SUCCEEDED` e snapshot presente, `FAILED`, `SUPERSEDED` e `SUCCEEDED` sem snapshot: exibir adoção e readback separadamente; apenas o primeiro é readback completo; nunca exibir snapshot nem afirmar rollback. Cobrir resultado desconhecido sem repetição.
- [ ] Usar fake que registra chamadas e falha imediatamente em qualquer método de iluminação, escrita DPS, `device.status` de outro alvo ou entrada JSON; demonstrar que só prepare e confirm são chamados e que o endereço não é gravado em arquivo.
- [ ] Executar os testes focados e confirmar as falhas esperadas; implementar mapeamento sanitizado, composição e encerramento. Documentar na própria saída que a adoção é volátil, limitada ao processo e não transferida ao desktop.
- [ ] Executar novamente os testes focados e confirmar aprovação.

### Tarefa 4: Documentação e verificação sem dispositivos

**Arquivos:** documentação pertinente, `docs/PROJECT_STATUS.md` e, se necessário, `docs/DECISIONS.md`.

- [ ] Documentar pré-requisitos, duas frases, efeitos de rede, TTL, privacidade, parada, readback e limitação de adoção em processo; registrar que aprovação do desenho não autoriza teste REAL.
- [ ] Registrar checkpoint e decisão aprovada com trade-offs, sem sobrescrever as alterações documentais existentes nem alegar homologação física.
- [ ] Executar `rtk py -m pytest backend/tests -q` com bloqueio de rede assegurado para a nova suíte; confirmar aprovação. Executar `rtk git diff --check` e revisar o diff para privacidade, escopo e preservação das quatro alterações anteriores. Não executar app ou teste REAL.
- [ ] Apresentar evidências e limitações para revisão arquitetural; não commitar, publicar ou executar recuperação REAL.
