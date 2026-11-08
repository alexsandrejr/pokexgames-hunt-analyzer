<script lang="ts">
  // Colar mensagens "Você recebeu:" do chat e somar os itens à sessão (ChatRewardsDialog).
  // A prévia mostra o nome que será gravado (editável), a quantidade e o preço que vai valer.
  import { message } from "@tauri-apps/plugin-dialog";
  import Modal from "../../components/Modal.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { sessions, type RewardLine } from "../../lib/sessions";

  let { huntId, onclose, onadded }: { huntId: number; onclose: () => void; onadded: () => void } = $props();

  let text = $state("");
  let lines = $state<RewardLine[]>([]);
  let status = $state("Nenhuma mensagem colada.");
  let color = $state("muted");
  let timer: ReturnType<typeof setTimeout> | undefined;

  /** Espera a pessoa parar de digitar, como o QTimer de 250 ms do Python. */
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(validate, 250);
  }

  async function validate() {
    clearTimeout(timer);
    const preview = await sessions.chatPreview(huntId, text);
    lines = preview.lines;
    status = preview.status;
    color = preview.color;
  }

  async function rename(index: number, name: string) {
    const old = lines[index];
    lines[index] = await sessions.chatQuote(old.chat_name, name, old.count);
    [status, color] = await sessions.chatStatus(huntId, text, $state.snapshot(lines));
  }

  async function pasteClipboard() {
    text = await navigator.clipboard.readText();
    await validate();
  }

  async function add() {
    try {
      await sessions.chatAdd(huntId, text, $state.snapshot(lines));
      onadded();
    } catch (e) {
      await message(String(e), { title: "Recompensas do chat", kind: "warning" });
    }
  }
</script>

<Modal title="Adicionar recompensas do chat" width={820} height={620} {onclose}>
  <h1>Recompensas do chat</h1>
  <p class="muted">
    Cole as mensagens do chat que começam com "Você recebeu:" (uma por linha). Os itens são somados aos drops desta
    sessão, e Raw gains e Profit sobem junto. O JSON original não é alterado.
  </p>
  <textarea
    class="editor"
    placeholder="Você recebeu: 15 Echo Shards, 2 Mystic Stars, 84 hundred dollars, 4 Heart Stones."
    bind:value={text}
    oninput={schedule}
  ></textarea>
  <div class="panel table-wrap">
    <table class="records">
      <thead>
        <tr>
          <th>No chat</th>
          <th>Item (editável)</th>
          <th class="numeric fit">Quantidade</th>
          <th class="numeric fit">Preço unitário</th>
          <th class="numeric fit">Total</th>
        </tr>
      </thead>
      <tbody>
        {#each lines as line, index (index)}
          <tr>
            <td>{line.chat_name}</td>
            <td>
              <input
                type="text"
                class:unknown={!line.known}
                value={line.item}
                title={line.known
                  ? ""
                  : "Item ainda não visto em nenhuma sessão. Confira o nome; o preço pode ser definido na página Preços."}
                onchange={(e) => rename(index, e.currentTarget.value)}
              />
            </td>
            <td class="numeric">{line.count_text}</td>
            <td class="numeric">{line.price_text}</td>
            <td class="numeric">{line.total_text}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="status {color}">{status}</p>
  {#snippet footer()}
    <button class="paste" onclick={pasteClipboard}><Icon name="paste" /> Colar da área de transferência</button>
    <button onclick={onclose}>Cancelar</button>
    <button class="primary" disabled={!lines.length} onclick={add}><Icon name="check" /> Adicionar à sessão</button>
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

  .editor {
    flex: 2;
    min-height: 80px;
    padding: 8px;
  }

  .table-wrap {
    flex: 3;
    min-height: 0;
    overflow: auto;
  }

  td {
    padding: 4px 11px;
  }

  td input {
    width: 100%;
  }

  input.unknown {
    color: var(--warning);
  }

  .status {
    white-space: pre-wrap;
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
