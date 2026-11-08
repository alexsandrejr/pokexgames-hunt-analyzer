<script lang="ts">
  // Seletor das categorias analisadas (como CategoryScopeCombo): Hunts, bosses ou tudo.
  import { analysis } from "../../lib/analysis.svelte";

  let { value = $bindable(0) }: { value?: number } = $props();

  let labels = $state<string[]>([]);
  analysis.scopes().then((items) => (labels = items));
</script>

<select bind:value title="Quais sessões entram nas estatísticas desta página">
  {#each labels as label, index (index)}
    <option value={index}>{label}</option>
  {/each}
</select>
