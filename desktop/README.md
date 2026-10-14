# Smart Home Tray — desktop

A aplicação usa React/Vite para a interface, Tauri 2/Rust para a janela e o system tray, e exclusivamente `MockDeviceController` para os controles. Não inicia o backend Python, não abre JSON Lines, não acessa LAN/cloud e não controla dispositivos físicos.

## Pré-requisitos no Windows

Instale os pré-requisitos oficiais do Tauri 2:

- Node.js 24 e npm 11.
- Rust estável com o alvo MSVC (x86_64-pc-windows-msvc).
- Visual Studio Build Tools com **Desktop development with C++**, incluindo o Windows SDK.
- Microsoft Edge WebView2 Runtime. Ele já vem com versões atuais do Windows 10/11; instale o Evergreen Runtime se estiver ausente.

Consulte [Tauri 2 — prerequisites](https://v2.tauri.app/start/prerequisites/). O projeto exige Rust 1.90 ou posterior (edition 2024).

## Executar

No PowerShell, dentro de `desktop/`:

```powershell
npm ci
npm run dev
```

Isso inicia somente a versão de navegador em `http://localhost:5173`. Ela continua útil para validar a interface; o botão nativo **Ocultar painel** não aparece no navegador.

Para executar a aplicação desktop:

```powershell
npm run tauri:dev
```

A janela começa oculta. Use o clique esquerdo no ícone de bandeja para abrir/ocultar, o menu de contexto para **Abrir Smart Home Tray** ou **Sair**, ou o botão acessível **Ocultar painel** na interface. Fechar a janela pelo sistema oculta o painel e preserva o WebView/estado React. Uma segunda execução traz a instância existente para frente.

## Testes e compilação

No diretório `desktop/`:

```powershell
npm run typecheck
npm run lint
npm test
npm run build
npm run tauri:build -- --no-bundle
```

No diretório `desktop/src-tauri/`:

```powershell
cargo fmt --all -- --check
cargo check --locked
cargo test --locked
```

`npm run build` valida e compila Vite, mas não substitui o build Rust/Tauri. `npm run tauri:build -- --no-bundle` valida a aplicação Windows sem criar instalador/empacotamento. O workflow `.github/workflows/desktop-tests.yml` mantém o job Node e adiciona um job Windows/MSVC para fmt, check, testes Rust e build sem bundle; ele ainda precisa executar no GitHub Actions para evidenciar a compilação nativa desta etapa.

## Arquitetura e permissões

- `src-tauri/src/lib.rs`: tray, menu, instância única, foco, ocultação e fechamento explícito.
- `src-tauri/src/positioning.rs`: posicionamento em pixels físicos e testes para work areas, monitor secundário com coordenadas negativas, taskbar superior e fallback.
- `src/platform/`: detecção do Tauri e ação de ocultar. Capability concede somente `core:window:allow-hide`.
- React mantém toda a interface e usa `MockDeviceController`. Não há comando de iluminação nativo.

`tauri-plugin-positioner` recebe os eventos do tray e atualiza a localização do ícone. A posição final é limitada à `work_area` do monitor para descontar a barra de tarefas; o helper do plugin limita à resolução total, então o app complementa essa etapa com a API de monitor do Tauri. Tray e monitores são consultados em coordenadas físicas para evitar conversão manual de DPI. Se o rect/monitor do tray não estiver disponível, o fallback fica no canto inferior direito da área útil primária. A barra de tarefas que se move enquanto a janela está aberta e troca de monitor após a abertura serão verificadas manualmente.

O popup não fecha ao perder foco; esse comportamento fica reservado porque competir com menus nativos e controles de seleção pode ocultar a janela durante uma interação. O tamanho é reduzido à área de trabalho disponível em monitores menores e CSS permite rolagem vertical.

## Checklist de validação manual no Windows

1. Iniciar com `npm run tauri:dev` e confirmar que a janela inicia oculta.
2. Confirmar o ícone e tooltip **Smart Home Tray** na bandeja.
3. Clicar no ícone com o botão esquerdo para abrir; clicar novamente para ocultar.
4. Usar **Ocultar painel** e reabrir, confirmando que seleção e controles permanecem.
5. Abrir pelo menu contextual e confirmar foco; testar **Sair** e confirmar remoção do ícone/processo.
6. Executar uma segunda instância e confirmar que a primeira abre sem tray duplicado.
7. Repetir com tray em monitor secundário e taskbar inferior, superior ou lateral quando disponível.
8. Repetir com escalas 100% e 125%, se disponíveis; verificar ausência de corte fora da work area.
9. Diminuir a área útil/resolução e confirmar que a janela cabe e o conteúdo rola.
10. Testar navegação por teclado e reduced motion.
11. Mover os controles simulados e confirmar que nenhuma lâmpada/dispositivo físico é alterado.

No primeiro acesso, Rust e MSVC não estavam no PATH; o toolchain local já instalado foi encontrado em `C:\Users\sandr\.cargo\bin`. `cargo fmt --check`, `cargo check --locked`, `cargo test --locked` (5 testes) e `npm run tauri:build -- --no-bundle` passaram. A inspeção manual de tray, foco, escala e múltiplos monitores ainda está pendente. O estado detalhado fica em `docs/PROJECT_STATUS.md`; a integração JSON Lines/backend segue reservada à F2C.
