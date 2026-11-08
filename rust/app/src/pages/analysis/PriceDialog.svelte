<script lang="ts">
  // Diálogo do preço de um item (como PriceDialog): nome (conhecido ou digitado) e preço unitário.
  import Modal from "../../components/Modal.svelte";
  import { analysis, type PriceCheck } from "../../lib/analysis.svelte";
  import Icon from "../../lib/Icon.svelte";

  let {
    names,
    initialName = "",
    initialPrice = "",
    onclose,
    onsave,
  }: {
    names: string[];
    initialName?: string;
    initialPrice?: string;
    onclose: () => void;
    onsave: (name: string, price: string) => Promise<string | null>;
  } = $props();

  // svelte-ignore state_referenced_locally
  let name = $state(initialName);
  // svelte-ignore state_referenced_locally
  let price = $state(initialPrice);
  let check = $state<PriceCheck>({ text: "", error: false, valid: false });
  let error = $state("");
  let priceInput = $state<HTMLInputElement>();

  $effect(() => {
    const [n, p] = [name, price];
    analysis.priceCheck(n, p).then((value) => {
      if (n === name && p === price) check = value;
    });
  });

  $effect(() => {
    if (initialName && priceInput) {
      priceInput.focus();
      priceInput.select();
    }
  });

  async function save() {
    if (!check.valid) return;
    error = (await onsave(name, price)) ?? "";
  }
</script>

<Modal title="Preço do item" width={460} {error} {onclose}>
  <div class="form">
    <label for="price-name">Item</label>
    <input
      id="price-name"
      list="price-names"
      placeholder="Escolha ou digite o item…"
      bind:value={name}
      onkeydown={(e) => e.key === "Enter" && save()}
    />
    <datalist id="price-names">{#each names as item (item)}<option value={item}></option>{/each}</datalist>
    <label for="price-value">Preço unitário</label>
    <input
      id="price-value"
      placeholder="Ex.: 1500, 800k, 1,2kk"
      bind:value={price}
      bind:this={priceInput}
      onkeydown={(e) => e.key === "Enter" && save()}
    />
  </div>
  {#if check.text}<p class="info" class:negative={check.error}>{check.text}</p>{/if}
  {#snippet footer()}
    <button onclick={onclose}>Cancelar</button>
    <button class="primary" disabled={!check.valid} onclick={save}><Icon name="check" /> Salvar</button>
  {/snippet}
</Modal>

<style>
  .info {
    margin: 12px 0 0;
    color: var(--muted);
  }

  .info.negative {
    color: var(--negative);
  }
</style>
