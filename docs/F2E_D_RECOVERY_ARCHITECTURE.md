# F2E.D.0 — Refinamento de confiança e recuperação manual de endereço

**Estado:** refinamento arquitetural; nenhuma funcionalidade desta etapa está implementada. A política de confiança abaixo foi aprovada pelo mantenedor e está registrada em D-018. Orçamentos, contratos públicos e escolhas de concorrência descritos como proposta ainda precisam de revisão antes das PRs de implementação.

## Contexto e evidências do código atual

- F2E.B (`backend/src/smart_home_tray/discovery.py`) separa `DiscoveryAnnouncement`, `DiscoveryCandidate` e `DiscoveryResult`. O normalizador filtra Device ID diferente, rejeita IPv4 especial, colapsa duplicatas iguais e preserva IPs distintos como `AMBIGUOUS`. Um candidato continua não verificado.
- F2E.C (`backend/src/smart_home_tray/lan_discovery.py`) coleta anúncios UDP em até 3 s, com limites de pacotes/candidatos e concorrência global unitária. Não chama `DeviceManager`, `status()` ou métodos de escrita.
- `DeviceManager` mantém configuração e adapter por Device ID. Leituras, escritas e `update_address()` usam um `threading.Lock` comum não reentrante por dispositivo. `update_address()` substitui a configuração em memória, define o adapter como `None`, invalida conexão/knowledge observado e preserva valores/intenção pendente. Não existe geração/revisão de configuração nem método público de snapshot privado.
- `TuyaAdapter.read_status()` chama `status()` e devolve DPS escalares validados; `write_dps()` chama `set_value()`. O adapter não expõe `close()`. Seus erros conhecidos são normalizados, incluindo autenticação (`AUTH_FAILED`) e transporte (`TIMEOUT`/`DEVICE_OFFLINE`).
- `CommandScheduler` tem uma fila FIFO e worker por dispositivo. A `Condition` não fica travada durante a operação do `DeviceManager`. JSONL aceita comandos por allowlist; hoje não existe comando de descoberta/recuperação. Rust expõe handlers Tauri fixos e tipados, sem JSONL genérico para a WebView.

## Decisão de confiança aprovada

1. Um endereço de Tuya 3.5 pode ser atualizado manualmente após leitura LAN autenticada válida com a Local Key já cadastrada e confirmação explícita do usuário.
2. A leitura constitui evidência de posse da Local Key usada, sob as premissas aplicáveis; não comprova independentemente que a chave pertence exclusivamente ao Device ID anunciado.
3. Esse risco residual é aceito somente para recuperação manual.
4. Tuya 3.3 pode aparecer como candidato, mas não recebe adoção de novo IP nesta fase.
5. Anúncio UDP isolado nunca autoriza adoção.
6. Múltiplos candidatos ou ambiguidade impedem seleção automática.
7. Recuperação automática continua proibida até decisão arquitetural futura.
8. Nenhuma mudança persiste no TOML nesta fase.

## A. Modelo de confiança e ameaças

### Estados que não devem ser confundidos

| Estado | Evidência | O que significa | O que não significa |
| --- | --- | --- | --- |
| Candidato anunciado | Anúncio UDP analisado por F2E.C e normalizado por F2E.B | Um pacote alegou Device ID/versão e chegou de um IPv4 | Identidade, posse da Local Key ou autorização de endereço |
| Endpoint que respondeu autenticado | Leitura read-only 3.5 aceita pelo protocolo usando a Local Key cadastrada | O endpoint observado conseguiu participar de uma troca aceita sob aquela chave | Vínculo independente da chave ou do endpoint ao Device ID |
| Endereço adotado manualmente | Usuário confirmou uma proposta backend válida e vigente | O app aceitou em memória o endpoint previamente testado, com risco residual conhecido | Identidade criptográfica, confirmação de estado de iluminação ou persistência |

### Threat model da LAN doméstica

| Ameaça | Mitigação proposta | Risco residual / aceite |
| --- | --- | --- |
| UDP forjado ou originado por host adversarial, incluindo `gwId` falso | Anúncio é só pista; filtrar ID, normalizar todos os IPs e exigir validação 3.5 antes de criar proposta | Um host pode induzir tentativa read-only e consumir o orçamento. O anúncio não autentica o remetente. |
| Anúncio repetido, atrasado ou conflitante | Duplicata idêntica colapsa em F2E.B; IPs diferentes produzem `AMBIGUOUS`; nenhum “primeiro IP” é escolhido | Pacote válido visto durante janela limitada não prova que a coleta foi exaustiva fora do budget. Falha/truncamento encerra como erro, nunca como candidato único. |
| Dispositivo LAN malicioso/comprometido | Validação autenticada 3.5 exige a chave cadastrada e proposta exige confirmação | Dispositivo comprometido que possui/acessa a Local Key pode responder. A leitura não prova que é o hardware originalmente cadastrado. Risco aceito somente nesta ação manual. |
| Local Key compartilhada, reutilizada ou vazada | Nunca exportar chave; usar somente configuração interna do backend; confirmação mostra que a validação é por chave configurada, sem alegar identidade absoluta | Outro dispositivo ou atacante que possua a mesma chave pode autenticar. A política aprovada aceita esse risco somente na recuperação manual; vazamento da chave exige remediação fora do scanner. |
| Anúncio/protocolo 3.3 | Permitir exibição como candidato, mas encerrar com `PROTOCOL_NOT_ELIGIBLE` antes de TCP ou adoção | 3.3 não tem a autenticação de frame/status 3.5 exigida pela política; não haverá fallback por DPS, CRC ou confirmação da UI. |
| Status plausível ou DPS conhecidos | Validador exige chamada read-only bem-sucedida sob 3.5 e validação semântica mínima de resposta; status não é mesclado no estado de iluminação | Status não inclui prova independente do Device ID conforme a investigação F2E.A. DPS válidos não são identidade; respostas parciais e capacidades variam por firmware. |
| Troca de endpoint entre descoberta e validação | Conectar somente ao IP candidato guardado pelo backend; validar sob lock do dispositivo e repetir a leitura após confirmação antes de commit | DHCP/ARP/host pode mudar imediatamente após o último read. Não há pinning/certificado de identidade do dispositivo. O risco residual é parte da aceitação manual, não se estende à adoção automática. |
| Proposta antiga ou configuração mudou durante a confirmação | Token de uso único, TTL monotônico, Device ID vinculado, geração/revisão e endereço original comparados no confirm; revalidar endpoint antes de aplicar | Reinício invalida propostas; mudança não observada fora do backend ou mutação futura sem incremento da geração precisará ser corrigida no owner da configuração. |

TinyTuya 1.20.0 (investigação F2E.A) usa sessão/HMAC e AES-GCM nos caminhos 3.4/3.5 com Local Key. Isso autentica a troca segundo a chave fornecida, mas não demonstra vínculo criptográfico independente entre o Device ID anunciado, a chave e o endpoint. Em 3.3, o frame tradicional não usa HMAC; CRC detecta corrupção acidental, não autentica remetente. A implementação futura deve confirmar novamente a semântica efetiva do TinyTuya usada pelo backend, sem promover detalhes de anúncio a prova de identidade.

## B. Fluxo de recuperação manual

```mermaid
sequenceDiagram
    actor U as Usuário
    participant UI as WebView
    participant T as Tauri tipado
    participant J as JSONL/backend
    participant C as F2E.C + F2E.B
    participant M as DeviceManager
    participant V as TuyaAdapter temporário

    U->>UI: Solicita recuperar Device ID cadastrado
    UI->>T: recovery.prepare(deviceId)
    T->>J: comando fixo; sem endereço ou chave
    J->>M: consulta elegibilidade/snapshot versionado
    J->>C: scan UDP limitado (até 3 s)
    C-->>J: NOT_FOUND / AMBIGUOUS / FAILED / candidato
    alt ausência, ambiguidade, falha ou truncamento
        J-->>UI: resultado tipado; sem proposta
    else candidato único
        J->>M: reserva transação por Device ID; compara revisão
        J->>V: status read-only em IP candidato, protocolo cadastrado 3.5, chave interna
        V-->>J: leitura aceita ou falha normalizada
        J->>J: cria token opaco, vinculado e expirável
        J-->>UI: proposta + IP para revisão + ressalva de confiança
        U->>UI: confirma explicitamente
        UI->>T: recovery.confirm(proposalId)
        T->>J: confirmação por token opaco apenas
        J->>M: barreira por dispositivo; confere token/TTL/revisão/endereço
        J->>V: nova leitura read-only no mesmo IP antes do commit
        V-->>J: validação aceita ou falha normalizada
        J->>M: troca somente IP em memória; invalida adapter/knowledge
        J->>M: libera lock; executa readback normal separado
        J-->>UI: ADOPTED + resultado do readback
    end
```

### Preparação da proposta

1. O usuário inicia uma recuperação para um Device ID que já consta do catálogo. O backend consulta configuração sem serializar `DeviceConfig`.
2. Executar uma única descoberta F2E.C com o budget aprovado abaixo; F2E.B normaliza a coleção.
3. `NOT_FOUND`, `AMBIGUOUS`, `TIMEOUT`, `PROVIDER_ERROR` ou qualquer truncamento/falha parcial terminam sem proposta e sem TCP. Nunca selecionar pela ordem, versão anunciada ou proximidade do IP salvo.
4. Para um candidato único, verificar elegibilidade usando a configuração cadastrada e anúncio apenas como filtro: protocolo cadastrado deve ser 3.5 e o protocolo anunciado deve ser compatível. Se for 3.3, apresentar `PROTOCOL_NOT_ELIGIBLE`; não testar 3.3 com Local Key nem interpretar erro como sucesso.
5. Validar o IP candidato sob o lock/coordenação exclusiva daquele Device ID usando um adapter temporário derivado da configuração cadastrada, alterando apenas o endereço da cópia. Chamar somente status/read-only. A leitura é válida se TinyTuya aceitar a resposta autenticada, o `dps` passar a validação escalar existente e ao menos um DPS mapeado no cadastro produzir valor semanticamente válido segundo os mesmos parsers/ranges do manager. Isso é critério de consistência da resposta, não prova de identidade. Fazer a validação por helper puro para não atualizar `_states`, `_last_read_fields`, adapter ativo ou configuração confirmada. D.2 deve revalidar a semântica TinyTuya 1.20.0.
6. Uma validação aceita cria proposta em memória, sem mudar endereço. A proposta armazena referência opaca, ID cadastrado, candidato, protocolo, endereço original, revisão de configuração, expiração monotônica e resultado reduzido da validação; não armazena Local Key, pacote, MAC, DPS crus ou exceção.

### Confirmação e aplicação

7. UI informa o IPv4 candidato e o limite da evidência: “respondeu com a Local Key cadastrada; identidade independente do Device ID não foi comprovada”. Usuário confirma deliberadamente.
8. A WebView envia somente `proposalId`. Backend consome o token atomicamente e confere existência, uso único, TTL, Device ID interno, revisão/endereço/protocolo original e ausência de mudança concorrente. Um pedido repetido não reaplica a proposta.
9. Enquanto mantém a exclusão do mesmo dispositivo, o backend faz uma segunda validação read-only no mesmo endpoint. Se falhar, não troca endereço. Antes do commit, invalidar e liberar o adapter ativo anterior: se tiver recursos, `TuyaAdapter` precisa de fechamento idempotente e falha de cleanup aborta o commit; se TinyTuya não retém recurso, demonstrar isso em teste e descartar a referência. Depois aplica somente o IP em memória, avança geração, mantém intenção pendente e zera `DeviceKnowledge` para `UNKNOWN`, como faz `update_address()` atual. Não chama a API pública `update_address()` por dentro do lock: ela readquire o mesmo `threading.Lock` e causaria deadlock. Usar novo helper transacional desbloqueado (`_update_address_unlocked`) atrás de um método público que adquira o lock uma vez.
10. Após liberar a seção crítica de estado, executar uma leitura normal separada para atualizar `connection`, valores e `knowledge`. A operação de recuperação pode continuar ocupando seu turno FIFO do scheduler durante essa segunda leitura, sem manter a condição do scheduler nem o lock do manager durante o I/O. Essa leitura não é a prova de validação e não muda retroativamente sua semântica. Se falhar depois da adoção, reportar endereço adotado + readback falhou; não fingir que a adoção foi revertida.

O gate da confirmação deve serializar operações do mesmo dispositivo com a fila do scheduler. A proposta é adicionar um item de barreira de recuperação tipado na FIFO por Device ID (sem permitir callback ou comando arbitrário do cliente): operações já enfileiradas terminam antes da validação final; operações posteriores executam depois do commit. `CommandScheduler` libera sua `Condition` antes de chamar o manager; o worker nunca deve segurar a condição enquanto espera lock ou rede. Leituras JSONL diretas continuam sincronizadas pelo lock do `DeviceManager`. Não adquirir a condição do scheduler enquanto mantém o lock do manager. Outros Device IDs não aguardam essa barreira.

### Resultados públicos propostos

Usar resultado específico de recuperação, sem exceção bruta, Local Key, MAC ou estrutura TinyTuya:

| Resultado | Quando | Endereço permanece |
| --- | --- | --- |
| `NOT_FOUND` | janela completa sem candidato | original |
| `AMBIGUOUS` | F2E.B encontrou mais de um IP distinto | original; sem proposal/token |
| `TRANSPORT_FAILED` | timeout, bind, socket, conexão ou resposta ausente | original |
| `AUTH_FAILED` | TinyTuya rejeitou a autenticação configurada | original |
| `VALIDATION_FAILED` | resposta malformada/inválida ou falha não classificável | original |
| `PROTOCOL_NOT_ELIGIBLE` | cadastro/anúncio incompatível ou protocolo não 3.5 | original |
| `PROPOSAL_READY` | candidato único passou validação inicial | original até confirmação |
| `PROPOSAL_EXPIRED` | token não existe, expirou ou já foi consumido | original |
| `CONFIG_CHANGED` | revisão, endereço ou protocolo mudou desde a captura | atual; não sobrepor |
| `BUSY` | limite de operação/proposta atingido | original |
| `ADOPTED` | confirmação válida e commit em memória concluído | candidato; readback reportado separadamente |

`DiscoveryFailure.TIMEOUT`/`PROVIDER_ERROR` do F2E.B devem ser mapeados a resultados de recuperação sem detalhes originais. Transport/auth/validation só devem ser distinguidos a partir de códigos estruturados já normalizados, nunca por comparação de texto de exceção.

## C. Concorrência, consistência e estado

### Fatos existentes

- Cada chamada `read_state`, escrita ou `update_address` segura o lock não reentrante do Device ID durante sua operação, inclusive o I/O LAN síncrono.
- `update_address()` valida/recria `DeviceConfig` sob lock, invalida o adapter atual e zera `DeviceKnowledge`; preserva `LightState` e estruturas de pending; usa `PENDING` quando existe intenção pendente, senão `UNKNOWN`.
- Scheduler mantém FIFO por dispositivo, mas só ordena operações nele submetidas. Leitura/status JSONL usa executor e compete pelo lock do manager. A fila não compartilha seu lock durante chamadas LAN.
- Não há geração/versionamento de configuração nem API de fechamento do adapter hoje. `TuyaAdapter` é descartado por referência; implementação F2E.D deve conferir ciclo de vida TinyTuya antes de assumir recursos persistentes.

### Mecanismo proposto

1. Introduzir `config_revision`/`address_generation` monotônico por Device ID, incrementado por toda substituição de configuração/endereço (incluindo `update_address()` existente). Capturar revisão + endereço + protocolo antes do scan; não guardar a chave em uma revisão/hash.
2. Fazer descoberta UDP sem lock do DeviceManager e sem bloquear outras lâmpadas. Resposta de scan só segue se revisão continuar compatível.
3. Para validar, adquirir a exclusão por dispositivo; criar adapter temporário sem registrá-lo no map `_adapters`; executar status com timeout finito; fechar/liberar recurso temporário. Mesmo Device ID aguarda; outros seguem independentes.
4. Não segurar lock entre criação da proposta e a ação humana. Proposta armazena revisão original e TTL. Comandos/leitura normais podem ocorrer nesse intervalo.
5. Confirmar por barreira FIFO no `CommandScheduler` e lock do manager. Recomparar revisão/endereço/protocolo e validar novamente o endpoint no lock antes da alteração. Usar uma única seção crítica com helper privado que não readquire lock.
6. Avançar revisão ao aplicar endereço; configurar adapter ativo como inválido e fechar o adapter anterior. D.2 deve definir fechamento idempotente, ou provar que TinyTuya não retém sessão/socket entre chamadas e que soltar a referência basta. Não reutilizar o adapter temporário como adapter normal.
7. Preservar `_pending_power` e `_pending_fields`; invalidar conhecimento de leitura anterior e não transportar a validação de endpoint para `LightState`. Readback normal posterior é a única fonte de novo observado/knowledge.
8. Ao retornar resultado, incluir revisão/generation ou uma sequência da operação para que o consumidor descarte status antigo recebido fora de ordem. Manter precedência existente de comando/snapshot; não reusar o resultado de validação como `DeviceStatus`.

Tokens são aleatórios, opacos, single-use e vinculados no backend a um único Device ID, endpoint e revisão. Proposta expira após 60 s monotônicos (valor sugerido), sem timer ou thread por proposta: limpeza oportunista ao preparar/confirmar e limite fixo de entradas. Encerramento limpa tabela e invalida tokens; propostas não sobrevivem a restart. Confirm concorrente do mesmo token reserva/consome a entrada antes de validar, impedindo dupla adoção.

## D. Orçamento e operação — proposta para aprovação

| Recurso | Limite sugerido | Justificativa / efeito |
| --- | ---: | --- |
| Descoberta UDP F2E.C | até 3 s; scanner mantém seu teto atual | Já validado como limite da coleta; janela menor pode não ver anúncio tardio. Budget inclui setup, bind, recepção e encerramento controlados pelo scanner. |
| Validação TCP | no máximo 1 candidato único por fase; sem TCP se not-found/ambíguo/3.3 | Evita testar todos os IPs anunciados e reduz superfície/tráfego. O único candidato é validado antes da proposta e novamente no confirm. |
| Tentativas read-only | máximo 2 por ação proposta (uma prepare + uma confirmação) | Reconfirma endpoint depois da decisão humana e reduz troca durante TTL; falha exige iniciar uma nova ação explícita. Cada fase não repete automaticamente. |
| Timeout por validação | teto sugerido de 2,5 s, menor entre esse teto e o timeout já configurado | Mantém compatibilidade de configuração e limite prático. Confirmar que TinyTuya limita construtor, connect e status de ponta a ponta na versão distribuída. |
| Operação ativa total | meta/teto sugerido de 9 s: até 3 s UDP + 2 × 2,5 s TCP + até 1 s de overhead | O tempo de espera da confirmação humana é excluído e regido pela expiração da proposta. Se a API síncrona não cumprir o teto real, não prometer hard cancellation nem criar thread abandonada. |
| Concorrência global | 1 prepare/confirm de recovery em operação por processo | Alinha-se ao lock global do scanner atual e limita sockets/conexões de validação. Requests seguintes retornam `BUSY`; não ficam em fila ilimitada. |
| Propostas pendentes | até 4 no processo, no máximo uma por Device ID | Catálogo atual é pequeno; limite restringe retenção de endpoints/tokens. Requests adicionais retornam `BUSY` até confirmação, cancelamento/expiração ou shutdown. |
| TTL | 60 s monotônicos por proposta | Dá tempo para revisar/confirmação humana sem manter lock. Prazo curto reduz janela de troca. Valor a validar com UX. |
| Limite UDP/candidatos | F2E.C: 256 pacotes e 64 IPs candidatos; F2E.B preserva ambiguidade | Já são os contratos implementados; qualquer saturação resulta em falha, nunca em proposta parcial. |

Os números desta tabela são recomendação de refinamento, não decisão aprovada. Antes de D.1/D.2, confirmar o orçamento de 9 s, timeout TinyTuya real, limite 4/TTL 60 s e o comportamento síncrono de encerramento. A chamada LAN já iniciada não pode ser cancelada arbitrariamente; o shutdown deve aguardar apenas operações que demonstradamente terminem dentro do timeout escolhido e limpar propostas. Não iniciar polling, startup scan ou retries.

## E. Fronteira de segurança e transporte

- Local Key é lida/usada somente no backend a partir da configuração já carregada. Nunca integra announcement, candidate, validation DTO, `DeviceStatus`, `BackendError`, JSONL, Rust, Tauri, frontend, argumentos ou logs.
- Nunca retornar bytes UDP, objeto TinyTuya, resposta DPS bruta, MAC, `DeviceConfig`, exceção original ou texto/traceback da biblioteca. Logs contêm somente código/categoria e contadores não identificadores.
- A WebView não fornece IP de adoção. `recovery.prepare` aceita somente Device ID existente; confirmação aceita somente token de proposta emitido pelo backend. O resultado de proposta pode mostrar o IP já descoberto/validado para a pessoa revisar; esse IP não é reutilizado como input de adoção.
- JSONL acrescenta apenas comandos allowlisted, sugeridos: `device.recovery.prepare` com `{deviceId}` e `device.recovery.confirm` com `{proposalId}`. Campos extras são recusados. Usar requestId existente e resultado discriminado. Nenhum `status`, `set_value`, CLI livre, texto JSON genérico ou caminho de config vindo da WebView.
- Rust/Tauri fornece dois handlers fixos e payloads tipados correspondentes; só encaminha para backend REAL após os gates já aprovados. FIXTURE/MOCK usam respostas sintéticas e não carregam TinyTuya nem rede.
- Nenhuma escrita de iluminação ocorre no recovery. Nenhuma mudança em TOML ou outro armazenamento; endereço fica em memória até reinício. Sem recuperação automática.
- Mensagens ao usuário distinguem candidato, endpoint que aceitou chave e adoção manual com ressalva. Não usar “identidade verificada”, “dispositivo provado” ou linguagem equivalente.

## F. Divisão de implementação e critérios de aceite

### D.1 — Contratos e orquestração backend

**Escopo:** tipos de resultado/proposta, estado de confiança explícito, provider injetável, composição F2E.C→F2E.B→eligibilidade, mapa de erros seguro e orçamento/capacidade. Sem validação TCP/adoção.

**Aceite:**
- not-found/ambiguous/timeout/falha/truncamento são tipos distintos; ambiguidade não cria proposta;
- só Device ID do catálogo inicia ação; dados gerados pelo scan vêm de provider fake;
- nenhum candidato é rotulado autenticado/identidade, não há Local Key em tipos/logs/IPC;
- budgets/limites rejeitam timeout inválido, operação concorrente e saturação sem resultado parcial;
- testes determinísticos cobrem estados, repetição, expiração, fechamento de sessão e shutdown.

**Riscos/dependências:** decidir outputs de erro públicos e se candidato ambíguo bloqueia tentativa inteira ou permite escolha humana futura. Depende de manter F2E.B/C contratos e sem dependência CLI/UI.

### D.2 — Validação read-only e concorrência

**Escopo:** validar candidato 3.5 usando Local Key interna e adapter temporário; revisão/generation, exclusão por dispositivo e barrier FIFO no scheduler; validação repetida na confirmação; lifecycle/timeout de adapters.

**Aceite:**
- apenas protocolo cadastrado 3.5 e candidato elegível executam status; 3.3 nunca executa status de adoção;
- testes provam chamada `status()` e zero chamadas `set_value()`/escrita/estado normal durante validation;
- uma proposta usa configuração e revisão estáveis; alteração concorrente, timeout, auth/transport/parse failure preserva endereço e não cria/aplica proposta;
- FIFO do mesmo ID e read/status concorrentes são serializados sem segurar condição do scheduler durante rede; outro ID progride;
- não existe deadlock por reaquisição de lock; prova via teste com timeout determinístico;
- token/preparação expira, é consumido uma única vez e não permanece após encerramento.

**Riscos/dependências:** verificar TinyTuya 1.20.0 e faixa instalada para status/auth/timeout e recurso `close`; confirmar limites operacionais propostos. Nenhum teste toca LAN real.

### D.3 — Adoção manual e protocolo JSONL

**Escopo:** `confirm(proposalId)`, rechecks atômicos, update de endereço em memória por helper transacional não reentrante, invalidar adapter, readback normal separado e resultados JSONL allowlisted.

**Aceite:**
- somente token ativo produzido pelo backend confirma; IP fornecido pelo cliente, replay, token expirado ou de outra revisão nunca atualiza;
- commit altera só endereço, conserva credenciais/capacidades/Device ID/intenção pendente, invalida conhecimento antigo e adapter;
- mudança ocorre uma vez sob lock; o método público de `update_address()` não é invocado recursivamente sob lock;
- readback separado atualiza observed/knowledge; sua falha não inventa estado nem reverte silenciosamente endereço;
- JSONL permite apenas `{deviceId}` para prepare e `{proposalId}` para confirm; não permite MAC, chave, bytes, erros crus ou comandos arbitrários;
- fixtures/todos testes usam adapters e relógios fakes; ausência de rede/cloud/escrita verificada.

**Riscos/dependências:** alinhamento de revisão/status out-of-order com frontend e UX; esclarecer comportamento para vários candidatos; compatibilidade retroativa do JSONL e teste de shutdown.

### D.4 — Integração Tauri e UX

**Escopo:** handlers Rust tipados, `DeviceController` e ação manual com revisão explícita do destino, ressalva de confiança, expiração e resultado/readback. Sem alteração de endereço livre.

**Aceite:**
- UI oferece ação somente para dispositivo cadastrado e explica que 3.3 não é elegível;
- usuário revisa IP + protocolo + evidência limitada e confirma explicitamente; chamada confirm envia apenas proposalId;
- ambiguidades nunca destacam/selecionam o primeiro endereço; status loading/not-found/ambiguous/auth/transport/expired/changed/adopted/readback falho são claros;
- respostas atrasadas/seleção trocada/unmount não afetam outro dispositivo; acessibilidade teclado/foco e cancelamento visual testados;
- MOCK/FIXTURE executam sem processo TinyTuya/rede; REAL continua opt-in; sem auto recovery/startup/polling.

**Riscos/dependências:** D.1-D.3 estáveis e contratos Rust/UI revisados; validação visual manual no Windows só após autorização separada, sem devices reais como teste automatizado.

## Riscos residuais e decisões ainda necessárias

### Riscos aceitos explicitamente

- posse da Local Key em 3.5 não é prova independente de associação exclusiva da chave ao Device ID/endereço; chaves compartilhadas, reutilizadas ou comprometidas ampliam o risco. Aceito apenas quando o usuário inicia e confirma recuperação manual.
- UDP pode ser forjado/repetido; continua sendo descoberta de pistas, nunca autorização.
- DHCP/ARP/host pode mudar depois da última validação; a validação repetida encurta, não elimina TOCTOU.
- sem persistência, novo endereço é perdido ao reiniciar e a pessoa pode precisar repetir o fluxo.
- rede/firewall/VLAN/firewall Windows/VPN podem impedir descoberta ou conectar a candidatos; isso deve resultar em falha/ausência, não fallback de sub-rede ou cloud.

### Aprovação do mantenedor necessária antes de implementação

1. Confirmar orçamento sugerido: 9 s total de trabalho ativo, até 2,5 s por read-only, 2 validações por proposta, 1 recovery ativo, 4 propostas e TTL de 60 s.
2. Definir se `AMBIGUOUS` bloqueia toda a recuperação manual ou se uma versão futura pode validar cada candidato e permitir escolha explícita pelo usuário. A proposta inicial deste documento é bloquear e não criar token.
3. Aprovar o contrato de resultados/códigos públicos de recovery e se o readback pós-adoção integra a mesma requisição ou retorna estado separado.
4. Confirmar semântica real de autenticação, timeout/cancelamento e lifecycle `close()` em TinyTuya da versão instalada/distribuída; a inspeção 1.20.0 de F2E.A não cobre toda faixa `>=1.20,<2`.
5. Aprovar fila de barreira tipada no `CommandScheduler`, incremento de generation em toda troca de config/endereço e regra de invalidação/fechamento do adapter antigo.
6. Definir texto/UX de consentimento para o risco residual sem sugerir identidade criptograficamente comprovada.

Não há aprovação para recuperação automática, atualização de TOML, scanning no startup, seleção por confiança/ordem, 3.3 adoption, novos comandos de iluminação ou testes físicos. Validação REAL exige autorização explícita separada.
