# Migração para Rust

Plano para reescrever o app em Rust com [Tauri](https://tauri.app). O trabalho acontece na branch `rust`, na pasta [`rust/`](../rust). O app Python continua sendo a referência e a versão distribuída até o corte (fase 6).

## Onde paramos (2026-11-08, corte)

- **O corte terminou**, menos o commit, o merge e o release, que só acontecem quando o dono pedir. Nada foi commitado: a pasta `rust/` e este arquivo continuam sem versionar, e o código Python apagado aparece como removido no `git status`.
- **Feito no corte:** a atualização real de uma 1.6.0 instalada para a 2.0.0, a última conferência de paridade, o banco real copiado para a pasta do `.exe`, o código Python apagado, o `README.md`, o `CLAUDE.md` e o `.gitignore` reescritos para a base em Rust, e o `Ctrl+Q` que faltava.
- **Próximos passos:**
  1. As conferências da lista **Falta** da fase 4, que dependem dos diálogos nativos do Windows. O dono as deixou para o teste final.
  2. Commit, merge da `rust` na `main` e release da 2.0.0 com o `.zip` de `node tools/build_exe.mjs`, só quando o dono pedir.
- As dicas para testar na janela estão no `CLAUDE.md`, em "Capturas e testes na janela".

## Decisões

| Decisão | Motivo |
|---|---|
| Tauri 2: lógica e banco em Rust, telas em HTML/CSS/TypeScript | Escolha do dono (2026-11-07). É o framework de interface mais maduro em Rust, gera um `.exe` pequeno e tem boas bibliotecas de tabela e gráfico. Usa o WebView2, que já vem no Windows 11 |
| Código em `rust/` neste repositório, na branch `rust` | Escolha do dono. O app Python fica intacto como referência até ser alcançado |
| Crate `pxg-core` sem nenhuma dependência do Tauri | Faz o papel de `app/services` + `app/database` + `app/utils`. É testável com `cargo test`, sem janela |
| Formato numérico (pt-BR/en-US) passado em cada chamada | No Python ele é global, mas os comandos do Tauri rodam em várias threads |
| Mesmo banco SQLite, mesmo esquema e mesmo `PRAGMA user_version` | O `hunts.db` do dono e dos colegas abre sem conversão. A versão em Rust continua a lista de migrações do Python (a próxima é a 11) |
| Primeira versão em Rust: **2.0.0** | Marca a troca de base. O formato do `.zip` e o `--apply-update` continuam iguais |

## Estrutura

```text
rust/
├── Cargo.toml          # workspace
├── core/               # pxg-core: regras, banco, importação, exportação, atualização
│   ├── src/
│   ├── sql/            # DDL das tabelas, gerado dos modelos SQLAlchemy
│   ├── examples/       # dump_db: esquema e dados de um banco, para conferir a paridade
│   └── tests/          # porta dos testes de tests/*.py; fixtures/ tem o esquema do Python
├── tools/              # build_exe.mjs (pacote), cdp.mjs e capture_window.ps1 (testes na janela)
└── app/                # (fase 4) Tauri: src-tauri/ com os comandos, ui/ com as telas
```

Comandos (o Rust fica em `%USERPROFILE%\.cargo\bin`):

```bash
cd rust
cargo test                    # testes do núcleo
cargo clippy --all-targets    # avisos
```

## Fases

Cada fase termina com os testes do Python correspondentes portados e passando em Rust.

### 1. Núcleo puro ✅ (2026-11-07)

- [x] Workspace e crate `pxg-core`
- [x] `format`: `format_number`, `format_plain`, `format_money`, `format_compact`, durações, datas e porcentagem
- [x] `parse`: `parse_user_number`, `parse_user_duration`, `parse_duration`, `to_int`/`to_float`/`to_bool`/`to_str`/`parse_datetime` sobre `serde_json::Value`
- [x] `dps::calculator`: enums, specs, `validate_spec` e `calculate`. Reproduz a lista do colega e o Chumbin em 3.046.300

### 2. Banco ✅ (2026-11-07)

- [x] `db`: uma conexão `rusqlite` (SQLite embutido) num `Mutex`, com `foreign_keys = ON`, `with` e `transaction`
- [x] `db::schema`: cria só as tabelas que faltam, com os índices delas, como o `create_all`, a partir de [`schema_models.sql`](../rust/core/sql/schema_models.sql)
- [x] `db::migrations`: as migrações 1 a 10 com o mesmo SQL do `migrations.py`, e `Error::SchemaTooNew`. Um banco mais novo é recusado antes de qualquer alteração
- [x] `db::datetime`: datas no texto do SQLAlchemy, `AAAA-MM-DD HH:MM:SS.ffffff`
- [x] `db::open_and_migrate`: backup `antes-atualizacao` antes de migrar um banco com dados
- [x] `backup`: mesmos nomes de arquivo, backup automático diário com limpeza, restauração pela API de backup do SQLite, sem fechar a conexão. Diferença em relação ao Python: recusa restaurar um backup de versão mais nova
- [x] `settings`: `settings.json` no mesmo formato, lido de forma tolerante
- [x] `config`: modos desenvolvimento, executável e portátil, `PXG_HUNTS_DB` e pasta de backups

**Paridade conferida:** um banco novo criado pelo Rust tem o `sqlite_master` igual ao do Python (teste `new_database_is_identical_to_the_one_python_creates`). Cópias do `hunts.db` real e dos 15 backups de `data/backups/` (versões 2 a 9) migraram para conteúdo idêntico nas duas versões. Para repetir:

```bash
.venv/Scripts/python.exe rust/tools/dump_db.py <cópia1.db> > python.txt
cd rust && cargo run -q -p pxg-core --example dump_db -- <cópia2.db> > ../rust.txt
diff python.txt rust.txt
```

Se o esquema do Python mudar, gere de novo a referência com `rust/tools/dump_db.py --schema-only > rust/core/tests/fixtures/schema_python.sql`.

**Falta decidir na fase 4:** a pasta de dados no modo desenvolvimento do Tauri. A pasta `data/` do projeto é o banco real do dono, e o Python a usa em desenvolvimento.

### 3. Services ✅ (2026-11-07)

Na ordem, do que o DPS precisa até o resto:

1. ✅ `dps_service` e `dps_transfer` (2026-11-07), em `dps::service`, `dps::repository` (o SQL) e `dps::transfer`. Os 43 testes de `ServiceTests` e os 19 de `test_dps_transfer.py` (menos os das telas) foram portados. Paridade conferida:
   - o arquivo exportado pelo Rust é idêntico byte a byte ao do Python, e o Rust lê o do Python (fixture `dps_export_python.json`, gerada por `rust/tools/export_fixture.py`);
   - o ranking de cada boss, com o detalhamento, e a exportação completa saem iguais nas duas versões no `hunts.db` real e nos backups de 2026-11-02 (os 8 monstros do colega) e de 2026-11-05. Para repetir, use `rust/tools/dps_report.py` e o exemplo `dps_report`, como no `dump_db`.
2. ✅ `settings_service`, `backup_service` (feitos na fase 2)
3. `json_importer`, `tsv_importer`, `categories`, `chat_rewards`, `hunt_service`
   - ✅ Leitura pura (2026-11-07): `hunts::analyzer` (JSON, validação, `content_hash`), `hunts::tsv`, `hunts::categories`, `hunts::chat_rewards` (leitura das mensagens e escolha do nome) e `pyjson` (o `json.dumps` do Python, para o hash). Paridade conferida com o exemplo `parse_report` e `rust/tools/parse_report.py`: fixtures, arquivos de `imports/`, o `raw_json` de cada sessão do banco real (hash igual ao gravado) e 440 arquivos sintéticos de `rust/tools/fuzz_analyzer.py`, sem diferença fora dos inteiros acima de 64 bits.
   - ✅ Gravação e consultas (2026-11-07): `hunts::service` (importar arquivo, texto e texto colado, duplicidade, categoria pela pasta e pelos inimigos, consultas, excluir, trocar categoria, recompensas do chat no banco), `hunts::repository` (o SQL), `hunts::files` (`json_files`) e `hunts::model` (`dto`). Testes portados: `test_hunt_service`, `test_json_importer`, `test_tsv_importer`, `test_paste_import`, `test_chat_rewards` e `test_bosses` (menos as telas e as estatísticas).
   - **Paridade conferida:** o exemplo `hunts_scenario` e `rust/tools/hunts_scenario.py` aplicam a mesma sequência (importar 53 arquivos entre fixtures, `imports/` e sintéticos; mudar e limpar preços; somar e tirar recompensas do chat; trocar categoria; excluir) num banco novo, e o `dump_db` das duas versões sai idêntico. Os 15 arquivos sintéticos com totais acima de 64 bits ficaram de fora: neles o Python trava com `OverflowError` ao gravar.
4. ✅ `price_service` (`prices`), `filters` e `query_filters` (`hunts::filters`, `hunts::query`), com os testes de `test_price_service` e `test_filters`.
   ✅ `advanced_search`, `statistics_service` e `entity_report` (2026-11-07), em `hunts::advanced_search` e `hunts::statistics`, com os testes de `test_statistics`, `test_entity_report`, `test_advanced_search` e as estatísticas de `test_bosses`. **Paridade conferida** com o exemplo `stats_report` e `rust/tools/stats_report.py` (visão geral com as médias derivadas, métricas, rankings, relatório de cada item, dano por elemento e buscas avançadas, em cada categoria): idêntico no `hunts.db` real e no banco do `hunts_scenario`.
5. ✅ `export_service` e `export_documents` (2026-11-07), em `export` e `export::documents`: CSV, JSON, Excel (`rust_xlsxwriter`) e o HTML do PDF (`document_html`). Testes de `test_export.py` portados.
   - **PDF:** no Python, o Qt desenha o PDF a partir de `document_html`. Em Rust, o mesmo HTML vai ser impresso pelo WebView2 (`PrintToPdf`) na fase 4, em retrato ou paisagem conforme `pdf_landscape`. Até lá, `export_document` recusa o formato PDF.
   - **Paridade conferida** com o exemplo `export_report` e `rust/tools/export_report.py` (sessões, sessões filtradas, comparação, relatório e item/inimigo), no `hunts.db` real e no banco do `hunts_scenario`: CSV em pt-BR e en-US, JSON e HTML idênticos byte a byte (70 arquivos), e o Excel com o mesmo conteúdo lido pelo openpyxl (valores com os 15 algarismos do Excel, formatos de número, abas, larguras, painel congelado e cabeçalho).
   - **Diferença:** o openpyxl recusa caracteres de controle nos textos, e o Python não consegue exportar para Excel uma sessão com eles; o `rust_xlsxwriter` grava os caracteres escapados.
6. ✅ `update_service` (2026-11-07), em `update`: verificação no GitHub (cliente `ureq`, com TLS próprio), download com conferência de tamanho e SHA-256, extração com as mesmas proteções, `apply_update` com devolução dos arquivos antigos em caso de falha, espera do processo antigo (API do Windows) e leitura de `--apply-update <pasta> <pid>` (`install_request`). Testes de `test_update.py` portados (menos as telas), com a rede e as falhas de arquivo simuladas.
   - **Vindo do Python:** a troca também tira a pasta `_internal` do PyInstaller (`LEGACY_NAMES`), que o pacote em Rust não traz; o teste `update_from_python_removes_the_pyinstaller_folder` cobre isso.
   - Conferido contra o GitHub real com o exemplo `update_check`: para a 1.5.0, oferece a 1.6.0 instalável; para a 1.6.0, diz que é a mais recente.
   - ✅ Na fase 4 (2026-11-07): a janela de progresso da instalação e o programa reaberto ao final.

### 4. Telas (Tauri) — em andamento

**Feito (2026-11-07):**
- Projeto em `rust/app/`: Svelte 5 + TypeScript (Vite) nas telas e o crate `pxg-app` (`src-tauri/`) com os comandos, que chamam o `pxg-core`. Tauri 2.
- Abertura como no Python: `--apply-update` tratado antes da janela, banco aberto com backup antes de migrar, backup automático diário e limpeza das sobras de atualização.
- **Dados em desenvolvimento:** `rust/data/` (decisão do dono, 2026-11-07), longe do banco real em `data/`. `PXG_HUNTS_DB` continua valendo.
- Tema claro e escuro com os tokens de `theme.py` (`src/app.css`), ícones de `resources/icons` recoloridos pelo tema e o ícone do app gerado do `app.svg`.
- Barra lateral com as 5 seções e a página DPS com a aba Ranking: seletor de boss, Calcular por, dummy, elementos e efetividade com as cores dos tipos, ranking com barra, detalhamento e Remover. Conferida com capturas em 1320×820, 980×620 e nos dois temas, ao lado da referência do Python.
- **Página DPS completa:** aba Pokémons (pesquisa, Novo, Editar, Testes, Duplicar, Excluir, Ver dano no dummy), Gerenciar bosses (novo, editar, excluir), Adicionar pokémon, Editar no Ranking (também com duplo clique e Enter), Ajustes, Exportar e Importar cadastros (com backup antes de Substituir) e a barra de status com as mensagens do Python.
- **Componentes base:** `Modal` (diálogo com erro de validação), `RecordTable` (ordenação pelo cabeçalho, pesquisa, seleção, Enter/Delete), lista de marcação e menu de botão.
- **Validação no Rust:** as telas mandam os textos digitados e `src-tauri/src/forms.rs` valida na ordem e com as mensagens dos diálogos do Python (pokémon, boss, ajustes, testes), com testes próprios.
- Conferido na janela, numa cópia do banco real: abrir e validar o pokémon, salvar um novo (com a troca do % sugerido), duplicar, testes (erro ao trocar de skill, gravar ao fechar, média ao digitar), novo boss (nome repetido), Adicionar pokémon com pesquisa e Ajustes inválidos. Exportar e importar só foram testados pelos testes do `pxg-core`: os seletores de arquivo são do Windows e a janela fechou antes do teste direto dos comandos.

- **Sessões, primeira parte:** sub-navegação (Todas, Hunts e os quatro tipos de boss, com as contagens), lista com seleção de várias linhas (Ctrl, Shift, Ctrl+A), pesquisa, Detalhes, Comparar, Mover, Excluir e Exportar (CSV, Excel e JSON); painel de filtros com a pesquisa avançada, o mesmo em todas as páginas; Importar pela barra lateral (arquivos, pasta e colar texto, com Ctrl+I, Ctrl+Shift+I e Ctrl+Shift+V), arrastar e soltar, pergunta em duplicidade, barra de progresso e resumo; detalhes da sessão (Resumo, Enemies, Drops, Supplies e JSON) com recompensas do chat; F5 recarrega. 
- Conferido na janela, numa cópia do banco real: lista e ordenação, seleção e ações, comparação, detalhes, filtro de Profit, diálogo de colar, exportação em CSV, prévia do chat, importação em Terrors e duplicidade, nas duas larguras e nos dois temas. Um laço de atualização na tabela, achado no log, foi corrigido.

- **Gráficos:** colunas por sessão (linha acima de 60), com a média, e barras horizontais ordenadas, em SVG, com as regras do `charts.py` (barras de até 24 px com a ponta arredondada, grade fina, dica com o valor e clique que abre a sessão). O Rust (`src-tauri/src/charts.rs`) calcula os valores, as marcas dos eixos e os textos. Entraram no Resumo de cada tipo de boss (cards, Bosses derrotados, Drops mais valiosos, Dano por elemento e Evolução por sessão) e na aba Gráficos dos detalhes.

- **Análise:** Relatórios (cards, Métricas, Mais frequentes em abas), Itens e Inimigos (cards, quantidade por Hunt com a média de quando aparece, Hunts em que apareceu, clique e duplo clique abrem a sessão) e Preços (pesquisa, Somente com preço personalizado, Definir preço com a validação do Python, Remover preço com confirmação). Seletor de categorias em cada página, lembrado enquanto o app está aberto, e exportação dos relatórios. Vistas em `src-tauri/src/analysis.rs`, com testes. Conferido na janela, numa cópia do banco real: os três relatórios, o aviso de nome não encontrado, o diálogo de preço (inválido, válido, salvar) e a exportação em CSV e Excel chamando os comandos direto, nas duas larguras e nos dois temas.

- **Início:** o app abre nele, como o Python. Seletor começando em "Hunts e bosses", os 4 cards em destaque e os 4 menores, o resumo por categoria (só com mais de uma categoria, independente do seletor) e os 8 gráficos de evolução por sessão, com os textos trocando entre Hunt e sessão conforme o escopo. Vista em `src-tauri/src/dashboard.rs`, com testes. Conferido na janela, numa cópia do banco real: cards, resumo por categoria (depois de mover uma sessão para Terrors), dica e clique nos gráficos e o escopo Hunts, nas duas larguras e nos dois temas.

- **Configurações:** Aparência (o tema muda na hora; formato de números), Atualizações (verificar ao abrir, 3 s depois da janela, e Verificar agora), Banco de dados (arquivo, tamanho, Hunts, Abrir pasta, Usar outro banco, Voltar ao banco padrão, aviso do PXG_HUNTS_DB e Reiniciar agora) e Backup (automático, quantos manter, fazer agora, salvar cópia, restaurar de arquivo ou selecionado, com confirmação, limpando os filtros). Comandos em `src-tauri/src/commands/settings.rs`.
- **Atualização:** diálogo "Nova versão disponível" com as novidades em Markdown (texto escapado), download com barra e cancelamento (evento `update-progress`), recusa fora do `.exe` e, no fim, o instalador aberto e o app fechado (`commands/update.rs`). A oferta espera os outros diálogos fecharem, como no Python.
- **Instalação (`--apply-update`):** janela pequena de progresso, sem fechar, no tema das configurações (`src-tauri/src/install.rs` e `src/InstallView.svelte`); aviso nativo se falhar e programa reaberto ao final; `--smoke-test` instala sem avisos e sem reabrir. A janela principal passou a ser criada pelo código (`"create": false`), para só a de progresso abrir nesse modo.
- **Erro ao abrir o banco:** caixa de mensagem nativa com o caminho e o erro, ou só a mensagem se o banco for de versão mais nova, como no Python.
- **Release:** `custom-protocol` nos recursos padrão do `pxg-app`, para o binário de release embutir as telas (o `tauri dev` desliga os recursos padrão).
- Conferido: a página na janela, numa cópia do banco real (Verificar agora, backup, formato de números, tema, restaurar e recusar arquivo inválido pelos comandos, Reiniciar agora, diálogo de versão nova com dados de teste); e, com o binário de release compilado em `rust/target` (sem gerar pacote), uma atualização simulada numa pasta temporária: janela de progresso, `.exe` trocado, `_internal` apagada, `data` preservada, código 0 e o programa reaberto no modo portátil. O aviso de banco inválido também foi visto no binário de release.

- **PDF:** `src-tauri/src/pdf.rs` grava o HTML de `document_html` num arquivo temporário, abre uma janela oculta com ele e chama o `PrintToPdf` do WebView2 (crate `webview2-com`, na mesma versão do Tauri): A4, margens de 12 mm, paisagem conforme `pdf_landscape`, com os fundos das linhas. Só no PDF entram o `charset` e regras para não separar o título da tabela nem quebrar uma linha entre páginas, porque o HTML do núcleo é conferido byte a byte com o do Python. A permissão de gravar é testada antes, para dar a mesma mensagem dos outros formatos. Conferido pelo comando, numa cópia do banco real: lista de sessões e Relatórios em paisagem (4 páginas), relatório de item em retrato e a recusa de uma pasta sem permissão, sem sobrar janela nem arquivo temporário.

**Comandos:**

```bash
cd rust/app
npm install                       # uma vez
npx tauri dev                     # abre o app (dados em rust/data, ou PXG_HUNTS_DB=<cópia.db>)
npm run check                     # tipos do Svelte/TypeScript
powershell -File ../tools/capture_window.ps1 -Out captura.png [-Width 980 -Height 620]
```

Para clicar e preencher a janela por script, sem mexer no mouse, abra o app com `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333` e rode JavaScript nela com `node ../tools/cdp.mjs "<código>"`. Os diálogos nativos (abrir, salvar, confirmar) ficam fora do alcance do script.

**Falta:**

- DPS: conferir Exportar e Importar cadastros na janela, Excluir pokémon e Excluir boss (confirmação nativa).
- Sessões e Análise: conferir o PDF pelo menu Exportar (o seletor de salvar é nativo). Preços: conferir Remover preço na janela (confirmação nativa). Configurações: conferir Usar outro banco, Salvar cópia e Restaurar de arquivo (seletores nativos) e a atualização real a partir de um release publicado.
- Conferir nas duas larguras (1320×820 e 980×620) e nos dois temas, como hoje.

### 5. Distribuição ✅ (2026-11-08)

- [x] `.exe` com o nome `PokeXGames Hunt Analyzer.exe` (`mainBinaryName`), dentro da pasta `PokeXGames Hunt Analyzer`, num `PokeXGames-Hunt-Analyzer-X.Y.Z-windows.zip`, com o `LEIA-ME.txt` (`rust/app/LEIA-ME.txt`, adaptado do Python: WebView2 no lugar de "nem Python" e o caminho do log). Os metadados do `.exe` têm o nome, a versão e a empresa (`publisher`).
- [x] **Compatibilidade da atualização:** a 1.6.0 em Python baixa o `.zip`, extrai e roda `"PokeXGames Hunt Analyzer.exe" --apply-update <pasta> <pid>`. O `.exe` em Rust aceita esses argumentos e faz a mesma troca de arquivos (cópia em `.update-new`, antigos em `.update-old`, pasta `data` protegida).
- [x] Na primeira atualização vinda do Python, a pasta `_internal` do PyInstaller é apagada.
- [x] **Log em arquivo** (`pxg_core::logging`): `logs/app.log` na pasta dos dados, rotativo como o do Python (1 MB, mais `app.log.1` a `app.log.3`), no mesmo formato, só com os registros do programa. Registra a abertura, o banco, o código de saída, os pânicos e os erros de JavaScript não tratados nas telas (`log_frontend_error`).
- [x] **`--smoke-test`:** a janela abre oculta, as telas visitam todas as páginas (Início, Todas, Hunts, os tipos de boss, Relatórios, Itens, Inimigos, Preços, DPS e Configurações) e chamam `smoke_test_done`, que sai com 0 ou 1. Uma página falha se não terminar de carregar em 20 s, se ficar vazia ou se alguma chamada ao Rust falhar. As telas chamam o Rust pelo `invoke` de `lib/diagnostics.ts`, que conta as chamadas em andamento (o `__TAURI_INTERNALS__.invoke` é somente leitura no binário de release). Depois de 180 s sem resposta, o programa sai com 1. Não verifica atualização nesse modo.
- [x] **Script de build** (`node tools/build_exe.mjs`, na pasta `rust/`; `--skip-test` pula os testes): confere se a versão do `tauri.conf.json` é a mesma do `Cargo.toml`, roda o `tauri build --no-bundle`, monta a pasta e o `.zip` (com o `tar.exe` do Windows), roda o `--smoke-test` com dados temporários e testa a atualização: extrai o `.zip` com o mesmo código da atualização automática (exemplo `extract_package`) e o instala por cima de uma cópia antiga em Python (com `_internal` e `data`). Se um teste falhar, apaga o `.zip`. O build leva de 7 a 13 minutos por causa do LTO.
- O smoke test achou um laço em Preços: o efeito da página lia a seleção dentro do `load`, que a trocava, e pedia a lista ao Rust sem parar. Corrigido com `untrack`.

### 6. Corte (2026-11-08)

- [x] **Atualização real de uma 1.6.0 instalada para a 2.0.0**, sem publicar nada: o `.exe` da 1.6.0 (do `.zip` publicado) foi aberto no modo portátil com uma cópia do banco real, e o código de atualização dela (`extract` e `start_installer`, rodados pelo Python) instalou o `.zip` 2.0.0 com o PID dela. A janela de progresso trocou os arquivos, apagou a `_internal`, manteve a `data`, limpou a pasta `updates` e abriu a 2.0.0 com os mesmos números. O log da 1.6.0 e o da 2.0.0 ficaram no mesmo arquivo, com o mesmo formato. O log do instalador vai para `%LOCALAPPDATA%`, como no Python, porque ele roda da pasta `updates`.
- [x] **Última conferência de paridade**, antes de apagar o Python: idêntico em 16 bancos (o real e os backups).
- [x] **Banco real do dono no `.exe`** (escolha do dono): `data/hunts.db` e `data/backups/` copiados para `%LOCALAPPDATA%\PokeXGames Hunt Analyzer`. O banco vazio que estava lá, de um teste da 1.1.0, foi guardado como `hunts_antigo_teste-1.1.0_2026-09-27.db`. O `data/` da raiz ficou como cópia.
- [x] **Código Python apagado:** `app/`, `tests/`, `scripts/`, `resources/`, `main.py` e os `requirements`. O código continua no git (`main` e o commit `b9b194e`). A `imports/` ficou, com os JSONs do dono e o exemplo. A pasta `rust/` continua no lugar (escolha do dono).
- [x] **Ferramentas de paridade apagadas** (escolha do dono): os `.py` de `rust/tools` e o `paridade.sh`. Como a pasta `rust/` nunca tinha sido commitada, elas **não** estão no histórico do git. Os exemplos em Rust (`dump_db`, `stats_report` etc.) e as fixtures geradas por elas continuam. As seções das fases 1 a 3 citam essas ferramentas como registro do que foi conferido.
- [x] `README.md`, `CLAUDE.md` e `.gitignore` reescritos para a base em Rust. Entraram o `Ctrl+Q`, que fecha o app como no Python, e a verificação de atualização ao abrir só no `.exe`, também como no Python.
- [ ] Commit, merge da branch `rust` na `main` e release da 2.0.0, só quando o dono pedir.

## Pontos de atenção

- **Tema:** muda na hora, sem o aviso de reiniciar do Python (lá era uma limitação do Qt).
- **Cache do WebView2:** fica em `%LOCALAPPDATA%\pokexgames.hunt-analyzer`, também no modo portátil. Os dados do programa continuam na pasta `data`.
- **Erros inesperados:** o Python mostrava uma caixa com o caminho do log. Em Rust, os erros das telas e os pânicos só vão para o log; o LEIA-ME diz onde ele fica.
- **Usar outro banco:** o seletor de salvar do Windows pergunta se quer substituir um arquivo existente; o Python desligava essa pergunta. Responder Sim só escolhe o banco, sem apagá-lo.
- **Ponto flutuante:** o Python e o Rust usam o mesmo `f64`, e o `calculate` soma na mesma ordem. Arredondamentos seguem o `round()` do Python (empate para o par): use `format::round_half_even` e `format::round_to`.
- **`format_plain`:** o Python escreve `1e16` ou mais em notação científica, e o Rust não. Não acontece com os valores do app.
- **`parse_datetime`:** o `fromisoformat` do Python aceita fuso horário; a versão em Rust lê só os formatos sem fuso. O Analyzer não exporta fuso.
- **Testes guardados por skill:** como no Python, editar um pokémon precisa preservar o `skill_id`, senão salvar apaga os testes.
- **Igualdade:** `SkillSpec` ignora o `skill_id` e `DamageTest` ignora as datas ao comparar, como os `field(compare=False)` do Python.
- **Relógio do DPS:** `DpsService::with_clock` substitui o `patch("...datetime")` dos testes do Python.
- **`casefold`:** nomes são comparados e ordenados com `text::casefold`, que cobre minúsculas e `ß`. A ordenação é estável, como o `sorted` do Python.
- **`content_hash`:** a detecção de duplicidade compara com os hashes gravados pelo Python, então `pyjson::dumps_canonical` precisa gerar os mesmos bytes do `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. Isso exige o `arbitrary_precision` do `serde_json` (inteiros sem limite e `1` diferente de `1.0`) e o `repr` do Python para números com casas (`pyjson::python_float`). Quando há duas opções igualmente curtas, o Python fica com a mais próxima do valor exato (empate para o par), e o formatador curto do Rust não: por isso os dígitos vêm do arredondamento exato.
- **Taxas derivadas:** `total × 3600 ÷ duração` usa `parse::int_true_div`, a divisão exata entre inteiros do Python, com um único arredondamento.
- **`strip()` e `split()`:** use `text::py_strip` e `text::py_split`, que tratam `\x1c`–`\x1f` como espaço, como o Python. O `trim()` do Rust não trata.
- **Quebras de linha:** o arquivo do Analyzer é lido trocando `\r\n` por `\n`, como o modo texto do Python, para o `raw_json` guardado ser o mesmo.
- **Inteiros acima de 64 bits na sessão:** o Python os aceita e falha ao gravar no SQLite; o Rust os trata como vazios (`parse::round_to_i64`). O hash continua igual, porque é calculado do documento inteiro.
- **Larguras no Excel:** o openpyxl grava a largura pura e o `rust_xlsxwriter` soma 5/7 de margem; o Rust desconta essa margem para as colunas ficarem iguais.
- **Inteiros na tela e no PDF:** `format::format_integer` formata inteiros sem passar por `f64`, como o `f"{n:,}"` do Python.
- **`NaN` e `Infinity` no arquivo do Analyzer:** o Python os aceita; o leitor do Rust recusa o arquivo como JSON inválido. O Analyzer não exporta esses valores.
- **Número enorme no arquivo do DPS:** o Python lê `10**400` e recusa como "incompleto"; o leitor de JSON do Rust recusa já ao ler ("não é um JSON válido"). Nos dois casos nada é importado.
- **% sugerido no cadastro do pokémon:** o Python lê o número do campo para saber se o % foi alterado à mão; a tela em Rust compara o texto com a sugestão (`75` igual a `75%`, mas `75,0` conta como alterado).
- **Erro ao exportar cadastros:** o Python fecha o diálogo e avisa numa caixa; a tela em Rust mostra o erro no próprio diálogo, mantendo as marcações.
- **Diálogos maiores que a janela:** o diálogo do pokémon (980×800 no Python) fica dentro da janela e rola quando ela é menor.
- **Detalhes e comparação de sessões:** no Python são janelas separadas, que podem ficar abertas lado a lado; no Tauri abrem como diálogo dentro da janela, uma de cada vez.
- **Marcas dos eixos dos gráficos:** o pyqtgraph escolhe as marcas pelo tamanho em pixels; o Rust usa até 6 marcas redondas (1, 2 ou 5 × 10ⁿ), e as de duração seguem a mesma regra do Python (30 min ou 1 h, dobrando).
- **Página que não cabe:** com os filtros abertos na janela mínima, a página inteira rola, e a lista mantém pelo menos 260 px.
- **Ctrl+Q:** o atalho para fechar o programa ainda não existe na versão em Rust.
