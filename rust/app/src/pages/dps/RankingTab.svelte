<script lang="ts">
  // Ranking dos pokémons anexados ao boss e de onde vem o dano de cada um (RankingTab do Python).
  import { ask, message } from "@tauri-apps/plugin-dialog";
  import Icon from "../../lib/Icon.svelte";
  import { api, type Boss, type DamageSource, type DpsOptions, type PokemonChoice, type RankingEntry } from "../../lib/api";
  import { announce } from "../../lib/status.svelte";
  import BossDialog from "./BossDialog.svelte";
  import BossPokemonsDialog from "./BossPokemonsDialog.svelte";
  import PokemonDialog from "./PokemonDialog.svelte";

  let { options, version, onchanged }: { options: DpsOptions; version: number; onchanged: () => void } = $props();

  let bosses = $state<Boss[]>([]);
  let bossId = $state<number | null>(null);
  let entries = $state<RankingEntry[]>([]);
  let selectedId = $state<number | null>(null);
  let error = $state("");
  let menuOpen = $state(false);
  let bossDialog = $state<{ id: number | null } | null>(null);
  let choosing = $state<PokemonChoice[] | null>(null);
  let editing = $state<RankingEntry | null>(null);

  const boss = $derived(bosses.find((b) => b.id === bossId) ?? null);
  const selected = $derived(entries.find((e) => e.pokemon_id === selectedId) ?? entries[0] ?? null);
  // A tabela do detalhamento vem do maior para o menor dano, como no Python.
  const lines = $derived(selected ? [...selected.lines].sort((a, b) => b.total - a.total) : []);

  async function run(action: () => Promise<unknown>) {
    try {
      error = "";
      await action();
    } catch (e) {
      error = String(e);
    }
  }

  async function refresh() {
    await run(async () => {
      const data = await api.dpsBosses();
      bosses = data.bosses;
      if (bossId === null || !bosses.some((b) => b.id === bossId)) {
        bossId = bosses.some((b) => b.id === data.last_boss_id) ? data.last_boss_id : (bosses[0]?.id ?? null);
      }
      entries = bossId === null ? [] : await api.dpsRanking(bossId);
    });
  }

  async function chooseBoss(id: number) {
    bossId = id;
    await run(() => api.dpsRememberBoss(id));
    await refresh();
  }

  async function setSource(source: DamageSource) {
    if (boss) await run(() => api.dpsSetSource(boss.id, source));
    onchanged();
  }

  async function setDummy(dummy: string) {
    if (boss) await run(() => api.dpsSetDummy(boss.id, dummy));
    onchanged();
  }

  async function removeSelected() {
    const [current, entry] = [boss, selected];
    if (!current || !entry) return;
    await run(() => api.dpsRemoveFromBoss(current.id, entry.pokemon_id));
    onchanged();
    announce(`${entry.name} removido de ${current.name}.`);
  }

  async function choosePokemons() {
    if (!boss) return;
    const pokemons = await api.dpsPokemonChoices();
    if (pokemons.length === 0) {
      await message("Cadastre um pokémon na aba Pokémons primeiro.", { title: "Adicionar ao boss", kind: "info" });
      return;
    }
    choosing = pokemons;
  }

  async function deleteBoss() {
    menuOpen = false;
    const current = boss;
    if (!current || bosses.length <= 1) return;
    const confirmed = await ask(`Excluir o boss ${current.name}?

Os pokémons continuam cadastrados.`, {
      title: "Excluir boss",
      kind: "warning",
      okLabel: "Sim",
      cancelLabel: "Não",
    });
    if (confirmed) {
      await run(() => api.dpsDeleteBoss(current.id));
      onchanged();
    }
  }

  function openBossDialog(id: number | null) {
    menuOpen = false;
    bossDialog = { id };
  }

  $effect(() => {
    void version;
    refresh();
  });
</script>

<svelte:window onclick={() => (menuOpen = false)} />

<div class="bar">
  <div class="row">
    <span class="field-label">Boss</span>
    <select value={bossId} onchange={(e) => chooseBoss(Number(e.currentTarget.value))}>
      {#each bosses as b (b.id)}
        <option value={b.id}>{b.label}</option>
      {/each}
    </select>
    <div class="menu-anchor">
      <button
        onclick={(e) => {
          e.stopPropagation();
          menuOpen = !menuOpen;
        }}
      >
        <Icon name="bosses" /> Gerenciar bosses <Icon name="chevron-down" size={10} />
      </button>
      {#if menuOpen}
        <div class="menu" role="menu">
          <button role="menuitem" onclick={() => openBossDialog(null)}>Novo boss…</button>
          <button role="menuitem" disabled={!boss} onclick={() => boss && openBossDialog(boss.id)}>Editar boss…</button>
          <button role="menuitem" disabled={bosses.length <= 1} onclick={deleteBoss}>Excluir boss…</button>
        </div>
      {/if}
    </div>
    <div class="grow"></div>
    <button class="primary" title="Marcar quais pokémons podem lutar contra este boss" onclick={choosePokemons}>
      Adicionar pokémon
    </button>
  </div>
  <div class="row">
    <span class="field-label">Calcular por</span>
    <select
      value={boss?.damage_source}
      title="Efetividade: teste no dummy Neutro × fraqueza do boss&#10;Dummy: teste no dummy escolhido&#10;Dano real: teste feito dentro deste boss"
      onchange={(e) => setSource(e.currentTarget.value as DamageSource)}
    >
      {#each options.sources as s (s.value)}
        <option value={s.value}>{s.label}</option>
      {/each}
    </select>
    {#if boss?.damage_source === "dummy"}
      <span class="field-label">Dummy</span>
      <select value={boss.dummy} title="De qual dummy vem o dano no ranking deste boss" onchange={(e) => setDummy(e.currentTarget.value)}>
        {#each options.dummies as d (d.value)}
          <option value={d.value}>{d.label}</option>
        {/each}
      </select>
    {/if}
  </div>
  {#if boss && boss.groups.length}
    <div class="groups">
      {#each boss.groups as group (group.title)}
        <span class="group">
          <span class="muted">{group.title}</span>
          {#each group.elements as tag (tag.label)}
            <span class="element-tag" style:background={tag.color} style:color={tag.text_color}>{tag.label}</span>
          {/each}
        </span>
      {/each}
    </div>
  {/if}
  {#if boss?.no_weaknesses}
    <p class="warning">
      Marque as fraquezas em Gerenciar bosses → Editar boss: por enquanto, todos os ataques contam como Normal (1x).
    </p>
  {/if}
  {#if error}<p class="warning">{error}</p>{/if}
</div>

{#if entries.length === 0}
  <div class="empty">
    <h2>Nenhum pokémon neste boss</h2>
    <p class="muted">Use “Adicionar” para anexar os pokémons cadastrados na aba Pokémons.</p>
  </div>
{:else}
  <div class="results">
    <ul class="ranking panel" role="listbox">
      {#each entries as entry (entry.pokemon_id)}
        <li
          role="option"
          aria-selected={entry === selected}
          class:selected={entry === selected}
          title={entry.note}
          onclick={() => (selectedId = entry.pokemon_id)}
          ondblclick={() => (editing = entry)}
          onkeydown={(e) => {
            if (e.key === "Delete") removeSelected();
            else if (e.key === "Enter") editing = entry;
          }}
          tabindex="0"
        >
          <div class="top">
            <span class="name">{entry.position}º&nbsp; {entry.name}</span>
            <strong>{entry.total_text}</strong>
            <span class="muted">{entry.dps_text} DPS</span>
          </div>
          <div class="bar-track"><div class="bar-fill" style:width="{entry.share * 100}%"></div></div>
          {#if entry.warnings}<div class="warning small">{entry.warnings}</div>{/if}
        </li>
      {/each}
    </ul>
    {#if selected}
      <section class="detail">
        <div class="heading">
          <div>
            <h2>{selected.name}</h2>
            <p class="muted">Dano total: {selected.total_text} · DPS: {selected.dps_text}</p>
          </div>
          <div class="actions">
            <button title="Editar o cadastro deste pokémon" onclick={() => (editing = selected)}>
              <Icon name="open" /> Editar
            </button>
            <button title="Tirar o pokémon deste boss, sem apagar o cadastro" onclick={removeSelected}>
              <Icon name="close" /> Remover
            </button>
          </div>
        </div>
        {#if selected.note}<p class="muted note">{selected.note}</p>{/if}
        {#if selected.missing_text}<p class="warning">{selected.missing_text}</p>{/if}
        <div class="panel table-wrap">
          <table class="records">
            <thead>
              <tr>
                <th class="fit">Origem</th>
                <th title="Dano / recarga · aproveitamento">Detalhe</th>
                <th class="numeric fit">Dano total</th>
                <th class="numeric fit">% do total</th>
              </tr>
            </thead>
            <tbody>
              {#each lines as line (line.source)}
                <tr>
                  <td class="fit">{line.source}</td>
                  <td>{line.detail}</td>
                  <td class="numeric">{line.total_text}</td>
                  <td class="numeric">{line.share_text}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>
    {/if}
  </div>
{/if}

{#if bossDialog}
  <BossDialog
    bossId={bossDialog.id}
    {options}
    onclose={() => (bossDialog = null)}
    onsaved={(id) => {
      bossDialog = null;
      onchanged();
      chooseBoss(id);
    }}
  />
{/if}

{#if choosing && boss}
  <BossPokemonsDialog
    {boss}
    pokemons={choosing}
    onclose={() => (choosing = null)}
    onsaved={() => {
      choosing = null;
      onchanged();
    }}
  />
{/if}

{#if editing && boss}
  <PokemonDialog
    pokemonId={editing.pokemon_id}
    dummy={boss.base_dummy}
    {options}
    onclose={() => (editing = null)}
    onsaved={(_, name) => {
      editing = null;
      onchanged();
      announce(`${name} salvo.`);
    }}
  />
{/if}

<style>
  .bar {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .grow {
    flex: 1;
  }

  .menu-anchor {
    position: relative;
  }

  .menu {
    top: calc(100% + 4px);
    left: 0;
  }

  .groups {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    margin-top: 4px;
  }

  .group {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  p {
    margin: 0;
  }

  .empty {
    padding: 40px 0;
  }

  .empty h2,
  .detail h2 {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
  }

  .results {
    flex: 1;
    min-height: 0;
    display: flex;
    gap: 16px;
    margin-top: 12px;
  }

  .ranking {
    flex: 1;
    min-width: 280px;
    margin: 0;
    padding: 4px;
    list-style: none;
    overflow-y: auto;
  }

  .ranking li {
    padding: 8px 10px 10px;
    border-radius: 6px;
    cursor: pointer;
    outline: none;
  }

  .ranking li:hover {
    background: var(--surface-hover);
  }

  .ranking li.selected {
    background: var(--selection);
  }

  .top {
    display: flex;
    align-items: baseline;
    gap: 10px;
  }

  .name {
    flex: 1;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .bar-track {
    height: 12px;
    margin-top: 6px;
    background: var(--surface-alt);
    border-radius: 3px;
    overflow: hidden;
  }

  .bar-fill {
    height: 100%;
    background: var(--accent);
  }

  .small {
    margin-top: 6px;
  }

  .detail {
    flex: 2;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .heading {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
  }

  .heading p {
    margin-top: 2px;
  }

  .actions {
    display: flex;
    gap: 8px;
  }

  .note {
    white-space: pre-wrap;
  }

  .table-wrap {
    flex: 1;
    overflow: auto;
  }
</style>
