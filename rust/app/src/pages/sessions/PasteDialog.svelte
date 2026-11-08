<script lang="ts">
  // Colar o texto do Analyzer (JSON ou TSV) em vez de escolher um arquivo (PasteJsonDialog).
  import Modal from "../../components/Modal.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { sessions, type CategoryChoice } from "../../lib/sessions";

  let {
    category,
    categories,
    onclose,
    onimport,
  }: {
    category: string | null;
    categories: CategoryChoice[];
    onclose: () => void;
    onimport: (text: string) => void;
  } = $props();

  let text = $state("");
  let status = $state("Nenhum conteúdo colado.");
  let color = $state("muted");
  let valid = $state(false);
  let saveDir = $state("");
  let timer: ReturnType<typeof setTimeout> | undefined;

  const destination = $derived.by(() => {
    const choice = categories.find((c) => c.value === category);
    return choice && choice.value !== "hunt" ? `A sessão vai para ${choice.plural}. ` : "";
  });

  // svelte-ignore state_referenced_locally
  sessions.pasteSaveDir(category).then((dir) => (saveDir = dir));

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(validate, 250);
  }

  async function validate() {
    clearTimeout(timer);
    const check = await sessions.pasteCheck(text);
    status = check.message;
    color = check.color;
    valid = check.valid;
  }

  async function pasteClipboard() {
    text = await navigator.clipboard.readText();
    await validate();
  }
</script>

<Modal title="Colar JSON/TSV do Analyzer" width={760} height={560} {onclose}>
  <h1>Colar JSON/TSV</h1>
  <p class="muted hint">{destination}Ao importar, o texto também é salvo como arquivo .json em:<br />{saveDir}</p>
  <textarea
    class="editor"
    spellcheck="false"
    placeholder="Cole aqui o JSON ou o TSV gerado pelo Analyzer (Ctrl+V)…"
    bind:value={text}
    oninput={schedule}
  ></textarea>
  <p class="status {color}">{status}</p>
  {#snippet footer()}
    <button class="paste" onclick={pasteClipboard}><Icon name="paste" /> Colar da área de transferência</button>
    <button onclick={onclose}>Cancelar</button>
    <button class="primary" disabled={!valid} onclick={() => onimport(text)}><Icon name="import" /> Importar</button>
  {/snippet}
</Modal>

<style>
  h1 {
    margin: 0;
    font-size: 21px;
    font-weight: 600;
  }

  p {
    margin: 0;
  }

  .hint {
    overflow-wrap: anywhere;
  }

  .editor {
    flex: 1;
    min-height: 120px;
    padding: 8px;
    white-space: pre;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 13px;
  }

  .status {
    overflow-wrap: anywhere;
  }

  .status.muted {
    color: var(--muted);
  }

  .status.positive {
    color: var(--positive);
  }

  .status.negative {
    color: var(--negative);
  }

  .paste {
    margin-right: auto;
  }
</style>
