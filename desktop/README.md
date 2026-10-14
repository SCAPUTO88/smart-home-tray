# Smart Home Tray — desktop

A interface usa React/Vite e continua isolada atrás de DeviceController. Navegador e Tauri padrão usam MockDeviceController. Em desenvolvimento, o Tauri pode iniciar o processo fixture ou o backend Python real explicitamente habilitado. A fixture não acessa rede nem dispositivos físicos.

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
- `src-tauri/src/positioning.rs`: posicionamento por lado da taskbar, tamanho preferencial com DPI do monitor, clamp na work area e testes geométricos.
- `src/platform/`: detecção Tauri, ocultação e arraste do painel. A capability concede `core:window:allow-hide` e `core:window:allow-start-dragging`.
- React mantém toda a interface e usa `MockDeviceController`. Não há comando de iluminação nativo.

`tauri-plugin-positioner` recebe os eventos do tray. O app identifica o monitor pela âncora física e compara `Monitor::size()` com `Monitor::work_area()`: taskbar superior abre abaixo do ícone, inferior acima, esquerda à direita e direita à esquerda. A janela fica a 10 px físicos do ícone e dentro da work area. O retângulo do tray já está em pixels físicos; `to_physical(1.0)` preserva os valores sem segunda escala. Se a âncora não corresponder a um monitor, o fallback usa a work area disponível.

O popup não fecha ao perder foco para evitar conflitos com menus/seleção. Cada abertura oculta aplica o tamanho preferencial de 420 × 720 pixels lógicos convertido pelo DPI do monitor; em work area menor, reduz a janela e volta ao tamanho preferido ao reabrir num monitor maior. Só posiciona ao abrir, preservando a posição manual enquanto visível. O conteúdo permite rolagem vertical.

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

12. Arrastar pelo cabeçalho e confirmar que Ocultar painel continua clicável sem mover a janela.
13. Com o painel visível, usar Abrir por uma segunda instância e confirmar que a posição manual não muda.
14. Ocultar e reabrir pelo tray; confirmar que a janela volta para perto do ícone.
15. Repetir com taskbar superior/inferior/esquerda/direita, monitor secundário e escalas 100%, 125% e 150%; verificar 8–12 px de margem e nenhum corte.
16. Reabrir após usar monitor pequeno e depois um maior; confirmar restauração dos 420 × 720 pixels lógicos quando couber.


O mantenedor confirmou no Windows que `npm run tauri:dev` abre a janela nativa e renderiza os dispositivos simulados. A interação do arraste e o novo ancoramento ainda precisam de confirmação manual. Nesta revisão: cargo fmt/check passaram, 12 testes Rust, 53 testes frontend, typecheck/lint/build Vite e `npm run tauri:build -- --no-bundle` passaram. O build mostra aviso não bloqueante de colisão PDB entre bin/lib. CI remoto aguarda execução.

## Modos de execução F2C.1

### Navegador (sempre mock)

```powershell
npm run dev
```

O navegador sempre usa MockDeviceController e ignora as variáveis de modo nativo. O painel de cenários continua disponível.

### Tauri padrão (mock)

```powershell
npm run tauri:dev
```

Sem configuração adicional, o Tauri também inicia no modo MOCK e mantém o comportamento existente.

### Tauri com processo fixture

No PowerShell, em desktop/, escolha FIXTURE no processo Rust antes de iniciar:

```powershell
$env:SMART_HOME_TRAY_BACKEND_MODE = "fixture"
npm run tauri:dev
```

A fixture implementa os envelopes JSON Lines existentes com dados artificiais, sem TinyTuya, configuração TOML ou acesso à rede. O rodapé identifica os dados como fixture e o painel Cenário de teste não aparece. Para retornar ao padrão, remova a variável da sessão:

```powershell
Remove-Item Env:SMART_HOME_TRAY_BACKEND_MODE
```

### REAL de desenvolvimento — opt-in não executado nesta etapa

O caminho REAL é preparado, mas não foi executado com equipamento. Requer Python compatível e dependências do backend instaladas, arquivo TOML externo válido com IDs/capacidades/DPS corretos e variáveis Local Key referenciadas por esse arquivo já presentes no ambiente do processo. O arquivo TOML deve ser absoluto. Nunca coloque valores de chave no TOML, no código ou no frontend.

```powershell
$env:SMART_HOME_TRAY_BACKEND_MODE = "real"
$env:SMART_HOME_TRAY_ALLOW_REAL = "1"
$env:SMART_HOME_TRAY_CONFIG = "C:\caminho\absoluto\config.toml"
npm run tauri:dev
```

Remova as três variáveis ao terminar. O app usa o comando fixo python -m smart_home_tray.cli --config <arquivo> serve. Somente Rust lê as variáveis; a WebView não pode solicitar outro executável, args ou caminho. Se REAL foi escolhido e o bridge falhar, a UI mostra erro e não muda silenciosamente para simulação. Faça a revisão arquitetural antes de testar hardware.

O produto ainda depende de um Python externo; sidecar Python empacotado, instalador, assinatura e atualização automática ficam para etapas posteriores.

## Backlog não incluído

- CR-20: ajustar a proximidade do popup ao tray em certas configurações multi-monitor; o mantenedor relatou distância excessiva durante validação F2B.
- Revisão futura da ilustração da Fita LED como fita COB flexível, parcialmente enrolada, com difusor contínuo.


### Atualização manual do estado

Use **Atualizar** no cartão de controles para consultar novamente somente o dispositivo selecionado. MOCK retorna o snapshot local; FIXTURE consulta apenas o processo fixture; REAL, quando habilitado explicitamente, consulta apenas o ID selecionado. A ação não cria polling, retry automático ou varredura. Durante uma escrita pendente o botão fica desabilitado para evitar que um readback concorrente substitua a intenção ainda em andamento. Em falha, a última observação é mantida como stale e a UI mostra o erro sem promover valores antigos a estado atual.

Os campos com conhecimento unknown/stale exibem “—” e só bloqueiam os controles que dependem daquele campo. Power, HSV, brilho branco, temperatura, work mode, colorValue e cena têm conhecimento independente. MOCK e FIXTURE continuam totalmente simulados e não abrem conexão LAN.

REAL permanece opt-in e depende de Python e configuração externos; a aplicação valida a existência do TOML e a resposta inicial do catálogo, mas os erros detalhados permanecem no processo local e não são enviados à WebView. A F2C.2 não incluiu validação de hardware nem empacotamento do runtime Python.
