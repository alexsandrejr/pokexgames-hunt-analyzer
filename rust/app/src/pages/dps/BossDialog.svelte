<script lang="ts">
  // Nome, tempo limite (em minutos), elementos e efetividade dos ataques contra o boss (BossDialog).
  import Modal from "../../components/Modal.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { api, type BossForm, type DpsOptions } from "../../lib/api";

  let {
    bossId,
    options,
    onclose,
    onsaved,
  }: { bossId: number | null; options: DpsOptions; onclose: () => void; onsaved: (id: number) => void } = $props();

  let form = $state<BossForm | null>(null);
  let error = $state("");

  // svelte-ignore state_referenced_locally
  api
    .dpsBossForm(bossId)
    .then((value) => (form = value))
    .catch((e) => (error = String(e)));

  async function save() {
    if (!form) return;
    try {
      onsaved(await api.dpsSaveBoss(bossId, form));
    } catch (e) {
      error = String(e);
    }
  }
</script>

<Modal title={bossId === null ? "Novo boss" : "Editar boss"} width={760} {error} {onclose}>
  {#if form}
    <div class="form">
      <span>Nome</span><input type="text" placeholder="Ex.: Terror" bind:value={form.name} />
      <span>Tempo limite (min)</span><input type="text" bind:value={form.minutes} />
      <span>Elementos</span>
      <div class="elements">
        {#each form.elements as _, index (index)}
          <select bind:value={form.elements[index]}>
            <option value={null}>—</option>
            {#each options.elements as element (element.value)}
              <option value={element.value}>{element.label}</option>
            {/each}
          </select>
        {/each}
      </div>
    </div>
    <h3 class="section-title">Efetividade dos ataques</h3>
    <p class="muted">
      Copie da Pokédex do jogo o resultado de cada ataque contra este boss. Só o cálculo por Efetividade usa esta lista;
      os elementos do boss são apenas informativos.
    </p>
    <div class="grid">
      {#each options.elements as element (element.value)}
        <span>{element.label}</span>
        <select bind:value={form.effectiveness[element.value]}>
          {#each options.levels as level (level.value)}
            <option value={level.value}>{level.label}</option>
          {/each}
        </select>
      {/each}
    </div>
  {/if}
  {#snippet footer()}
    <button onclick={onclose}>Cancelar</button>
    <button class="primary" onclick={save}><Icon name="check" /> Salvar</button>
  {/snippet}
</Modal>

<style>
  p {
    margin: 0;
  }

  .elements {
    display: flex;
    gap: 10px;
  }

  /* Três colunas de elemento + seletor, como o QGridLayout do Python. */
  .grid {
    display: grid;
    grid-template-columns: repeat(3, max-content 1fr);
    align-items: center;
    gap: 8px 10px;
  }

  .grid select {
    min-width: 0;
  }
</style>
