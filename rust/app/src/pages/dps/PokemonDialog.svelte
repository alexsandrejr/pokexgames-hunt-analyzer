<script lang="ts">
  // Nome, observação, ataque básico, buff e tabela de skills (PokemonDialog).
  // O dano só é mostrado: vem dos testes, no dummy escolhido em "Ver dano no dummy".
  import { tick } from "svelte";
  import Modal from "../../components/Modal.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { api, type DamageTexts, type DpsOptions, type PokemonDialogData, type SkillRow } from "../../lib/api";

  let {
    pokemonId,
    dummy: initialDummy,
    options,
    onclose,
    onsaved,
  }: {
    pokemonId: number | null;
    dummy: string;
    options: DpsOptions;
    onclose: () => void;
    onsaved: (id: number, name: string) => void;
  } = $props();

  let data = $state<PokemonDialogData | null>(null);
  // svelte-ignore state_referenced_locally
  let dummy = $state(initialDummy);
  let damages = $state<DamageTexts | null>(null);
  let current = $state(-1);
  let error = $state("");
  let table = $state<HTMLTableSectionElement>();

  // svelte-ignore state_referenced_locally
  api
    .dpsPokemonForm(pokemonId)
    .then((value) => (data = value))
    .catch((e) => (error = String(e)));

  $effect(() => {
    api
      .dpsDamageTexts(pokemonId, dummy)
      .then((value) => (damages = value))
      .catch((e) => (error = String(e)));
  });

  function skillDamage(skill: SkillRow): string {
    if (skill.skill_id === null || !damages) return "sem teste";
    return damages.skills[String(skill.skill_id)] ?? "sem teste";
  }

  /** Atualiza o % sugerido, a menos que a pessoa já o tenha alterado. */
  function classChanged(skill: SkillRow) {
    if (!data) return;
    const suggestion =
      skill.shape === "target" && skill.reach === "melee" ? data.suggestions.target_melee : data.suggestions.default;
    if (skill.percent.trim().replace(/%$/, "").trim() === skill.suggestion) skill.percent = suggestion;
    skill.suggestion = suggestion;
  }

  async function addSkill() {
    if (!data) return;
    data.form.skills.push(structuredClone($state.snapshot(data.empty_skill)));
    current = data.form.skills.length - 1;
    await tick();
    table?.querySelector<HTMLInputElement>(`tr:nth-child(${current + 1}) input.cooldown`)?.focus();
  }

  function removeSkill() {
    if (!data) return;
    const row = current >= 0 && current < data.form.skills.length ? current : data.form.skills.length - 1;
    if (row >= 0) data.form.skills.splice(row, 1);
    current = -1;
  }

  async function save() {
    if (!data) return;
    try {
      const form = $state.snapshot(data.form);
      onsaved(await api.dpsSavePokemon(pokemonId, form), form.name.trim());
    } catch (e) {
      error = String(e);
    }
  }
</script>

<Modal title={pokemonId === null ? "Novo pokémon" : "Editar pokémon"} width={980} height={800} {error} {onclose}>
  {#if data}
    {@const form = data.form}
    <div class="form">
      <span>Nome</span>
      <!-- svelte-ignore a11y_autofocus -->
      <input type="text" placeholder="Ex.: Chumbin" bind:value={form.name} autofocus />
      <span>Observação</span>
      <textarea rows="2" placeholder="Ex.: +70, X-Attack, dano medido no boss Terror" bind:value={form.note}></textarea>
    </div>

    <div class="extras">
      <section class="card basic">
        <label class="check"><input type="checkbox" bind:checked={form.has_basic} /> Tem ataque básico</label>
        <fieldset class="form" disabled={!form.has_basic}>
          <span>Dano (dos testes)</span><span>{damages?.basic ?? ""}</span>
          <span>Aproveitamento (%)</span><input type="text" bind:value={form.basic_percent} />
          <span>Elemento</span>
          <select bind:value={form.basic_element}>
            <option value={null}>—</option>
            {#each options.elements as element (element.value)}
              <option value={element.value}>{element.label}</option>
            {/each}
          </select>
        </fieldset>
        <p class="hint">{data.turn_hint}</p>
      </section>
      <section class="card buff">
        <label class="check"><input type="checkbox" bind:checked={form.has_buff} /> Tem buff</label>
        <fieldset class="form" disabled={!form.has_buff}>
          <span>Recarga (s)</span><input type="text" placeholder="Ex.: 50" bind:value={form.buff_cooldown} />
          <span>Multiplicador do básico</span><input type="text" bind:value={form.buff_basic} />
          <span>Duração no básico (s)</span><input type="text" bind:value={form.buff_duration} />
          <span>Multiplicador da próxima magia</span><input type="text" bind:value={form.buff_spell} />
        </fieldset>
        <p class="hint">Multiplicador: 1 = sem efeito, 1,5 = +50%, 2 = dobra. A próxima magia é a que mais rende.</p>
      </section>
    </div>

    <div class="skills-header">
      <h3 class="section-title">Skills</h3>
      <div class="grow"></div>
      <span class="field-label">Ver dano no dummy</span>
      <select bind:value={dummy}>
        {#each options.dummies as d (d.value)}
          <option value={d.value}>{d.label}</option>
        {/each}
      </select>
      <button onclick={addSkill}>Adicionar skill</button>
      <button class="danger" onclick={removeSkill}><Icon name="trash" /> Remover skill</button>
    </div>

    <div class="panel skills">
      <table class="records">
        <thead>
          <tr>
            <th>Nome (opcional)</th>
            <th class="fixed">Forma</th>
            <th class="fixed">Alcance</th>
            <th class="fixed">Elemento</th>
            <th>Dano</th>
            <th>Recarga (s)</th>
            <th>Aproveitamento (%)</th>
          </tr>
        </thead>
        <tbody bind:this={table}>
          {#each form.skills as skill, index (skill)}
            <tr class:selected={index === current} onfocusin={() => (current = index)}>
              <td><input type="text" bind:value={skill.name} /></td>
              <td>
                <select bind:value={skill.shape} onchange={() => classChanged(skill)}>
                  {#each options.shapes as shape (shape.value)}
                    <option value={shape.value}>{shape.label}</option>
                  {/each}
                </select>
              </td>
              <td>
                <select bind:value={skill.reach} onchange={() => classChanged(skill)}>
                  {#each options.reaches as reach (reach.value)}
                    <option value={reach.value}>{reach.label}</option>
                  {/each}
                </select>
              </td>
              <td>
                <select bind:value={skill.element}>
                  <option value={null}>—</option>
                  {#each options.elements as element (element.value)}
                    <option value={element.value}>{element.label}</option>
                  {/each}
                </select>
              </td>
              <td class="damage">{skillDamage(skill)}</td>
              <td><input class="cooldown" type="text" bind:value={skill.cooldown} /></td>
              <td><input type="text" bind:value={skill.percent} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
  {#snippet footer()}
    <button onclick={onclose}>Cancelar</button>
    <button class="primary" onclick={save}><Icon name="check" /> Salvar</button>
  {/snippet}
</Modal>

<style>
  textarea {
    height: 56px;
  }

  .extras {
    display: flex;
    gap: 12px;
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }

  .basic {
    flex: 2;
  }

  .buff {
    flex: 3;
  }

  fieldset {
    margin: 0;
    padding: 0;
    border: none;
    min-width: 0;
  }

  fieldset:disabled {
    color: var(--muted);
  }

  fieldset input,
  fieldset select {
    min-width: 0;
  }

  .hint {
    margin: 0;
  }

  .skills-header {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .grow {
    flex: 1;
  }

  .skills {
    flex: 1;
    min-height: 180px;
    overflow: auto;
  }

  .skills td {
    padding: 4px 6px;
  }

  .skills th.fixed,
  .skills td select {
    width: 110px;
    min-width: 110px;
  }

  .skills td input {
    width: 100%;
    min-width: 60px;
  }

  .skills td.damage {
    color: var(--muted);
    white-space: nowrap;
    padding-left: 11px;
  }

  .skills tr.selected {
    background: var(--selection);
  }
</style>
