# F2A — Protótipo Visual Interativo

## Objetivo e limites

Entregar em `desktop/` um protótipo React/TypeScript utilizável no navegador e preparado como frontend de Tauri 2. Nesta etapa todas as lâmpadas são simuladas. Não haverá acesso ao backend Python, JSON Lines, LAN, cloud, equipamentos físicos, APIs nativas, credenciais ou persistência.

## Arquitetura

Vite serve e compila a UI sem depender do runtime nativo; a configuração Tauri 2 referencia o mesmo servidor e os artefatos `dist`. Componentes dependem de tipos públicos normalizados e de `DeviceController`; `MockDeviceController` implementa catálogo, comandos assíncronos determinísticos e cenários controlados. O adapter real Tauri/JSON Lines fica para fase futura.

Cada dispositivo possui estado confirmado independente. A interação atualiza uma prévia local imediatamente; os comandos carregam sequência por dispositivo para que respostas antigas não substituam intenções recentes. Estado solicitado, prévia, pendência, confirmação e erro permanecem distintos. Mock inclui cenários de sucesso, atraso, cancelamento, offline e falha sem abrir sockets ou iniciar processos.

## Experiência

Janela responsiva com tema carvão azulado, cartões compactos, foco acessível, botão de energia, seletor de dispositivos, controles por capability e ilustrações SVG próprias para Luz Mesa e Fita LED. A luz usa HSV real convertido para RGB; branco mantém brilho e temperatura separados. Temperatura é exibida sem afirmar qual extremo é fisicamente quente/frio. Fita LED não mostra controles brancos nem cenas fictícias.

Motion cobre transições de layout e microinterações; CSS cobre gradientes/halos e controles simples. A UI respeita `prefers-reduced-motion`, permite teclado e comunica conexão/operação sem depender apenas da cor.

## Verificação e limites conhecidos

Vitest e React Testing Library cobrem modelos, controlador, ordenação de respostas e interações acessíveis. CI frontend roda npm ci, typecheck, lint, testes e build, sem matriz Rust. Execução visual e validação física são evidências separadas; ausência de Rust/Cargo limita somente a compilação desktop nativa.
