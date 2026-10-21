# F2E.D.4.V1 — relatório de validação FIXTURE

## Homologação complementar — checklist de teclado/acessibilidade (2026-10-21)

**Parecer atualizado: GO para integrar a documentação da F2E.D.4.V1 e aceitar a jornada funcional principal em FIXTURE, com cobertura e ressalvas explicitadas.** Este parecer sucede o NO-GO inicial do agente (sem janela) e o GO restrito da gravação. Não significa que os 17 cenários tenham sido exercitados individualmente na WebView nativa ou que cada evento `invoke` tenha sido capturado.

**Checklist executado manualmente pelo mantenedor no Windows — 7/7 itens reportados como aprovados:**

1. Navegação entre dispositivos e controles por `Tab` e `Shift+Tab`.
2. `Enter` ou `Espaço` acionam a expansão e os botões.
3. Após preparar proposta, foco direcionado ao título de confirmação.
4. `Escape` fecha o painel quando permitido e devolve o foco ao controle de abertura.
5. Destaque de foco visível e controles alcançáveis por teclado.
6. Texto, botões e TTL legíveis sem cortes, inclusive com rolagem.
7. Anúncios de mensagens importantes pelo Narrador do Windows.

**Evidências anteriores complementares:** gravação (~71 s) da janela Tauri em FIXTURE, incluindo `fixture-tuya35` prepare/confirm e `ADOPTED`, Tuya 3.3 inelegível, `ADOPTED + FAILED`, refresh manual e ocultar/reabrir pelo tray; e consulta PowerShell sem `python(w).exe` executando `smart_home_tray.fixture` após encerramento. O vídeo e o checklist foram fornecidos/reportados na conversa; não há artefato de vídeo anexado ao repositório nem log do dispatcher nativo.

**Verificação remota antes deste complemento:** quatro jobs do head `9196026` concluídos com SUCCESS (Python 3.12/3.14 Windows, Frontend Node 24 e Tauri/Rust Windows MSVC). O CI do novo head documental deverá ser verificado separadamente.

**Limites conscientemente aceitos para o merge documental:** sem captura direta de `requestId`/dispatcher ou contagem de `list()`; nem todos os C01–C17 foram repetidos na UI real; escala 125%, monitor secundário e operação confirm pendente durante ocultação não possuem evidência manual específica. Eles permanecem como cobertura automatizada por camadas ou backlog de QA ampliado, conforme matriz, sem serem marcados falsamente como passes nativos.

**Backlog UX não bloqueante:** texto histórico da falha do readback após refresh posterior válido; status “Pronto para controlar” com alguns campos stale/unknown; nomes extensos na lista sintética. Nenhuma alteração de código de produto nesta PR.

---

## Atualização de homologação manual — 2026-10-21 (evidência posterior à execução automatizada)

**Parecer vigente: GO restrito para a jornada funcional principal em Tauri/FIXTURE; NO-GO para encerramento integral de F2E.D.4.V1.** A conclusão inicial de indisponibilidade da WebView abaixo é histórica e foi parcialmente superada por uma gravação feita pelo mantenedor no Windows. O vídeo foi fornecido na conversa de revisão; não foi versionado neste repositório, e não há transcrição de tráfego interno do dispatcher.

**Evidência observada na gravação (~71 s):**
- **C01 (parcial):** janela Tauri abriu com indicação `Fixture · simulação`, dispositivos sintéticos e controles. A interface visual não apresentou fallback aparente para REAL ou MOCK. A gravação isoladamente não rastreia cada chamada Tauri.
- **C02–C03 (jornada principal):** em `fixture-tuya35`, preparação explícita mostrou candidato `198.51.100.35`, TTL aproximadamente 60 s e aviso de confiança; a confirmação manual resultou em mensagem de adoção em memória e leitura reconciliada. A sequência é compatível com React → Tauri → Python FIXTURE, corroborada pelos testes Rust ↔ subprocesso real e pelos testes React separados; não equivale a captura do dispatcher de ponta a ponta.
- **C04:** `fixture-tuya33` mostrou inelegibilidade e preparação desabilitada.
- **C09:** `fixture-recovery-readback-failed` exibiu `ADOPTED` separado de readback falho, controles dependentes sem estado confirmado; após refresh manual, os valores voltaram a aparecer. O teste de confirmação com falha foi repetido e o estado não confirmado voltou a ser exibido.
- **C14 (parcial):** ocultar e reabrir o painel pelo tray preservou a seleção e o estado exibido. A gravação **não** comprova ocultação durante uma confirmação pendente nem ausência de segunda `list()` por inspeção de IPC.
- **C17 (complementar):** após encerrar o aplicativo, o mantenedor executou `Get-CimInstance Win32_Process` filtrando `python.exe`/`pythonw.exe` e `*smart_home_tray.fixture*`; o comando não retornou processos. Isso evidencia ausência de subprocesso FIXTURE residual **no momento da consulta**, não demonstra sozinho a ordem interna de shutdown.

**Ainda não verificado manualmente:** execução completa por teclado, `Escape`/retorno de foco, leitor de tela/`aria-live`, escalas 100%/125%, monitor secundário, seleção/troca durante confirmação pendente, verificação por logs de `requestId` e chamadas `list()`, e todos os cenários C05–C08/C10–C13/C15–C16 em uma mesma jornada nativa. A matriz original abaixo permanece evidência por camada para esses cenários, não passe nativo universal.

**Oportunidades UX, não bloqueantes para o GO restrito:** (1) a mensagem da recuperação continua referindo-se ao readback original falho mesmo após refresh manual posteriormente bem-sucedido — separar histórico da recuperação de knowledge atual; (2) “Pronto para controlar” pode aparecer quando alguns controles dependentes permanecem indisponíveis por knowledge stale/unknown. O catálogo FIXTURE usa nomes extensos e demanda scroll, sem indício de erro funcional.

**Atualização GitHub:** a PR #51 foi efetivamente criada após a tentativa inicialmente bloqueada registrada abaixo; no head `5a1226e` os quatro jobs de CI terminaram com sucesso. As referências históricas abaixo a “PR não criada/0 checks” correspondem somente à situação anterior à abertura da PR.

**Próximo gate:** homologação assistiva/teclado e critérios nativos pendentes, com evidência explícita; nenhuma alteração de backend/contratos, nenhum uso de REAL, LAN ou hardware. Este complemento não substitui a decisão de não fazer merge automático.

---

## Parecer inicial (antes da gravação nativa)

**NO-GO para aceite ponta a ponta/nativo.** Os testes automatizados comprovam o processo Python FIXTURE real iniciado pelo `BridgeClient` Rust, o protocolo JSON Lines, os DTOs/parsers Rust e, em suítes separadas, controller, reconciliação e UI React usando doubles. Não foi possível observar ou interagir com a janela WebView2 nesta sessão: a superfície de UI informou `apps: []` e `browsers: []`. Portanto, não há evidência da jornada React → `invoke` → handlers Tauri registrados → `BridgeState` → subprocesso Python na janela nativa.

Nenhum defeito concreto foi reproduzido e nenhuma alteração de arquitetura ou código de produto foi feita. Este relatório registra a cobertura que existe e o roteiro para fechar a evidência nativa.

## Escopo e ambiente

- Repositório: `SCAPUTO88/smart-home-tray`.
- Worktree: `D:\Projetos\smart-home-tray\.worktrees\f2e-d4v1-fixture-e2e`.
- Branch: `test/f2e-d4v1-fixture-e2e`.
- Base: `origin/develop`; merge da PR #49 `55404c58bc7e7c5b141374d53cf1c11f76d19eb2` é ancestral do HEAD.
- HEAD validado: `55404c58bc7e7c5b141374d53cf1c11f76d19eb2`.
- Estado inicial confirmado limpo; as únicas alterações desta validação são documentação.
- Windows, Node `v24.14.1`, npm `11.11.0`, Python `3.14.3` (dentro de `>=3.12,<3.15`), Rust/Cargo `1.99.0`, Tauri `2.12.3`, alvo `x86_64-pc-windows-msvc`.
- Dependências desktop instaladas com `npm ci` (133 pacotes).
- Cada execução de testes/build que poderia iniciar backend foi delimitada a `SMART_HOME_TRAY_BACKEND_MODE=fixture`, com `SMART_HOME_TRAY_ALLOW_REAL` e `SMART_HOME_TRAY_CONFIG` removidas. O modo REAL, TinyTuya, Local Keys, TOML real, LAN, cloud e hardware não foram usados. Não houve consulta a endereços domésticos.
- IDs são sintéticos. Endereços da fixture pertencem ao bloco documental `198.51.100.0/24`, sem roteamento.

## Auditoria do caminho e limites de cobertura

1. **Bootstrap React:** `main.tsx` monta `ApplicationSessionHost`; este chama `resolveDeviceIntegration()` uma vez e mantém a sessão acima da árvore visual. Em Tauri, `platformController.ts` consulta `bridge_info`; `mock` resolve mock, `fixture`/`real` indisponível falha explicitamente e não troca silenciosamente para mock. Há testes do resolver e do host, mas usam `invoke` substituído; a janela real não foi inicializada.
2. **Registro dos comandos:** `lib.rs` registra `bridge_info`, `bridge_list`, `bridge_recovery_prepare` e `bridge_recovery_confirm` em `generate_handler!`. `bridge.rs` expõe prepare com `device_id` e confirm com `proposal_id`; os argumentos são validados, a confirmação não aceita Device ID/IP, e respostas são reduzidas a DTOs allowlisted. Compilação e testes de DTO foram executados; nenhum teste chamou os handlers pelo dispatcher Tauri real.
3. **Processo e IPC:** `ProcessConfig::Fixture` gera `python -u -m smart_home_tray.fixture`. O teste Rust `fixture_process_starts_lists_and_shuts_down_without_orphan` cria `BridgeClient` com essa configuração, consulta o catálogo e verifica cleanup; `recovery_fixture_runs_prepare_confirm_and_blocks_replay_over_jsonl` faz prepare/confirm/replay pelo cliente e pelo processo Python real. O protocolo correlaciona por `requestId`, inclusive respostas fora de ordem. Essa cobertura não passa pelo `invoke` do WebView nem pelos handlers Tauri.
4. **Fixture Python:** `RecoveryFixture` mantém catálogo, propostas e endereços sintéticos em memória. A expiração usa relógio monotônico injetável. O catálogo não persiste TOML.
5. **UI e reconciliação:** os testes React cobrem contratos, apresentação, foco/ARIA, TTL, isolamento por Device ID, barreiras CR-48/CR-49 e estado stale. Integração Tauri é simulada por invoke falso nessas suítes.

### Cobertura anterior e validação desta execução

| Camada | Evidência | Limite |
| --- | --- | --- |
| Python FIXTURE + JSONL | `backend/tests/test_fixture.py`, `test_protocol.py`; 400 testes da suíte | O teste de protocolo usa fixture/processo Python no âmbito do backend; não inicia WebView/Tauri. |
| Rust `BridgeClient` + subprocesso Python FIXTURE | Testes em `desktop/src-tauri/src/bridge.rs`; inclui catálogo, prepare, confirm, replay, correlação, erros, timeout e shutdown | Não atravessa `generate_handler!` nem uma chamada `invoke` do React. |
| DTOs/contratos Rust | Parse estrito de prepare/confirm e erros; `cargo test` | Não é execução dos handlers em app Tauri. |
| Controller/React/reconciliação | `npm test`; 224 testes em 17 arquivos, inclusive camada UI e CR-49.3 | `invoke`/bridge substituídos por doubles; não é E2E nativo. |
| Aplicação nativa/WebView2 | Build release sem bundle concluído | Janela não acessível à automação; nenhuma validação visual ou jornada nativa declarada. |

## Matriz C01–C17

Os resultados `PASS` abaixo significam que os comportamentos citados passaram nas respectivas camadas automatizadas listadas. Não significam que uma única jornada percorreu React, dispatcher Tauri e processo Python. C01, C14 e C17 permanecem bloqueados para o aceite nativo solicitado.

| Cenário | Resultado | Evidência e limite |
| --- | --- | --- |
| C01 — Bootstrap FIXTURE | **BLOCKED** | Há prova Rust de subprocesso real e testes de resolver/UI com doubles. Sem janela nativa, não foi observado catálogo vindo do subprocesso na UI nem rodapé FIXTURE. Registro/código não mostra fallback silencioso. |
| C02 — Elegibilidade Tuya 3.5 | **PASS** (camadas) | `fixture-tuya35` produz proposta com candidato `198.51.100.35` e TTL 60 s no backend/Rust; teste de painel cobre prepare explícito, aviso de confiança, IP e TTL com invoke substituído. |
| C03 — Confirmação bem-sucedida | **PASS** (camadas) | Teste Rust → processo confirma somente proposalId, consome proposta, retorna `ADOPTED + SUCCEEDED` e readback do mesmo Device ID. Testes UI/controller cobrem aplicar o readback. Catálogo é volátil em memória; nenhuma persistência TOML. A junção nativa das camadas não foi observada. |
| C04 — Tuya 3.3 inelegível | **PASS** (camadas) | Fixture retorna `PROTOCOL_NOT_ELIGIBLE`; painel desabilita prepare para elegibilidade negativa. Chegada do clique ao handler real não verificada. |
| C05 — Candidato ambíguo | **PASS** (camadas) | Fixture retorna `AMBIGUOUS`; testes de parse/apresentação preservam estado ambíguo e não oferecem confirmação. |
| C06 — Candidato não encontrado | **PASS** (camadas) | Fixture retorna `NOT_FOUND`; testes de mensagem pública apresentam erro seguro. |
| C07 — Falha de autenticação | **PASS** (camadas) | Fixture tem falha em prepare e perfil separado de falha terminal no confirm; testes validam DTO/apresentação sem detalhes internos. |
| C08 — Falha de transporte | **PASS** (camadas) | Fixture tem falhas de prepare e confirm; apresentação não alega adoção. |
| C09 — Readback falho após adoção | **PASS** (camadas) | Fixture retorna `ADOPTED + FAILED`; testes de controller/hook mantêm conhecimento stale e bloqueiam comandos dependentes até refresh explícito. |
| C10 — Readback superado | **PASS** (camadas) | Fixture retorna `ADOPTED + SUPERSEDED`; testes de reconciliação não sobrescrevem observação causalmente mais nova nem alegam rollback/sucesso físico. |
| C11 — Falhas terminais de confirmação | **PASS** (camadas) | Perfis fixture cobrem `AUTH_FAILED`, `TRANSPORT_FAILED`, `CONFIG_CHANGED`, `TIMEOUT`; parser mantém esses resultados distintos de erro/timeout de transporte Rust após envio, que a UI classifica como indeterminate. |
| C12 — Replay | **PASS** | Rust inicia Python FIXTURE real; a primeira confirmação consome a proposta e o replay com o mesmo token retorna `PROPOSAL_EXPIRED`. Coberto na ponte Rust↔Python, sem controle de replay adicional no produto. |
| C13 — Expiração | **PASS** (automatizado) | `RecoveryFixture` recebe relógio monotônico injetável; UI usa relógio controlado e teste remount não renova TTL. Sem sleep de 60 s. A combinação nativa não foi observada. |
| C14 — Ocultar/reabrir janela | **BLOCKED** | Não foi possível acessar janela/tray nesta sessão. Nenhuma afirmação visual sobre sessão preservada, foco ou ausência de segunda listagem. Roteiro manual abaixo. |
| C15 — Isolamento entre dispositivos | **PASS** (camadas) | Fixture isola proposals por ID; testes React/controller preservam resultado e knowledge por Device ID durante troca de seleção. |
| C16 — Concorrência/barreira causal | **PASS** (automatizado por camada) | 224 testes frontend incluem intents pendentes, readbacks antigos, barreiras causais e invariantes CR-48/49; testes Rust cobrem correlação fora de ordem. Nenhum retry automático é exercitado como ação de produto. |
| C17 — Shutdown/subprocesso | **BLOCKED** para app; **PASS** para cliente | Teste Rust confirma `BridgeClient` fecha o filho Python e não mantém `child`; shutdown normal da aplicação/tray não foi observado por falta de janela acessível. |

## Verificações executadas

Todos os comandos abaixo terminaram com código zero, salvo indicação. Os comandos de backend/Rust/desktop que poderiam usar backend foram executados com FIXTURE e as variáveis de REAL/configuração removidas.

| Comando | Resultado |
| --- | --- |
| `python -m pytest backend/tests -q` | **400 passed** (2,94 s), Python 3.14.3. |
| `npm ci` (`desktop/`) | Concluído; 133 pacotes instalados; 0 vulnerabilidades reportadas. |
| `npm test` (`desktop/`) | **224 passed**, 17 arquivos. |
| `npm run typecheck` | Passou (`tsc -b`). |
| `npm run lint` | Passou (`oxlint`). |
| `npm run build` | Passou; 2.350 módulos transformados. |
| `cargo fmt --all -- --check` | Passou. |
| `cargo check --locked` | Passou; 230 crates compilados. |
| `cargo test --locked` | **28 passed**, 3 suites. |
| `npm run tauri:build -- --no-bundle` | Passou; produziu `smart-home-tray.exe` Windows release. Aviso não bloqueante: colisão de nome PDB entre targets lib/bin. Build não executa a janela. |

As dependências de UI faltavam inicialmente (`vitest`/`tsc` não encontrados); `npm ci` corrigiu o ambiente sem modificar manifestos. A suíte foi então repetida e passou.

## QA visual/acessibilidade e roteiro para o mantenedor

**Não executado nesta sessão:** largura/scroll de 420 px, perfis selecionáveis na janela, expansão/recolhimento, corte de textos/IP/TTL, foco, Escape, aria-live, teclado, reduced motion, tray ocultar/reabrir, escala 100%/125% ou monitor secundário. A inspeção de superfícies informou `apps: []`, `browsers: []`; não houve screenshot ou interação visual.

Roteiro reproduzível em Windows, com WebView2 e bandeja disponíveis:

```powershell
Set-Location 'D:\Projetos\smart-home-tray\.worktrees\f2e-d4v1-fixture-e2e\desktop'
$env:SMART_HOME_TRAY_BACKEND_MODE = 'fixture'
Remove-Item Env:SMART_HOME_TRAY_ALLOW_REAL -ErrorAction SilentlyContinue
Remove-Item Env:SMART_HOME_TRAY_CONFIG -ErrorAction SilentlyContinue
npm run tauri:dev
```

1. Clique no ícone Smart Home Tray para abrir; confirme o rótulo/simulação FIXTURE, catálogo e ausência do painel MOCK de cenários.
2. Localize `fixture-tuya35`, confira protocolo elegível, expanda recuperação, navegue por teclado, prepare e confira candidato sintético e TTL de 60 s. Confirme explicitamente; confira `ADOPTED` separado do readback e o estado atualizado do mesmo dispositivo.
3. Confirme que `fixture-tuya33` bloqueia prepare. Percorra `fixture-recovery-ambiguous`, `fixture-recovery-not-found`, `fixture-recovery-auth-failed`, `fixture-recovery-transport-failed`, `fixture-recovery-readback-failed` e `fixture-recovery-readback-superseded`; observe as mensagens e bloqueios conforme a matriz.
4. Com proposal pronta e durante confirmação, alterne seleção para outro Device ID e use ocultar/reabrir pelo tray. Confirme contexto preservado, sem segunda confirmação ou nova listagem; valide intents/readback conforme CR-48/49.
5. Verifique 420 px, rolagem, texto longo, IP/TTL, foco pós-prepare, Escape/retorno de foco, `aria-live`, navegação somente por teclado e preferência por movimento reduzido.
6. Repita em escala 100%, 125% e monitor secundário quando disponíveis. Encerre pelo menu **Sair**; confirme encerramento do app e do subprocesso Python.
7. Remova `SMART_HOME_TRAY_BACKEND_MODE` ao terminar. Não defina REAL, ALLOW_REAL ou CONFIG durante a sessão.

Após a execução, preencher neste relatório os resultados visuais e conferir logs/processos locais para cleanup. Não usar endereço real, TOML real ou Local Key.

## Problemas, riscos residuais e recomendação

- **Problema de ambiente resolvido:** dependências npm ausentes antes de `npm ci`; os checks desktop passaram depois da instalação.
- **Risco residual principal:** os handlers Tauri estão registrados e compilados, e os contratos Rust são testados, mas nenhum teste invocou o dispatcher real e a janela nativa não foi observada. A aceitação exige uma jornada React → handlers Tauri → subprocesso FIXTURE que ainda precisa ser vista pelo mantenedor em Windows.
- **Limite de QA:** escala, monitor secundário, foco/ARIA e tray ficam para execução manual; não foram inferidos a partir do build nem dos testes de DOM.
- **Arquitetura:** nenhuma decisão aprovada/superada foi alterada. Nenhuma mudança de código de produto ou contrato; apenas relatório e checkpoint documental.
- **Recomendação:** manter **NO-GO** para declarar F2E.D.4.V1 completa até o roteiro nativo validar ao menos prepare/confirm através dos handlers registrados e as verificações de segurança/retorno de foco. A validação automatizada das regressões permanece verde.

## Publicação e checks remotos

- Commit documental publicado na branch remota `test/f2e-d4v1-fixture-e2e`: `200a2c9937c91af606aa90710989adc3231a3bd4`; o pai remoto conferido é a base `55404c58bc7e7c5b141374d53cf1c11f76d19eb2`.
- A criação da PR para `develop` foi solicitada pelo conector GitHub, mas a chamada foi recusada com: `MCP tool call requires approval, but approval policy is never`. `gh pr list` também não pôde conectar pela configuração de proxy local. A PR **não foi criada** e não houve merge.
- Leitura remota do commit retornou `check_runs: []` e `total_count: 0`; como não há PR, os checks de pull request estão **NOT RUN**. Checks locais estão listados acima.

## Resumo para revisão arquitetural

Base `55404c58`; frontend 224/224, backend 400/400, Rust 28/28, typecheck/lint/build/compile Tauri sem bundle aprovados. O teste `BridgeClient` usa processo Python FIXTURE real e prova prepare/confirm/replay/shutdown sobre JSONL. React continua testado com invoke doubles. A janela/WebView não estava acessível (`apps: []`), logo os handlers Tauri no dispatcher e QA visual não foram percorridos. Sem REAL/LAN/hardware/credenciais. Parecer NO-GO até execução manual reproduzível.
