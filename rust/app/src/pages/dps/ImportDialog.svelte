<script lang="ts">
  // O que há no arquivo; em cada nome repetido, a pessoa escolhe o que fazer (DpsImportDialog).
  import Modal from "../../components/Modal.svelte";
  import Icon from "../../lib/Icon.svelte";
  import type { ImportPlan } from "../../lib/api";

  let {
    plan,
    onclose,
    onconfirm,
  }: { plan: ImportPlan; onclose: () => void; onconfirm: (actions: string[]) => void } = $props();

  // svelte-ignore state_referenced_locally
  let actions = $state(plan.rows.map((row) => row.action));
  const replacing = $derived(actions.includes("replace"));
</script>

<Modal title="Importar cadastros do DPS" width={820} height={560} {onclose}>
  <p class="muted">{plan.summary}</p>
  <div class="panel table-wrap">
    <table class="records">
      <thead>
        <tr>
          <th class="fit">Tipo</th>
          <th>Nome</th>
          <th>Conteúdo</th>
          <th class="fit">Situação</th>
          <th class="action">O que fazer</th>
        </tr>
      </thead>
      <tbody>
        {#each plan.rows as row, index (index)}
          <tr>
            <td class="fit">{row.kind}</td>
            <td title={row.name}>{row.name}</td>
            <td title={row.content}>{row.content}</td>
            <td class="fit">{row.status}</td>
            <td class="fit">
              <select bind:value={actions[index]}>
                {#each row.actions as action (action.value)}
                  <option value={action.value}>{action.label}</option>
                {/each}
              </select>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  {#if replacing}
    <p class="warning">
      Substituir troca a ficha e apaga os testes atuais desse cadastro. Antes de importar, o app faz um backup do banco.
    </p>
  {/if}
  <p class="muted">
    Criar cópia mantém o cadastro atual e adiciona “Nome (importado)”. Testes feitos em um boss que não vem no arquivo e
    não existe aqui não entram.
  </p>
  {#snippet footer()}
    <button onclick={onclose}>Cancelar</button>
    <button class="primary" onclick={() => onconfirm($state.snapshot(actions))}><Icon name="import" /> Importar</button>
  {/snippet}
</Modal>

<style>
  p {
    margin: 0;
  }

  .table-wrap {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }

  td {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 0;
  }

  td.fit {
    max-width: none;
  }

  th.action,
  td select {
    width: 150px;
    min-width: 150px;
  }
</style>
