<script lang="ts">
  // Card com título, valor principal e uma dica opcional (como StatCard).
  let { title, value, hint = "", compact = false }: { title: string; value: string; hint?: string; compact?: boolean } =
    $props();
</script>

<div class="card stat" class:compact>
  <div class="title">{title}</div>
  <div class="value">{value}</div>
  {#if hint}<div class="hint">{hint}</div>{/if}
</div>

<style>
  .stat {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 14px 18px;
    min-width: 0;
  }

  .stat.compact {
    gap: 2px;
    padding: 10px 14px;
  }

  .title {
    color: var(--muted);
    font-size: 12px;
  }

  .value {
    font-size: 24px;
    font-weight: 600;
    overflow-wrap: anywhere;
    user-select: text;
  }

  /* A dica pode ter duas linhas (
), como no resumo por categoria do Início. */
  .stat .hint {
    white-space: pre-line;
  }

  .compact .value {
    font-size: 16px;
  }
</style>
