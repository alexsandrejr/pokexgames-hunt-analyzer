<script lang="ts">
  // Página DPS: aba Ranking (dano no boss) e aba Pokémons (cadastro), como dps_widget.py.
  import { message, open } from "@tauri-apps/plugin-dialog";
  import Icon from "../lib/Icon.svelte";
  import { api, type Boss, type DpsOptions, type ImportPlan, type PokemonChoice } from "../lib/api";
  import { announce } from "../lib/status.svelte";
  import ExportDialog from "./dps/ExportDialog.svelte";
  import ImportDialog from "./dps/ImportDialog.svelte";
  import PokemonsTab from "./dps/PokemonsTab.svelte";
  import RankingTab from "./dps/RankingTab.svelte";
  import SettingsDialog from "./dps/SettingsDialog.svelte";

  const TRANSFER_FILTERS = [
    { name: "Cadastros do DPS", extensions: ["json"] },
    { name: "Todos os arquivos", extensions: ["*"] },
  ];

  let tab = $state<"ranking" | "pokemons">("ranking");
  let options = $state<DpsOptions | null>(null);
  /** Sobe a cada mudança nos cadastros: as duas abas recarregam. */
  let version = $state(0);
  let editingSettings = $state(false);
  let exporting = $state<{ bosses: Boss[]; pokemons: PokemonChoice[] } | null>(null);
  let importing = $state<ImportPlan | null>(null);

  api.dpsOptions().then((value) => (options = value));

  function changed() {
    version += 1;
  }

  async function exportFile() {
    const [bosses, pokemons] = await Promise.all([api.dpsBosses(), api.dpsPokemonChoices()]);
    exporting = { bosses: bosses.bosses, pokemons };
  }

  async function importFile() {
    const path = await open({ title: "Importar cadastros do DPS", filters: TRANSFER_FILTERS, multiple: false });
    if (!path) return;
    try {
      importing = await api.dpsImportPlan(path);
    } catch (e) {
      await message(String(e), { title: "Importar cadastros", kind: "warning" });
    }
  }

  async function applyImport(actions: string[]) {
    importing = null;
    try {
      const result = await api.dpsImportApply(actions);
      changed();
      announce(result.summary);
      if (result.details) await message(result.details, { title: "Importar cadastros", kind: "info" });
    } catch (e) {
      await message(String(e), { title: "Importar cadastros", kind: "warning" });
    }
  }
</script>

<header class="page-header">
  <div>
    <h1>DPS</h1>
    <p class="muted">Dano estimado no tempo limite do boss</p>
  </div>
  <div class="actions">
    <button title="Trazer bosses e pokémons de um arquivo exportado" onclick={importFile}>
      <Icon name="import" /> Importar cadastros
    </button>
    <button title="Salvar bosses e pokémons em um arquivo, para enviar a outra pessoa ou guardar" onclick={exportFile}>
      <Icon name="export" /> Exportar cadastros
    </button>
    <button title="Turno do ataque básico e aproveitamentos sugeridos" onclick={() => (editingSettings = true)}>
      <Icon name="settings" /> Ajustes
    </button>
  </div>
</header>

<div class="tabs" role="tablist">
  <button role="tab" class:active={tab === "ranking"} onclick={() => (tab = "ranking")}>Ranking</button>
  <button role="tab" class:active={tab === "pokemons"} onclick={() => (tab = "pokemons")}>Pokémons</button>
</div>

<div class="content">
  {#if options}
    {#if tab === "ranking"}
      <RankingTab {options} {version} onchanged={changed} />
    {:else}
      <PokemonsTab {options} {version} onchanged={changed} />
    {/if}
  {/if}
</div>

{#if editingSettings}
  <SettingsDialog
    onclose={() => (editingSettings = false)}
    onsaved={() => {
      editingSettings = false;
      changed();
    }}
  />
{/if}

{#if exporting}
  <ExportDialog
    bosses={exporting.bosses}
    pokemons={exporting.pokemons}
    onclose={() => (exporting = null)}
    onexported={(path) => {
      exporting = null;
      announce(`Cadastros exportados: ${path}`);
    }}
  />
{/if}

{#if importing}
  <ImportDialog plan={importing} onclose={() => (importing = null)} onconfirm={applyImport} />
{/if}

<style>
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
  }

  h1 {
    margin: 0;
    font-size: 21px;
    font-weight: 600;
  }

  .page-header p {
    margin: 4px 0 0;
  }

  .actions {
    display: flex;
    gap: 8px;
  }

  .tabs {
    display: flex;
    gap: 4px;
    margin-top: 16px;
  }

  .tabs button {
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    background: transparent;
    padding: 8px 16px;
    color: var(--muted);
  }

  .tabs button.active {
    color: var(--text);
    border-bottom-color: var(--accent);
  }

  .content {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    padding-top: 14px;
  }
</style>
