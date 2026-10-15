# F2E.A — investigação técnica e contratos de descoberta LAN

**Estado:** investigação concluída; desenho e contratos são propostas para revisão. Nenhuma decisão arquitetural foi aprovada. Não há provider, aceitação de endereço nem integração funcional implementados.

## Escopo e método

O pacote efetivamente instalado foi inspecionado por leitura de metadados e código-fonte local: TinyTuya **1.20.0**, em `D:\AppData\Python\Python314\site-packages\tinytuya`. Nenhuma função de descoberta, status ou conexão foi invocada. Nenhum socket foi aberto por esta investigação. Não foram lidos arquivos locais de dispositivos ou snapshots.

As conclusões de implementação abaixo se referem a esse código instalado. A dependência do backend continua como `tinytuya>=1.20,<2`; uma instalação 1.20.0 não comprova compatibilidade com todas as versões futuras 1.x.

## APIs verificadas

### `find_device(dev_id=None, address=None)`

Implementada em `tinytuya/core/XenonDevice.py`. Exige um ID ou endereço; sem ambos retorna um dicionário sentinela com `ip`, `version`, `id` e `product_id` nulos e `data` vazio. Com um filtro, chama `scanner.devices(verbose=False, poll=False, forcescan=False, byID=True, wantids=..., wantips=...)`. Retorna `{ip, version, id, product_id, data}` para o primeiro resultado que corresponde ou o mesmo sentinela se não encontrar. Não tem parâmetro público de timeout, não retorna uma lista de candidatos e não representa ambiguidade; o scanner agrega o resultado por `gwId`, podendo ocultar anúncios duplicados do mesmo ID.

O caminho usado por `find_device()` deixa `tuyadevices=None` no scanner. `scanner.devices()` então chama `load_devicefile(DEVICEFILE)`, cujo caminho padrão é o `devices.json` do TinyTuya. A investigação não executou essa chamada nem leu esse arquivo. Portanto, F2E.B não deve usar `find_device()` diretamente enquanto não houver uma forma verificada de impedir esse acesso incidental a arquivo privado.

### `deviceScan(verbose=False, maxretry=None, color=True, poll=True, forcescan=False, byID=False)`

Atalho público em `tinytuya/core/core.py` para `scanner.devices()`. Retorna dicionário por endereço ou por ID conforme `byID`. `maxretry` é repassado como `scantime`; `poll=False` evita o polling TCP de status dos dispositivos anunciados, mas não evita a descoberta UDP. A assinatura pública não expõe `wantids` ou `tuyadevices`, e o carregamento incidental de `devices.json` continua possível.

O método interativo `scan()` imprime saída; não é apropriado como contrato de aplicação. `XenonDevice` também chama internamente `find_device()` quando construído sem endereço (`None`, `Auto` ou `0.0.0.0`) e pode repetir essa busca ao abrir socket. Essa conveniência automática deve ser evitada no backend, que sempre constrói o adapter com endereço explícito.

### UDP, interfaces, timeout e erros

Em `scanner.devices()`, com `discover=True`, TinyTuya abre listeners UDP IPv4 nas portas 6666, 6667 e 7000, ligando-os a `('', porta)`. `get_ip_to_broadcast()` enumera endereços IPv4 com `netifaces`, ou `psutil` como alternativa, e monta broadcasts por interface; endereços com o mesmo broadcast são deduplicados no mapa. Se nenhum mapa estiver disponível, o fallback escolhe o IP da rota obtido por um socket auxiliar. A descoberta ativa para anúncios 3.5 envia broadcast UDP à porta 7000, vinculada ao endereço de cada interface enumerada, se a biblioteca de criptografia oferecer GCM. Falhas de bind dessa etapa são registradas e a interface é pulada; falhas no envio são registradas. Falhas de bind dos listeners iniciais não têm tratamento local equivalente e podem propagar.

O padrão instalado é `SCANTIME=18` segundos. A implementação calcula prazo absoluto; a busca dirigida pode terminar antes quando encontra o ID pedido. `find_device()` não permite reduzir esse prazo. `deviceScan(maxretry=...)` aceita uma janela, mas seu uso ainda precisa ser limitado pelo chamador e não cria cancelamento forte da operação síncrona. A própria API bloqueia até terminar. Se o ID não anunciar, o resultado pode consumir a janela inteira e retornar “não encontrado”. `poll=False` e `forcescan=False` limitam esse caminho a broadcasts e evitam a varredura TCP de sub-redes.

VPNs, adaptadores sem broadcast, interfaces down, Wi-Fi isolado, firewall, VLANs e redes roteadas podem fazer a enumeração omitir interfaces ou impedir envio/recepção. A lista de interfaces não prova que a rota até o dispositivo exista. Dispositivo que não anuncia, ou cuja família de firmware não responde ao broadcast suportado, pode não aparecer. Nada disso foi testado em rede nesta tarefa.

### Conteúdo de anúncios e identidade

O parser UDP de `scanner.py` descriptografa/parsa o pacote, exige a presença de `gwId` e usa o endereço de origem como IP candidato. O objeto também pode conter `version`, `productKey` e outros campos. Esses campos vêm do broadcast e não são uma resposta autenticada por uma Local Key específica. Um pacote UDP forjado, repetido, atrasado ou originado de um endpoint adversarial pode produzir uma pista falsa. Igualdade textual de `gwId` filtra candidatos, mas não prova quem controla o IP.

### Status, autenticação e versões

O `status()` de `XenonDevice` envia consulta de leitura de DPS e retorna resposta interpretada ou erro TinyTuya. Para versões até 3.3, o parser usa o enquadramento 55AA com CRC32 quando não recebe `hmac_key`; a carga 3.2/3.3 é cifrada com AES, mas esse caminho não fornece integridade criptográfica de mensagem. CRC detecta corrupção acidental, não autentica remetente. Os layouts 3.4/3.5 mudam a consulta e deixam de incluir `gwId`/`devId` no payload de status; a associação no objeto do cliente não implica que o responder ecoou o ID.

Em 3.4/3.5, TinyTuya negocia chave de sessão usando HMAC com a Local Key; o enquadramento 6699 usa AES-GCM, e o enquadramento 55AA usa HMAC quando a chave é fornecida. Isso é evidência de posse da chave configurada para a sessão/frame, não uma afirmação protocolar independente de que a chave corresponde univocamente ao Device ID esperado. O pacote de anúncio UDP 7000 usa a chave UDP compartilhada da biblioteca, não a Local Key do cadastro; não vincula o `gwId` ao status.

**Conclusão de identidade:** DPS sintaticamente válidos não comprovam identidade. Alguns anúncios podem ter integridade sob a chave UDP compartilhada da biblioteca, mas isso não demonstra posse da Local Key do cadastro nem vínculo do `gwId` ao status. 3.4/3.5 podem provar posse da Local Key configurada, mas o código consultado não demonstra que a resposta foi criptograficamente vinculada ao Device ID fornecido nem que chaves não são compartilhadas/reutilizadas. Em 3.3, além da falta desse vínculo, não há HMAC no enquadramento de status. Logo, a evidência inspecionada é insuficiente para trocar automaticamente o endereço com segurança para todo o catálogo atualmente suportado. A aceitação de IP fica bloqueada; nenhum fallback baseado apenas em anúncio, DPS, protocolo ou código de erro é permitido.

## Backend existente inspecionado

- `DeviceManager` indexa configurações por Device ID imutável e usa um `threading.Lock` por dispositivo em leituras, escritas e `update_address()`.
- `DeviceConfig` é imutável, aceita atualmente endereço IP por `ipaddress.ip_address()` (IPv4 ou IPv6), contém protocolo, mapeamento DPS, timeout e Local Key privada.
- `TuyaAdapter` recebe `DeviceConfig`, constrói TinyTuya com `dev_id`, endereço, Local Key, versão e timeout; `read_status()` retorna somente DPS validados. O adaptador não entrega evidência de identidade do endpoint.
- `update_address()` valida que o ID já está cadastrado, substitui apenas o endereço em memória sob o lock, descarta o adapter, marca conexão unknown e invalida knowledge confirmada, preservando os valores atuais e intenção pendente. A configuração não é persistida.
- Testes existentes cobrem a invalidação de confirmação, preservação de intenção pendente, recriação do adapter e estabilidade do Device ID. Endereços de teste são reservados e chaves são sintéticas.

## Contratos propostos para revisão (não aprovados)

Não foram adicionados tipos/interfaces Python porque o gate de identidade acima não permite definir uma validação confiável que produza aceitação de endereço.

Para F2E.B, após resolver o gate, avaliar um boundary de provider injetável que não importe TinyTuya em testes e não leia arquivos padrão:

- `DiscoveryCandidate`: ID reportado, endereço textual, versão reportada e origem/anúncio; nenhum MAC, DPS, chave ou payload cru atravessa a fronteira.
- `DiscoveryProvider.discover(expected_device_id, budget)`: operação síncrona encapsulada em executor limitado; retorna candidatos brutos limitados ou erro normalizado. A implementação fake é determinística. Provider TinyTuya real não é permitido até que possa evitar `devices.json`, limitar duração e preservar todos os candidatos distintos necessários à detecção de ambiguidade.
- `RecoveryResult`: estados distintos `found`, `not_found`, `ambiguous`, `rejected` e `failed`; não carrega credenciais ou exceção original. `found` só pode ser construído por validador que produza evidência de identidade adequada, ainda não encontrada nesta investigação.
- Validar endereço com `ipaddress.IPv4Address`; rejeitar inválidos e endereços não utilizáveis conforme uma política LAN que ainda precisa ser aprovada. Exigir igualdade exata de Device ID entre consulta, anúncio e evidência validada; igualdade do anúncio sozinha não satisfaz a condição.
- Sem candidato, candidato inválido, timeout ou falha parcial: preservar endereço, adapter e status atuais. Mais de um candidato validado: retornar ambíguo sem escolher. Nenhum erro original/TinyTuya ou detalhe de chave deve ser publicado.
- Somente um candidato que passe validação de identidade e de IPv4 pode chegar a `update_address()`. Executar a recuperação sob coordenação do mesmo lock por Device ID desde a captura da configuração até aplicação, ou usar geração de configuração para descartar resultado atrasado. Um orçamento de lock que expire deve retornar falha sem mudança. Evitar lock global durante operação de dispositivo; scans simultâneos ainda precisariam de limite global explícito.
- Depois de `update_address()`, uma leitura normal é responsável por atualizar estado. Resposta de descoberta nunca confirma iluminação. A persistência continua somente em memória conforme a semântica existente.

Timeout total, quantidade máxima de candidatos, concorrência global e faixa de endereços aceitável permanecem valores de proposta a medir/revisar; não são decisões adotadas neste checkpoint.

## Alternativas e decisões em aberto

1. **Bloqueio principal — identidade:** definir evidência criptográfica de vínculo entre Device ID e endpoint para 3.3 e 3.5. Opções para discussão: limitar a feature a protocolos cuja identidade possa ser provada com desafio autenticado e vínculo estável; introduzir confirmação explícita do usuário que aceite risco residual (sem chamar isso de verificação automática); ou adiar a atualização de endereço até o protocolo/configuração oferecer identidade verificável. A resposta de status/DPS e um `gwId` de broadcast não são prova suficiente.
2. **API de descoberta:** criar wrapper próprio/fork ou solicitar ajuste upstream para busca restrita que não carregue o arquivo default, aceite budget/cancelamento e retorne todos candidatos. A chamada pública `find_device` não oferece esses controles.
3. **Faixa IPv4:** decidir se a aceitação futura exige IPv4 privado/unicast na LAN cadastrada ou apenas rejeita endereços especiais. Não escolher silenciosamente a política.
4. **Compatibilidade:** a faixa `>=1.20,<2` não foi validada a partir de uma única versão. Escolher entre fixar a dependência, limitar a faixa validada ou manter CI nas versões mínima e máxima compatíveis e falhar fechado diante de API alterada.
5. **Orçamentos:** medir broadcast em Windows com múltiplos adaptadores e decidir timeout, máximo de candidatos, concorrência global, cancelamento no encerramento e política de erros sem imprimir dados sensíveis.
6. **Protocolo:** tratamento específico para 3.3 (incluindo o caso pendente de 904 da Luz Escritório) precisa continuar distinto; 904 não prova IP incorreto, falha de identidade ou causa do problema físico.

## Proposta de F2E.B

1. Criar contratos internos e processador puro de anúncios com candidato explicitamente não verificado. Isso pode avançar sem resolver identidade porque não acessa nem altera `DeviceManager`.
2. Injetar provider pela interface tipada e exercitá-lo apenas com fake determinístico; preservar candidatos distintos, normalizar falha/timeout e provar ausência de socket, status ou escrita.
3. Não implementar nesta etapa o scanner TinyTuya REAL, validação de identidade ou aceitação/atualização de endereço. Não integrar CLI/JSONL, Rust/Tauri ou frontend.
4. Resolver o modelo de confiança por protocolo somente antes de qualquer camada futura que valide ou adote IP. Registrar decisões em `DECISIONS.md` apenas após aprovação explícita do mantenedor.

## Estratégia de testes proposta para F2E.B

- Provider fake: retorna zero, um ou múltiplos candidatos; verificar resultado exato sem depender de ordem.
- Candidate: rejeitar Device ID diferente, IPv6 e IPv4 malformado/especial conforme política aprovada; confirmar que nenhum caminho de rejeição chama `update_address()`.
- Validador fake: distinguir sucesso autenticado, falta de prova, resposta malformada, timeout e erro; DPS conhecidos sem prova devem ser rejeitados.
- Concorrência: manter descoberta em progresso enquanto comando/readback do mesmo ID tenta obter lock; provar ausência de troca tardia e independência para outro ID.
- Limites: budget expirado, limite de candidatos atingido e limite global ocupado resultam em falha segura, sem mudar endereço/configuração.
- Atualização: somente `found` validado chama `update_address()` uma vez; confirmar reconstrução do adapter e invalidação/retensão de estado conforme testes existentes.
- Garantia de isolamento: fakes não importam scanner TinyTuya nem criam socket; dados usam apenas identificadores fictícios e endereços reservados. Nenhum teste chama `update_address()`, `set_value()` ou `status()`.

## Critérios e bloqueios registrados ao encerrar F2E.A

- **Investigado:** versão instalada, assinaturas e caminhos de código descritos com fonte local; diferenças relevantes entre 3.3 e 3.4/3.5; riscos de broadcast, interfaces, timeout e arquivo default registrados.
- **Implementado:** somente documentação F2E.A. Nenhum contrato executável, provider, integração ou alteração de endereço foi implementado.
- **Testado:** somente revisão estática desta investigação e verificações documentais do worktree; nenhuma chamada de rede, scanner, status ou conexão executada. Testes backend não se aplicam porque nenhum Python foi alterado.
- **Bloqueio F2E.B:** falta prova demonstrada de vínculo entre Device ID esperado e endpoint, especialmente para 3.3; e falta um caminho de API que evite `devices.json` e limite completamente a descoberta.
- **Aceite para retomada:** revisão arquitetural do mantenedor, decisão explícita sobre identidade/protocolos e modo de descoberta, compatibilidade, faixa IPv4 e orçamentos. O plano não aprova por si só nenhuma dessas decisões.

## Referências

Código instalado localmente (TinyTuya 1.20.0; fonte primária usada nesta investigação):

- `tinytuya/core/XenonDevice.py`: `find_device` (linhas 27–65), construtor e descoberta automática (238–365), autenticação/parse de mensagens (aprox. 490–510, 780–815), `status()` (1069–1085) e payloads por versão (138–205, 1290–1375).
- `tinytuya/core/core.py`: wrappers públicos `scan`/`deviceScan` (228–251).
- `tinytuya/scanner.py`: enumeração de broadcast/interfaces (183–266), leitura de arquivo default (1131–1190), listeners/timeout (1196–1275), parse de UDP e agregação por ID (1532–1620, 1778–1795).
- `tinytuya/core/message_helper.py`: CRC/HMAC e autenticação AES-GCM em `pack_message`/`unpack_message` (28–176).
- `tinytuya/core/const.py`: tempos e portas padrão (6–11).

Fontes upstream fixadas:

- [XenonDevice.py — v1.20.0](https://github.com/jasonacox/tinytuya/blob/v1.20.0/tinytuya/core/XenonDevice.py)
- [scanner.py — v1.20.0](https://github.com/jasonacox/tinytuya/blob/v1.20.0/tinytuya/scanner.py)
- [API TinyTuya — referência atual, pode divergir da versão instalada](https://github.com/jasonacox/tinytuya/blob/master/API.md)

## Resumo para revisão arquitetural

F2E.A confirmou TinyTuya 1.20.0 e mapeou que `find_device()` é um scan síncrono com broadcast UDP, prazo padrão de 18 s sem override, resultado único e possível leitura incidental de `devices.json`. O anúncio `gwId` não autentica identidade; status 3.4/3.5 autentica posse da Local Key, mas a fonte não prova vínculo criptográfico com o Device ID, e 3.3 não usa HMAC no frame tradicional. A identidade bloqueia adoção automática ainda não aprovada, mas não bloqueia um provider isolado que só retorne candidatos.

## Revisão arquitetural F2E.A e checkpoint F2E.B

### Separação de responsabilidades

Descoberta de candidatos, validação de identidade e aceitação de endereço são camadas independentes. O provider e o processador F2E.B podem coletar/normalizar anúncios sem validar quem controla o IP. Um `DiscoveryCandidate` é uma pista não confiável; nenhum resultado desta camada significa `verified` ou `recovered`. A política de confiança bloqueia a adoção automática insegura, mas não impede um provider isolado que não conhece nem altera `DeviceManager`.

### Proposta de modelo de confiança por protocolo — não aprovada

As seguintes premissas e opções ficam para revisão do mantenedor; não são decisões arquiteturais aprovadas:

- Avaliar um threat model de LAN doméstica confiável, dispositivos previamente cadastrados e Local Keys individuais, não compartilhadas entre cadastros.
- Para Tuya 3.5, avaliar correspondência exata do Device ID anunciado combinada com negociação autenticada usando a Local Key configurada e readback válido. Isso indicaria posse da chave sob essas premissas, mas **não prova vínculo criptográfico independente entre a chave e o Device ID**.
- Para Tuya 3.3, manter política mais restritiva: confirmação manual de adoção ou nenhuma recuperação automática até haver evidência suficiente.
- Em qualquer versão, falha, timeout, anúncio conflitante, múltiplos IPs ou identidade insuficiente nunca aplicam endereço automaticamente. Uma confirmação manual também não deve ser descrita como prova criptográfica.

### Contratos e comportamento F2E.B implementados

`backend/src/smart_home_tray/discovery.py` contém:

- `DiscoveryAnnouncement`: allowlist imutável de Device ID, endereço textual e versão anunciada; sem MAC ou payload UDP bruto.
- `DiscoveryCandidate`: Device ID, IPv4 normalizado e conjunto ordenado de versões anunciadas para esse IP. Não contém credenciais ou campo de verificação.
- `DiscoveryProvider`: `Protocol` injetável que recebe o Device ID esperado e timeout explícito; nenhum provider TinyTuya REAL acompanha esta PR.
- `DiscoveryResult` com `NOT_FOUND`, `CANDIDATES`, `AMBIGUOUS` e `FAILED`, e falhas tipadas sem texto de exceção.
- `process_announcements()` e `discover_candidates()` fazem processamento puro e uma chamada ao provider, respectivamente. Nenhum deles recebe `DeviceManager` ou `TuyaAdapter`.

IDs divergentes são ignorados antes de examinar seu endereço. Anúncio malformado correspondente ao ID pedido faz o lote falhar sem resultado parcial. IPs IPv4 unspecified, loopback, multicast e limited broadcast são rejeitados; IPv6 e texto inválido também falham. A política não usa `is_private`/`is_global` e não declara que o IP está na sub-rede local. Duplicatas idênticas são colapsadas; IPs distintos permanecem todos no resultado `AMBIGUOUS`, ordenados numericamente, sem escolha pelo primeiro anúncio. Versões diferentes anunciadas para o mesmo IP são preservadas como metadados conflitantes e nunca autenticam identidade nem substituem a versão configurada.

O provider fake existe somente nos testes. Não há chamadas TinyTuya, sockets, status, `update_address()`, `set_value()`, retries, polling ou integração de produção. A suíte focada de descoberta passou com 27 testes determinísticos, sem depender do TinyTuya instalado ou da rede.

### Fora do escopo e condições de entrada da F2E.C

Esta PR não abre sockets, implementa scanner real, autentica endpoint, consulta DPS, decide sub-rede, modifica endereço em memória/TOML, expõe operação pela CLI/JSONL/Tauri/frontend ou habilita qualquer comportamento no startup/REAL. Nenhuma política de adoção foi aprovada.

Antes da F2E.C, revisar especificamente:

1. Um caminho de scanner TinyTuya que não carregue `devices.json` nem outro arquivo privado, não colapse candidatos e não dependa de `find_device()`/`deviceScan()` como contrato insuficiente.
2. Budget finito, cancelamento/encerramento, limite de candidatos e concorrência em Windows com múltiplas interfaces; valores devem ser justificados e aprovados, sem defaults arbitrários.
3. Política de identidade/adoção por protocolo, incluindo as premissas propostas para 3.5 e a regra mais restritiva para 3.3. Sem decisão, F2E.C pode ser limitada à observação de candidatos e não pode atualizar IP.
4. Testes padrão sempre fake; qualquer validação que possa tocar hardware permanece fora da suíte padrão e exige opt-in explícito do mantenedor.
