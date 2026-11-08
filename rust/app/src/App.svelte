<script lang="ts">
  // Janela principal (como main_window.py): barra lateral, sub-navegação das seções, a página
  // escolhida, a barra de status, arrastar e soltar e o fluxo de importação.
  import { invoke, takeProblems, waitIdle } from "./lib/diagnostics";
  import { getCurrentWebview } from "@tauri-apps/api/webview";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { tick } from "svelte";
  import { message } from "@tauri-apps/plugin-dialog";
  import Modal from "./components/Modal.svelte";
  import SectionBar from "./components/SectionBar.svelte";
  import Sidebar, { type NavItem } from "./components/Sidebar.svelte";
  import UpdateDialog from "./components/UpdateDialog.svelte";
  import DashboardPage from "./pages/DashboardPage.svelte";
  import DpsPage from "./pages/DpsPage.svelte";
  import EntityPage from "./pages/analysis/EntityPage.svelte";
  import PricesPage from "./pages/analysis/PricesPage.svelte";
  import ReportsPage from "./pages/analysis/ReportsPage.svelte";
  import Placeholder from "./pages/Placeholder.svelte";
  import SessionsPage from "./pages/SessionsPage.svelte";
  import SettingsPage from "./pages/SettingsPage.svelte";
  import PasteDialog from "./pages/sessions/PasteDialog.svelte";
  import { api, type AppInfo } from "./lib/api";
  import { emptyForm, filterPanel } from "./lib/filters.svelte";
  import { updates } from "./lib/settings";
  import { checkForUpdates, updater } from "./lib/updater.svelte";
  import {
    chooseFiles,
    chooseFolder,
    configureImporter,
    importPasted,
    importPaths,
    importer,
    openPaste,
    pasteCategory,
  } from "./lib/importer.svelte";
  import { sessions, type CategoryChoice } from "./lib/sessions";
  import { announce, status } from "./lib/status.svelte";

  const items: NavItem[] = [
    { key: "dashboard", label: "Início", icon: "dashboard" },
    { key: "sessions", label: "Sessões", icon: "hunts" },
    { key: "analysis", label: "Análise", icon: "reports" },
    { key: "dps", label: "DPS", icon: "dps" },
    { key: "settings", label: "Configurações", icon: "settings", atBottom: true },
  ];

  const importItems = [
    { label: "Arquivos JSON/TSV…", icon: "import", shortcut: "Ctrl+I", action: chooseFiles },
    { label: "Pasta inteira…", icon: "folder", shortcut: "Ctrl+Shift+I", action: chooseFolder },
    { label: "Colar texto…", icon: "paste", shortcut: "Ctrl+Shift+V", action: openPaste },
  ];

  let info = $state<AppInfo | null>(null);
  let section = $state("dashboard");
  let page = $state("dashboard");
  let categories = $state<CategoryChoice[]>([]);
  let counts = $state<Record<string, number>>({});
  /** Sobe a cada mudança de dados vinda de fora da página (importação, F5). */
  let version = $state(0);
  let selectAfterImport = $state<number[]>([]);
  let dragging = $state(false);
  let error = $state("");

  /** Ao voltar a uma seção, abre a última sub-página usada nela. */
  const lastInSection: Record<string, string> = { sessions: "all_sessions", analysis: "reports" };

  const analysisPages = [
    { key: "reports", label: "Relatórios" },
    { key: "items", label: "Itens" },
    { key: "enemies", label: "Inimigos" },
    { key: "prices", label: "Preços" },
  ];

  const sessionPages = $derived([
    { key: "all_sessions", label: "Todas" },
    { key: "hunts", label: "Hunts" },
    ...categories.filter((c) => c.value !== "hunt").map((c) => ({ key: `boss:${c.value}`, label: c.plural })),
  ]);
  const sectionItems = $derived(
    section === "sessions"
      ? sessionPages.map((p) => ({ ...p, label: counts[p.key] ? `${p.label} (${counts[p.key]})` : p.label }))
      : section === "analysis"
        ? analysisPages
        : [],
  );

  api
    .appInfo()
    .then((value) => {
      info = value;
      document.documentElement.dataset.theme = value.theme;
      if (value.smoke_test) runSmokeTest();
    })
    .catch((e) => (error = String(e)));
  sessions.categories().then((value) => (categories = value));

  /** Deixa a janela abrir antes de ir à internet, como o Python. */
  const UPDATE_CHECK_DELAY_MS = 3000;
  updates.checkOnStart().then((enabled) => {
    if (enabled) setTimeout(() => checkForUpdates(true), UPDATE_CHECK_DELAY_MS);
  });

  /** `--smoke-test` (como o Python): visita todas as páginas e avisa o Rust, que fecha o programa. */
  async function runSmokeTest() {
    const choices = await sessions.categories();
    const keys = [
      "dashboard",
      "all_sessions",
      "hunts",
      ...choices.filter((c) => c.value !== "hunt").map((c) => `boss:${c.value}`),
      ...analysisPages.map((p) => p.key),
      "dps",
      "settings",
    ];
    const errors: string[] = [];
    if (!(await waitIdle())) errors.push("abertura: não terminou de carregar");
    errors.push(...takeProblems().map((p) => `abertura: ${p}`));
    for (const key of keys) {
      show(key);
      await tick();
      if (!(await waitIdle())) errors.push(`${key}: não terminou de carregar`);
      if (!document.querySelector("main")?.childElementCount) errors.push(`${key}: página vazia`);
      errors.push(...takeProblems().map((p) => `${key}: ${p}`));
    }
    await invoke("smoke_test_done", { pages: keys, errors });
  }

  /** Depois de restaurar um backup: limpa os filtros (o Rust já limpou o dele) e recarrega. */
  function dataReplaced() {
    filterPanel.form = emptyForm();
    filterPanel.parts = [];
    filterPanel.version += 1;
    version += 1;
  }

  // As contagens da sub-navegação acompanham as mudanças nas sessões e nos filtros.
  $effect(() => {
    void version;
    void filterPanel.version;
    if (section === "sessions") sessions.counts().then((value) => (counts = value));
  });

  function show(key: string) {
    const target = lastInSection[key] ?? key;
    const parent =
      target === "all_sessions" || target === "hunts" || target.startsWith("boss:")
        ? "sessions"
        : analysisPages.some((p) => p.key === target)
          ? "analysis"
          : target;
    section = parent;
    page = target;
    if (parent in lastInSection) lastInSection[parent] = target;
  }

  configureImporter({
    // Importar com um tipo de boss aberto grava as sessões nele; fora dele, é automático.
    category: () => (page.startsWith("boss:") ? page.replace("boss:", "") : null),
    imported: async (huntIds) => {
      const target = await sessions.importTarget(huntIds);
      selectAfterImport = target.hunt_ids;
      show(target.category === "hunt" ? "hunts" : `boss:${target.category}`);
      version += 1;
      if (target.message) announce(target.message);
    },
  });

  // Arrastar e soltar arquivos .json/.tsv ou pastas em qualquer ponto da janela.
  getCurrentWebview().onDragDropEvent(async (event) => {
    const payload = event.payload;
    if (payload.type === "enter") {
      dragging = (await sessions.droppedPaths(payload.paths)).length > 0;
    } else if (payload.type === "leave") {
      dragging = false;
    } else if (payload.type === "drop") {
      dragging = false;
      const paths = await sessions.droppedPaths(payload.paths);
      if (paths.length) await importPaths(paths);
    }
  });

  function onkeydown(event: KeyboardEvent) {
    const key = event.key.toLowerCase();
    if (event.ctrlKey && key === "i") {
      event.preventDefault();
      if (event.shiftKey) chooseFolder();
      else chooseFiles();
    } else if (event.ctrlKey && event.shiftKey && key === "v") {
      event.preventDefault();
      openPaste();
    } else if (event.key === "F5") {
      event.preventDefault();
      version += 1;
    } else if (event.ctrlKey && !event.shiftKey && key === "q") {
      event.preventDefault();
      getCurrentWindow().close();
    }
  }

  function about() {
    message(
      `PokeXGames Hunt Analyzer ${info?.version ?? ""}\n\nHistórico, análise e relatórios das Hunts exportadas pelo Analyzer do PokeXGames.`,
      { title: "Sobre o PokeXGames Hunt Analyzer", kind: "info" },
    );
  }
</script>

<svelte:window {onkeydown} />

<div class="window">
  <div class="panes">
    <Sidebar {items} current={section} version={info?.version ?? ""} {importItems} onselect={show} onabout={about} />
    <div class="content">
      {#if sectionItems.length}
        <SectionBar items={sectionItems} current={page} onselect={show} />
      {/if}
      <main>
        {#if error}
          <p class="warning">{error}</p>
        {:else if section === "dashboard"}
          <DashboardPage {version} onchanged={() => (version += 1)} />
        {:else if section === "dps"}
          <DpsPage />
        {:else if section === "sessions"}
          <SessionsPage
            pageKey={page}
            {categories}
            {version}
            onchanged={() => (version += 1)}
            bind:select={selectAfterImport}
          />
        {:else if page === "reports"}
          <ReportsPage {version} />
        {:else if page === "items" || page === "enemies"}
          {#key page}
            <EntityPage {page} {version} onchanged={() => (version += 1)} />
          {/key}
        {:else if page === "prices"}
          <PricesPage {version} onchanged={() => (version += 1)} />
        {:else if section === "settings"}
          <SettingsPage {version} ondatareplaced={dataReplaced} ondisplaychanged={() => (version += 1)} />
        {:else}
          <Placeholder title={items.find((i) => i.key === section)?.label ?? ""} />
        {/if}
      </main>
    </div>
  </div>
  {#if status.text}
    <footer class="status">{status.text}</footer>
  {/if}
  {#if dragging}
    <div class="drop-overlay">
      <div class="frame">
        <strong>Solte para importar</strong>
        <span class="muted">Arquivos .json/.tsv do Analyzer ou pastas inteiras</span>
      </div>
    </div>
  {/if}
</div>

{#if updater.offer}
  <UpdateDialog release={updater.offer} onclose={() => (updater.offer = null)} />
{/if}

{#if importer.pasting}
  <PasteDialog
    category={pasteCategory()}
    {categories}
    onclose={() => (importer.pasting = false)}
    onimport={(text) => {
      importer.pasting = false;
      importPasted(text);
    }}
  />
{/if}

{#if importer.progress}
  <Modal title="Importação" width={460} onclose={() => (importer.cancelRequested = true)}>
    <p class="progress-label">{importer.progress.label}</p>
    <progress max={importer.progress.max} value={importer.progress.value}></progress>
    {#snippet footer()}
      <button onclick={() => (importer.cancelRequested = true)}>Cancelar</button>
    {/snippet}
  </Modal>
{/if}

<style>
  .window {
    position: relative;
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .panes {
    flex: 1;
    min-height: 0;
    display: flex;
  }

  .content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }

  /* A página rola quando o conteúdo não cabe (ex.: filtros abertos na janela mínima). */
  main {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    padding: 24px 28px 24px;
    overflow-y: auto;
  }

  /* Barra de status, como o statusBar do Python: só aparece com mensagem. */
  .status {
    padding: 4px 12px;
    background: var(--sidebar);
    color: var(--muted);
    border-top: 1px solid var(--border);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    user-select: text;
  }

  .drop-overlay {
    position: absolute;
    inset: 0;
    z-index: 50;
    padding: 24px;
    background: color-mix(in srgb, var(--bg) 84%, transparent);
    pointer-events: none;
  }

  .frame {
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    border: 2px dashed var(--accent);
    border-radius: 16px;
  }

  .frame strong {
    font-size: 21px;
  }

  .progress-label {
    margin: 0;
  }

  progress {
    width: 100%;
    height: 14px;
    accent-color: var(--accent);
  }
</style>
