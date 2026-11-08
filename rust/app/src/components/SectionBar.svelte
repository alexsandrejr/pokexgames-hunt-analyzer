<script lang="ts">
  // Sub-navegação de uma seção (como SectionBar): botões arredondados, um deles marcado.
  let {
    items,
    current,
    onselect,
  }: { items: { key: string; label: string }[]; current: string; onselect: (key: string) => void } = $props();
</script>

<nav class="section-bar">
  {#each items as item (item.key)}
    <button class:checked={item.key === current} onclick={() => onselect(item.key)}>{item.label}</button>
  {/each}
</nav>

<style>
  .section-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    padding: 16px 28px 0 26px;
  }

  button {
    border: 1px solid transparent;
    border-radius: 14px;
    background: transparent;
    color: var(--muted);
    padding: 5px 14px;
  }

  button:hover {
    background: var(--surface-hover);
    color: var(--text);
    border-color: transparent;
  }

  /* Sem negrito ao marcar, como no Python: a largura não muda. */
  button.checked {
    background: var(--accent-soft);
    color: var(--accent);
  }
</style>
