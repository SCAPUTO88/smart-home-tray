# F2E.D.3.A — confirmação interna e adoção atômica

**Estado:** arquitetura aprovada; implementação autorizada após os esclarecimentos abaixo.  
**Base:** `origin/develop` após a PR #39, merge `abab02c360947730e2df62bbf2e044371fb23503`.  
**Branch/worktree:** `feature/f2e-d3a-adoption` / `.worktrees/f2e-d3a-adoption`.

## Objetivo e limites

Implementar a confirmação exclusivamente interna de uma proposta emitida por `prepare_internal()`. A confirmação recebe somente o token opaco; não recebe nem aceita IP. A confirmação consome uma proposta de uso único, revalida o endpoint candidato por Tuya 3.5 read-only, adota o endereço apenas em memória e faz um readback normal separado. O resultado de adoção e o resultado do readback são independentes.

Preservar D-018 e D-019: somente Tuya 3.5; confirmação explícita; segunda validação read-only; um slot global por processo para o trabalho ativo; barreira FIFO tipada por Device ID; até quatro propostas com TTL monotônico de 60 segundos; sem retry automático, adoção automática, persistência TOML ou escrita DPS.

Fora de escopo: JSONL, IPC, Tauri/React, UI, APIs públicas, seleção/entrada de endereço, Tuya 3.3, cloud, hardware real, persistência, confirmação automática e alteração de qualquer DPS.

## Fluxo proposto

1. `RecoveryService.confirm_internal(token, ...)` valida apenas a forma do token e lifecycle local, adquire o slot global sem fila e define o deadline de trabalho. Não aceita Device ID ou endereço como autoridade para escolher o dispositivo.
2. Sob o mutex do `ProposalStore`, o claim decodifica e localiza o digest, expurga entradas expiradas, compara o owner privado com a identidade da instância solicitante e confere o prazo. **Somente após ownership válido** remove a entrada e a marca consumida. Um token de outra instância não é removido nem consumido. Resultado interno do claim preserva `binding`, owner e o `expires_at` original; esses dados privados nunca são serializados ou incluídos em repr/log.
3. Depois que o lock do store foi liberado, o coordenador submete uma solicitação tipada `CONFIRM_RECOVERY` à fila do scheduler do Device ID vinculado. A solicitação é discreta, FIFO, não coalescível e não contém callback arbitrário. A operação conserva o slot global até toda a validação, commit e readback terminarem. Nenhuma Condition do scheduler cobre locks do manager ou I/O LAN.
4. Dentro de uma única lease do manager, adquirir uma vez o lock não reentrante do Device ID e comparar revisão monotônica, endereço original, protocolo cadastrado 3.5, owner, TTL original, deadline, cancelamento e lifecycle. A comparação ocorre antes do I/O e novamente nos pontos necessários antes do commit. Nunca chamar `update_address()` dentro da lease.
5. Ainda sob a lease e antes do commit, executar a segunda validação read-only no candidato vinculado ao token. Qualquer falha de autenticação, transporte, consistência, deadline, cleanup, configuração, TTL ou fechamento consome definitivamente o token e impede adoção. Não restaurar o token após claim.
6. Sob a mesma lease, fechar o adapter normal anterior por uma API de `TuyaAdapter.close()` que torna cleanup observável. O DeviceManager não acessa `_device` nem seu socket. Falha de fechamento aborta o commit, preserva configuração/endereço/revisão/estado como antes da adoção e retorna resultado tipado sanitizado; nenhuma exceção bruta atravessa o contrato.
7. Definir o ponto de commit como a seção curta e indivisível sob o lock do Device ID e o mutex de lifecycle do serviço. A ordem é ID → lifecycle; o fechamento do serviço não segura lifecycle enquanto espera o lock do ID. Dentro da seção, revalidar TTL original (`now < expires_at`), deadline, revisão, endereço, protocolo, cancelamento e lifecycle imediatamente antes de aplicar a substituição. O lock de lifecycle lineariza commit contra `close()`: ou o fechamento vence e não há adoção, ou o commit termina antes do fechamento linearizar.
8. Aplicar por helper transacional interno desbloqueado; nunca reacquirir o lock do ID. Preservar Device ID, Local Key, protocolo, DPS, capacidades, timeout e intenções `_pending_power`/`_pending_fields`. Incrementar a revisão exatamente uma vez, invalidar adapter antigo e knowledge/readback antigo, atualizar somente endereço e estado de conexão/qualidade para `UNKNOWN` ou `PENDING` conforme as intenções já existentes. A validação de recovery não é aplicada como estado observado.
9. O lock do Device ID lineariza adoção contra `update_address()`: atualização que concluir antes da lease altera a revisão e bloqueia a adoção obsoleta; atualização que linearizar após o commit é uma nova alteração e não invalida retroativamente o resultado `ADOPTED` já confirmado. A revisão incrementada no commit identifica precisamente a configuração adotada.
10. **Após o ponto de commit, adoção é definitiva em memória.** Liberar a lease do manager. No mesmo turno FIFO, executar readback normal separado; este readback readquire o lock do ID exclusivamente pelo caminho normal e compara, dentro do lock, a revisão atual com a revisão do commit. Se a revisão diferir, não fazer I/O nem reportar leitura como confirmação do endereço adotado; retornar readback separado como `SUPERSEDED`/não realizado. Se coincidir, chamar a leitura normal. Falha posterior não reverte o endereço nem converte `ADOPTED` em falha de adoção; timeout, shutdown ou erro de readback após commit só afetam o resultado de readback/encerramento e mantêm `adoption=ADOPTED`.
11. Liberar o slot global apenas depois de concluir o readback (ou confirmar que uma revisão posterior o tornou obsoleto) e montar o resultado terminal. Operações posteriores do mesmo ID permanecem atrás da barreira; outros IDs continuam independentes conforme o scheduler.

## Ownership, TTL e concorrência

- O claim verifica owner atomicamente antes do consumo, para que uma instância não possa consumir tokens de outra. `expires_at` é capturado no store e propagado sem recalcular ou estender TTL.
- Expiração é testada no claim, na entrada da lease, após espera FIFO, antes/depois da segunda validação e no último ponto anterior ao commit. `now >= expires_at` bloqueia o commit mesmo que o token fosse válido no claim.
- Replay, claim concorrente e claim repetido após falha nunca restauram a proposta. Apenas um claim do owner correto pode vencer.
- Mudanças de configuração são detectadas pela revisão monotônica; A→B→A continua inválido. Uma mudança que lineariza antes da lease/commit impede adoção. Uma mudança que lineariza depois do commit não desfaz a adoção já concluída; a revisão nova impede que o readback tardio seja atribuído ao endereço anterior.
- Shutdown e commit são linearizados pelo mutex de lifecycle no ponto de commit. Se o serviço fechar antes de o commit adquirir o mutex, não há adoção. Se o commit já detém o mutex, o commit termina antes de `close()` concluir seu passo linearizável. Operações de I/O iniciadas são drenadas; não se solta slot ou lease enquanto permanecem ativas.
- Ordem de locks: Device ID → lifecycle durante o commit. O mutex do store é usado apenas no claim/invalidação e nunca segura lock do ID. O scheduler não mantém mutex durante chamada ao manager/I/O.

## Adapter ativo e limite de cleanup

O `TuyaAdapter` encapsulará toda interação com o objeto TinyTuya, inclusive fechamento. A implementação deve investigar a versão compatível e testar o comportamento com fakes. O DeviceManager invoca apenas a API pública/interna do adapter e não inspeciona atributos privados do dispositivo.

O adapter deve capturar falha de cleanup e convertê-la em falha tipada, sem mensagem ou causa bruta. `close()` deve ser idempotente após fechamento bem-sucedido. Se o cleanup falhar parcial ou totalmente, impedir commit e marcar a instância do adapter como não reutilizável; manter qualquer recurso ainda observável encapsulado no próprio adapter para impedir seu uso acidental e permitir cleanup controlado, sem alegar rollback físico completo. A configuração e o endereço não são adotados. O cleanup ocorre com o lock do Device ID, portanto não existe read/write concorrente daquele adapter ativo. O DeviceManager nunca acessa `_device.socket`.

Limitação: um socket close executado em TinyTuya/Python/OS não permite provar que firmware, kernel ou chamada nativa concluiu liberação física em prazo rígido. O contrato é limitado ao recurso observável e à conclusão/erro retornado pelo fechamento que o adapter controla; não alegar hard cancellation ou garantia contra travamento nativo. Se a implementação não conseguir observar e propagar a falha de cleanup sem acessar o socket pelo DeviceManager, parar antes do commit de adoção e registrar o bloqueio. Não introduzir thread destacada ou abandonar I/O.

## Resultados internos

Separar no resultado terminal:

- `adoption`: `ADOPTED` somente depois do commit; erros antes dele nunca retornam `ADOPTED`.
- `readback`: `SUCCEEDED` com o resultado normal do manager ou `FAILED` com erro tipado sanitizado, somente quando houve commit.
- Erros de token indisponível/expirado/owner incorreto, config alterada, protocolo inelegível, auth/validation, cleanup, timeout e shutdown não incluem Local Key, configuração privada, token em repr/log, exceção bruta, payload/DPS crus ou detalhes de socket.

Os nomes finais dos enums permanecem internos nesta etapa e não alteram contratos JSONL/UI.

## Testes determinísticos

Usar somente adapters/providers/managers falsos, relógios monotônicos injetados, Events e barriers; nenhum socket real, rede, hardware, credencial ou cloud.

- sucesso: claim do owner, segunda validação aceita, cleanup bem-sucedido, commit só de endereço/revisão e readback separado;
- auth failure ou validação/cleanup failure: token consumido, sem commit nem readback após falha pré-commit;
- TTL: token válido no claim mas expirado aguardando FIFO; expiração durante validação; expiração imediatamente antes do commit;
- ownership: duas instâncias compartilham store; claim errado não consome; owner correto pode confirmar; close de outra instância não invalida operação ativa;
- replay/concorrência: duas confirmações para o mesmo token disputam por barrier; exatamente uma pode claim;
- configuração: A→B→A, atualização enquanto espera FIFO e enquanto valida; nenhum resultado antigo adota;
- lifecycle/deadline: rechecagem de lifecycle depois de obter slot; close antes do commit impede adoção; commit linearizado antes de close permanece adotado; timeout ou shutdown após commit não reverte `ADOPTED`; deadline drena I/O antes de liberar lease/slot;
- adapter: socket fake fecha uma vez, idempotência, exceção de close propagada como falha sanitizada e endereço inalterado;
- comandos: comando anterior termina antes da barreira, comando posterior após readback, outro Device ID progride durante validação/readback; `update_address()` antes da lease impede adoção e após commit não reverte `ADOPTED`;
- readback com revisão: mudança de endereço entre liberação da lease de adoção e readback impede I/O sob configuração posterior e retorna resultado de readback `SUPERSEDED`;
- readback: falha após commit mantém `ADOPTED`, endereço candidato e resultado de readback `FAILED`;
- invariância: Device ID, Local Key, protocolo, DPS/capacidades, `_pending_power`, `_pending_fields` e intenção de usuário preservados; knowledge antigo invalidado no commit e atualizado apenas pelo readback normal.

## Verificação e parada

Após execução do plano, rodar testes focados, suíte backend, `compileall` e `git diff --check`. Revisar o diff e apresentar o checkpoint para code review. A implementação está autorizada, mas deve parar antes de commit/push/merge funcional para revisão do usuário.
