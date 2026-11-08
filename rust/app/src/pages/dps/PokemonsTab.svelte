<script lang="ts">
  // Aba Pokémons: todos os cadastrados, em qualquer boss ou em nenhum (dps_pokemons_tab.py).
  import { ask } from "@tauri-apps/plugin-dialog";
  import RecordTable from "../../components/RecordTable.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { api, type DpsOptions, type PokemonRow, type SkillLine } from "../../lib/api";
  import { announce } from "../../lib/status.svelte";
  import type { Column } from "../../lib/table";
  import PokemonDialog from "./PokemonDialog.svelte";
  import TestsDialog from "./TestsDialog.svelte";

  let { options, version, onchanged }: { options: DpsOptions; version: number; onchanged: () => void } = $props();

  let pokemons = $state<PokemonRow[]>([]);
  let selectedId = $state<number | null>(null);
  let search = $state("");
  let visibleCount = $state(0);
  let dummy = $state("neutral");
  let error = $state("");
  let editing = $state<{ id: number | null } | null>(null);
  let testing = $state<PokemonRow | null>(null);
  /** Pokémon a selecionar quando a lista recarregar (o novo, o duplicado ou o editado). */
  let pendingSelect: number | null = null;

  const selected = $derived(pokemons.find((p) => p.id === selectedId) ?? null);

  const columns: Column<PokemonRow>[] = [
    { title: "Nome", value: (p) => p.name },
    { title: "Skills", value: (p) => p.skill_count_text, sort: (p) => p.skill_count, numeric: true, fit: true },
    { title: "Básico", value: (p) => p.basic, fit: true, tooltip: "Aproveitamento · elemento" },
    { title: "Buff", value: (p) => p.buff, fit: true, tooltip: "Efeitos / recarga; “magia” é a próxima magia" },
    { title: "Bosses", value: (p) => p.bosses },
    { title: "Observação", value: (p) => p.note_line },
  ];

  type SkillItem = SkillLine & { index: number };
  const skillColumns: Column<SkillItem>[] = [
    { title: "Skill", value: (s) => s.label, fit: true },
    { title: "Forma", value: (s) => s.shape },
    { title: "Alcance", value: (s) => s.reach },
    { title: "Elemento", value: (s) => s.element },
    { title: "Dano", value: (s) => s.damage, numeric: true, fit: true },
    { title: "Recarga (s)", value: (s) => s.cooldown, numeric: true },
    { title: "Aproveitamento", value: (s) => s.efficiency, numeric: true, fit: true },
    {
      title: "Testes",
      value: (s) => s.tests,
      numeric: true,
      fit: true,
      tooltip: "Quantos dummies e bosses foram testados nesta skill",
    },
  ];
  const skills = $derived<SkillItem[]>(selected ? selected.skills.map((s, index) => ({ ...s, index })) : []);

  $effect(() => {
    void version;
    api
      .dpsPokemons(dummy)
      .then((value) => {
        pokemons = value;
        if (pendingSelect !== null) selectedId = pendingSelect;
        pendingSelect = null;
      })
      .catch((e) => (error = String(e)));
  });

  function changed(pokemonId: number | null, message: string) {
    pendingSelect = pokemonId;
    onchanged();
    announce(message);
  }

  async function run(action: () => Promise<void>) {
    try {
      error = "";
      await action();
    } catch (e) {
      error = String(e);
    }
  }

  function duplicate() {
    const pokemon = selected;
    if (pokemon)
      run(async () => changed(await api.dpsDuplicatePokemon(pokemon.id), `${pokemon.name} duplicado.`));
  }

  async function remove() {
    const pokemon = selected;
    if (!pokemon) return;
    const confirmed = await ask(`Excluir ${pokemon.name}?\n\nEle será apagado de todos os bosses.`, {
      title: "Excluir pokémon",
      kind: "warning",
      okLabel: "Sim",
      cancelLabel: "Não",
    });
    if (confirmed)
      run(async () => {
        await api.dpsDeletePokemon(pokemon.id);
        changed(null, "Pokémon excluído.");
      });
  }
</script>

<div class="toolbar">
  <input type="search" class="search" placeholder="Pesquisar pokémon…" bind:value={search} />
  <span class="muted">{visibleCount} de {pokemons.length} pokémons</span>
  <div class="grow"></div>
  <button class="danger" disabled={!selected} onclick={remove}><Icon name="trash" /> Excluir</button>
  <button disabled={!selected} title="Copiar o pokémon, para comparar outra build" onclick={duplicate}>
    <Icon name="copy" /> Duplicar
  </button>
  <button
    disabled={!selected}
    title="Danos medidos nos dummies e nos bosses, por skill e no ataque básico"
    onclick={() => (testing = selected)}>Testes</button
  >
  <button disabled={!selected} onclick={() => selected && (editing = { id: selected.id })}>Editar</button>
  <button class="primary" onclick={() => (editing = { id: null })}>Novo</button>
</div>
{#if error}<p class="warning">{error}</p>{/if}

{#if pokemons.length === 0}
  <div class="empty">
    <h2>Nenhum pokémon cadastrado</h2>
    <p class="muted">Use “Novo” para cadastrar o primeiro.</p>
  </div>
{:else}
  <div class="list">
    <div class="main-table">
      <RecordTable
        {columns}
        rows={pokemons}
        rowKey={(p) => p.id}
        bind:selected={selectedId}
        bind:visibleCount
        {search}
        onactivate={(p) => (editing = { id: p.id })}
        ondelete={remove}
      />
    </div>
    <div class="title">
      <h3 class="section-title">{selected?.name ?? ""}</h3>
      <span class="muted">{selected?.basic_damage ?? ""}</span>
      <div class="grow"></div>
      <span class="field-label">Ver dano no dummy</span>
      <select bind:value={dummy}>
        {#each options.dummies as d (d.value)}
          <option value={d.value}>{d.label}</option>
        {/each}
      </select>
    </div>
    {#if selected?.note}<p class="muted note">{selected.note}</p>{/if}
    <div class="skills-table">
      <RecordTable columns={skillColumns} rows={skills} rowKey={(s) => s.index} sortable={false} selectable={false} />
    </div>
  </div>
{/if}

{#if editing}
  <PokemonDialog
    pokemonId={editing.id}
    dummy="neutral"
    {options}
    onclose={() => (editing = null)}
    onsaved={(id, name) => {
      const created = editing?.id === null;
      editing = null;
      changed(id, created ? `${name} cadastrado. Anexe-o a um boss na aba Ranking.` : `${name} salvo.`);
    }}
  />
{/if}

{#if testing}
  <TestsDialog
    pokemonId={testing.id}
    onclose={() => {
      const { id, name } = testing!;
      testing = null;
      changed(id, `Testes de ${name} salvos.`);
    }}
  />
{/if}

<style>
  .toolbar {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .search {
    flex: 1;
    min-width: 130px;
    max-width: 300px;
  }

  .grow {
    flex: 1;
  }

  p {
    margin: 0;
  }

  .empty {
    padding: 40px 0;
  }

  .empty h2 {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
  }

  .list {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 12px;
  }

  .main-table {
    flex: 3;
    min-height: 0;
    display: flex;
  }

  .skills-table {
    flex: 2;
    min-height: 0;
    display: flex;
  }

  .main-table > :global(*),
  .skills-table > :global(*) {
    flex: 1;
  }

  .title {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .note {
    white-space: pre-wrap;
  }
</style>
