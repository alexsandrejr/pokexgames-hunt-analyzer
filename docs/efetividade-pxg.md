# Efetividade de elementos no PokeXGames

Referência sobre o sistema de efetividade do jogo, transcrita de prints enviados pelo dono do projeto (wiki e telas do jogo).

No código, só os multiplicadores de PvE são usados, no cálculo por **Efetividade** da página DPS (`EffectivenessLevel`). A tabela de tipos não está no app: o resultado de cada ataque é marcado à mão em cada boss, copiado da Pokédex do jogo. Por isso as interpretações 1 e 4 abaixo não afetam a conta.

Trate como fato só o que está nas seções de **Dados**. A seção [Interpretações](#interpretações-a-confirmar) é dedução e ainda precisa de confirmação.

## Tipos

Um pokémon é de **tipo puro** (um elemento) ou **tipo duplo** (dois). Cada golpe também tem um tipo, que pode ser diferente do tipo do pokémon que o usa.

Os 18 tipos de ataque: Normal, Fire, Water, Grass, Electric, Ice, Fighting, Poison, Ground, Flying, Psychic, Bug, Rock, Ghost, Dragon, Dark, Steel, Fairy.

**Crystal** é um 19º tipo. Na tabela da wiki, ele aparece na aba Defesa, mas não na lista da aba Ataque. Mesmo assim, as listas de defesa incluem ataques Crystal (ver Grass + Poison e Crystal abaixo). Até onde o dono sabe (2026-11-03), não existem dummy de Crystal nem golpes do tipo Crystal, por isso ele fica fora do app.

## Dados: multiplicadores

Segundo a wiki, o comportamento pode variar com o contexto: PvE, PvP ou áreas específicas, como o Nightmare World. Por isso a imunidade tem valores diferentes em cada contexto.

### Defensor de tipo puro

| Situação | Multiplicador | Descrição |
|---|---:|---|
| Fraco contra o ataque | 2x | Super Efetivo |
| Neutro contra o ataque | 1x | Normal |
| Resistente contra o ataque | 0,5x | Muito Inefetivo |
| Nulo contra o ataque (PvE) | 0x | Nulo |
| Nulo contra o ataque (PvE Nightmare World) | 0,5x | Muito Inefetivo |
| Nulo contra o ataque (PvP) | 0,4x | — |

### Defensor de tipo duplo

| Situação | Multiplicador | Descrição |
|---|---:|---|
| Ambos fracos contra o ataque | 2x | Super Efetivo |
| Apenas um fraco contra o ataque | 1,75x | Efetivo |
| Um fraco e outro resistente | 1x | Normal |
| Ambos neutros | 1x | Normal |
| Um resistente e outro neutro | 0,75x | Inefetivo |
| Ambos resistentes | 0,5x | Muito Inefetivo |
| Um nulo contra o ataque (PvE) | 0x | Nulo |
| Um nulo contra o ataque (PvE Nightmare World) | 0,5x | Muito Inefetivo |
| Um nulo contra o ataque (PvP) | 0,4x | — |

## Dados: tabela de tipos (incompleta)

A wiki tem uma **Tabela de Efetividades** interativa, com duas abas: **Defesa** (selecione até 2 tipos) e **Ataque** (selecione 1 tipo). Só as combinações abaixo foram enviadas, algumas vindas da Pokédex do jogo. As demais são **desconhecidas**: confirme com a tabela do jogo, em vez de presumir que seguem os jogos oficiais de Pokémon.

### Ataque: Grass

| Resultado | Dano contra |
|---|---|
| Super Efetivo | Water, Ground, Rock |
| Normal | Normal, Electric, Ice, Fighting, Psychic, Ghost, Dark, Fairy |
| Muito Inefetivo | Fire, Grass, Poison, Flying, Bug, Dragon, Steel |

### Defesa: Grass + Poison (ex.: Venusaur)

| Resultado | Ataques que causam |
|---|---|
| Efetivo | Fire, Ice, Flying, Psychic |
| Normal | Normal, Poison, Ground, Bug, Rock, Ghost, Dragon, Dark, Steel, Crystal |
| Inefetivo | Water, Electric, Fighting, Fairy |
| Muito Inefetivo | Grass |

A tela do Venusaur no jogo mostra o mesmo grupo "Efetivo" e o mesmo grupo "Normal". O grupo "Inefetivo" aparece cortado no print.

### Defesa: Crystal (ex.: Crystal Onix)

Vem da tela do Crystal Onix (#095, T1C) na Pokédex do jogo. Ele mostra um único ícone de tipo, Crystal. Os nomes foram lidos dos ícones, que são pequenos no print. As listas cobrem os 19 tipos, sem repetição.

| Resultado | Ataques |
|---|---|
| Super efetivo | Fire, Grass, Fighting, Poison, Ground, Steel |
| Normal | Bug, Ghost, Dark, Crystal, Fairy |
| Muito inefetivo | Normal, Water, Ice, Flying, Psychic, Rock, Dragon |
| Imune | Electric |

O jogo escreve "Crystal Onix é imune a" onde a wiki fala em "nulo contra o ataque".

## Dados: informações nas telas do jogo

A Pokédex do jogo traz, para cada pokémon:

- **Tipos**: o Venusaur (#003, T3) aparece com os ícones Grass e Poison.
- **Efetividades**: listas "Efetivo contra", "Normal contra" e "Inefetivo contra" aquele pokémon.
- **Golpes**: cada golpe mostra nome, nível, recarga, descrição e o elemento.

Exemplo de golpe:

| Campo | Vine Whip (Venusaur) |
|---|---|
| Nível | 80 |
| Recarga | 20 s |
| Descrição | Causa dano em área frontal. Em alguns casos, a área é em torno do Pokémon. |
| Ícones | Um ícone de Grass e dois outros, cujo significado não foi identificado |
| Dano | Não aparece no print |

## Dados: exemplo de boss (Kame)

A página do boss na wiki informa:

- O Kame é do tipo **Water** e tem fraqueza a **Electric** e **Grass**.
- O ideal é usar pokémons dos elementos que causam dano a ele **e** que resistem a ele.
- Não é recomendado usar **tanques** de elementos que recebam dano normal (1x), mesmo que tenham efetividade sobre o Kame.

## Interpretações a confirmar

Deduções a partir dos dados acima, não informações do jogo:

1. **O multiplicador sai dos dois tipos do defensor.** A ideia é comparar o ataque com cada tipo do defensor e aplicar a tabela de tipo duplo. Só deu para conferir um caso, porque só veio a tabela de ataque de Grass: Grass e Poison resistem a Grass, logo 0,5x, "Muito Inefetivo", como o jogo mostra.
2. **A efetividade depende do tipo do golpe, não do pokémon.** A wiki diz que os golpes têm tipo próprio e o jogo mostra o elemento em cada golpe. Assim, um mesmo pokémon pode ter multiplicadores diferentes por skill contra o mesmo boss.
3. **Golpes do tipo Crystal.** As listas de defesa sugerem que eles existem, mas falta a linha de ataque de Crystal, porque ele não aparece na aba Ataque. O dono não conhece nenhum.
4. **Os bosses seguem as mesmas tabelas.** A página do Kame usa os mesmos termos, mas não há confirmação dos números.
5. **O dummy Neutro vale 1x.** O cálculo por Efetividade depende disso. Para conferir, teste um golpe no Neutro e em um dummy em que o jogo diga que ele é Super Efetivo: o dano deve dobrar. Ainda não foi medido.
