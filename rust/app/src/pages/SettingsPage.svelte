<script lang="ts">
  // Página Configurações (como settings_widget.py): aparência, atualizações, banco de dados e
  // backups.
  import { ask, message, open, save } from "@tauri-apps/plugin-dialog";
  import RecordTable from "../components/RecordTable.svelte";
  import Icon from "../lib/Icon.svelte";
  import { settings, type SettingsView } from "../lib/settings";
  import { announce } from "../lib/status.svelte";
  import { viewColumns, type RowView } from "../lib/table";
  import { checkForUpdates, updater } from "../lib/updater.svelte";

  let {
    version,
    ondatareplaced,
    ondisplaychanged,
  }: {
    version: number;
    /** O banco foi restaurado de um backup: os filtros foram limpos e tudo recarrega. */
    ondatareplaced: () => void;
    /** O formato de números mudou: as páginas recarregam. */
    ondisplaychanged: () => void;
  } = $props();

  const DB_FILTERS = [
    { name: "Banco SQLite", extensions: ["db"] },
    { name: "Todos os arquivos", extensions: ["*"] },
  ];

  let view = $state<SettingsView | null>(null);
  let error = $state("");
  let restartNotice = $state("");
  let selectedKeys = $state<number[]>([]);

  async function load() {
    try {
      view = await settings.view();
      error = "";
    } catch (e) {
      error = String(e);
    }
  }

  $effect(() => {
    void version;
    load();
  });

  async function run(action: () => Promise<void>) {
    try {
      await action();
    } catch (e) {
      await message(String(e), { title: "Configurações", kind: "warning" });
    }
  }

  // ------------------------------------------------------------------ aparência

  function setTheme(theme: string) {
    run(async () => {
      await settings.setTheme(theme);
      // Diferente do Python, o tema muda na hora: não precisa reiniciar.
      document.documentElement.dataset.theme = theme;
      view!.theme = theme;
    });
  }

  function setNumberFormat(name: string) {
    run(async () => {
      await settings.setNumberFormat(name);
      ondisplaychanged();
    });
  }

  // ------------------------------------------------------------------ banco

  async function chooseDatabase() {
    if (!view) return;
    const path = await save({
      title: "Escolher ou criar um banco",
      defaultPath: view.database_path,
      filters: DB_FILTERS,
    });
    if (path) setDatabase(path);
  }

  function setDatabase(path: string | null) {
    settings
      .setDatabasePath(path)
      .then((notice) => {
        restartNotice = notice;
        load();
      })
      .catch((e) => message(String(e), { title: "Banco inválido", kind: "warning" }));
  }

  // ------------------------------------------------------------------ backups

  function saveBackupOptions(autoBackup: boolean, keep: number) {
    if (!view) return;
    const clamped = Math.min(view.max_backups, Math.max(view.min_backups, Math.round(keep) || view.min_backups));
    view.auto_backup = autoBackup;
    view.backups_to_keep = clamped;
    run(() => settings.setBackupOptions(autoBackup, clamped));
  }

  async function backup(destination: string | null) {
    try {
      announce(await settings.backupNow(destination));
      await load();
    } catch (e) {
      await message(String(e), { title: "Falha no backup", kind: "warning" });
    }
  }

  async function saveCopy() {
    const path = await save({
      title: "Salvar cópia do banco",
      defaultPath: await settings.copyDefaultPath(),
      filters: DB_FILTERS,
    });
    if (path) backup(path);
  }

  async function restoreFromFile() {
    const path = await open({
      title: "Restaurar backup",
      defaultPath: await settings.backupsDir(),
      filters: DB_FILTERS,
      multiple: false,
      directory: false,
    });
    if (typeof path === "string") restore(path);
  }

  function restoreSelected() {
    if (view && selectedKeys.length === 1) restore(view.backup_paths[selectedKeys[0]]);
  }

  async function restore(path: string) {
    let question: string;
    try {
      question = await settings.inspectBackup(path);
    } catch (e) {
      await message(String(e), { title: "Backup inválido", kind: "warning" });
      return;
    }
    const confirmed = await ask(question, { title: "Restaurar backup", kind: "warning", okLabel: "Sim", cancelLabel: "Não" });
    if (!confirmed) return;
    try {
      const text = await settings.restoreBackup(path);
      selectedKeys = [];
      ondatareplaced();
      announce(text);
    } catch (e) {
      await message(String(e), { title: "Falha na restauração", kind: "error" });
    }
  }

  function parentDir(path: string): string {
    return path.replace(/[\\/][^\\/]*$/, "");
  }
</script>

<header>
  <h1>Configurações</h1>
  <p class="muted">Aparência, atualizações, banco de dados e backups</p>
</header>

{#if error}<p class="warning">{error}</p>{/if}

{#if view}
  <div class="body">
    {#if restartNotice}
      <div class="card notice">
        <p class="muted">{restartNotice}</p>
        <button class="primary" onclick={() => settings.restart()}>Reiniciar agora</button>
      </div>
    {/if}

    <section class="card">
      <h3 class="section-title">Aparência</h3>
      <div class="form">
        <label for="settings-theme">Tema</label>
        <select id="settings-theme" value={view.theme} onchange={(e) => setTheme(e.currentTarget.value)}>
          {#each view.themes as theme (theme.value)}<option value={theme.value}>{theme.label}</option>{/each}
        </select>
        <label for="settings-numbers">Formato de números</label>
        <select
          id="settings-numbers"
          value={view.number_format}
          onchange={(e) => setNumberFormat(e.currentTarget.value)}
        >
          {#each view.number_formats as format (format.value)}<option value={format.value}>{format.label}</option>{/each}
        </select>
      </div>
      <p class="hint">O formato de números vale para as telas, os filtros e a exportação CSV.</p>
    </section>

    <section class="card">
      <h3 class="section-title">Atualizações</h3>
      <label class="check">
        <input
          type="checkbox"
          checked={view.check_updates}
          onchange={(e) => run(() => settings.setCheckUpdates(e.currentTarget.checked))}
        />
        Verificar se há versão nova ao abrir o aplicativo
      </label>
      <div class="row">
        <button disabled={updater.checking} onclick={() => checkForUpdates()}><Icon name="refresh" /> Verificar agora</button>
        <span class="hint">{updater.status || `Versão instalada: ${view.version}.`}</span>
      </div>
      <p class="hint">
        A verificação só consulta os releases do projeto no GitHub. Nada é instalado sem você confirmar, e seus dados
        continuam onde estão.
      </p>
    </section>

    <section class="card">
      <h3 class="section-title">Banco de dados</h3>
      <div class="form">
        <span class="field-label">Arquivo</span>
        <span class="value path">{view.database_path}</span>
        <span class="field-label">Tamanho</span>
        <span class="value">{view.database_size}</span>
        <span class="field-label">Hunts armazenadas</span>
        <span class="value">{view.hunt_count}</span>
        <span class="field-label">Versão do aplicativo</span>
        <span class="value">{view.version}</span>
      </div>
      <div class="row">
        <button onclick={() => run(() => settings.openPath(parentDir(view!.database_path)))}>
          <Icon name="folder" /> Abrir pasta
        </button>
        <button disabled={view.env_locked} onclick={chooseDatabase}>Usar outro banco…</button>
        <button disabled={view.env_locked || !view.custom_database} onclick={() => setDatabase(null)}>
          Voltar ao banco padrão
        </button>
      </div>
      {#if view.env_locked}
        <p class="hint">
          O banco está definido pela variável de ambiente PXG_HUNTS_DB, que tem prioridade sobre esta configuração.
        </p>
      {/if}
    </section>

    <section class="card">
      <h3 class="section-title">Backup</h3>
      <label class="check">
        <input
          type="checkbox"
          checked={view.auto_backup}
          onchange={(e) => saveBackupOptions(e.currentTarget.checked, view!.backups_to_keep)}
        />
        Fazer backup automático ao abrir o aplicativo (no máximo um por dia)
      </label>
      <div class="form">
        <label for="settings-keep">Manter os últimos</label>
        <span class="keep">
          <input
            id="settings-keep"
            type="number"
            min={view.min_backups}
            max={view.max_backups}
            value={view.backups_to_keep}
            onchange={(e) => saveBackupOptions(view!.auto_backup, Number(e.currentTarget.value))}
          />
          backups automáticos
        </span>
      </div>
      <div class="row">
        <button class="primary" onclick={() => backup(null)}>Fazer backup agora</button>
        <button onclick={saveCopy}>Salvar cópia em…</button>
        <button onclick={restoreFromFile}>Restaurar de arquivo…</button>
        <button onclick={async () => run(async () => settings.openPath(await settings.backupsDir(), true))}>
          <Icon name="folder" /> Abrir pasta de backups
        </button>
      </div>
      <div class="table">
        <RecordTable
          columns={viewColumns(view.backups.columns)}
          rows={view.backups.rows}
          rowKey={(r: RowView) => r.id}
          multiple
          sortable={false}
          bind:selectedKeys
          onactivate={restoreSelected}
        />
      </div>
      <div class="row">
        <button disabled={selectedKeys.length !== 1} onclick={restoreSelected}>Restaurar selecionado</button>
      </div>
      <p class="hint">{view.backups_hint}</p>
    </section>
  </div>
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

  .body {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 16px 0 8px;
  }

  section {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px 18px;
  }

  section p,
  section h3 {
    margin: 0;
  }

  .notice {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 12px 12px 18px;
  }

  .notice p {
    flex: 1;
    margin: 0;
  }

  .form select {
    max-width: 320px;
  }

  .value {
    user-select: text;
  }

  .path {
    overflow-wrap: anywhere;
  }

  .row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }

  .row .hint {
    flex: 1;
    min-width: 200px;
  }

  .keep {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .keep input {
    width: 80px;
  }

  .table {
    display: flex;
    height: calc(44px + 34px * 6);
  }

  .table > :global(.wrap) {
    flex: 1;
  }
</style>
