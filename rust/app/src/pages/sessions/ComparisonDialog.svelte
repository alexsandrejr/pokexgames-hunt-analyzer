<script lang="ts">
  // Sessões lado a lado (como ComparisonDialog): métricas nas linhas, sessões nas colunas, sem
  // ranking nem destaque de "melhor".
  import ExportButton from "../../components/ExportButton.svelte";
  import Modal from "../../components/Modal.svelte";
  import { sessions, type Comparison } from "../../lib/sessions";

  let { huntIds, onclose }: { huntIds: number[]; onclose: () => void } = $props();

  let data = $state<Comparison | null>(null);

  // svelte-ignore state_referenced_locally
  sessions.comparison(huntIds).then((value) => (data = value));
</script>

<Modal title={data?.title ?? "Comparação"} width={Math.min(1300, 260 + 170 * huntIds.length)} height={660} {onclose}>
  {#if data}
    <div class="header">
      <div class="titles">
        <h1>Comparação de Hunts</h1>
        <p class="muted">{data.subtitle}</p>
      </div>
      <ExportButton request={() => ({ kind: "comparison", hunt_ids: huntIds })} />
    </div>
    <div class="panel table-wrap">
      <table class="records">
        <thead>
          <tr>
            <th class="fit">Métrica</th>
            {#each data.headers as [hunt, date], i (i)}
              <th class="numeric">{hunt}<br />{date}</th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each data.rows as row, r (r)}
            <tr class:alt={r % 2 === 1}>
              {#each row as cell, c (c)}
                <td class:numeric={c > 0} class:fit={c === 0}>{cell}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</Modal>

<style>
  .header {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }

  .titles {
    flex: 1;
  }

  h1 {
    margin: 0;
    font-size: 21px;
    font-weight: 600;
  }

  .titles p {
    margin: 2px 0 0;
  }

  .table-wrap {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }

  th.numeric {
    min-width: 130px;
  }

  tr.alt {
    background: var(--surface-alt);
  }
</style>
