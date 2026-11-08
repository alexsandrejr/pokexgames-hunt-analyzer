# PokeXGames Hunt Analyzer

App desktop Windows (Rust, Tauri 2, Svelte 5 + TypeScript, SQLite) que guarda as sessões exportadas pelo Analyzer do jogo PokeXGames e compara o dano de pokémons em bosses com tempo limite. O dono joga PokeXGames, usa o app e o distribui para colegas.

Até a 1.6.0 o app era em Python (PySide6). A 2.0.0 é a reescrita em Rust, e o Python foi apagado no corte (2026-11-08). O histórico, as decisões da migração e os pontos de atenção estão em [docs/migracao-rust.md](docs/migracao-rust.md). Para ver o código Python, use o git (`main` ou o commit `b9b194e`).

Escreva em português do Brasil: conversa, interface, comentários, docstrings, commits e documentação. Nomes de identificadores ficam em inglês.

Consulte o [README.md](README.md) para instalação, funcionalidades de cada página, build do `.exe`, tabelas do banco e como suportar um novo campo do Analyzer. Atualize-o junto com cada funcionalidade.

## Comandos

O `cargo` fica em `%USERPROFILE%\.cargo\bin`; acrescente essa pasta ao `PATH` se o terminal não a tiver.

```bash
cd rust && cargo test                        # suíte do núcleo e dos comandos
cd rust && cargo test -p pxg-core --test dps_calculator   # um arquivo de testes
cd rust && cargo clippy --all-targets        # avisos: precisa sair limpo
cd rust/app && npm run check                 # tipos das telas (svelte-check)
cd rust/app && PXG_HUNTS_DB=<cópia.db> npx tauri dev       # abre o app em desenvolvimento
cd rust && node tools/build_exe.mjs          # .exe e .zip em rust/dist/, já testados; 7 a 13 min: rode em segundo plano
```

## Antes de dar uma tarefa por concluída

Rode `cargo test`, `cargo clippy --all-targets` e `npm run check`. Para mudanças de tela, rode também o `node tools/build_exe.mjs`, que faz o `--smoke-test` no binário de release: em 2026-11-08, ele achou um laço em Preços que nenhum teste pegava.

Para mudanças de tela, gere capturas e olhe nas duas larguras (1320×820 e o mínimo, 980×620) e nos dois temas. Veja [Capturas e testes na janela](#capturas-e-testes-na-janela).

## Dados reais

- O dono usa o `.exe`, com o banco real em `%LOCALAPPDATA%\PokeXGames Hunt Analyzer\hunts.db` (copiado de `data/hunts.db` em 2026-11-08). **Nunca abra esse banco em teste.** Teste em uma cópia, numa pasta temporária, apontada por `PXG_HUNTS_DB`.
- `data/` na raiz é a cópia antiga do Python (banco e backups), fora do git. Também não teste nele.
- Em desenvolvimento, o app usa `rust/data/` (banco, configurações, logs e backups).
- Abrir o app migra o banco, com backup automático em `backups/`, ao lado dele. Um banco migrado é recusado por versões mais antigas (`Error::SchemaTooNew`).

## Arquitetura

```text
Telas (Svelte, rust/app/src) → comandos (pxg-app, rust/app/src-tauri) → serviços (pxg-core) → repositórios → SQLite
```

- `rust/core` (`pxg-core`): regras de negócio e banco, sem nenhuma dependência do Tauri. Erros para o usuário são `Error::user("mensagem em português")`, já prontos para mostrar.
- SQL fica só nos repositórios de cada área (`hunts/repository.rs`, `dps/repository.rs`, `prices.rs`, `backup.rs`).
- `rust/app/src-tauri` (`pxg-app`): comandos chamados pelas telas (`commands/`), as vistas prontas para a tela (`sessions.rs`, `analysis.rs`, `dashboard.rs`, `charts.rs`, `view.rs`), a validação dos diálogos (`forms.rs`), o PDF (`pdf.rs`) e a instalação da atualização (`install.rs`). Comando novo entra no `generate_handler!` de `lib.rs`.
- `rust/app/src`: telas. A navegação fica em `App.svelte` (`items` tem as seções da barra lateral; `analysisPages` e `sessionPages`, a sub-navegação; `show` aceita seção, página ou `boss:<categoria>`). Página nova entra também na lista do `runSmokeTest`, em `App.svelte`.
- As telas chamam o Rust pelo `invoke` de `lib/diagnostics.ts`, nunca pelo de `@tauri-apps/api/core`: ele conta as chamadas para o `--smoke-test`.
- Ícones: `rust/app/src/assets/icons`, SVGs desenhados com o traço `#aeb6c4`, que `Icon.svelte` troca pela cor do texto.

## Convenções

- **Banco:** o esquema de um banco novo está em `rust/core/sql/schema_models.sql`. Coluna nova, coluna apagada ou dado inicial exige também uma `Migration` no fim de `MIGRATIONS` (`core/src/db/migrations.rs`), com SQL idempotente: bancos novos também rodam todas as migrações. A próxima é a 11. Testes de migração usam `LATEST_VERSION`, nunca um número fixo.
- **Fração x porcentagem:** aproveitamentos são guardados como fração de 0 a 1, e só a interface fala em %.
- **Números digitados:** `parse::parse_user_number` aceita `14k`, `1,2kk` e `1.000.000`. Para preencher um campo, use `format::format_plain`, que devolve um texto que o parser lê de volta no formato ativo. Para exibir, use `format_number` e `format_money`. O formato (pt-BR/en-US) é passado em cada chamada (`state.number_format()`).
- **Arredondamento e textos:** siga os pontos de atenção de [docs/migracao-rust.md](docs/migracao-rust.md#pontos-de-atenção) (`round_half_even`, `py_strip`, `casefold`, hash canônico). Eles mantêm o resultado igual ao das versões em Python, inclusive a detecção de duplicidade.
- **Tabelas:** use o componente `RecordTable`, com `fit` nas colunas que não podem ser cortadas.
- **Cores:** use os tokens de `rust/app/src/app.css`, redefinidos no tema claro. O dono usa o tema claro; o padrão é o escuro. Vermelho e verde indicam prejuízo e lucro, então a cor forte fica nas etiquetas de elemento (`element_color`, em `view.rs`), iguais nos dois temas. Só o botão principal usa `--primary`, escolhido pelo contraste com o texto branco.
- **Ações de lista:** as que dependem de seleção só aparecem quando podem ser usadas.
- **Diálogos com validação:** as telas mandam os textos digitados, e `forms.rs` valida e devolve a mensagem. O `Modal` mostra o erro e continua aberto.
- **Efeitos do Svelte:** um `$effect` que chama uma função de carregar passa a depender de todo estado lido antes do primeiro `await`. Se a função também grava esse estado, use `untrack`, senão o efeito roda sem parar.
- **Quebras de linha:** o repositório guarda LF e a cópia de trabalho usa CRLF (`core.autocrlf`). Ao editar por script, preserve as quebras de linha para não gerar um diff do arquivo inteiro.
- **Versão:** em `rust/Cargo.toml` (`[workspace.package]`) e em `rust/app/src-tauri/tauri.conf.json`; o build recusa versões diferentes. Commits seguem o formato `Título em português (x.y.0)`, com um corpo em tópicos.
- **Git e release:** faça commit, push ou build só quando o dono pedir. Publicar um release oferece a atualização a todos que usam o `.exe`, então só publique com o `.zip` testado pelo `build_exe.mjs`.
- **Atualização automática:** toda versão precisa continuar aceitando `--apply-update <pasta> <pid>` e publicar `PokeXGames-Hunt-Analyzer-X.Y.Z-windows.zip` com a pasta `PokeXGames Hunt Analyzer` dentro, senão as versões já instaladas (inclusive a 1.6.0, em Python) não conseguem se atualizar. Veja [Atualização do programa](README.md#atualização-do-programa).

## Domínio

- **Sessão / Hunt:** cada arquivo importado vira uma sessão permanente em `hunt_sessions`, com o JSON original em `raw_json`.
- **Categoria:** `Category` separa Hunts de Rifts, Energia Vermelha, Energia Azul e Terrors. As regras estão em [Bosses](README.md#bosses).
- **Boss do DPS:** registro manual em `dps_bosses`, com nome, tempo limite, origem do dano e fraquezas. **Não tem relação** com as categorias nem com as sessões importadas.
- **Efetividade:** multiplicadores por elemento e tabela de tipos do jogo estão em [docs/efetividade-pxg.md](docs/efetividade-pxg.md). Consulte ao tratar de elementos, tipos, fraquezas ou dano contra um boss.

## Página DPS

Código: `rust/core/src/dps/calculator.rs` (conta pura), `service.rs` (cadastro e ranking), `transfer.rs` (exportar e importar), `rust/app/src/pages/dps/`. As fórmulas estão em [DPS](README.md#dps).

**Objetivo:** escolher o melhor pokémon para um boss com tempo limite (ex.: 7 min). O dono usa **um único pokémon a batalha inteira**, por isso o ranking é individual e não há revezamento.

**Abas:**
- **Ranking:** mostra só os pokémons anexados ao boss selecionado. Tem os seletores de boss e Calcular por (Efetividade, Dummy ou Dano real; o de dummy só aparece na opção Dummy), Gerenciar bosses e Adicionar pokémon. Editar e Remover ficam ao lado do pokémon selecionado; o duplo clique também abre a edição.
- **Pokémons:** mostra o cadastro inteiro. Tem Novo, Editar, Testes, Duplicar e Excluir. Dano total e DPS ficam só no Ranking, porque valem para o boss em que o pokémon está anexado; aqui, o seletor Ver dano no dummy mostra só o dano de cada skill.

**Decisões do dono e o motivo:**

| Decisão | Motivo |
|---|---|
| Cálculo pela média (`dano ÷ recarga`), sem simular a luta | Reproduz a conta do colega e é fácil de conferir. Contar usos inteiros mantém a mesma ordem e soma de 1,3% a 2,9%. Simular a luta exigiria o tempo de execução de cada skill |
| Forma (Área/Target) e alcance (Melee/Ranged) separados | Só sugerem o aproveitamento e aparecem na tela; não entram direto na conta |
| Aproveitamento por skill, sugerindo Target + Melee 75% e o resto 100% | A skill target melee exige estar colado no boss, então não sai toda vez que a recarga acaba |
| Sugestão muda ao trocar a classificação só se o % não foi alterado à mão | Preserva o valor que o dono digitou |
| Ataque básico com aproveitamento próprio, começando em 75% | O básico é por turno e o dono precisa se afastar do boss às vezes. O 75% é um chute inicial |
| Turno do básico único, 2,5 s, em Ajustes | O dono não sabe a duração real; ao descobrir, muda em um lugar só. Se variar por pokémon, o campo passa para o cadastro |
| Um buff por pokémon, com multiplicadores livres para o básico e a próxima magia | Os buffs variam: há os só de básico, os de básico e magia, e os que aumentam só uma parte |
| A próxima magia é escolhida sozinha: a que mais rende | Supõe que o dono guarda a melhor magia para o buff |
| O dano vem só dos testes: nunca é digitado no cadastro | Evita digitar duas vezes. No cadastro, a coluna Dano é só leitura e o seletor não altera o Elemento da skill |
| Cada boss guarda um dummy, e todos os pokémons dele usam esse dummy | É como o dono escolhe o dano de cada boss, e mantém a comparação justa. Isso substituiu a ideia de guardar um dano por boss |
| Cada boss escolhe como calcular: Efetividade, Dummy ou Dano real, com o mesmo critério para todos os pokémons dele | Pedido do dono. Mantém a comparação justa. A fórmula é a mesma nas três; só muda a origem do dano. Bosses existentes ficaram em Dummy, sem mudar o ranking |
| Efetividade = teste no dummy Neutro × multiplicador do elemento do golpe | Dá uma estimativa sem testar em cada dummy. Supõe que o Neutro vale 1x, o que ainda não foi medido |
| Efetividade marcada à mão em cada boss, sem tabela de tipos | A tabela conhecida está incompleta; a Pokédex do jogo já traz o resultado pronto, inclusive em tipo duplo |
| Elementos do boss só informativos | Decisão explícita do dono: servem para saber as fraquezas. Na conta entra a lista marcada |
| Dano real por skill, com até 3 danos, separado por boss, sem multiplicador | O dono consegue medir cada skill dentro do boss, e esse dano já inclui a efetividade |
| Sem teste na origem do boss, ou golpe sem elemento na Efetividade: dano 0 e aviso, sem substituto | Decisão explícita do dono; evita misturar danos de origens diferentes. O modo Automático, que mistura, foi deixado para depois |
| Boost e held fora da conta; aviso "resiste ao boss" fora do escopo | O dano é o medido. O dono deixou o aviso de resistência para depois |
| Testes guardados à parte: até 3 danos por dummy (Neutro ou 18 elementos) ou por boss, em cada skill e no básico | Neutro, Normal e Fighting são dummies diferentes. Crystal ficou de fora: o dono não conhece dummy nem golpes desse tipo |
| Cada teste guarda as datas de cadastro e de modificação, sem data inventada para os antigos | Pedido do dono, para perceber pela data que um teste está desatualizado quando o pokémon muda. Modificado só muda quando os danos mudam, e trocar o dummy ou o boss cria um teste novo. Duplicar mantém as datas, porque a medição continua sendo a antiga |
| Elemento do golpe opcional | Só o cálculo por Efetividade precisa dele |
| Duplicar copia os testes, de forma independente | Como o dano só vem dos testes, uma cópia sem eles nasceria zerada |
| Exportar e importar por arquivo, com lista para marcar o que vai e testes incluídos; em nome repetido, escolha por cadastro entre Pular (padrão), Substituir e Criar cópia | Decisão do dono (2026-11-05). Sem os testes, o pokémon chegaria zerado. Substituir faz backup antes e mantém os bosses que o pokémon já tinha |
| Sem vida do boss, colar texto ou painel de filtros | Fora do pedido. O dono recusou explicitamente colar texto |

**Conferência da conta:** no `calculate`, com os danos da lista do colega, básico a 100% e sem o bônus da próxima magia, os totais em 420 s reproduzem a lista do colega (Chumbin 2.916.520, Muq 2.626.680, Maurolem 2.596.300, Sandsmauro 2.441.543, Jeremia 2.347.850, Polishop 2.273.505, Jolt 2.124.150, Bartolomeu 1.878.800). Com as regras atuais, o Chumbin dá **3.046.300**. Esses casos estão em `rust/core/tests/dps_calculator.rs` e precisam continuar passando; mudar a fórmula de propósito exige combinar com o dono.

**Testes e edição:** `apply_spec` (`dps/repository.rs`) reaproveita as skills pelo `skill_id` do `SkillSpec`, porque os testes apontam para elas. Preserve esse id em qualquer fluxo de edição, senão salvar o pokémon apaga os testes.

**Dados do colega:** os 8 monstros foram inseridos uma vez no banco real e depois excluídos de propósito pelo dono (2026-11-02). O app não traz monstros embutidos. Os números originais continuam em `rust/core/tests/dps_calculator.rs`, e as skills e recargas, no backup `hunts_backup_2026-11-02_19-18-01_antes-atualizacao.db`.

## Capturas e testes na janela

- Abra o app numa cópia do banco, numa pasta temporária, com a porta de depuração: `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333 PXG_HUNTS_DB=<cópia> npx tauri dev`, a partir de `rust/app`.
- Rode JavaScript na janela com `node rust/tools/cdp.mjs "(async()=>{...})()"`. Eventos de teclado precisam de `bubbles: true`, porque o Svelte 5 delega os eventos. Para chamar um comando direto: `window.__TAURI_INTERNALS__.invoke("nome", {...})`.
- Capture com `powershell -File rust/tools/capture_window.ps1 -Out captura.png [-Width 980 -Height 620]`. O tema muda pelo seletor em Configurações.
- Os diálogos nativos do Windows (abrir, salvar, confirmar) ficam fora do alcance do script.
- Para fechar: `taskkill //F //IM pxg-app.exe` e encerre o processo na porta 1420. Às vezes o app fecha logo ao abrir quando é reaberto em seguida a um `taskkill`; espere alguns segundos.

## Estado em 2026-11-08

**Código**
- A 2.0.0 (Rust) está pronta na branch `rust`, sem commit e sem release. O `.zip` testado está em `rust/dist/`. O corte terminou: o Python foi apagado, e o README e este arquivo descrevem a base em Rust. Faltam o commit, o merge na `main` e o release, só quando o dono pedir.
- Foi testada a atualização de uma 1.6.0 instalada (o `.exe` de verdade, com uma cópia do banco real) para a 2.0.0, pelo código de atualização da 1.6.0, sem passar pelo GitHub.
- Ainda não foram conferidos à mão os fluxos com diálogos nativos: PDF pelo menu, Excluir pokémon e boss, Exportar e Importar cadastros, Remover preço, Usar outro banco, Salvar cópia e Restaurar de arquivo. O dono deixou para o teste final.
- Revisão do DPS (2026-11-03): nenhuma fórmula errada. Sugestões aguardando o dono: avisar testes muito diferentes entre si, marcar empates e fichas incompletas no ranking, avisar pokémon sem básico, aceitar dano 0 dentro do boss e comparar a estimativa com o dano real.

**Banco real**
- Versão 10, com 3 sessões, os bosses Padrão e TESTE e 1 pokémon (Steelix, com testes), anexado a um boss. A 2.0.0 não criou migração.
- Na pasta do `.exe` ficou guardado, com outro nome, um banco vazio de um teste da 1.1.0 (`hunts_antigo_teste-1.1.0_2026-09-27.db`).

**Perguntas em aberto**
- O dummy Neutro vale mesmo 1x? O cálculo por Efetividade depende disso. Falta o dono testar um golpe no Neutro e em um dummy Super Efetivo.
- Qual é a duração real do turno do ataque básico? O valor de 2,5 s veio da lista do colega, e o dono vai medir.
- O 75% do básico e do target melee são chutes iniciais, ainda sem medição.

**Detalhes conhecidos**
- Remover uma skill no cadastro apaga os testes dela ao salvar, sem aviso.
- Desmarcar "Tem ataque básico" esconde os testes do básico sem apagá-los.
- Um erro inesperado só vai para o log; o Python mostrava uma caixa com o caminho dele.
