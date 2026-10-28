# Recuperação REAL da Luz Mesa por CLI restrita — desenho

## Intenção e decisão aprovada

Disponibilizar uma entrada manual específica para avaliar a recuperação REAL da Luz Mesa com duas autorizações independentes, reduzindo a possibilidade de enviar comandos físicos acidentalmente. A aprovação do desenho não autoriza execução REAL, acesso à LAN ou interação com dispositivos.

Alternativas avaliadas: `serve` interativo mantém o fluxo atual, mas aceita JSON arbitrário e comandos de iluminação, sem os gates REAL do desktop; o desktop possui esses gates, mas em modo REAL lê o estado de todas as entradas do catálogo e pode acessar a Luz Escritório. A opção aprovada é uma entrada dedicada que usa o serviço de recuperação existente, sem expor `serve`, JSON ou comandos de iluminação.

## Parser e despacho

Hoje `--config` é globalmente obrigatório e `main` chama `load_config(args.config)` antes de despachar a operação. Para conciliar os contratos, tornar `--config` opcional no parser e, imediatamente após o parsing, validar sua presença conforme a operação, antes de qualquer carregamento ou construção de serviço. Todos os subcomandos existentes continuam exigindo `--config` na posição global existente; sua ausência produz erro de argumento, e o caminho fornecido continua usado pelo carregamento genérico e pelo despacho atual.

Para `recover-luz-mesa`, rejeitar a presença de `--config` como erro de argumento, inclusive o valor vazio; argumentos extras ou `--config` após o subcomando também são rejeitados. Despachar essa operação antes de `load_config(args.config)` e da construção genérica de `DeviceManager`. A entrada dedicada obtém exclusivamente `SMART_HOME_TRAY_CONFIG`, valida gates e caminho absoluto existente, e só então chama o carregador com esse caminho. Erros de parser, gates ou seleção não criam serviço de recuperação nem iniciam rede. As chamadas antigas e o `serve` mantêm sua semântica existente.

## Limites e pré-requisitos

- Selecionar exatamente uma entrada com nome exato `Luz Mesa`, Device ID não vazio e protocolo numérico 3.5. Zero ou múltiplas entradas com esse nome, ID inválido ou protocolo diferente encerram antes de qualquer rede. Não inferir identidade pelo nome isoladamente: o operador ainda revisa o candidato.
- Exigir `SMART_HOME_TRAY_BACKEND_MODE=real`, `SMART_HOME_TRAY_ALLOW_REAL=1` e `SMART_HOME_TRAY_CONFIG` com caminho absoluto para arquivo existente, coerentes com o desktop. A nova entrada não deve aceitar uma configuração alternativa que contorne esses gates. Carregar a configuração normalmente, sem modificá-la.
- Informar que o carregador exige as variáveis de Local Key de todos os dispositivos no TOML. Nunca mostrar seus valores, o TOML, outros dispositivos, o Device ID completo ou o token. Saídas e erros devem ser sanitizados; não imprimir exceções ou entrada do usuário.
- Requerer console interativo de entrada e saída; rejeitar redirecionamentos e ausência de console antes de qualquer rede. Não fornecer flags para respostas, padrões de confirmação, execução não interativa ou entrada JSON. A checagem de console não prova presença humana nem impede automação de terminal; a autorização do operador continua necessária.
- Uma única tentativa por execução. Nenhuma escrita DPS, comando de iluminação, varredura genérica, cloud ou acesso dirigido à Luz Escritório. A descoberta escuta anúncios UDP na LAN, que podem incluir outros dispositivos, mas apenas um candidato do ID selecionado pode passar à validação TCP.

## Fluxo

1. Antes de criar qualquer operação de rede, mostrar o alvo, protocolo e efeitos da preparação: descoberta UDP e eventual leitura TCP autenticada. Solicitar a frase exata `PREPARAR LUZ MESA`; outra resposta, EOF ou interrupção encerra sem preparar.
2. Executar `prepare_internal` uma vez. Reutilizar os limites, exclusão mútua, validação autenticada e critérios de candidato único e anúncio 3.5 do serviço existente. Falha, ambiguidade ou protocolo inesperado encerra sem confirmação.
3. Para uma proposta válida, mostrar somente alvo, protocolo, IPv4 candidato, tempo restante estimado e aviso de que a autenticação comprova posse da chave, não identidade física independente. Manter o token exclusivamente em memória; não gravar ou exibir. A proposta existente tem TTL de 60 s medido pelo relógio monotônico do serviço, não renovado pela interface.
4. Pausar para revisão e solicitar a frase independente exata `CONFIRMAR LUZ MESA`. Só essa resposta, antes do prazo monotônico original, permite chamar `confirm_internal` com o token em memória. Usar espera interativa com prazo no Windows, para que expiração, EOF ou interrupção encerrem sem exigir outra entrada. Não aceitar confirmação antecipada ou reaproveitada da primeira etapa. A validade final continua sob autoridade do serviço.
5. Confirmar uma única vez. O serviço revalida por leitura autenticada, adota o endereço em memória quando suas guardas passam e faz readback separado. Mostrar `ADOPTED` e o status do readback separadamente, sem mostrar o snapshot. `FAILED`, `SUPERSEDED`, snapshot ausente, resultado indeterminado ou erro exige parada; adoção pode já ter ocorrido. Não repetir automaticamente.
6. Ao recusar, expirar, interromper ou terminar, fechar o serviço, invalidar propostas de sua propriedade e drenar o scheduler conforme lifecycle existente. Não alegar cancelamento de I/O já iniciado ou prazo rígido para chamadas nativas bloqueadas. A adoção é apenas neste processo, não persiste no TOML e não se transfere ao desktop; ao encerrar, perde-se o endereço adotado.

Parar também em erro 904 quando observável, falha de autenticação/transporte, timeout, mudança física ou anomalia. Erros sanitizados podem não distinguir 904; ausência desse número não é prova de ausência do erro. A ferramenta não observa automaticamente alterações físicas: essa decisão cabe ao operador.

## Estrutura e aceite

Nova implementação em `backend/src/smart_home_tray/mesa_recovery_cli.py`, integrada por uma suboperação específica em `backend/src/smart_home_tray/cli.py`, com testes em `backend/tests/test_mesa_recovery_cli.py`. Manter `serve`, protocolos públicos e desktop sem mudança comportamental. Interfaces de console, relógio e serviço devem permitir fakes, sem conectar sockets nos testes.

Aceite: gates e seleção falham sem rede; frases são independentes; proposta expira mesmo durante espera; nenhum token, segredo, ID completo ou dados de outros dispositivos aparece na saída; somente prepare e confirm são invocados; nenhuma entrada arbitrária alcança iluminação; todos os caminhos encerram corretamente e distinguem adoção de readback. Testes usam fakes e bloqueio de rede; nenhuma execução REAL decorre deste desenho.
