<script lang="ts">
  // Turno do ataque básico e aproveitamentos sugeridos para novos cadastros (DpsSettingsDialog).
  import Modal from "../../components/Modal.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { api, type SettingsForm } from "../../lib/api";

  let { onclose, onsaved }: { onclose: () => void; onsaved: () => void } = $props();

  let form = $state<SettingsForm | null>(null);
  let error = $state("");

  api
    .dpsSettingsForm()
    .then((value) => (form = value))
    .catch((e) => (error = String(e)));

  async function save() {
    if (!form) return;
    try {
      await api.dpsSaveSettings(form);
      onsaved();
    } catch (e) {
      error = String(e);
    }
  }
</script>

<Modal title="Ajustes do DPS" width={460} {error} {onclose}>
  {#if form}
    <div class="form">
      <span>Turno do ataque básico (s)</span><input type="text" bind:value={form.turn} />
      <span>Target + Melee (%)</span><input type="text" bind:value={form.target_melee} />
      <span>Demais skills (%)</span><input type="text" bind:value={form.default} />
      <span>Ataque básico (%)</span><input type="text" bind:value={form.basic} />
    </div>
    <p class="muted">
      O turno vale para todos os pokémons e muda o ranking na hora. Os % são só sugestões para novos cadastros: não
      alteram o que já foi salvo.
    </p>
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
</style>
