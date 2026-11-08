<script lang="ts">
  // Detalhes de uma sessão (como HuntDetailsDialog): Resumo, Enemies, Drops, Supplies e o JSON
  // original, com as recompensas do chat. `onchanged` avisa a lista quando os drops mudam.
  import { ask, message } from "@tauri-apps/plugin-dialog";
  import Modal from "../../components/Modal.svelte";
  import RankedChart from "../../components/RankedChart.svelte";
  import RecordTable from "../../components/RecordTable.svelte";
  import StatCard from "../../components/StatCard.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { sessions, type HuntDetails, type ListTab } from "../../lib/sessions";
  import { viewColumns, type RowView } from "../../lib/table";
  import ChatRewardsDialog from "./ChatRewardsDialog.svelte";

  let { huntId, onclose, onchanged }: { huntId: number; onclose: () => void; onchanged: () => void } = $props();

  type Tab = "summary" | "enemies" | "drops" | "supplies" | "charts" | "json";
  let hunt = $state<HuntDetails | null>(null);
  let tab = $state<Tab>("summary");
  let addingChat = $state(false);
  let copied = $state(false);

  const lists = $derived<[Tab, string, ListTab][]>(
    hunt
      ? [
          ["enemies", "Enemies", hunt.enemies],
          ["drops", "Drops", hunt.drops],
          ["supplies", "Supplies", hunt.supplies],
        ]
      : [],
  );

  async function load(): Promise<boolean> {
    const value = await sessions.details(huntId);
    if (value === null) {
      await message("A Hunt selecionada não existe mais no banco de dados.", {
        title: "Hunt não encontrada",
        kind: "warning",
      });
      onchanged();
      onclose();
      return false;
    }
    hunt = value;
    return true;
  }

  load();

  async function chatAdded() {
    addingChat = false;
    onchanged();
    if (await load()) tab = "drops";
  }

  async function removeChat() {
    if (!hunt?.chat_messages.length) return;
    const confirmed = await ask(
      "Remover desta sessão todos os drops vindos de mensagens do chat?\n\nRaw gains e Profit voltam aos valores sem esses itens.",
      { title: "Remover recompensas do chat", kind: "warning", okLabel: "Sim", cancelLabel: "Não" },
    );
    if (!confirmed) return;
    await sessions.chatRemove(huntId);
    onchanged();
    await load();
  }

  async function copyJson() {
    if (!hunt) return;
    await navigator.clipboard.writeText(hunt.json);
    copied = true;
  }
</script>

<Modal title={hunt?.title ?? "Sessão"} width={1040} height={720} {onclose}>
  {#if hunt}
    <div class="header">
      <div class="titles">
        <h1>{hunt.title}</h1>
        <p class="muted">{hunt.subtitle}</p>
      </div>
      <button
        title={'Somar aos drops os itens de mensagens "Você recebeu:" que não vieram no JSON (ex.: sacolas de boss)'}
        onclick={() => (addingChat = true)}><Icon name="paste" /> Recompensas do chat…</button
      >
      <button
        class="danger"
        disabled={!hunt.chat_messages.length}
        title={hunt.chat_messages.length
          ? `Tirar desta sessão os drops vindos do chat:\n${hunt.chat_messages.join("\n")}`
          : "Nenhuma recompensa do chat nesta sessão."}
        onclick={removeChat}><Icon name="trash" /> Remover do chat</button
      >
    </div>

    <div class="tabs" role="tablist">
      <button role="tab" class:active={tab === "summary"} onclick={() => (tab = "summary")}>Resumo</button>
      {#each lists as [key, label, list] (key)}
        <button role="tab" class:active={tab === key} onclick={() => (tab = key)}>
          {label} ({list.table.rows.length})
        </button>
      {/each}
      <button role="tab" class:active={tab === "charts"} onclick={() => (tab = "charts")}>Gráficos</button>
      <button role="tab" class:active={tab === "json"} onclick={() => (tab = "json")}>JSON Original</button>
    </div>

    <div class="tab-body">
      {#if tab === "summary"}
        <div class="scroll">
          <div class="cards">
            {#each hunt.cards as card (card.title)}
              <StatCard title={card.title} value={card.value} hint={card.hint} />
            {/each}
          </div>
          <div class="groups">
            {#each hunt.groups as group (group.title)}
              <section class="card group">
                <h3 class="section-title">{group.title}</h3>
                {#each group.fields as [label, value] (label)}
                  <span class="field-label">{label}</span>
                  <span class="field-value">{value}</span>
                {/each}
              </section>
            {/each}
          </div>
        </div>
      {:else if tab === "charts"}
        <div class="scroll">
          {#each hunt.charts as chart (chart.title)}
            <RankedChart {chart} />
          {:else}
            <div class="empty">
              <h2>Sem gráficos</h2>
              <p class="muted">Esta Hunt tem poucos inimigos e itens para comparar.</p>
            </div>
          {/each}
        </div>
      {:else if tab === "json"}
        <div class="bar">
          <span class="muted grow">JSON exatamente como foi importado (formatado para leitura).</span>
          {#if copied}<span class="muted">Copiado!</span>{/if}
          <button onclick={copyJson}><Icon name="copy" /> Copiar JSON</button>
        </div>
        <pre class="json panel">{hunt.json}</pre>
      {:else}
        {@const list = lists.find(([key]) => key === tab)![2]}
        <p class="muted list-summary">
          {#each list.summary as [label, value], i (label)}
            {#if i > 0}&nbsp;·&nbsp;{/if}{label}: <strong>{value}</strong>
          {/each}
        </p>
        {#if list.table.rows.length}
          {#key tab}
            <RecordTable
              columns={viewColumns(list.table.columns)}
              rows={list.table.rows}
              rowKey={(r: RowView) => r.id}
              multiple
              sortColumn={list.sort_column}
              sortAscending={false}
            />
          {/key}
        {:else}
          <div class="empty">
            <h2>Sem registros</h2>
            <p class="muted">{list.empty_message}</p>
          </div>
        {/if}
      {/if}
    </div>
  {/if}
</Modal>

{#if addingChat}
  <ChatRewardsDialog {huntId} onclose={() => (addingChat = false)} onadded={chatAdded} />
{/if}

<style>
  .header {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }

  .titles {
    flex: 1;
    min-width: 0;
  }

  h1 {
    margin: 0;
    font-size: 21px;
    font-weight: 600;
  }

  .titles p {
    margin: 4px 0 0;
  }

  .tabs {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--border);
  }

  .tabs button {
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    background: transparent;
    padding: 8px 14px;
    color: var(--muted);
  }

  .tabs button.active {
    color: var(--text);
    border-bottom-color: var(--accent);
  }

  .tab-body {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .tab-body > :global(.wrap) {
    flex: 1;
  }

  .scroll {
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 14px;
  }

  .groups {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 14px;
    align-items: start;
  }

  .group {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 8px 24px;
    padding: 16px 18px;
  }

  .group h3 {
    grid-column: 1 / -1;
  }

  .field-value {
    text-align: right;
    font-weight: 600;
    user-select: text;
    overflow-wrap: anywhere;
  }

  .list-summary {
    margin: 0;
  }

  .list-summary strong {
    color: var(--text);
  }

  .bar {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .grow {
    flex: 1;
  }

  .json {
    flex: 1;
    min-height: 0;
    margin: 0;
    padding: 10px 12px;
    overflow: auto;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 13px;
    user-select: text;
  }

  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }

  .empty h2 {
    margin: 0;
    font-size: 17px;
    font-weight: 600;
  }

  .empty p {
    margin: 6px 0 0;
  }
</style>
