// Chamadas da página Configurações e da atualização (src-tauri/src/commands/settings.rs e
// update.rs) e os tipos que elas devolvem.

import { invoke } from "./diagnostics";
import type { Choice } from "./api";
import type { TableView } from "./table";

export interface SettingsView {
  version: string;
  theme: string;
  themes: Choice[];
  number_format: string;
  number_formats: Choice[];
  check_updates: boolean;
  auto_backup: boolean;
  backups_to_keep: number;
  min_backups: number;
  max_backups: number;
  database_path: string;
  database_size: string;
  hunt_count: string;
  env_locked: boolean;
  custom_database: boolean;
  backups: TableView;
  backup_paths: string[];
  backups_hint: string;
}

export interface ReleaseView {
  version: string;
  current: string;
  notes: string;
  page_url: string;
  can_install: boolean;
  hint: string;
}

export type DownloadOutcome = { kind: "ready"; new_root: string } | { kind: "cancelled" };

export const settings = {
  view: () => invoke<SettingsView>("settings_view"),
  setTheme: (theme: string) => invoke<void>("settings_set_theme", { theme }),
  setNumberFormat: (name: string) => invoke<void>("settings_set_number_format", { name }),
  setCheckUpdates: (enabled: boolean) => invoke<void>("settings_set_check_updates", { enabled }),
  setBackupOptions: (autoBackup: boolean, keep: number) =>
    invoke<void>("settings_set_backup_options", { autoBackup, keep }),
  setDatabasePath: (path: string | null) => invoke<string>("database_set_path", { path }),
  backupNow: (destination: string | null) => invoke<string>("backup_now", { destination }),
  copyDefaultPath: () => invoke<string>("backup_copy_default_path"),
  backupsDir: () => invoke<string>("backups_dir"),
  inspectBackup: (path: string) => invoke<string>("backup_inspect", { path }),
  restoreBackup: (path: string) => invoke<string>("backup_restore", { path }),
  openPath: (target: string, create = false) => invoke<void>("open_path", { target, create }),
  restart: () => invoke<void>("app_restart"),
};

export const updates = {
  check: () => invoke<{ status: string; release: ReleaseView | null }>("update_check"),
  download: () => invoke<DownloadOutcome>("update_download"),
  cancel: () => invoke<void>("update_cancel"),
  install: (newRoot: string) => invoke<void>("update_install", { newRoot }),
  checkOnStart: () => invoke<boolean>("update_check_on_start"),
};
