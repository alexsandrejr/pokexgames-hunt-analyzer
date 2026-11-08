<script lang="ts">
  // Marca o que vai no arquivo; tudo começa marcado (DpsExportDialog).
  import { save } from "@tauri-apps/plugin-dialog";
  import Modal from "../../components/Modal.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { api, type Boss, type PokemonChoice } from "../../lib/api";

  let {
    bosses,
    pokemons,
    onclose,
    onexported,
  }: { bosses: Boss[]; pokemons: PokemonChoice[]; onclose: () => void; onexported: (path: string) => void } =
    $props();

  // O diálogo abre do zero a cada vez: os valores iniciais bastam.
  // svelte-ignore state_referenced_locally
  let bossIds = $state(new Set(bosses.map((b) => b.id)));
  // svelte-ignore state_referenced_locally
  let pokemonIds = $state(new Set(pokemons.map((p) => p.id)));
  let error = $state("");

  const columns = $derived([
    { title: "Bosses", items: bosses.map((b) => ({ id: b.id, label: b.name })), kind: "bosses" as const },
    { title: "Pokémons", items: pokemons.map((p) => ({ id: p.id, label: p.name })), kind: "pokemons" as const },
  ]);

  function setOf(kind: "bosses" | "pokemons") {
    return kind === "bosses" ? bossIds : pokemonIds;
  }

  function update(kind: "bosses" | "pokemons", next: Set<number>) {
    if (kind === "bosses") bossIds = next;
    else pokemonIds = next;
  }

  function toggle(kind: "bosses" | "pokemons", id: number, on: boolean) {
    const next = new Set(setOf(kind));
    if (on) next.add(id);
    else next.delete(id);
    update(kind, next);
  }

  async function exportFile() {
    if (bossIds.size === 0 && pokemonIds.size === 0) {
      error = "Marque ao menos um boss ou pokémon.";
      return;
    }
    try {
      const path = await save({
        title: "Salvar cadastros do DPS",
        defaultPath: await api.dpsExportPath(),
        filters: [{ name: "Cadastros do DPS", extensions: ["json"] }],
      });
      if (!path) return;
      await api.dpsExport(path, [...bossIds], [...pokemonIds]);
      onexported(path);
    } catch (e) {
      error = String(e);
    }
  }
</script>

<Modal title="Exportar cadastros do DPS" width={640} height={520} {error} {onclose}>
  <div class="lists">
    {#each columns as column (column.kind)}
      <div class="column">
        <h3 class="section-title">{column.title}</h3>
        <div class="row">
          <button onclick={() => update(column.kind, new Set(column.items.map((i) => i.id)))}>Marcar todos</button>
          <button onclick={() => update(column.kind, new Set())}>Desmarcar todos</button>
        </div>
        <ul class="check-list panel">
          {#each column.items as item (item.id)}
            <li>
              <label>
                <input
                  type="checkbox"
                  checked={setOf(column.kind).has(item.id)}
                  onchange={(e) => toggle(column.kind, item.id, e.currentTarget.checked)}
                />
                {item.label}
              </label>
            </li>
          {/each}
        </ul>
      </div>
    {/each}
  </div>
  <p class="muted">
    Os pokémons levam os testes, com as datas, e os nomes dos bosses em que estão anexados. Os ajustes da página não
    entram no arquivo.
  </p>
  {#snippet footer()}
    <button onclick={onclose}>Cancelar</button>
    <button class="primary" onclick={exportFile}><Icon name="export" /> Exportar…</button>
  {/snippet}
</Modal>

<style>
  p {
    margin: 0;
  }

  .lists {
    flex: 1;
    min-height: 0;
    display: flex;
    gap: 14px;
  }

  .column {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .row {
    display: flex;
    gap: 8px;
  }

  .check-list {
    flex: 1;
    min-height: 0;
  }
</style>
