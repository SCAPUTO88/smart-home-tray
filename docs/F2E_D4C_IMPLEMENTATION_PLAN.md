# F2E.D.4.C Implementation Plan

**Goal:** entregar a interface de recuperação manual sobre D.4.A/B, sem alterar contratos ou reconciliação.
**Spec:** `docs/F2E_D4_TAURI_UX_DESIGN.md` e requisitos D.4.C do mantenedor.
**Architecture:** um `ApplicationSessionHost` estável por runtime ativo mantém integração, controller, `useLightingSession`, propostas/confirmações e `RecoveryPresentation` acima da árvore visual. Remontar `LightingApp` não relista nem destrói estado transacional; integrações injetadas ficam isoladas por identidade.
**Tech Stack:** React, TypeScript, Vitest, Testing Library/userEvent; dependências existentes.

## Restrições

- Confirmação somente com proposalId; sem rede, IPC, scheduler ou reconciliação no componente.
- TTL monotônico finito >= 0, confirmação bloqueada com <= 2 s; sem polling ou retry automático.
- UNKNOWN não autoriza prepare; indeterminate não autoriza repetir confirm.
- Não modificar D-015–D-019, backend, protocolos ou LightingDevice.
- Sem hardware/REAL, merge ou nova fase.
- A sessão existe somente em memória durante o runtime ativo; reload/destruição da WebView ou encerramento do aplicativo/processo não promete cancelar, adotar ou reverter operação.

## Tarefas

- [ ] Testar e implementar `recoveryPresentation.ts` e `ManualRecoveryPanel.tsx`: estados públicos, TTL, duplicidade, resultados e acessibilidade. Inputs: operações de useLightingSession; output: somente apresentação. Executar teste focado RED/GREEN.
- [ ] Integrar resolveDeviceIntegration no LightingApp; prop integration opcional, controller existente preservado. Testar UI + controllers reais com bridges falsos, MOCK sem invoke e FIXTURE com invokes fixos; preservar intents/knowledge.
- [ ] Verificar npm test/typecheck/lint/build e diff-check; revisar diff, registrar camadas exercitadas e limitações em PROJECT_STATUS/memória; commits e PR para develop, sem merge.

## Foco de revisão

- Remontagem não apaga confirmação em andamento; manter apresentação na identidade da integração.
- Resposta de outro dispositivo não move foco nem contamina seleção atual.
- Retorno de janela oculta reavalia deadline, sem renovar TTL ou cancelar backend.
- Refresh manual não representa confirmação retroativa de adoção incerta.
- Descartar proposta não cancela token backend; explicar possível BUSY até expiração.

## CR-49.1 — host estável do runtime

O `ApplicationSessionHost` da raiz do runtime possui a integração e mantém o hook de sessão montado enquanto a árvore visual pode sair e voltar. O bootstrap e `controller.list()` são idempotentes sob StrictMode. A apresentação é criada para a identidade desse host, e suas injeções não compartilham estado. A sessão não grava em disco nem replica epochs, knowledge, base confirmada ou reconciliação do controller.

Regressões obrigatórias: proposta confirmável após remount; `ADOPTED + FAILED` e `ADOPTED + SUCCEEDED` durante desmontagem; resultado indeterminado sem retry; TTL expirado sem renovação; intenção de iluminação pendente; troca de dispositivo durante confirm; StrictMode; listagem/checkpoints sem reinicialização; e isolamento de identidades injetadas. Usar promises deferred e relógio injetado, sem sleeps ou rede.

## Baseline

Worktree D.4.C já isolada em b5f09a2, ancestral de origin/develop após fetch. develop local está antigo e foi preservado. npm ci concluído; 148 testes em 14 arquivos passaram. Nenhuma alteração nas demais worktrees.
