// Erros não tratados e chamadas ao Rust em andamento.
//
// Os erros vão para o log (logs/app.log), como no Python. O `--smoke-test` usa as duas coisas
// para saber quando cada página terminou de carregar e se alguma chamada falhou.
//
// As telas chamam o Rust pelo `invoke` daqui, e não pelo do pacote, para as chamadas serem
// contadas (o `__TAURI_INTERNALS__.invoke` é somente leitura e não pode ser interceptado).

import { invoke as tauriInvoke, type InvokeArgs } from "@tauri-apps/api/core";

let pending = 0;
/** Guardados desde a abertura, com limite, para o `--smoke-test` pegar também os da abertura. */
const problems: string[] = [];
const MAX_PROBLEMS = 100;

function record(problem: string) {
  if (problems.length < MAX_PROBLEMS) problems.push(problem);
}

function describe(reason: unknown): string {
  if (reason instanceof Error) return reason.stack ?? `${reason.name}: ${reason.message}`;
  return String(reason);
}

function reportUncaught(text: string) {
  record(text);
  // O `catch` evita que uma falha ao gravar o log vire outro erro não tratado.
  tauriInvoke("log_frontend_error", { message: text }).catch(() => {});
}

/** Liga os avisos de erro; roda antes de montar as telas. */
export function installDiagnostics() {
  window.addEventListener("error", (event) => reportUncaught(describe(event.error ?? event.message)));
  window.addEventListener("unhandledrejection", (event) => reportUncaught(describe(event.reason)));
}

/** O `invoke` do pacote, contando as chamadas em andamento e guardando as falhas. */
export async function invoke<T>(command: string, args?: InvokeArgs): Promise<T> {
  pending += 1;
  try {
    return await tauriInvoke<T>(command, args);
  } catch (error) {
    record(`${command}: ${describe(error)}`);
    throw error;
  } finally {
    pending -= 1;
  }
}

/** Problemas guardados desde a última chamada. */
export function takeProblems(): string[] {
  return problems.splice(0);
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Espera nenhuma chamada ficar pendente por `quietMs`; `false` se passar de `timeoutMs`. */
export async function waitIdle(quietMs = 300, timeoutMs = 20000): Promise<boolean> {
  const started = performance.now();
  let quietSince = performance.now();
  while (performance.now() - started < timeoutMs) {
    await sleep(50);
    if (pending > 0) quietSince = performance.now();
    else if (performance.now() - quietSince >= quietMs) return true;
  }
  return false;
}
