<script lang="ts">
  // Páginas da seção Sessões (hunts_widget.py e bosses_widget.py): Todas, Hunts e cada tipo de
  // boss, com o painel de filtros e a lista.
  import FilterPanel from "../components/FilterPanel.svelte";
  import type { CategoryChoice } from "../lib/sessions";
  import BossSummary from "./sessions/BossSummary.svelte";
  import HuntDetails from "./sessions/HuntDetails.svelte";
  import HuntList, { type ListTexts } from "./sessions/HuntList.svelte";

  const IMPORT_HINT = "Clique em Importar, na barra lateral, ou arraste arquivos .json/.tsv para a janela.";

  let {
    pageKey,
    categories,
    version,
    onchanged,
    select = $bindable([]),
  }: {
    /** "all_sessions", "hunts" ou "boss:<categoria>". */
    pageKey: string;
    categories: CategoryChoice[];
    version: number;
    onchanged: () => void;
    select?: number[];
  } = $props();

  const category = $derived(
    pageKey === "all_sessions" ? null : pageKey === "hunts" ? "hunt" : pageKey.replace("boss:", ""),
  );
  const choice = $derived(categories.find((c) => c.value === category));
  const isBoss = $derived(pageKey.startsWith("boss:"));
  /** Aba de cada tipo de boss: Resumo (padrão) ou Lista. */
  let bossTab = $state<"summary" | "list">("summary");
  let detailsId = $state<number | null>(null);

  // As sessões recém-importadas aparecem na Lista, selecionadas.
  $effect(() => {
    if (select.length) bossTab = "list";
  });

  const heading = $derived.by((): { title: string; subtitle: string; texts: ListTexts } => {
    if (pageKey === "all_sessions") {
      return {
        title: "Todas as sessões",
        subtitle: "Hunts e bosses, da mais recente para a mais antiga",
        texts: { singular: "sessão", plural: "sessões", emptyTitle: "Nenhuma sessão importada", emptyMessage: IMPORT_HINT },
      };
    }
    if (pageKey === "hunts") {
      return {
        title: "Hunts",
        subtitle: "Sessões de caça importadas",
        texts: { singular: "Hunt", plural: "Hunts", emptyTitle: "Nenhuma Hunt importada", emptyMessage: IMPORT_HINT },
      };
    }
    const plural = choice?.plural ?? "";
    return {
      title: plural,
      subtitle: `O que você importar agora entra em ${plural}`,
      texts: {
        singular: "sessão",
        plural: "sessões",
        emptyTitle: `Nenhuma sessão de ${plural}`,
        emptyMessage: `Importe com este tipo aberto, ou selecione uma sessão em Hunts e use “Mover” → ${plural}. ${IMPORT_HINT}`,
      },
    };
  });
</script>

<header>
  <h1>{heading.title}</h1>
  <p class="muted">{heading.subtitle}</p>
</header>

<div class="filters">
  <FilterPanel />
</div>

{#if isBoss}
  <div class="tabs" role="tablist">
    <button role="tab" class:active={bossTab === "summary"} onclick={() => (bossTab = "summary")}>Resumo</button>
    <button role="tab" class:active={bossTab === "list"} onclick={() => (bossTab = "list")}>Lista</button>
  </div>
{/if}

{#if isBoss && bossTab === "summary"}
  {#key pageKey}
    <BossSummary category={category!} {version} onopen={(id) => (detailsId = id)} />
  {/key}
{:else}
  <div class="list">
    {#key pageKey}
      <HuntList {category} texts={heading.texts} {categories} {version} {onchanged} bind:select />
    {/key}
  </div>
{/if}

{#if detailsId !== null}
  <HuntDetails huntId={detailsId} onclose={() => (detailsId = null)} onchanged={onchanged} />
{/if}

<style>
  h1 {
    margin: 0;
    font-size: 21px;
    font-weight: 600;
  }

  header p {
    margin: 2px 0 0;
  }

  .filters {
    margin-top: 16px;
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

  .list {
    flex: 1;
    min-height: 260px;
    display: flex;
    flex-direction: column;
    margin-top: 16px;
  }
</style>
