<script lang="ts">
  // "Nova versão disponível" (como UpdateDialog): novidades, download com progresso e a
  // instalação, que fecha o app para o instalador trocar os arquivos.
  import { listen } from "@tauri-apps/api/event";
  import { markdownToHtml } from "../lib/markdown";
  import { settings, updates, type ReleaseView } from "../lib/settings";
  import Icon from "../lib/Icon.svelte";
  import Modal from "./Modal.svelte";

  let { release, onclose }: { release: ReleaseView; onclose: () => void } = $props();

  let downloading = $state(false);
  let cancelling = $state(false);
  let progress = $state<{ fraction: number; text: string } | null>(null);
  let error = $state("");

  const notes = $derived(release.notes.trim() ? markdownToHtml(release.notes) : "");

  $effect(() => {
    const unlisten = listen<{ fraction: number; text: string }>("update-progress", (event) => {
      if (downloading && !cancelling) progress = event.payload;
    });
    return () => {
      unlisten.then((stop) => stop());
    };
  });

  async function start() {
    if (downloading) return;
    error = "";
    downloading = true;
    progress = { fraction: 0, text: "Baixando…" };
    try {
      const outcome = await updates.download();
      if (outcome.kind === "cancelled") {
        onclose();
        return;
      }
      progress = { fraction: 1, text: "Preparando a instalação…" };
      await updates.install(outcome.new_root);
    } catch (e) {
      error = String(e);
      progress = null;
    } finally {
      downloading = false;
      cancelling = false;
    }
  }

  /** Durante o download, só pede o cancelamento: o diálogo fecha quando o Rust confirmar. */
  function close() {
    if (downloading) {
      cancelling = true;
      if (progress) progress = { ...progress, text: "Cancelando…" };
      updates.cancel();
      return;
    }
    onclose();
  }

  function onclick(event: MouseEvent) {
    const link = (event.target as HTMLElement).closest("a[data-href]");
    if (link) {
      event.preventDefault();
      settings.openPath(link.getAttribute("data-href")!);
    }
  }
</script>

<Modal title="Nova versão disponível" width={620} onclose={close}>
  <div class="update">
    <h3 class="section-title">Versão {release.version} disponível</h3>
    <p class="muted">Você está na versão {release.current}.</p>
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="notes" {onclick}>
      {#if notes}
        <!-- O texto é escapado em markdownToHtml; só as marcas conhecidas viram HTML. -->
        {@html notes}
      {:else}
        <p>Esta versão não traz uma lista de novidades.</p>
      {/if}
    </div>
    <p class="muted">{release.hint}</p>
    {#if progress}
      <progress max="1" value={progress.fraction}></progress>
      <p class="muted">{progress.text}</p>
    {/if}
    {#if error}<p class="error-label">{error}</p>{/if}
  </div>
  {#snippet footer()}
    <button onclick={() => settings.openPath(release.page_url)}>Abrir no GitHub</button>
    <div class="grow"></div>
    <button disabled={cancelling} onclick={close}>{downloading ? "Cancelar" : "Agora não"}</button>
    {#if release.can_install}
      <button class="primary" disabled={downloading} onclick={start}><Icon name="refresh" /> Atualizar agora</button>
    {/if}
  {/snippet}
</Modal>

<style>
  .update {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .update p,
  .update h3 {
    margin: 0;
  }

  .notes {
    height: 240px;
    overflow-y: auto;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-alt);
    user-select: text;
  }

  .notes :global(h3),
  .notes :global(h4),
  .notes :global(h5) {
    margin: 10px 0 4px;
  }

  .notes :global(p),
  .notes :global(ul),
  .notes :global(ol) {
    margin: 4px 0;
  }

  .notes :global(a) {
    color: var(--accent);
  }

  progress {
    width: 100%;
    height: 12px;
    accent-color: var(--accent);
  }

  .grow {
    flex: 1;
  }
</style>
