<script lang="ts">
  // Lista de marcação com os pokémons que podem lutar contra o boss (BossPokemonsDialog).
  import Modal from "../../components/Modal.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { api, type Boss, type PokemonChoice } from "../../lib/api";

  let {
    boss,
    pokemons,
    onclose,
    onsaved,
  }: { boss: Boss; pokemons: PokemonChoice[]; onclose: () => void; onsaved: () => void } = $props();

  // svelte-ignore state_referenced_locally
  let checked = $state(new Set<number>(boss.pokemon_ids));
  let search = $state("");
  let error = $state("");

  const needle = $derived(search.trim().toLowerCase());
  const visible = $derived(pokemons.filter((p) => p.label.toLowerCase().includes(needle)));

  function toggle(id: number, on: boolean) {
    const next = new Set(checked);
    if (on) next.add(id);
    else next.delete(id);
    checked = next;
  }

  function checkVisible(on: boolean) {
    const next = new Set(checked);
    for (const p of visible) {
      if (on) next.add(p.id);
      else next.delete(p.id);
    }
    checked = next;
  }

  /** Inclui os marcados que a pesquisa escondeu. */
  async function save() {
    try {
      await api.dpsSetBossPokemons(boss.id, [...checked]);
      onsaved();
    } catch (e) {
      error = String(e);
    }
  }
</script>

<Modal title="Pokémons de {boss.name}" width={460} height={560} {error} {onclose}>
  <input type="search" placeholder="Pesquisar pokémon…" bind:value={search} />
  <div class="row">
    <button onclick={() => checkVisible(true)}>Marcar visíveis</button>
    <button onclick={() => checkVisible(false)}>Desmarcar visíveis</button>
  </div>
  <ul class="check-list panel">
    {#each visible as pokemon (pokemon.id)}
      <li>
        <label>
          <input
            type="checkbox"
            checked={checked.has(pokemon.id)}
            onchange={(e) => toggle(pokemon.id, e.currentTarget.checked)}
          />
          {pokemon.label}
        </label>
      </li>
    {/each}
  </ul>
  {#snippet footer()}
    <button onclick={onclose}>Cancelar</button>
    <button class="primary" onclick={save}><Icon name="check" /> Salvar</button>
  {/snippet}
</Modal>

<style>
  .row {
    display: flex;
    gap: 8px;
  }

  .check-list {
    flex: 1;
    min-height: 0;
  }
</style>
