<script lang="ts">
  // Botão "Exportar" com os formatos (como ExportButton): o Rust monta o documento e grava.
  import { message, save } from "@tauri-apps/plugin-dialog";
  import { sessions, type ExportRequest } from "../lib/sessions";
  import { announce } from "../lib/status.svelte";
  import MenuButton, { type MenuItem } from "./MenuButton.svelte";

  let {
    request,
    disabled = false,
    title,
  }: { request: () => ExportRequest | null; disabled?: boolean; title?: string } = $props();

  let items = $state<MenuItem[]>([]);

  sessions.exportFormats().then((formats) => {
    items = formats.map((format) => ({ label: format.label, action: () => exportAs(format) }));
  });

  async function exportAs(format: { value: string; label: string; description: string }) {
    const document = request();
    if (!document) return;
    try {
      const path = await save({
        title: `Exportar ${format.label.split(" (")[0]}`,
        defaultPath: await sessions.exportDefaultPath(document, format.value),
        filters: [{ name: format.description, extensions: [format.value] }],
      });
      if (!path) return;
      announce(`Exportado: ${await sessions.exportRun(document, format.value, path)}`);
    } catch (e) {
      await message(String(e), { title: "Falha na exportação", kind: "warning" });
    }
  }
</script>

<MenuButton label="Exportar" icon="export" {items} {disabled} {title} align="right" />
