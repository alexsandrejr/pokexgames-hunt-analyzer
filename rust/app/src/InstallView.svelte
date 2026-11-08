<script lang="ts">
  // Janela de progresso da instalação (como o QProgressDialog de install_window.py): aberta pelo
  // `.exe` novo com `--apply-update`, fecha sozinha quando os arquivos terminam de ser trocados.
  import { invoke } from "@tauri-apps/api/core";

  invoke<string>("install_theme")
    .then((theme) => (document.documentElement.dataset.theme = theme))
    .catch(() => {});
</script>

<div class="install">
  <p>Instalando a atualização…</p>
  <progress></progress>
</div>

<style>
  .install {
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 12px;
    padding: 0 24px;
  }

  p {
    margin: 0;
  }

  progress {
    width: 100%;
    height: 12px;
    accent-color: var(--accent);
  }
</style>
