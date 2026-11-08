<script lang="ts">
  // Testes de um pokémon: até 3 danos por dummy ou boss, em cada skill e no ataque básico
  // (DamageTestsDialog). Grava ao trocar de skill e ao fechar: não há o que descartar.
  import { tick } from "svelte";
  import Modal from "../../components/Modal.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { api, type TestRow, type TestsDialogData } from "../../lib/api";

  let { pokemonId, onclose }: { pokemonId: number; onclose: () => void } = $props();

  let data = $state<TestsDialogData | null>(null);
  let index = $state(0);
  let rows = $state<TestRow[]>([]);
  let currentRow = $state(-1);
  let error = $state("");
  let body = $state<HTMLTableSectionElement>();

  const target = $derived(data?.targets[index] ?? null);

  // svelte-ignore state_referenced_locally
  api
    .dpsTestsForm(pokemonId)
    .then((value) => {
      data = value;
      rows = structuredClone(value.targets[0]?.tests ?? []);
    })
    .catch((e) => (error = String(e)));

  function targetText(i: number): string {
    const t = data!.targets[i];
    return t.tests.length ? `${t.label} (${t.tests.length})` : t.label;
  }

  /** Grava os testes da skill aberta; se forem inválidos, mostra o erro e devolve false. */
  async function saveCurrent(): Promise<boolean> {
    if (!data || !target) return true;
    try {
      const input = rows.map((row) => ({ place: row.place, damages: [...row.damages] }));
      target.tests = await api.dpsSaveTests(pokemonId, target.skill_id, input);
      error = "";
      return true;
    } catch (e) {
      error = String(e);
      return false;
    }
  }

  async function chooseTarget(i: number) {
    if (i === index || !data) return;
    if (!(await saveCurrent())) return;
    index = i;
    rows = structuredClone($state.snapshot(data.targets[i].tests));
    currentRow = -1;
  }

  /** O primeiro dummy ainda sem teste nesta skill. */
  function freeDummy(): string {
    const dummies = data!.places.slice(0, data!.dummy_count);
    const used = new Set(rows.map((row) => row.place));
    return (dummies.find((d) => !used.has(d.value)) ?? dummies[0]).value;
  }

  async function addTest() {
    if (!data) return;
    rows.push({ ...structuredClone($state.snapshot(data.empty_row)), place: freeDummy() });
    currentRow = rows.length - 1;
    await tick();
    body?.querySelector<HTMLInputElement>(`tr:nth-child(${currentRow + 1}) input`)?.focus();
  }

  function removeTest() {
    const row = currentRow >= 0 && currentRow < rows.length ? currentRow : rows.length - 1;
    if (row >= 0) rows.splice(row, 1);
    currentRow = -1;
  }

  async function updateAverage(row: TestRow) {
    row.average = await api.dpsTestAverage([...row.damages]);
  }

  async function close() {
    if (await saveCurrent()) onclose();
  }
</script>

<Modal title={data?.title ?? "Testes"} width={960} height={520} {error} onclose={close}>
  {#if data && target}
    <div class="content">
      <ul class="targets panel" role="listbox">
        {#each data.targets as _, i (i)}
          <li role="option" aria-selected={i === index} class:selected={i === index}>
            <button onclick={() => chooseTarget(i)}>{targetText(i)}</button>
          </li>
        {/each}
      </ul>
      <div class="side">
        <h3 class="section-title">{target.heading}</h3>
        <div class="panel table-wrap">
          <table class="records">
            <thead>
              <tr>
                <th class="place">Testado em</th>
                {#each data.empty_row.damages as _, n (n)}
                  <th>Dano {n + 1}</th>
                {/each}
                <th>Média</th>
                <th class="fit">Cadastrado</th>
                <th class="fit">Modificado</th>
              </tr>
            </thead>
            <tbody bind:this={body}>
              {#each rows as row, r (row)}
                <tr class:selected={r === currentRow} onfocusin={() => (currentRow = r)}>
                  <td>
                    <select bind:value={row.place}>
                      {#each data.places as place, p (place.value)}
                        {#if p === data.dummy_count}<option disabled>──────────</option>{/if}
                        <option value={place.value}>{place.label}</option>
                      {/each}
                    </select>
                  </td>
                  {#each row.damages as _, d (d)}
                    <td><input type="text" bind:value={row.damages[d]} oninput={() => updateAverage(row)} /></td>
                  {/each}
                  <td class="muted">{row.average}</td>
                  <td class="fit muted" title={row.created_tip}>{row.created}</td>
                  <td class="fit muted" title={row.updated_tip}>{row.updated}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div class="actions">
          <button onclick={addTest}>Adicionar teste</button>
          <button class="danger" onclick={removeTest}><Icon name="trash" /> Remover teste</button>
        </div>
        <p class="muted">
          Escolha um dummy ou, para o dano real, “Boss: nome”. O ranking usa a média conforme o “Calcular por” de cada
          boss, considerando só os danos preenchidos. Modificado muda só quando os danos mudam; passe o mouse sobre uma
          data para ver a hora.
        </p>
      </div>
    </div>
  {:else if data}
    <p class="muted">Cadastre uma skill ou o ataque básico para registrar testes.</p>
  {/if}
  {#snippet footer()}
    <button class="primary" onclick={close}><Icon name="check" /> Fechar</button>
  {/snippet}
</Modal>

<style>
  p {
    margin: 0;
  }

  .content {
    flex: 1;
    min-height: 0;
    display: flex;
    gap: 14px;
  }

  .targets {
    flex: none;
    width: 210px;
    margin: 0;
    padding: 4px;
    list-style: none;
    overflow-y: auto;
  }

  .targets button {
    width: 100%;
    border: none;
    background: transparent;
    padding: 6px;
    border-radius: 6px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .targets button:hover {
    background: var(--surface-alt);
  }

  .targets li.selected button {
    background: var(--selection);
  }

  .side {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .table-wrap {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }

  td {
    padding: 4px 6px;
  }

  th.place,
  td select {
    width: 150px;
    min-width: 150px;
  }

  td input {
    width: 100%;
    min-width: 56px;
  }

  td.muted {
    white-space: nowrap;
    padding-left: 11px;
  }

  tr.selected {
    background: var(--selection);
  }

  .actions {
    display: flex;
    gap: 8px;
  }
</style>
