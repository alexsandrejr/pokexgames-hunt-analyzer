# PokeXGames Hunt Analyzer

App desktop Windows (Python 3.12, PySide6, SQLAlchemy 2, SQLite, pyqtgraph) que guarda as sessões exportadas pelo Analyzer do jogo PokeXGames e compara o dano de pokémons em bosses com tempo limite. O dono joga PokeXGames, usa o app e o distribui para colegas.

Escreva em português do Brasil: conversa, interface, comentários, docstrings, commits e documentação. Nomes de identificadores ficam em inglês.

Consulte o [README.md](README.md) para instalação, funcionalidades de cada página, build do `.exe`, tabelas do banco e como suportar um novo campo do Analyzer. Atualize-o junto com cada funcionalidade.

## Comandos

Use sempre o Python do `.venv`; o Python global não tem as dependências.

```bash
.venv/Scripts/python.exe main.py                                 # abre o app com data/hunts.db
.venv/Scripts/python.exe -m unittest tests.test_dps              # um módulo (o projeto usa unittest)
.venv/Scripts/python.exe -m unittest discover -s tests -t .      # suíte completa, 10 a 12 min: rode em segundo plano
PXG_HUNTS_DB=<cópia.db> .venv/Scripts/python.exe main.py --smoke-test   # visita todas as páginas; código 0 = ok
.venv/Scripts/python.exe scripts/build_exe.py                    # .exe e .zip em dist/ (requirements-dev.txt)
```

## Antes de dar uma tarefa por concluída

Rode a **suíte completa** e o `--smoke-test`, mesmo que os testes do módulo alterado passem. Em 2026-11-02, os testes do DPS passavam enquanto a página Preços estava quebrada, e só a suíte completa revelou o erro.

Para mudanças de tela, gere capturas e olhe nas duas larguras (1320×820 e o mínimo, 980×620) e nos dois temas. Veja [Capturas de tela](#capturas-de-tela).

## Dados reais

- `data/hunts.db` é o **banco real do dono**. Teste em uma cópia, apontada por `PXG_HUNTS_DB`. O `--smoke-test` também migra o banco que abrir, então vale a mesma regra.
- Abrir o app migra o banco, com backup automático em `data/backups/`. Um banco migrado é recusado por versões mais antigas (`SchemaTooNewError`).
- O `.exe` usa outro banco, em `%LOCALAPPDATA%\PokeXGames Hunt Analyzer`. O banco de lá não tem as sessões do dono.

## Arquitetura

```text
UI (PySide6) → Services → Repositories → SQLAlchemy → SQLite
```

- `app/services/`: regras de negócio, sem importar Qt. Lançam `ValueError` com mensagem em português, pronta para mostrar ao usuário.
- `app/database/repositories.py`: todo o SQL fica aqui, com uma classe por área. Ao adicionar uma classe, coloque-a **no fim do arquivo** e confira onde termina a anterior, pois os métodos de uma classe longa continuam depois do trecho visível.
- `app/ui/`: uma pasta por página. Uma página nova entra em `NAV_ITEMS` e `self.pages` (`main_window.py`) e expõe `refresh()`, chamado sempre que ela aparece.
- `resources/icons/`: SVGs desenhados com o traço `#aeb6c4`, que `icons.py` troca pela cor do tema.

## Convenções

- **Banco:** tabela nova entra em `models.py` e é criada pelo `create_all`. Coluna nova, coluna apagada (`dropped_columns`) ou dado inicial exige uma `Migration` no fim de `MIGRATIONS`, com SQL idempotente. Bancos novos também rodam todas as migrações, então o SQL não pode depender de uma coluna que já saiu de `models.py`. Testes de migração usam `LATEST_VERSION`, nunca um número fixo.
- **Fração x porcentagem:** aproveitamentos são guardados como fração de 0 a 1, e só a interface fala em %.
- **Números digitados:** `parse_user_number` aceita `14k`, `1,2kk` e `1.000.000`. Para preencher um campo, use `format_plain`, que devolve um texto que o parser lê de volta no formato ativo. Para exibir, use `format_number` e `format_money`.
- **Tabelas:** use `RecordTable` + `Column`, com `fit_contents=True` nas colunas que não podem ser cortadas.
- **Cores:** use `COLORS` e o QSS de `theme.py`, com `objectName` para estilizar. O dono usa o tema claro; o padrão é o escuro.
- **Diálogos com validação:** valide em `accept()`, mostre o erro em um `ErrorLabel` e mantenha o diálogo aberto. Com edição dentro de tabela, deixe o botão Salvar sempre habilitado: é o foco nele que grava a célula em edição.
- **Testes de interface:** definem `QT_QPA_PLATFORM=offscreen` antes de importar o Qt e guardam o diálogo em uma variável, senão o Python o destrói no meio do teste.
- **Quebras de linha:** o repositório guarda LF e a cópia de trabalho usa CRLF (`core.autocrlf`). Ao editar por script, preserve as quebras de linha para não gerar um diff do arquivo inteiro.
- **Versão:** `APP_VERSION` em `app/utils/constants.py`. Commits seguem o formato `Título em português (x.y.0)`, com um corpo em tópicos.
- **Git e release:** faça commit, push ou build só quando o dono pedir.

## Domínio

- **Sessão / Hunt:** cada arquivo importado vira uma `HuntSession` permanente, com o JSON original em `raw_json`.
- **Categoria:** `Category` separa Hunts de Rifts, Energia Vermelha, Energia Azul e Terrors. As regras estão em [Bosses](README.md#bosses).
- **Boss do DPS:** registro manual em `dps_bosses`, com nome, tempo limite, origem do dano e fraquezas. **Não tem relação** com as categorias nem com as sessões importadas.
- **Efetividade:** multiplicadores por elemento e tabela de tipos do jogo estão em [docs/efetividade-pxg.md](docs/efetividade-pxg.md). Consulte ao tratar de elementos, tipos, fraquezas ou dano contra um boss.

## Página DPS

Código: `app/services/dps_calculator.py` (conta pura), `dps_service.py` (cadastro e ranking), `app/ui/dps/`. As fórmulas estão em [DPS](README.md#dps).

**Objetivo:** escolher o melhor pokémon para um boss com tempo limite (ex.: 7 min). O dono usa **um único pokémon a batalha inteira**, por isso o ranking é individual e não há revezamento.

**Abas:**
- **Ranking:** mostra só os pokémons anexados ao boss selecionado. Tem os seletores de boss e Calcular por (Efetividade, Dummy ou Dano real; o de dummy só aparece na opção Dummy), e Adicionar e Remover do boss; o duplo clique abre a edição.
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
| Elemento do golpe opcional | Só o cálculo por Efetividade precisa dele |
| Duplicar copia os testes, de forma independente | Como o dano só vem dos testes, uma cópia sem eles nasceria zerada |
| Sem vida do boss, colar texto, exportação ou painel de filtros | Fora do pedido. O dono recusou explicitamente colar texto |

**Conferência da conta:** no `calculate`, com os danos da lista do colega, básico a 100% e sem o bônus da próxima magia, os totais em 420 s reproduzem a lista do colega (Chumbin 2.916.520, Muq 2.626.680, Maurolem 2.596.300, Sandsmauro 2.441.543, Jeremia 2.347.850, Polishop 2.273.505, Jolt 2.124.150, Bartolomeu 1.878.800). Com as regras atuais, o Chumbin dá **3.046.300**. Esses casos estão em `tests/test_dps.py` e precisam continuar passando; mudar a fórmula de propósito exige combinar com o dono.

**Testes e edição:** `_apply_spec` reaproveita as skills pelo `SkillSpec.skill_id`, porque os testes apontam para elas. Preserve esse id em qualquer fluxo de edição, senão salvar o pokémon apaga os testes.

**Dados do colega:** os 8 monstros foram inseridos uma vez em `data/hunts.db` e depois excluídos de propósito pelo dono (2026-11-02). O app não traz monstros embutidos. Os números originais continuam em `tests/test_dps.py`, e as skills e recargas, no backup `hunts_backup_2026-11-02_19-18-01_antes-atualizacao.db`.

## Capturas de tela

Em `offscreen` o Qt não encontra fontes e o texto vira quadradinhos. Antes de capturar, carregue a fonte real:

```python
for font in ("segoeui", "seguisb", "segoeuib"):
    QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font}.ttf")
use_palette(theme); apply_theme(app)
window.show(); window.show_page("dps"); app.processEvents()
window.grab().save("captura.png")
```

## Estado em 2026-11-03

**Código**
- Versão 1.4.0 com commit local e sem push, com a página DPS (abas Ranking e Pokémons), os testes e o seletor Calcular por (Efetividade, Dummy ou Dano real). Confira com `git status` e `git log` antes de continuar.
- O `.exe` e o `.zip` em `dist/` ainda são da 1.3.0.

**Banco real**
- `data/hunts.db` está na versão 8, com 3 sessões, o boss Padrão e 1 pokémon (Steelix, com testes no dummy Neutro), que não está anexado ao boss. O dono excluiu de propósito os 8 monstros do colega.
- A próxima abertura do app aplica a migração 9, com backup antes: o boss fica em Dummy, sem mudar o ranking. Numa cópia, a migração manteve as sessões, o pokémon e os testes.

**Perguntas em aberto**
- O dummy Neutro vale mesmo 1x? O cálculo por Efetividade depende disso. Falta o dono testar um golpe no Neutro e em um dummy Super Efetivo.
- Qual é a duração real do turno do ataque básico? O valor de 2,5 s veio da lista do colega, e o dono vai medir.
- O 75% do básico e do target melee são chutes iniciais, ainda sem medição.

**Detalhes conhecidos**
- Remover uma skill no cadastro apaga os testes dela ao salvar, sem aviso.
- Desmarcar "Tem ataque básico" esconde os testes do básico sem apagá-los.
- Na janela mínima, a tabela de detalhamento do Ranking precisa de rolagem horizontal para mostrar Dano total e %.
- A setinha dos `QComboBox` tem um cantinho escuro em todas as páginas, porque o tema não estiliza `::drop-down`. Não foi corrigido.
