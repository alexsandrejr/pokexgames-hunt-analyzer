<script lang="ts">
  // Painel de filtros (como FilterPanel): cabeçalho recolhível com o resumo dos filtros ativos
  // e o formulário. O Rust monta e guarda o filtro; campos vazios não filtram nada.
  import Icon from "../lib/Icon.svelte";
  import { emptyForm, filterPanel } from "../lib/filters.svelte";
  import { sessions, type FilterSetup } from "../lib/sessions";

  const ADVANCED_HELP = [
    "Condições separadas por “e”, “;” ou “&”, todas combinadas.",
    "• Item ou inimigo: nightmare ore > 50   ·   Mecha Charizard >= 40   ·   metal scraps",
    "• Métricas: profit/h >= 800k   ·   kills/h > 300   ·   duração >= 1h30",
    "• Operadores: >  >=  =  <=  <",
    "• Para forçar o tipo: drop: nome   ·   supply: nome   ·   inimigo: nome",
  ].join("\n");

  let setup = $state<FilterSetup | null>(null);
  let errors = $state<string[]>([]);
  let invalid = $state<string[]>([]);
  const form = filterPanel.form;

  const custom = $derived(form.preset === "custom");
  const itemOptions = $derived(form.item_source === "supplies" ? setup?.supply_items : setup?.drop_items);

  // As listas de players, inimigos e itens mudam com as importações: recarrega a cada versão.
  $effect(() => {
    void filterPanel.version;
    sessions.filterSetup().then((value) => {
      setup = value;
      filterPanel.parts = value.parts;
    });
  });

  async function presetChanged() {
    if (form.preset === "custom") return;
    const [from, to] = await sessions.presetRange(form.preset);
    if (from && to) {
      form.date_from = from;
      form.date_to = to;
    }
  }

  async function apply() {
    const result = await sessions.filterApply($state.snapshot(form));
    errors = result.errors;
    invalid = result.invalid;
    if (!result.errors.length) {
      filterPanel.parts = result.parts;
      filterPanel.version += 1;
    }
  }

  async function clear() {
    Object.assign(form, { ...emptyForm(), date_from: form.date_from, date_to: form.date_to });
    errors = [];
    invalid = [];
    await sessions.filterClear();
    filterPanel.parts = [];
    filterPanel.version += 1;
  }

  function onkeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && (event.target as HTMLElement).tagName === "INPUT") apply();
  }

  /** Ao digitar de novo, o campo deixa de ficar marcado como inválido. */
  function touched(field: string) {
    invalid = invalid.filter((f) => f !== field);
  }
</script>

<section class="filter-panel">
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="header" onclick={() => (filterPanel.expanded = !filterPanel.expanded)}>
    <span class="toggle"><Icon name="filter" /> Filtros</span>
    {#if filterPanel.parts.length}<span class="badge">{filterPanel.parts.length}</span>{/if}
    <span class="summary muted" title={filterPanel.parts.join("\n")}>
      {filterPanel.parts.length ? filterPanel.parts.join("  ·  ") : "Nenhum filtro ativo"}
    </span>
    {#if filterPanel.parts.length}
      <button
        class="ghost"
        onclick={(e) => {
          e.stopPropagation();
          clear();
        }}><Icon name="close" /> Limpar</button
      >
    {/if}
    <span class="chevron"><Icon name={filterPanel.expanded ? "chevron-down" : "chevron-right"} /></span>
  </div>

  {#if filterPanel.expanded && setup}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="body" {onkeydown}>
      <div class="columns">
        <div class="form">
          <span>Período</span>
          <div class="row">
            <select class="grow" bind:value={form.preset} onchange={presetChanged}>
              {#each setup.presets as preset (preset.value)}
                <option value={preset.value}>{preset.label}</option>
              {/each}
            </select>
            <input type="date" disabled={!custom} bind:value={form.date_from} />
            <span>a</span>
            <input type="date" disabled={!custom} bind:value={form.date_to} />
          </div>
          <span>Player</span>
          <input type="search" list="filter-players" placeholder="Qualquer player" bind:value={form.player} />
          <span>Inimigo</span>
          <div class="row">
            <input
              class="grow"
              type="search"
              list="filter-enemies"
              placeholder="Qualquer inimigo"
              bind:value={form.enemy}
            />
            <select class="operator" bind:value={form.enemy_operator}>
              {#each setup.operators as op (op.value)}<option value={op.value}>{op.label}</option>{/each}
            </select>
            <input
              class="quantity"
              class:invalid={invalid.includes("enemy_quantity")}
              type="text"
              placeholder="qtd."
              bind:value={form.enemy_quantity}
              oninput={() => touched("enemy_quantity")}
            />
          </div>
          <span>Item</span>
          <div class="row">
            <select bind:value={form.item_source}>
              {#each setup.item_sources as source (source.value)}<option value={source.value}>{source.label}</option>{/each}
            </select>
            <input class="grow" type="search" list="filter-items" placeholder="Qualquer item" bind:value={form.item} />
            <select class="operator" bind:value={form.item_operator}>
              {#each setup.operators as op (op.value)}<option value={op.value}>{op.label}</option>{/each}
            </select>
            <input
              class="quantity"
              class:invalid={invalid.includes("item_quantity")}
              type="text"
              placeholder="qtd."
              bind:value={form.item_quantity}
              oninput={() => touched("item_quantity")}
            />
          </div>
        </div>
        <div class="form">
          {#each setup.metrics as [key, label, example], index (key)}
            <span>{label}</span>
            <div class="row">
              <select class="operator" bind:value={form.metrics[index][1].operator}>
                {#each setup.operators as op (op.value)}<option value={op.value}>{op.label}</option>{/each}
              </select>
              <input
                class="grow"
                class:invalid={invalid.includes(key)}
                type="text"
                placeholder={example}
                bind:value={form.metrics[index][1].value}
                oninput={() => touched(key)}
              />
            </div>
          {/each}
        </div>
      </div>
      <div class="form">
        <span>Avançada</span>
        <input
          type="text"
          class:invalid={invalid.includes("advanced")}
          title={ADVANCED_HELP}
          placeholder="Pesquisa avançada — ex.: nightmare ore > 50 e nightmare gem > 1000; kills/h >= 300"
          bind:value={form.advanced}
          oninput={() => touched("advanced")}
        />
      </div>
      <div class="footer">
        <p class="hint grow">
          Todos os critérios são combinados (E). Campos vazios não filtram. Valores aceitam 800k, 1,2kk ou 1.000.000.
        </p>
        {#if errors.length}<p class="error-label grow">{errors.join(" ")}</p>{/if}
        <button class="primary" onclick={apply}>Aplicar filtros</button>
      </div>
      <datalist id="filter-players">{#each setup.players as name (name)}<option value={name}></option>{/each}</datalist>
      <datalist id="filter-enemies">{#each setup.enemies as name (name)}<option value={name}></option>{/each}</datalist>
      <datalist id="filter-items">{#each itemOptions ?? [] as name (name)}<option value={name}></option>{/each}</datalist>
    </div>
  {/if}
</section>

<style>
  .filter-panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 8px 10px 8px 14px;
  }

  .header {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    min-height: 28px;
  }

  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
  }

  .badge {
    background: var(--accent-soft);
    border-radius: 9px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 600;
  }

  .summary {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ghost {
    background: transparent;
    border: none;
    color: var(--muted);
    padding: 4px 8px;
  }

  .ghost:hover {
    color: var(--text);
    background: var(--surface-alt);
  }

  .chevron {
    display: inline-flex;
    padding: 4px;
    border-radius: 6px;
  }

  .chevron:hover {
    background: var(--surface-alt);
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 6px 4px 4px 2px;
  }

  .columns {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
    gap: 14px;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }

  .grow {
    flex: 1;
    min-width: 0;
  }

  .operator {
    width: 64px;
    min-width: 64px;
  }

  .quantity {
    width: 90px;
  }

  input[type="date"] {
    width: 130px;
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
  }

  input.invalid {
    border-color: var(--negative);
  }

  .footer {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .footer p {
    margin: 0;
  }
</style>
