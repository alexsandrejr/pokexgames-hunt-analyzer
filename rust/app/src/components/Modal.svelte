<script lang="ts">
  // Diálogo modal (como o QDialog): título, conteúdo, erro de validação e botões.
  // Esc e o X chamam `onclose`; quem abriu decide se fecha (os testes gravam antes de fechar).
  import type { Snippet } from "svelte";
  import Icon from "../lib/Icon.svelte";

  let {
    title,
    width = 560,
    height,
    error = "",
    onclose,
    children,
    footer,
  }: {
    title: string;
    width?: number;
    /** Altura fixa; sem ela, o diálogo cresce com o conteúdo. */
    height?: number;
    error?: string;
    onclose: () => void;
    children: Snippet;
    footer?: Snippet;
  } = $props();

  let dialog: HTMLDialogElement;

  $effect(() => {
    dialog.showModal();
    return () => dialog.close();
  });
</script>

<dialog
  bind:this={dialog}
  style:width="{width}px"
  style:height={height ? `${height}px` : undefined}
  oncancel={(e) => {
    e.preventDefault();
    onclose();
  }}
>
  <header>
    <h2>{title}</h2>
    <button class="close" title="Fechar" onclick={onclose}><Icon name="close" /></button>
  </header>
  <div class="body">
    {@render children()}
  </div>
  {#if error}<p class="error-label">{error}</p>{/if}
  {#if footer}
    <footer>{@render footer()}</footer>
  {/if}
</dialog>

<style>
  dialog {
    max-width: calc(100vw - 32px);
    max-height: calc(100vh - 32px);
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--bg);
    color: var(--text);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
  }

  dialog[open] {
    display: flex;
    flex-direction: column;
  }

  dialog::backdrop {
    background: rgba(0, 0, 0, 0.35);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 12px 0 20px;
  }

  h2 {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
  }

  .close {
    border: none;
    background: transparent;
    padding: 6px;
  }

  .body {
    flex: 1;
    min-height: 0;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px 20px;
  }

  .error-label {
    padding: 0 20px 8px;
  }

  footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    padding: 0 20px 18px;
  }
</style>
