<script lang="ts">
  // Botão com menu (como QPushButton.setMenu): abre embaixo e fecha ao escolher ou clicar fora.
  import Icon from "../lib/Icon.svelte";

  export interface MenuItem {
    label: string;
    icon?: string;
    /** Atalho mostrado à direita, como no QMenu. */
    shortcut?: string;
    disabled?: boolean;
    action: () => void;
  }

  let {
    label,
    icon,
    items,
    primary = false,
    disabled = false,
    title,
    align = "left",
    wide = false,
  }: {
    label: string;
    icon?: string;
    items: MenuItem[];
    primary?: boolean;
    disabled?: boolean;
    title?: string;
    /** De que lado o menu se alinha ao botão. */
    align?: "left" | "right";
    /** Botão na largura toda (barra lateral). */
    wide?: boolean;
  } = $props();

  let open = $state(false);

  function choose(item: MenuItem) {
    open = false;
    item.action();
  }
</script>

<svelte:window onclick={() => (open = false)} />

<div class="anchor" class:wide>
  <button
    class:primary
    {disabled}
    {title}
    onclick={(e) => {
      e.stopPropagation();
      open = !open;
    }}
  >
    {#if icon}<Icon name={icon} />{/if}
    <span class="label">{label}</span>
    <Icon name={primary ? "chevron-down-white" : "chevron-down"} size={10} />
  </button>
  {#if open}
    <div class="menu" class:right={align === "right"} role="menu">
      {#each items as item (item.label)}
        <button role="menuitem" disabled={item.disabled} onclick={() => choose(item)}>
          {#if item.icon}<Icon name={item.icon} />{/if}
          <span class="item-label">{item.label}</span>
          {#if item.shortcut}<span class="shortcut">{item.shortcut}</span>{/if}
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .anchor {
    position: relative;
  }

  .anchor.wide > button {
    width: 100%;
    justify-content: center;
  }

  .menu {
    top: calc(100% + 4px);
    left: 0;
  }

  .menu.right {
    left: auto;
    right: 0;
  }

  .menu button {
    gap: 10px;
  }

  .item-label {
    flex: 1;
    text-align: left;
  }

  .shortcut {
    color: var(--muted);
    font-size: 12px;
    margin-left: 16px;
  }
</style>
