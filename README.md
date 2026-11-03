# PokeXGames Hunt Analyzer

Aplicação desktop para **armazenar, organizar e analisar** as sessões de Hunt exportadas em JSON ou TSV pelo Analyzer do jogo PokeXGames.

Cada arquivo importado vira um **registro histórico permanente** no banco SQLite local, com seus inimigos derrotados, drops e supplies em tabelas relacionadas. O JSON original é sempre preservado por completo (um TSV é guardado já convertido para JSON, com todas as seções), então campos novos que o Analyzer venha a adicionar não se perdem.

> **Status: Fases 1 a 4 concluídas.** Importação (arquivos, pastas, arrastar e soltar ou texto colado), duplicidade, filtros combináveis e pesquisa avançada, Dashboard com gráficos, Relatórios, relatórios por item e por inimigo, página Bosses (Rifts, bosses de Energia Vermelha e Azul e Terrors, separados das Hunts), recompensas do chat ("Você recebeu:") somadas às sessões, comparação de Hunts, preços personalizados de itens (recalculam Raw gains, Supplies e Profit de todas as Hunts), página DPS (ranking de pokémons por boss com tempo limite, calculado por Efetividade, Dummy ou Dano real), exportação (CSV, Excel, PDF, JSON), backup e restauração, tema claro/escuro e formato de números configurável.

## Baixar

**[⬇ Baixar a versão mais recente (Windows)](https://github.com/alexsandrejr/pokexgames-hunt-analyzer/releases/latest)**: baixe o arquivo `.zip`, extraia e abra `PokeXGames Hunt Analyzer.exe`. Não precisa instalar Python. O `LEIA-ME.txt` dentro do `.zip` explica o resto.

## Tecnologias

| Tecnologia | Uso |
|---|---|
| Python 3.12 | Linguagem principal |
| PySide6 (Qt 6) | Interface gráfica |
| SQLAlchemy 2 | ORM sobre o SQLite |
| SQLite | Banco de dados local (`data/hunts.db`) |
| pyqtgraph | Gráficos |
| openpyxl | Exportação para Excel (.xlsx) |
| unittest | Testes automatizados (biblioteca padrão) |
| PyInstaller | Geração do executável (só para quem gera o build) |

## Instalação

Pré-requisito: Python 3.12 (verifique com `py -0p`).

```powershell
python -m venv .venv
```

Ativação no Windows:

```bat
.venv\Scripts\activate
```

> No PowerShell use `.venv\Scripts\Activate.ps1`. Se a política de execução bloquear, rode diretamente `.venv\Scripts\python.exe`.

Instalação das dependências:

```powershell
pip install -r requirements.txt
```

## Execução

A partir da raiz do projeto, com o ambiente ativado:

```powershell
python main.py
```

Na primeira execução o banco `data/hunts.db` é criado automaticamente.

## Gerar o executável (para distribuir)

Com o ambiente ativado, instale as ferramentas de build uma vez e rode o script:

```powershell
pip install -r requirements-dev.txt
python scripts/build_exe.py
```

O script gera o ícone e os metadados do `.exe`, empacota com o PyInstaller, **abre o executável gerado para testá-lo** (`--smoke-test`, com dados temporários, sem tocar nos seus) e compacta tudo:

| Saída | Para quê |
|---|---|
| `dist/PokeXGames Hunt Analyzer/PokeXGames Hunt Analyzer.exe` | Executável (pasta com as bibliotecas ao lado) |
| `dist/PokeXGames-Hunt-Analyzer-<versão>-windows.zip` | **O arquivo para enviar aos colegas**, com um `LEIA-ME.txt` |

`python scripts/build_exe.py --onefile` gera um único `.exe`. É mais simples de enviar, mas cada abertura demora alguns segundos (ele se descompacta a cada vez) e antivírus costumam desconfiar mais desse formato. Por isso o padrão é pasta + `.zip`.

**No executável**, os dados de cada usuário ficam em `%LOCALAPPDATA%\PokeXGames Hunt Analyzer` (banco, backups, configurações, `imports/` e `logs/app.log`). Atualizar o programa (trocar a pasta pela versão nova) não apaga nada. **Modo portátil:** se existir uma pasta `data` ao lado do `.exe`, tudo passa a ficar nela.

Erros inesperados são gravados em `logs/app.log` e mostrados numa mensagem com o caminho do arquivo, que o usuário pode enviar para você.

> O `.exe` não tem assinatura digital, então o Windows SmartScreen avisa na primeira execução ("Mais informações" → "Executar assim mesmo"). O `LEIA-ME.txt` explica isso aos colegas.

## Como importar uma Hunt

1. No jogo, exporte a sessão pelo Analyzer (é gerado um arquivo `.json`).
2. No aplicativo, use **Hunts → Importar JSON…** (`Ctrl+I`) ou o botão **Importar JSON** da página Hunts.
3. Selecione um ou **vários** arquivos. A pasta `imports/` do projeto é aberta por padrão e contém um exemplo (`exemplo_hunt_1080.json`).
4. As Hunts importadas aparecem selecionadas na página Hunts. Dê **duplo clique** (ou `Enter`) para abrir os detalhes.

### Importar vários de uma vez

- **Pasta**: **Hunts → Importar pasta…** (`Ctrl+Shift+I`) ou o botão **Importar pasta** importa todos os `.json` da pasta e das subpastas.
- **Arrastar e soltar**: arraste arquivos `.json` ou pastas inteiras para qualquer ponto da janela.

Na importação de vários arquivos, as Hunts já importadas são **ignoradas sem perguntar**. Com 5 arquivos ou mais aparece uma barra de progresso, que permite cancelar. No fim, um resumo mostra quantas foram importadas, ignoradas por duplicidade e com erro, com o motivo de cada arquivo. Um arquivo único continua perguntando: **Cancelar** ou **Importar mesmo assim**.

### Colar o JSON (sem arquivo)

Use **Hunts → Colar JSON…** (`Ctrl+Shift+V`) ou o botão **Colar JSON** da página Hunts e cole o texto copiado do Analyzer. O conteúdo é validado enquanto você cola: o diálogo mostra a Hunt reconhecida (ID, player, data, duração e profit) ou o erro, e o botão **Importar** só fica ativo com um JSON válido.

Ao importar, o texto também é **salvo como arquivo** em `imports/`, com o nome `hunt_<SessionID>_<AAAA-MM-DD_HH-MM-SS>.json` (ex.: `hunt_1080_2026-09-26_15-24-20.json`). Esse nome fica registrado como arquivo de origem da Hunt.

- Arquivos existentes nunca são sobrescritos: se o nome já existir, é usado `_2`, `_3`…
- O arquivo só é criado se a Hunt for realmente gravada. JSON inválido ou duplicidade cancelada não deixam arquivos para trás.

### Validação e erros

| Situação | Comportamento |
|---|---|
| Arquivo não é JSON válido | Mensagem **"JSON inválido."** e nada é gravado |
| JSON sem seção `Session` utilizável | **"O arquivo não possui uma sessão válida do Analyzer."** |
| Campos ausentes, `null` ou com tipo inesperado | Viram vazio (`—`) sem interromper a importação |
| Taxa por hora ausente (ex.: `Profit per hour`) | Calculada a partir do total e da duração |
| Registros inválidos em `Drops`/`Supplies`/`Enemies Defeated` | Ignorados, com aviso ao final |
| Campos desconhecidos | Preservados no JSON original |

### Duplicidade

Uma Hunt é considerada já importada quando:

- o **conteúdo** do JSON é idêntico (hash SHA-256 do JSON canônico, que ignora espaços e ordem das chaves), **ou**
- a combinação **`Session ID` + player + início** coincide com uma Hunt existente (cobre a mesma sessão exportada novamente mais tarde).

O `Session ID` sozinho não é usado, pois não há garantia de que seja único. Ao detectar duplicidade, o app pergunta: **Cancelar** ou **Importar mesmo assim**.

O JSON do Analyzer não traz o player na seção `Session`. Ele é obtido do campo `Player` das listas. Em sessões com vários players, os nomes ficam unidos por vírgula.

## Bosses

Além das Hunts, o app separa os quatro tipos de boss do PokeXGames: **Rifts**, **Energia Vermelha**, **Energia Azul** e **Terrors**. O JSON exportado pelo Analyzer é o mesmo de uma Hunt, então cada sessão recebe uma **categoria** ao ser importada:

1. **Pasta do arquivo**: arquivos em `imports/rifts/`, `imports/energia_vermelha/`, `imports/energia_azul/` ou `imports/terrors/` entram na categoria da pasta.
2. **Aba aberta**: importar (arquivo, pasta, arrastar e soltar ou colar) com uma aba da página **Bosses** aberta grava as sessões naquele tipo de boss.
3. **Boss já conhecido**: se todos os inimigos da sessão já apareceram só em sessões de um mesmo tipo de boss, ela vai para lá sozinha, mesmo importada fora da página Bosses.
4. Caso contrário, a sessão é uma **Hunt**.

Errou a categoria? Selecione as sessões e use **Mover** (na página Hunts ou em qualquer aba de Bosses). As sessões antigas continuam como Hunts até serem movidas.

JSONs de boss colados são salvos na subpasta da categoria (ex.: `imports/terrors/hunt_651_2026-10-04_13-04-54.json`), então reimportar a pasta `imports/` mantém cada sessão no lugar certo.

Cada aba de Bosses tem:

- **Resumo**: cards com sessões, kills, tempo total e tempo por kill, profit e profit por kill, Profit/h (total ÷ tempo e média das sessões), supplies e experience por kill, Damage dealt/s e Damage taken/s; tabelas de bosses derrotados, drops mais valiosos e **dano por elemento** (causado e recebido, da seção `Damage` do JSON); e gráficos por sessão (Profit, Profit/h, Duração e Damage dealt/s) a partir de 2 sessões.
- **Sessões**: a mesma lista da página Hunts (pesquisa, detalhes, comparação, exclusão, exportação), só com as sessões daquele tipo de boss.

A página **Hunts** mostra só Hunts. O **Dashboard** tem um seletor de categoria que começa em **Hunts e bosses**, para o dinheiro dos bosses entrar na visão geral, e um **Resumo por categoria** com cada tipo separado. **Relatórios**, **Itens** e **Inimigos** têm o mesmo seletor no topo (Hunts, Todos os bosses, um tipo de boss ou Hunts e bosses), que começa em Hunts para os bosses não misturarem as médias.

## Recompensas do chat

Algumas recompensas (bosses, Secret Lab, Subject 14, Tentacruel Chosen…) vêm numa sacola aberta depois: os itens aparecem só no chat e **não entram no JSON** do Analyzer. Para somá-los à sessão:

1. Abra os detalhes da sessão e clique em **Recompensas do chat…**.
2. Cole as mensagens do chat, uma por linha (linhas com horário ou outras falas são ignoradas):

   ```text
   Você recebeu: 15 Echo Shards, 2 Mystic Stars, 84 hundred dollars, 4 Heart Stones.
   Você recebeu: 1 giant fang, 1 Water Stone, 2 Shiny Tentacruel tentacles.
   ```

3. Confira a prévia e clique em **Adicionar à sessão**.

Na prévia:

- O nome do chat é aproximado do item já conhecido no banco, sem diferenciar maiúsculas e tirando o plural: `Echo Shards` → `Echo Shard`, `hundred dollars` → `one hundred dollars`. Nomes nunca vistos ficam em destaque, e plurais desconhecidos vão para o singular (`big poison bottles` → `big poison bottle`). **Dê duplo clique no nome para corrigir.**
- Um item repetido em várias mensagens vira uma linha só, somada.
- O preço é o personalizado (página **Preços**) ou o do Analyzer na Hunt mais recente com o item. Itens sem preço entram com valor 0 até você definir um preço, que recalcula a sessão normalmente.
- Colar de novo uma mensagem já adicionada à sessão gera um aviso (somaria os itens duas vezes).

Os itens viram drops da sessão com **Origem: Chat** na aba *Drops*, e **Raw gains** e **Profit** (e as taxas por hora) sobem com o valor deles. Eles entram em Relatórios, Itens, filtros e na página Preços como qualquer drop. O JSON original não é alterado. **Remover do chat** tira todos os drops vindos do chat e volta os totais.

## DPS

A página **DPS** compara o dano dos pokémons em bosses com tempo limite. Ela não usa as sessões importadas: tudo é cadastrado à mão e fica no mesmo banco, então entra nos backups.

- **Bosses**: cada boss tem nome e tempo limite (o boss **Padrão**, de 7 minutos, já vem criado). O seletor da aba **Ranking** escolhe o boss, e o app lembra o último usado. Em **Bosses → Novo/Editar boss** também ficam os elementos dele (só informativos) e a efetividade de cada ataque contra ele, copiada da Pokédex do jogo; o que não for marcado conta como Normal. **Adicionar** abre a lista para marcar quem pode lutar contra ele, e **Remover** tira o pokémon sem apagar o cadastro.
- **Calcular por**: seletor do Ranking, salvo em cada boss, que define de onde vem o dano de cada skill e do básico. Todos os pokémons do boss usam a mesma opção. Veja a tabela abaixo.
- **Pokémons**: a aba **Pokémons** lista todos os cadastrados, com pesquisa e as skills do selecionado, e é onde ficam **Novo**, **Editar**, **Duplicar** e **Excluir**. Um pokémon novo nasce sem boss. No Ranking, o duplo clique também abre a edição. O cadastro tem nome, observação, ataque básico, buff e skills, com elemento opcional no básico e em cada skill (usado só no cálculo por Efetividade). O dano não é digitado no cadastro: lá ele só aparece, conforme o dummy escolhido em **Ver dano no dummy**. Cada skill tem forma (Área ou Target), alcance (Melee ou Ranged), dano, recarga e aproveitamento. **Duplicar** serve para comparar builds, ou o mesmo pokémon com danos diferentes em dois bosses.
- **Ranking**: só os pokémons anexados ao boss, com dano total e DPS no tempo limite, com barra proporcional ao 1º colocado. À direita aparece quanto cada skill, o básico e o buff somam ao total.
- **Testes**: na aba **Pokémons**, o botão **Testes** registra os danos medidos nos dummies do jogo (Neutro ou um dos 18 elementos) e dentro dos bosses cadastrados (**Boss: nome**). Cada skill e o ataque básico podem ter um teste por dummy e por boss, com até 3 danos e a média dos preenchidos. O que não foi testado onde o boss pede conta como **0** e aparece com o aviso "sem teste", sem usar outro teste como substituto. Excluir um boss apaga os testes feitos nele. Tudo é gravado ao trocar de skill e ao fechar a janela. **Duplicar** copia os testes, e remover uma skill apaga os dela.
- **Ajustes**: turno do ataque básico (2,5 s, vale para todos os pokémons) e os aproveitamentos sugeridos em novos cadastros (Target + Melee 75%, demais skills 100%, ataque básico 75%).

De onde vem o dano, conforme o **Calcular por** do boss:

| Opção | Dano usado | Sem dado |
|---|---|---|
| **Efetividade** | teste no dummy Neutro × multiplicador do elemento do golpe contra o boss | golpe sem teste no Neutro ou sem elemento conta como 0, com aviso |
| **Dummy** (padrão) | teste no dummy escolhido no boss | sem teste nesse dummy conta como 0, com aviso |
| **Dano real** | teste feito dentro daquele boss, sem multiplicador (ele já inclui a efetividade) | sem teste nesse boss conta como 0, com aviso |

Multiplicadores da efetividade (valores de PvE): Super Efetivo 2x, Efetivo 1,75x, Normal 1x, Inefetivo 0,75x, Muito Inefetivo 0,5x e Nulo 0x. Bosses do Nightmare World, onde o Nulo vale 0,5x, podem ser marcados como Muito Inefetivo. Mais detalhes em [docs/efetividade-pxg.md](docs/efetividade-pxg.md).

O dano é uma estimativa média, sem simular a luta (animações e deslocamento ficam de fora):

```text
skill         = dano ÷ recarga × tempo × aproveitamento
básico        = dano ÷ turno × tempo × aproveitamento
buff (básico) = básico × (duração ÷ recarga do buff) × (multiplicador − 1)
buff (magia)  = dano × aproveitamento × (multiplicador − 1) × tempo ÷ maior recarga entre a magia e o buff
DPS           = total ÷ tempo
```

Cada pokémon tem no máximo um buff. O bônus na próxima magia usa a magia que mais rende, supondo que ela é guardada para o buff, já considerando a efetividade. Boost e held não entram na conta: anote na observação as condições do teste.

## Funcionalidades

- **Filtros** (no topo do Dashboard, Hunts, Bosses e Relatórios): um único filtro vale para todas essas páginas. Veja [Filtros](#filtros).
- **Dashboard**: seletor de categoria (começa em Hunts e bosses; também Hunts, Todos os bosses ou um tipo de boss); cards com sessões analisadas, tempo total, kills, profit, Profit/h médio, Kills/h médio, supplies e raw gains; **Resumo por categoria**, com profit, sessões, kills, tempo e Profit/h de Hunts, Rifts, Energia Vermelha, Energia Azul e Terrors (com os filtros, independente do seletor); e 8 gráficos por sessão em ordem cronológica: Profit/h, Kills/h, Profit, Supplies/h, Damage dealt/s, Damage taken/s, Kills e Duração. Passe o mouse para ver o valor; clique em uma barra para abrir a sessão. Os gráficos aparecem a partir de 2 sessões, e com mais de 60 viram linha. O resumo detalhado de cada boss fica na página [Bosses](#bosses).
  O **Profit/h médio** (média simples dos Profit/h de cada Hunt) é exibido separado do **Profit total ÷ tempo total** (ponderado pela duração).
- **Hunts**: tabela ordenável por qualquer coluna, pesquisa rápida, seleção múltipla, detalhes, **comparação**, exclusão (`Del`), exportação e atualização (`F5`).
- **Comparação**: selecione 2 ou mais Hunts (`Ctrl`+clique ou `Shift`+clique) e clique em **Comparar**. As métricas ficam nas linhas e as Hunts nas colunas, lado a lado, em ordem cronológica e sem ranking. Pode ser exportada.
- **Itens** e **Inimigos**: escolha um drop, supply ou inimigo para ver quantidade total, valor total, presença (em quantas Hunts apareceu), média por Hunt e por hora, valor médio, maior e menor quantidade, gráfico por Hunt e a lista das Hunts em que apareceu. As médias consideram as Hunts em que o item apareceu; no gráfico, as Hunts em que ele não apareceu ficam como barras vazias.
- **Relatórios**: tabela de métricas (duração, kills, profit, supplies, raw gains, experience, damage dealt/taken) com total, média por Hunt, mínimo, máximo, **média das taxas** e **total ÷ tempo total**, mais rankings (top 25) de drops por valor, supplies por custo e inimigos por quantidade.
- **Detalhes da Hunt**: abas *Resumo*, *Enemies*, *Drops* (com valor total, quantidade e origem: Analyzer ou [chat](#recompensas-do-chat)), *Supplies* (com custo total), *Gráficos* (inimigos, drops e supplies em barras ordenadas) e *JSON Original* (formatado, somente leitura, com botão de cópia). Várias Hunts podem ficar abertas ao mesmo tempo.
- **DPS**: ranking dos pokémons em um boss com tempo limite, com cadastro e testes de dano. Veja [DPS](#dps).
- **Preços**: define um preço próprio para qualquer item, que vale para todas as Hunts e recalcula Raw gains, Supplies e Profit.
- **Configurações**: tema claro ou escuro, formato de números, banco de dados em uso e backups. Veja [Configurações e backup](#configurações-e-backup).

## Filtros

Clique em **Filtros** para abrir o painel. Todos os critérios são combinados com **E** (a Hunt precisa atender a todos), e campos vazios não filtram. Depois de preencher, use **Aplicar filtros** (ou `Enter`). **Limpar** remove todos os critérios.

| Critério | Como funciona |
|---|---|
| Período | Todo o período, hoje, últimos 7/30 dias, este mês, mês passado ou datas personalizadas (dias inclusivos) |
| Player | Contém o texto, sem diferenciar maiúsculas |
| Inimigo | A Hunt derrotou esse inimigo; com quantidade, compara o total (ex.: `Mecha Charizard >= 40`) |
| Item | Drop ou supply presente; com quantidade, compara o total (ex.: `nightmare ore > 50`). Hunts sem o item contam como 0 |
| Profit, Profit/h, Kills, Kills/h, Duração | Operadores `>`, `>=`, `=`, `<=`, `<` |

### Pesquisa avançada

O campo **Avançada** do painel aceita várias condições em texto, combinadas com as demais (E):

```text
nightmare ore > 50 e nightmare gem > 1000
Mecha Charizard >= 40; profit/h >= 800k; duração >= 1h30
supply: Healing Elixir > 5 & kills/h > 300
```

- Separadores: `e`, `and`, `;` ou `&`.
- Operadores: `>`, `>=`, `=`, `<=`, `<` (também `≥` e `≤`). Sem operador, basta o item ou inimigo aparecer na Hunt.
- Métricas: `profit`, `profit/h`, `kills`, `kills/h`, `duração`, `supplies`, `supplies/h`, `raw gains`, `raw gains/h`.
- Sem prefixo, o nome é procurado nos drops, depois nos inimigos e nos supplies já importados (sem diferenciar maiúsculas). Para forçar o tipo, use `drop:`, `supply:` ou `inimigo:`.
- Nomes desconhecidos, valores inválidos ou métricas sem operador são apontados em vermelho e o filtro não é aplicado.

Valores aceitam a notação do jogo: `800k`, `1,2kk`, `1.5kk`, `1.000.000`. A duração aceita `1:30` (h:mm), `90` (minutos), `1h30` ou `45min`. No operador `=` sobre taxas (ex.: Profit/h), vale o valor arredondado exibido na tabela.

## Exportação

O botão **Exportar** (menu com os formatos) existe nas páginas Hunts, Relatórios, Itens e Inimigos e na janela de Comparação. Sempre exporta o que está na tela: as Hunts filtradas e pesquisadas, na ordem exibida, ou o relatório com os filtros atuais, descritos no próprio arquivo.

| Formato | Conteúdo |
|---|---|
| CSV | Separador `;`, vírgula decimal e UTF-8 com BOM (abre direto no Excel em português). Relatórios com várias tabelas viram seções no mesmo arquivo |
| Excel (.xlsx) | Uma aba por tabela, com números reais, formato de milhar, datas e durações `[h]:mm:ss` (somáveis no Excel) e cabeçalho fixo |
| PDF | Tabelas formatadas como na tela, em tema claro para impressão (A4, paisagem para tabelas largas) |
| JSON | Valores brutos: durações em segundos (chaves com sufixo ` (s)`), datas em ISO 8601 |

## Configurações e backup

As preferências ficam em `data/settings.json` (não versionado). Se o arquivo estiver ausente ou corrompido, o app usa os padrões.

| Opção | Efeito |
|---|---|
| Tema | Escuro ou claro. Aplicado ao reiniciar; o botão **Reiniciar agora** faz isso na hora |
| Formato de números | `1.234.567,89` (pt-BR) ou `1,234,567.89` (en-US). Vale na hora para as telas, os valores digitados nos filtros e o CSV (pt-BR: `;` e vírgula decimal; en-US: `,` e ponto) |
| Banco de dados | **Usar outro banco…** abre um arquivo existente ou cria um novo; **Voltar ao banco padrão** volta para `data/hunts.db`. Aplicado ao reiniciar. A variável `PXG_HUNTS_DB` tem prioridade |
| Backup automático | Ao abrir o app, no máximo um por dia (e só se houver Hunts), mantendo os últimos N (padrão 10) |

**Backups** ficam em `backups/`, ao lado do banco (`data/backups/` no padrão). São cópias consistentes feitas pela API de backup do SQLite, e podem ser criadas com o app aberto.

- **Fazer backup agora** grava na pasta de backups; **Salvar cópia em…** grava onde você escolher (ex.: nuvem ou pendrive).
- **Restaurar selecionado** / **Restaurar de arquivo…**: o arquivo é validado antes (precisa ser um banco deste app), e o banco atual é **sempre** salvo como backup "Antes de restaurar" antes de ser substituído. Backups de versões antigas são atualizados automaticamente.
- Só os backups automáticos são apagados pela rotação; manuais, "antes de restaurar" e "antes de atualizar" são mantidos.

### Atualização do banco

O esquema tem versão (`PRAGMA user_version`). Ao abrir um banco de uma versão anterior, o app faz um backup "Antes de atualizar" e aplica as migrações pendentes. Bancos criados por uma versão **mais nova** do app são recusados, com uma mensagem, para evitar perda de dados.

## Estrutura

```text
pokexgames-hunt-analyzer/
├── main.py                      # Ponto de entrada (--smoke-test: abre, visita as telas e fecha)
├── scripts/
│   ├── build_exe.py             # Gera o executável + .zip para distribuir
│   └── LEIA-ME.txt              # Instruções que vão dentro do .zip
├── app/
│   ├── application.py           # Montagem: banco + serviços + tema + janela
│   ├── config.py                # Caminhos por modo (desenvolvimento, .exe, portátil)
│   ├── logging_setup.py         # Log em arquivo e aviso de erros inesperados
│   ├── database/
│   │   ├── database.py          # Engine, sessões, criação do esquema
│   │   ├── models.py            # HuntSession, EnemyDefeated, Drop, Supply, ItemPrice, ChatReward, tabelas Dps*
│   │   ├── migrations.py        # Versões do esquema e migrações
│   │   ├── query_filters.py     # Tradução de HuntFilter em condições SQL
│   │   └── repositories.py      # TODAS as consultas SQL ficam aqui
│   ├── services/
│   │   ├── json_importer.py     # Leitura, validação e extração do JSON (sem banco)
│   │   ├── hunt_service.py      # Importação (arquivo ou texto colado), duplicidade, consulta, exclusão
│   │   ├── json_files.py        # Salva JSON colado como arquivo (nome sugerido, sem sobrescrever)
│   │   ├── chat_rewards.py      # Lê "Você recebeu: ..." do chat e aproxima os nomes dos itens
│   │   ├── categories.py        # Categorias: Hunt, Rift, Energia Vermelha/Azul, Terror
│   │   ├── filters.py           # HuntFilter e condições (sem SQL, sem interface)
│   │   ├── advanced_search.py   # Pesquisa avançada em texto → condições do filtro
│   │   ├── entity_report.py     # Relatório de um item/inimigo ao longo das Hunts
│   │   ├── rates.py             # Taxas por hora/segundo
│   │   ├── export_service.py    # Escrita de CSV, Excel, PDF e JSON
│   │   ├── export_documents.py  # Tabelas exportáveis (Hunts, relatório, comparação…)
│   │   ├── backup_service.py    # Backup, rotação e restauração do banco
│   │   ├── dps_calculator.py    # Conta do dano estimado (funções puras)
│   │   ├── dps_service.py       # Bosses, pokémons e ranking da página DPS
│   │   ├── settings_service.py  # Preferências (data/settings.json)
│   │   ├── statistics_service.py# Totais, médias, taxas, métricas e rankings
│   │   └── dto.py               # Objetos trocados entre serviços e interface
│   ├── ui/
│   │   ├── main_window.py       # QMainWindow + menu + navegação
│   │   ├── sidebar.py           # Barra lateral
│   │   ├── theme.py             # Temas escuro e claro (paleta + QSS)
│   │   ├── icons.py             # Ícones SVG de resources/icons
│   │   ├── import_controller.py # Fluxo de importação na interface
│   │   ├── charts/              # Gráficos pyqtgraph (por Hunt e barras ordenadas)
│   │   ├── filters/             # Estado do filtro + painel de filtros
│   │   ├── dashboard/           # Página Dashboard
│   │   ├── bosses/              # Página Bosses (uma aba por tipo de boss)
│   │   ├── dps/                 # Página DPS (abas Ranking e Pokémons, cadastro e testes)
│   │   ├── hunts/               # Lista de Hunts, detalhes, comparação e colar JSON
│   │   ├── items/               # Páginas Itens e Inimigos
│   │   ├── prices/              # Página Preços
│   │   ├── reports/             # Página Relatórios
│   │   ├── settings/            # Configurações
│   │   └── widgets/             # Tabela genérica, cards, combos, botão Exportar
│   └── utils/
│       ├── constants.py         # Nomes e chaves do JSON do Analyzer
│       ├── formatters.py        # 1.119.522 · 01:11:50 · 119,5 M
│       └── validators.py        # Conversões seguras (to_int, parse_datetime…)
├── docs/                        # Efetividade de elementos no jogo
├── data/                        # hunts.db (não versionado)
├── imports/                     # Pasta sugerida para os JSONs
├── resources/icons/             # Ícones SVG
└── tests/                       # Testes automatizados
```

Fluxo de dependências (a interface nunca executa SQL):

```text
UI (PySide6) → Services → Repositories → SQLAlchemy → SQLite
```

## Banco de dados

Arquivo padrão: `data/hunts.db`. Para usar outro arquivo sem alterar código, defina a variável de ambiente `PXG_HUNTS_DB`:

```powershell
$env:PXG_HUNTS_DB = "C:\caminho\outro.db"; python main.py
```

| Tabela | Conteúdo | Índices |
|---|---|---|
| `hunt_sessions` | Métricas da seção `Session`, `category` (hunt, rift, boss_red, boss_blue, terror), `raw_json` (texto original), `content_hash`, `source_file`, `created_at` | `session_id`, `player`, `start_datetime`, `category`, `content_hash`, (`session_id`, `player`, `start_datetime`) |
| `enemies_defeated` | `enemy`, `count`, `player`, `rare`, `ignored` | `hunt_id`, `enemy` |
| `drops` | `item`, `count`, `unit_price`, `total_price`, `original_unit_price`, `original_total_price`, `player`, `ignored`, `chat_reward_id` (drops vindos do chat) | `hunt_id`, `item`, `chat_reward_id` |
| `supplies` | mesmas colunas de `drops`, sem `chat_reward_id` | `hunt_id`, `item` |
| `chat_rewards` | `hunt_id`, `text` (mensagens "Você recebeu:" coladas), `created_at` | `hunt_id` |
| `dps_bosses` | `name`, `time_limit_seconds`, `damage_source` (Calcular por), `dummy`, `element_1`, `element_2` | — |
| `dps_boss_effectiveness` | `boss_id`, `element`, `level` (só o que difere de Normal) | (`boss_id`, `element`) |
| `dps_pokemons` | `name`, `note`, ataque básico (`basic_efficiency`, `basic_element`) e buff (`buff_*`) | — |
| `dps_skills` | `pokemon_id`, `position`, `name`, `shape`, `reach`, `cooldown`, `efficiency`, `element` | `pokemon_id` |
| `dps_damage_tests` | `pokemon_id`, `skill_id` (vazio = ataque básico), `dummy` (`boss` em teste dentro do boss), `boss_id`, `damage_1` a `damage_3` | `pokemon_id`, `skill_id`, `boss_id` |
| `dps_boss_pokemons` | `boss_id`, `pokemon_id` (quem pode lutar contra cada boss) | (`boss_id`, `pokemon_id`), `pokemon_id` |
| `dps_settings` | Turno do básico, aproveitamentos sugeridos e `last_boss_id` | — |

As tabelas filhas usam `ON DELETE CASCADE`: excluir uma Hunt remove seus inimigos, drops, supplies e recompensas do chat.

Backups e restauração são feitos em **Configurações** (veja [Configurações e backup](#configurações-e-backup)).

## Como desenvolver

Rodar todos os testes (incluindo o teste de fumaça da interface, que roda sem abrir janelas):

```powershell
python -m unittest discover -s tests -t .
```

Os testes cobrem: JSON válido, inválido e incompleto; importação por arquivo e por texto colado; duplicidade (conteúdo idêntico, re-exportação, forçar importação); exclusão em cascata; persistência em arquivo; cálculos de duração, dinheiro e estatísticas; cada critério de filtro e suas combinações contra o SQLite real; pesquisa avançada; relatórios por item/inimigo; cada formato de exportação (gravado e lido de volta); migrações; backup, rotação e restauração; configurações e formato de números; leitura das mensagens do chat e recompensas somadas e removidas das sessões; importação de pastas e arrastar e soltar; a conta do DPS (com a conferência da lista do colega), as três opções de Calcular por, os testes de dano e a migração dos bancos antigos; e os fluxos da interface (painel de filtros, Dashboard, Relatórios, comparação, Itens, Inimigos, detalhes e DPS).

### Suportar um novo campo do Analyzer

1. Adicione a coluna em `HuntSession` (`app/database/models.py`) e o atributo em `ParsedSession`.
2. Adicione uma linha em `SESSION_FIELDS` (`app/services/json_importer.py`) com a chave do JSON e o conversor.
3. Para bancos existentes, adicione uma `Migration` no fim de `MIGRATIONS` (`app/database/migrations.py`), por exemplo `ALTER TABLE hunt_sessions ADD COLUMN ...`. Ela é aplicada (com backup antes) na próxima abertura.

Hunts antigas continuam com o JSON original completo em `raw_json`, então os valores novos podem ser reprocessados a partir dele.

### Pontos de extensão já preparados

- **Filtros**: `HuntFilter` aceita qualquer número de condições de item, inimigo e métrica. Uma métrica filtrável nova é uma entrada em `Metric` (e um apelido em `METRIC_ALIASES` para a pesquisa avançada).
- **Exportação**: qualquer tela pode exportar montando um `ExportDocument` (tabelas com valores brutos e o tipo de cada coluna) e usando `ExportButton`.
- **Tabelas**: `RecordTable` + `Column` servem para qualquer listagem, como relatórios e comparação.

## Roadmap

- Substituir uma Hunt reimportada (sessão "Active" exportada de novo com mais dados) em vez de só duplicar.
- Assinatura digital do `.exe` (remove o aviso do SmartScreen) e instalador.
