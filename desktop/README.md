# Smart Home Tray - frontend

Prototipo visual da Fase 2, Etapa F2A. A interface roda em React/TypeScript no navegador e usa exclusivamente `MockDeviceController`; nenhum equipamento, backend Python, processo externo, socket, rede local, cloud ou API nativa Tauri e consultado.

## Requisitos

- Node.js 24 LTS e npm 11.
- Para abrir a janela desktop Tauri no Windows: Rust estavel, Microsoft C++ Build Tools com “Desktop development with C++” e WebView2. Consulte [pre-requisitos oficiais do Tauri 2](https://v2.tauri.app/start/prerequisites/).

## Executar no Windows

No PowerShell, a partir desta pasta:

```powershell
npm ci
npm run dev
```

`npm run dev` abre o prototipo no navegador em `http://localhost:5173`. O comando Tauri usa um servidor dedicado sem abrir outra janela. Para executar na janela desktop (requer os pre-requisitos nativos):

```powershell
npm run tauri:dev
```

## Verificacoes

```powershell
npm run typecheck
npm run lint
npm test
npm run build
```

`npm run lint` usa Oxlint, um linter rapido compativel com TypeScript/React. `npm run build` valida TypeScript e gera `dist/`.

## Mock e estado

`MockDeviceController` fornece Luz Mesa e Fita LED com IDs ficticios. A lampada declara energia, RGB, brilho branco e temperatura; a fita declara apenas energia e RGB. O painel “Cenario de teste” permite simular sucesso, atraso, cancelamento, erro e dispositivo offline. A demora e deterministica; os testes podem configura-la sem espera aleatoria.

`useLightingSession` mantem por dispositivo o patch solicitado, a previa que a interface mostra imediatamente, as operacoes pendentes, o ultimo estado confirmado pelo controlador e o erro/resultado. A precedencia e controlada por campo e por canal HSV. Cada resposta atualiza somente os campos que ainda pertencem a sua intencao, fazendo merge do readback sem desfazer alteracoes independentes. Durante pending a previa combina valores confirmados e pedidos ativos; apos cancelamento/erro ela retorna aos ultimos valores confirmados. Offline preserva esses valores e marca qualidade/conexao como offline. Qualidade `unknown` nao e promovida artificialmente.

## Relacao com o backend

Os tipos cobrem identidade (`deviceId`, `name`), capabilities, conexao, estado, qualidade e HSV normalizado compativeis conceitualmente com os contratos publicos da Etapa D. O contrato do backend usa allowlist para nao expor configuracao privada; este frontend nao copia `DeviceConfig`, TOML, DPS ou credenciais.

A integracao futura substituira o controlador simulado por um adapter Tauri para comandos JSON Lines. Nao ha IPC real nem sidecar nesta branch. O scheduler de comandos continua pertencendo ao backend; o frontend nao implementa outro scheduler. Branco/RGB e um seletor visual, nao um comando IPC existente: o adapter devera associar a selecao a uma operacao de iluminacao suportada, sem inventar um comando de troca de modo.

## Limites

- IDs, estados e respostas sao demonstrativos e nao persistem apos recarregar a pagina.
- A cor branca por temperatura e apenas uma aproximacao visual; o percentual nao indica direcao fisica quente/fria.
- Nenhuma validacao foi feita em lampadas reais.
- Rust/Cargo nao estavam instalados no ambiente de implementacao; a configuracao Tauri foi gerada, mas o alvo nativo nao foi compilado.
