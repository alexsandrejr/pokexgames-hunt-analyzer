# PokeXGames Hunt Analyzer

Aplicação desktop para **armazenar, organizar e analisar** as sessões de Hunt exportadas em JSON ou TSV pelo Analyzer do jogo PokeXGames.

Cada arquivo importado vira um **registro histórico permanente** no banco SQLite local, com seus inimigos derrotados, drops e supplies em tabelas relacionadas. O JSON original é sempre preservado por completo (um TSV é guardado já convertido para JSON, com todas as seções), então campos novos que o Analyzer venha a adicionar não se perdem.

> **Versão 2.0.0, em Rust.** A versão 1.x era em Python e foi reescrita em Rust (Tauri), com as mesmas funcionalidades, o mesmo banco e a mesma atualização automática. O histórico da migração está em [docs/migracao-rust.md](docs/migracao-rust.md).
>
> **Funcionalidades:** Importação (arquivos, pastas, arrastar e soltar ou texto colado), duplicidade, filtros combináveis e pesquisa avançada, Início com gráficos, Relatórios, relatórios por item e por inimigo, sessões por tipo de boss (Rifts, bosses de Energia Vermelha e Azul e Terrors, separados das Hunts), recompensas do chat ("Você recebeu:") somadas às sessões, comparação de Hunts, preços personalizados de itens (recalculam Raw gains, Supplies e Profit de todas as Hunts), página DPS (ranking de pokémons por boss com tempo limite, calculado por Efetividade, Dummy ou Dano real), exportação (CSV, Excel, PDF, JSON), backup e restauração, tema claro/escuro e formato de números configurável.

## Baixar

**[⬇ Baixar a versão mais recente (Windows)](https://github.com/alexsandrejr/pokexgames-hunt-analyzer/releases/latest)**: baixe o arquivo `.zip`, extraia e abra `PokeXGames Hunt Analyzer.exe`. Não precisa instalar nada: o programa usa o Microsoft Edge WebView2, que já vem no Windows 11 e no Windows 10 atualizado. O `LEIA-ME.txt` dentro do `.zip` explica o resto.

## Tecnologias

| Tecnologia | Uso |
|---|---|
| Rust (edição 2024) | Regras, banco, importação, exportação e atualização (`rust/core`) |
| Tauri 2 | Janela do programa e ligação entre o Rust e as telas (`rust/app/src-tauri`) |
| Svelte 5 + TypeScript (Vite) | Telas (`rust/app/src`), com os gráficos desenhados em SVG |
| SQLite (rusqlite) | Banco de dados local (`hunts.db`) |
| rust_xlsxwriter | Exportação para Excel (.xlsx) |
| WebView2 | Mostra as telas e imprime o PDF da exportação |

## Instalação (para desenvolver)

Pré-requisitos:

- Rust, pelo [rustup](https://rustup.rs). O `cargo` fica em `%USERPROFILE%\.cargo\bin`.
- Node.js 20 ou mais novo.

Dependências das telas, uma vez:

```powershell
cd rust/app
npm install
```

## Execução

A partir de `rust/app`:

```powershell
npx tauri dev
```

Em desenvolvimento, os dados ficam em `rust/data/` (banco, backups, configurações e logs), criados na primeira execução. Para abrir outro banco, defina `PXG_HUNTS_DB` (veja [Banco de dados](#banco-de-dados)).

## Gerar o executável (para distribuir)

A partir de `rust/`:

```powershell
node tools/build_exe.mjs
```

O script leva de 7 a 13 minutos. Ele confere se a versão é a mesma no `tauri.conf.json` e no `Cargo.toml`, compila, **abre o executável gerado para testá-lo** (`--smoke-test`, com dados temporários, sem tocar nos seus) e **testa a instalação de uma atualização** a partir do próprio `.zip`, por cima de uma cópia antiga. Se um teste falhar, o `.zip` é apagado.

| Saída | Para quê |
|---|---|
| `rust/dist/PokeXGames Hunt Analyzer/PokeXGames Hunt Analyzer.exe` | Executável, com o `LEIA-ME.txt` ao lado |
| `rust/dist/PokeXGames-Hunt-Analyzer-<versão>-windows.zip` | **O arquivo para enviar aos colegas** |

`node tools/build_exe.mjs --skip-test` pula os testes; não publique esse `.zip`.

**No executável**, os dados de cada usuário ficam em `%LOCALAPPDATA%\PokeXGames Hunt Analyzer` (banco, backups, configurações, `imports/` e `logs/app.log`). Atualizar o programa não apaga nada. **Modo portátil:** se existir uma pasta `data` ao lado do `.exe`, tudo passa a ficar nela. O cache do WebView2 fica em `%LOCALAPPDATA%\pokexgames.hunt-analyzer`, também no modo portátil.

Erros inesperados (das telas e do Rust) são gravados em `logs/app.log`, que o usuário pode enviar para você.

> O `.exe` não tem assinatura digital, então o Windows SmartScreen avisa na primeira execução ("Mais informações" → "Executar assim mesmo"). O `LEIA-ME.txt` explica isso aos colegas.

## Navegação

A barra lateral tem as quatro seções de trabalho, as Configurações no rodapé e o botão **Importar**, sempre visível. O número da versão, no rodapé, abre a janela Sobre.

| Seção | Conteúdo |
|---|---|
| **Início** | Visão geral: cards, resumo por categoria e gráficos |
| **Sessões** | **Todas**, **Hunts**, **Rifts**, **Energia Vermelha**, **Energia Azul** e **Terrors**, escolhidos nos botões do topo, com a quantidade de sessões |
| **Análise** | **Relatórios**, **Itens**, **Inimigos** e **Preços**, escolhidos nos botões do topo |
| **DPS** | Abas **Ranking** e **Pokémons** |
| **Configurações** | Tema, formato de números, banco de dados e backups |

Ao voltar a Sessões ou Análise, abre a última página usada ali. Nas listas de sessões, **Detalhes**, **Comparar**, **Mover** e **Excluir** só aparecem quando há uma seleção que permite usá-los. Atalhos: `Ctrl+I` importa arquivos, `Ctrl+Shift+I` importa uma pasta, `Ctrl+Shift+V` cola texto, `F5` atualiza a página e `Ctrl+Q` fecha o app.

## Como importar uma Hunt

1. No jogo, exporte a sessão pelo Analyzer (é gerado um arquivo `.json`).
2. No aplicativo, clique em **Importar → Arquivos JSON/TSV…** (`Ctrl+I`), na barra lateral.
3. Selecione um ou **vários** arquivos. A pasta `imports/` dos dados é aberta por padrão. O repositório tem um exemplo em `imports/exemplo_hunt_1080.json`.
4. As Hunts importadas aparecem selecionadas em **Sessões → Hunts**. Dê **duplo clique** (ou `Enter`) para abrir os detalhes.

### Importar vários de uma vez

- **Pasta**: **Importar → Pasta inteira…** (`Ctrl+Shift+I`) importa todos os `.json` da pasta e das subpastas.
- **Arrastar e soltar**: arraste arquivos `.json` ou pastas inteiras para qualquer ponto da janela.

Na importação de vários arquivos, as Hunts já importadas são **ignoradas sem perguntar**. Com 5 arquivos ou mais aparece uma barra de progresso, que permite cancelar. No fim, um resumo mostra quantas foram importadas, ignoradas por duplicidade e com erro, com o motivo de cada arquivo. Um arquivo único continua perguntando: **Cancelar** ou **Importar mesmo assim**.

### Colar o JSON (sem arquivo)

Use **Importar → Colar texto…** (`Ctrl+Shift+V`) e cole o texto copiado do Analyzer. O conteúdo é validado enquanto você cola: o diálogo mostra a Hunt reconhecida (ID, player, data, duração e profit) ou o erro, e o botão **Importar** só fica ativo com um JSON válido.

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
2. **Tipo aberto**: importar (arquivo, pasta, arrastar e soltar ou colar) com um tipo de boss aberto em **Sessões** grava as sessões nele.
3. **Boss já conhecido**: se todos os inimigos da sessão já apareceram só em sessões de um mesmo tipo de boss, ela vai para lá sozinha, mesmo importada com outra página aberta.
4. Caso contrário, a sessão é uma **Hunt**.

Errou a categoria? Selecione as sessões e use **Mover**, em qualquer lista da seção Sessões. As sessões antigas continuam como Hunts até serem movidas.

JSONs de boss colados são salvos na subpasta da categoria (ex.: `imports/terrors/hunt_651_2026-10-04_13-04-54.json`), então reimportar a pasta `imports/` mantém cada sessão no lugar certo.

Cada tipo de boss tem:

- **Resumo**: cards com sessões, kills, tempo total e tempo por kill, profit e profit por kill, Profit/h (total ÷ tempo e média das sessões), supplies e experience por kill, Damage dealt/s e Damage taken/s; tabelas de bosses derrotados, drops mais valiosos e **dano por elemento** (causado e recebido, da seção `Damage` do JSON); e gráficos por sessão (Profit, Profit/h, Duração e Damage dealt/s) a partir de 2 sessões.
- **Lista**: a mesma lista de Hunts (pesquisa, detalhes, comparação, exclusão, exportação), só com as sessões daquele tipo de boss.

Em **Sessões**, **Todas** mostra todas as categorias, com uma coluna Categoria, e **Hunts** mostra só Hunts. O **Início** tem um seletor de categoria que começa em **Hunts e bosses**, para o dinheiro dos bosses entrar na visão geral, e um **Resumo por categoria** com cada tipo que tem sessões. **Relatórios**, **Itens** e **Inimigos** têm o mesmo seletor no topo (Hunts, Todos os bosses, um tipo de boss ou Hunts e bosses), que começa em Hunts para os bosses não misturarem as médias.

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

- **Bosses**: cada boss tem nome e tempo limite (o boss **Padrão**, de 7 minutos, já vem criado). Não têm relação com os tipos de boss da seção Sessões. O seletor da aba **Ranking** escolhe o boss, e o app lembra o último usado. Em **Gerenciar bosses → Novo/Editar boss** também ficam os elementos dele (só informativos) e a efetividade de cada ataque contra ele, copiada da Pokédex do jogo; o que não for marcado conta como Normal. Os elementos e a efetividade aparecem no Ranking como etiquetas com as cores dos tipos. **Adicionar pokémon** abre a lista para marcar quem pode lutar contra ele.
- **Calcular por**: seletor do Ranking, salvo em cada boss, que define de onde vem o dano de cada skill e do básico. Todos os pokémons do boss usam a mesma opção. Veja a tabela abaixo.
- **Pokémons**: a aba **Pokémons** lista todos os cadastrados, com pesquisa e as skills do selecionado, e é onde ficam **Novo**, **Editar**, **Duplicar** e **Excluir**. Um pokémon novo nasce sem boss. No Ranking, **Editar** (ou o duplo clique) abre a edição, e **Remover** tira o pokémon do boss sem apagar o cadastro. O cadastro tem nome, observação, ataque básico, buff e skills, com elemento opcional no básico e em cada skill (usado só no cálculo por Efetividade). O dano não é digitado no cadastro: lá ele só aparece, conforme o dummy escolhido em **Ver dano no dummy**. Cada skill tem forma (Área ou Target), alcance (Melee ou Ranged), dano, recarga e aproveitamento. **Duplicar** serve para comparar builds, ou o mesmo pokémon com danos diferentes em dois bosses.
- **Ranking**: só os pokémons anexados ao boss, com dano total e DPS no tempo limite, com barra proporcional ao 1º colocado. À direita aparece quanto cada skill, o básico e o buff somam ao total.
- **Testes**: na aba **Pokémons**, o botão **Testes** registra os danos medidos nos dummies do jogo (Neutro ou um dos 18 elementos) e dentro dos bosses cadastrados (**Boss: nome**). Cada skill e o ataque básico podem ter um teste por dummy e por boss, com até 3 danos e a média dos preenchidos. O que não foi testado onde o boss pede conta como **0** e aparece com o aviso "sem teste", sem usar outro teste como substituto. Excluir um boss apaga os testes feitos nele. Tudo é gravado ao trocar de skill e ao fechar a janela. **Duplicar** copia os testes com as datas deles, e remover uma skill apaga os dela. Cada teste mostra as datas de **Cadastrado** e **Modificado**, para perceber quando uma medição está desatualizada. Modificado só muda quando os danos mudam; trocar o dummy ou o boss de um teste cria um teste novo. Testes de antes da versão 1.6.0 ficam sem data de cadastro.
- **Exportar e importar**: **Exportar cadastros** abre uma lista para marcar bosses e pokémons (todos começam marcados) e salva um arquivo `.json` para enviar a um colega ou guardar. **Importar cadastros** valida o arquivo inteiro e mostra uma prévia, sem gravar nada até a confirmação. Cadastro novo entra por padrão. Em nome repetido, o padrão é **Pular**, e dá para escolher **Substituir** ou **Criar cópia** (`Nome (importado)`). Veja [Exportar e importar cadastros](#exportar-e-importar-cadastros).
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

### Exportar e importar cadastros

O arquivo traz, de cada boss, o nome, o tempo limite, o Calcular por, o dummy, os elementos e a efetividade; de cada pokémon, a ficha, a observação, os testes com as datas e os nomes dos bosses em que está anexado. Os **Ajustes** da página são de cada pessoa e ficam de fora. Os bosses são citados pelo nome, sem diferenciar maiúsculas, porque os ids mudam de um banco para outro.

| Escolha | Boss | Pokémon |
|---|---|---|
| **Pular** | Não muda nada. Os pokémons do arquivo que citam esse nome são anexados ao boss daqui | Não muda nada |
| **Substituir** | Troca tempo, Calcular por, dummy, elementos e efetividade. Mantém os pokémons anexados e os testes | Troca a ficha, a observação e **todos os testes** pelos do arquivo. Mantém o id e os bosses que já tinha, e soma os do arquivo |
| **Criar cópia** | Cria `Nome (importado)`, e os pokémons do arquivo apontam para a cópia | Cria `Nome (importado)` |

Regras da importação:

- Com alguma substituição, o app faz antes um backup "Antes de importar". Se o backup falhar, nada é importado.
- Tudo é gravado em uma única transação: se algo falhar, nada muda.
- Um teste feito em um boss que não veio no arquivo e não existe no banco fica de fora, assim como o vínculo com esse boss. O app informa quantos ficaram de fora.
- Os testes mantêm as datas originais, porque a medição continua sendo a mesma.
- Arquivo de uma versão mais nova do formato é recusado, com uma mensagem.

## Funcionalidades

- **Filtros** (no topo do Início, das listas de Sessões, de Relatórios, Itens e Inimigos): um único filtro vale para todas essas páginas. Veja [Filtros](#filtros).
- **Início**: seletor de categoria (começa em Hunts e bosses; também Hunts, Todos os bosses ou um tipo de boss); cards em destaque com profit, Profit/h médio, Kills/h médio e tempo total, e menores com sessões analisadas, kills, supplies e raw gains; **Resumo por categoria**, com profit, sessões, kills, tempo e Profit/h de cada categoria com sessões, aparecendo só quando há mais de uma (com os filtros, independente do seletor); e 8 gráficos por sessão em ordem cronológica: Profit/h, Kills/h, Profit, Supplies/h, Damage dealt/s, Damage taken/s, Kills e Duração. Passe o mouse para ver o valor; clique em uma barra para abrir a sessão. Os gráficos aparecem a partir de 2 sessões, e com mais de 60 viram linha. O resumo detalhado de cada boss fica na seção Sessões, explicada em [Bosses](#bosses).
  O **Profit/h médio** (média simples dos Profit/h de cada Hunt) é exibido separado do **Profit total ÷ tempo total** (ponderado pela duração).
- **Listas de sessões**: tabela ordenável por qualquer coluna, pesquisa rápida, seleção múltipla, detalhes, **comparação**, exclusão (`Del`) e exportação.
- **Comparação**: selecione 2 ou mais Hunts (`Ctrl`+clique ou `Shift`+clique) e clique em **Comparar**. As métricas ficam nas linhas e as Hunts nas colunas, lado a lado, em ordem cronológica e sem ranking. Pode ser exportada.
- **Itens** e **Inimigos**: escolha um drop, supply ou inimigo para ver quantidade total, valor total, presença (em quantas Hunts apareceu), média por Hunt e por hora, valor médio, maior e menor quantidade, gráfico por Hunt e a lista das Hunts em que apareceu. As médias consideram as Hunts em que o item apareceu; no gráfico, as Hunts em que ele não apareceu ficam como barras vazias.
- **Relatórios**: tabela de métricas (duração, kills, profit, supplies, raw gains, experience, damage dealt/taken) com total, média por Hunt, mínimo, máximo, **média das taxas** e **total ÷ tempo total**, mais rankings (top 25) de drops por valor, supplies por custo e inimigos por quantidade.
- **Detalhes da Hunt**: abas *Resumo*, *Enemies*, *Drops* (com valor total, quantidade e origem: Analyzer ou [chat](#recompensas-do-chat)), *Supplies* (com custo total), *Gráficos* (inimigos, drops e supplies em barras ordenadas) e *JSON Original* (formatado, somente leitura, com botão de cópia). Abre num diálogo por cima da lista, uma sessão por vez.
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

O botão **Exportar** (menu com os formatos) existe nas listas de sessões, em Relatórios, Itens e Inimigos e na janela de Comparação. Sempre exporta o que está na tela: as Hunts filtradas e pesquisadas, na ordem exibida, ou o relatório com os filtros atuais, descritos no próprio arquivo.

| Formato | Conteúdo |
|---|---|
| CSV | Separador `;`, vírgula decimal e UTF-8 com BOM (abre direto no Excel em português). Relatórios com várias tabelas viram seções no mesmo arquivo |
| Excel (.xlsx) | Uma aba por tabela, com números reais, formato de milhar, datas e durações `[h]:mm:ss` (somáveis no Excel) e cabeçalho fixo |
| PDF | Tabelas formatadas como na tela, em tema claro para impressão (A4, paisagem para tabelas largas) |
| JSON | Valores brutos: durações em segundos (chaves com sufixo ` (s)`), datas em ISO 8601 |

## Configurações e backup

As preferências ficam em `settings.json`, na pasta dos dados. Se o arquivo estiver ausente ou corrompido, o app usa os padrões.

| Opção | Efeito |
|---|---|
| Tema | Escuro ou claro, aplicado na hora |
| Formato de números | `1.234.567,89` (pt-BR) ou `1,234,567.89` (en-US). Vale na hora para as telas, os valores digitados nos filtros e o CSV (pt-BR: `;` e vírgula decimal; en-US: `,` e ponto) |
| Banco de dados | **Usar outro banco…** abre um arquivo existente ou cria um novo; **Voltar ao banco padrão** volta para o `hunts.db` da pasta dos dados. Aplicado ao reiniciar, com o botão **Reiniciar agora**. A variável `PXG_HUNTS_DB` tem prioridade |
| Atualizações | **Verificar se há versão nova ao abrir o aplicativo** (ligado por padrão) e **Verificar agora**. Veja [Atualização do programa](#atualização-do-programa) |
| Backup automático | Ao abrir o app, no máximo um por dia (e só se houver Hunts), mantendo os últimos N (padrão 10) |

**Backups** ficam em `backups/`, ao lado do banco. São cópias consistentes feitas pela API de backup do SQLite, e podem ser criadas com o app aberto.

- **Fazer backup agora** grava na pasta de backups; **Salvar cópia em…** grava onde você escolher (ex.: nuvem ou pendrive).
- **Restaurar selecionado** / **Restaurar de arquivo…**: o arquivo é validado antes (precisa ser um banco deste app), e o banco atual é **sempre** salvo como backup "Antes de restaurar" antes de ser substituído. Backups de versões antigas são atualizados automaticamente.
- Só os backups automáticos são apagados pela rotação; manuais, "antes de restaurar" e "antes de atualizar" são mantidos.

### Atualização do banco

O esquema tem versão (`PRAGMA user_version`). Ao abrir um banco de uma versão anterior, o app faz um backup "Antes de atualizar" e aplica as migrações pendentes. Bancos criados por uma versão **mais nova** do app são recusados, com uma mensagem, para evitar perda de dados.

## Atualização do programa

No `.exe`, o app consulta o último release do GitHub 3 segundos depois de abrir, sem travar a janela. Sem internet, nada aparece. Se houver versão nova, a janela mostra as novidades e **Atualizar agora**: nada é instalado sem confirmação. Em desenvolvimento (`npx tauri dev`), o app não verifica ao abrir, e **Verificar agora** oferece só o link para a página.

1. A versão atual baixa o `.zip` para `updates/`, na pasta de dados, e confere o tamanho e o SHA-256 informados pelo GitHub.
2. Ela extrai o pacote, abre o `.exe` novo com `--apply-update <pasta> <pid>` e fecha.
3. O `.exe` novo espera a versão atual fechar, copia os arquivos para dentro da pasta do programa, troca os antigos pelos novos e abre o programa. Se algo falhar, devolve os antigos.

Só os arquivos que vêm no pacote são trocados: a pasta `data` do modo portátil e outros arquivos ao lado do `.exe` ficam intactos. Abrir uma versão nova limpa o que sobrou em `updates/`. O banco é migrado ao abrir, com o backup de sempre.

**Para publicar uma versão:** mude a versão em `rust/Cargo.toml` (`[workspace.package]`) e em `rust/app/src-tauri/tauri.conf.json`, gere o `.zip` com `node tools/build_exe.mjs`, que também testa a instalação de uma atualização a partir dele, e anexe-o a um release com a tag `vX.Y.Z`. O app só oferece a instalação se o arquivo se chamar `PokeXGames-Hunt-Analyzer-X.Y.Z-windows.zip`, se o release não for rascunho nem pré-lançamento e se a tag for maior que a versão instalada. Publicar um release, portanto, oferece a atualização a todos.

Quem está em uma versão anterior à 1.6.0 precisa baixar a versão nova manualmente uma vez, porque as versões antigas não têm o atualizador. A 1.6.0 (em Python) se atualiza sozinha para a 2.0.0 (em Rust): o `.exe` novo aceita o mesmo `--apply-update` e apaga a pasta `_internal` que sobrava do Python.

## Estrutura

```text
pokexgames-hunt-analyzer/
├── rust/
│   ├── Cargo.toml               # Workspace e versão do programa
│   ├── core/                    # pxg-core: regras e banco, sem nenhuma dependência do Tauri
│   │   ├── src/
│   │   │   ├── config.rs        # Caminhos por modo (desenvolvimento, .exe, portátil)
│   │   │   ├── db/              # Abertura, esquema (sql/schema_models.sql) e migrações
│   │   │   ├── hunts/           # Leitura do Analyzer (JSON e TSV), importação, filtros, pesquisa avançada, estatísticas, categorias e chat
│   │   │   ├── dps/             # Conta do DPS, cadastro, ranking e exportar/importar cadastros
│   │   │   ├── export/          # Documentos exportáveis e escrita de CSV, Excel e JSON (e o HTML do PDF)
│   │   │   ├── backup.rs        # Backup, rotação e restauração
│   │   │   ├── prices.rs        # Preços personalizados
│   │   │   ├── settings.rs      # Preferências (settings.json)
│   │   │   ├── update.rs        # Verificar, baixar e instalar versões do GitHub
│   │   │   ├── logging.rs       # Log em arquivo (logs/app.log)
│   │   │   └── format.rs, parse.rs, text.rs  # Números, datas e textos como o jogo escreve
│   │   ├── sql/                 # DDL das tabelas
│   │   ├── examples/            # Utilitários de linha de comando (ex.: extract_package, usado no build)
│   │   └── tests/               # Testes do núcleo, com fixtures
│   ├── app/
│   │   ├── src-tauri/           # pxg-app: abertura, comandos chamados pelas telas, PDF e instalação
│   │   ├── src/                 # Telas em Svelte: App.svelte, pages/, components/ e lib/
│   │   └── LEIA-ME.txt          # Instruções que vão dentro do .zip
│   └── tools/                   # build_exe.mjs, e cdp.mjs e capture_window.ps1 para testar na janela
├── docs/                        # Efetividade dos elementos no jogo e o histórico da migração
├── data/                        # Dados locais (não versionado)
└── imports/                     # JSONs do Analyzer (só o exemplo é versionado)
```

Fluxo de dependências (as telas nunca executam SQL):

```text
Telas (Svelte) → comandos (pxg-app) → serviços (pxg-core) → repositórios → SQLite
```

## Banco de dados

Arquivo padrão: o `hunts.db` da pasta dos dados (`rust/data/` em desenvolvimento). Para usar outro arquivo sem alterar código, defina a variável de ambiente `PXG_HUNTS_DB`:

```powershell
$env:PXG_HUNTS_DB = "C:\caminho\outro.db"; npx tauri dev
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
| `dps_damage_tests` | `pokemon_id`, `skill_id` (vazio = ataque básico), `dummy` (`boss` em teste dentro do boss), `boss_id`, `damage_1` a `damage_3`, `created_at` (vazio = anterior ao registro de datas), `updated_at` (vazio = nunca modificado) | `pokemon_id`, `skill_id`, `boss_id` |
| `dps_boss_pokemons` | `boss_id`, `pokemon_id` (quem pode lutar contra cada boss) | (`boss_id`, `pokemon_id`), `pokemon_id` |
| `dps_settings` | Turno do básico, aproveitamentos sugeridos e `last_boss_id` | — |

As tabelas filhas usam `ON DELETE CASCADE`: excluir uma Hunt remove seus inimigos, drops, supplies e recompensas do chat.

Backups e restauração são feitos em **Configurações** (veja [Configurações e backup](#configurações-e-backup)).

## Como desenvolver

A partir de `rust/`:

```powershell
cargo test                    # testes do núcleo e dos comandos
cargo clippy --all-targets    # avisos
cd app; npm run check         # tipos das telas (svelte-check)
```

Os testes cobrem: JSON e TSV válidos, inválidos e incompletos; importação por arquivo e por texto colado; duplicidade; exclusão em cascata; cálculos de duração, dinheiro e estatísticas; cada critério de filtro contra o SQLite real; pesquisa avançada; relatórios por item e inimigo; cada formato de exportação (gravado e lido de volta); migrações; backup, rotação e restauração; configurações e formato de números; recompensas do chat; a conta do DPS (com a conferência da lista do colega), as três opções de Calcular por e os testes de dano; a atualização (verificação, download, extração e troca de arquivos); o log; e a validação dos diálogos. O `--smoke-test` do build abre o programa e visita todas as páginas.

### Suportar um novo campo do Analyzer

1. Adicione a coluna em `rust/core/sql/schema_models.sql` (bancos novos) e o campo em `ParsedSession` (`rust/core/src/hunts/analyzer.rs`), na lista de campos da seção `Session`.
2. Para bancos existentes, adicione uma `Migration` no fim de `MIGRATIONS` (`rust/core/src/db/migrations.rs`), por exemplo `ALTER TABLE hunt_sessions ADD COLUMN ...`, com SQL idempotente. Ela é aplicada (com backup antes) na próxima abertura. A próxima é a 11.

Hunts antigas continuam com o JSON original completo em `raw_json`, então os valores novos podem ser reprocessados a partir dele.

### Pontos de extensão já preparados

- **Filtros**: `HuntFilter` aceita qualquer número de condições de item, inimigo e métrica. Uma métrica filtrável nova é uma entrada em `Metric` (e um apelido na pesquisa avançada).
- **Exportação**: qualquer tela pode exportar montando um `ExportDocument` (tabelas com valores brutos e o tipo de cada coluna) no Rust e usando o `ExportButton` nas telas.
- **Tabelas**: o componente `RecordTable` serve para qualquer listagem, com ordenação, pesquisa e seleção.

## Roadmap

- Substituir uma Hunt reimportada (sessão "Active" exportada de novo com mais dados) em vez de só duplicar.
- Assinatura digital do `.exe` (remove o aviso do SmartScreen) e instalador.
- Mostrar uma mensagem com o caminho do log quando acontece um erro inesperado (o Python mostrava; em Rust o erro só vai para o log).
