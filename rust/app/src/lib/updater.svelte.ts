// Verificação de atualização (como UpdateController): o texto de status da página
// Configurações, o botão desabilitado durante a consulta e a versão a oferecer.

import { updates, type ReleaseView } from "./settings";

export const updater = $state({
  status: "",
  checking: false,
  /** Versão nova a oferecer no diálogo "Nova versão disponível". */
  offer: null as ReleaseView | null,
});

const MODAL_RETRY_MS = 5000;

/** Em `silent` (ao abrir o app), só aparece algo se houver versão nova. */
export async function checkForUpdates(silent = false) {
  if (updater.checking) return;
  updater.checking = true;
  if (!silent) updater.status = "Verificando…";
  try {
    const result = await updates.check();
    if (result.release || !silent) updater.status = result.status;
    if (result.release) offer(result.release);
  } catch (e) {
    // Sem internet ao abrir o app não é um problema a mostrar.
    if (!silent) updater.status = String(e);
  } finally {
    updater.checking = false;
  }
}

/** Não interrompe quem está com outro diálogo aberto, como o cadastro de um pokémon. */
function offer(release: ReleaseView) {
  if (document.querySelector("dialog[open]")) {
    setTimeout(() => offer(release), MODAL_RETRY_MS);
    return;
  }
  updater.offer = release;
}
