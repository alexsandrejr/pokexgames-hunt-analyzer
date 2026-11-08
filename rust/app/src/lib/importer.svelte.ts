// Fluxo de importação (como app/ui/import_controller.py): arquivos, pastas, arrastar e soltar
// e texto colado.
//
// * Um único arquivo: em caso de duplicidade, a pessoa decide (Cancelar/Importar mesmo assim).
// * Vários arquivos: duplicatas são ignoradas sem perguntar e aparecem no resumo; a partir de
//   5 arquivos, uma barra de progresso permite cancelar.
//
// A categoria vem de `categoryProvider` (a página de boss aberta); `null` deixa o Rust decidir.

import { ask, message, open } from "@tauri-apps/plugin-dialog";
import { sessions, type ImportOutcome } from "./sessions";
import { announce } from "./status.svelte";

const ANALYZER_FILTERS = [
  { name: "Analyzer", extensions: ["json", "tsv", "txt"] },
  { name: "JSON", extensions: ["json"] },
  { name: "TSV", extensions: ["tsv", "txt"] },
  { name: "Todos os arquivos", extensions: ["*"] },
];
const PROGRESS_THRESHOLD = 5;

export const importer = $state({
  progress: null as null | { label: string; value: number; max: number },
  cancelRequested: false,
  pasting: false,
});

let categoryProvider: () => string | null = () => null;
let onImported: (huntIds: number[]) => void = () => {};

export function configureImporter(options: {
  category: () => string | null;
  imported: (huntIds: number[]) => void;
}) {
  categoryProvider = options.category;
  onImported = options.imported;
}

export async function chooseFiles() {
  const paths = await open({
    title: "Importar JSON/TSV do Analyzer",
    defaultPath: await sessions.importStartDir(),
    filters: ANALYZER_FILTERS,
    multiple: true,
  });
  if (paths && paths.length) await importPaths(paths);
}

export async function chooseFolder() {
  const folder = await open({
    title: "Importar todos os JSON/TSV de uma pasta",
    defaultPath: await sessions.importStartDir(),
    directory: true,
  });
  if (folder) await importPaths([folder]);
}

/** Importa arquivos e pastas (as pastas são percorridas com subpastas). */
export async function importPaths(paths: string[]) {
  const files = await sessions.collectFiles(paths);
  if (files.length === 0) {
    await message("Nenhum arquivo .json ou .tsv foi encontrado.", { title: "Resultado da importação", kind: "info" });
    return;
  }
  const category = categoryProvider();
  if (files.length === 1) {
    const result = await confirmingDuplicate((force) => sessions.importFile(files[0], force, category));
    await finish([result], false);
    return;
  }
  const results: ImportOutcome[] = [];
  const showProgress = files.length >= PROGRESS_THRESHOLD;
  importer.cancelRequested = false;
  try {
    for (const [index, path] of files.entries()) {
      if (showProgress) {
        const name = path.split(/[\\/]/).pop();
        importer.progress = { label: `Importando ${index + 1} de ${files.length}: ${name}`, value: index, max: files.length };
        // Dá tempo de a tela mostrar o progresso e o clique em Cancelar.
        await new Promise((resolve) => setTimeout(resolve, 0));
        if (importer.cancelRequested) break;
      }
      results.push(await sessions.importFile(path, false, category));
    }
  } finally {
    importer.progress = null;
  }
  await finish(results, results.length < files.length);
}

export function openPaste() {
  importer.pasting = true;
}

/** Importa o texto colado (JSON ou TSV); se importado, também vira um arquivo .json. */
export async function importPasted(text: string) {
  const category = categoryProvider();
  const result = await confirmingDuplicate((force) => sessions.importPasted(text, force, category));
  await finish([result], false);
}

export function pasteCategory(): string | null {
  return categoryProvider();
}

async function confirmingDuplicate(run: (force: boolean) => Promise<ImportOutcome>): Promise<ImportOutcome> {
  const result = await run(false);
  if (result.status !== "duplicate") return result;
  const force = await ask(`${result.message}\n\nDeseja importar novamente?\n\nArquivo: ${result.source_name}`, {
    title: "Hunt duplicada",
    kind: "info",
    okLabel: "Importar mesmo assim",
    cancelLabel: "Cancelar",
  });
  return force ? run(true) : result;
}

async function finish(results: ImportOutcome[], cancelled: boolean) {
  if (results.length) {
    const report = await sessions.importReport(results, cancelled);
    announce(report.summary);
    const errors = results.filter((r) => r.status === "error");
    const warnings = results.filter((r) => r.status === "imported" && r.warnings.length);
    const duplicates = results.filter((r) => r.status === "duplicate");
    if (results.length === 1 && errors.length) {
      const error = errors[0];
      const detail = error.detail ? `\n\n${error.detail}` : "";
      await message(`${error.message}\n\nArquivo: ${error.source_name}${detail}`, {
        title: "Erro na importação",
        kind: "warning",
      });
    } else if (results.length > 1 && (errors.length || warnings.length || duplicates.length || cancelled)) {
      const lines = report.lines.length ? `\n\n${report.lines.join("\n")}` : "";
      await message(`${report.summary}${lines}`, { title: "Resultado da importação", kind: "info" });
    }
  }
  const imported = results.filter((r) => r.status === "imported" && r.hunt_id !== null).map((r) => r.hunt_id!);
  if (imported.length) onImported(imported);
}
