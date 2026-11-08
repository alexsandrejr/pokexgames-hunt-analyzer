<script lang="ts">
  // Barra lateral: marca, botão Importar e navegação entre as seções (como app/ui/sidebar.py).
  import Icon from "../lib/Icon.svelte";
  import MenuButton, { type MenuItem } from "./MenuButton.svelte";

  export interface NavItem {
    key: string;
    label: string;
    icon: string;
    atBottom?: boolean;
  }

  let {
    items,
    current,
    version,
    importItems,
    onselect,
    onabout,
  }: {
    items: NavItem[];
    current: string;
    version: string;
    importItems: MenuItem[];
    onselect: (key: string) => void;
    onabout: () => void;
  } = $props();
</script>

<aside class="sidebar">
  <div class="brand">
    <Icon name="app" size={30} />
    <div>
      <div class="title">PokeXGames</div>
      <div class="subtitle">Hunt Analyzer</div>
    </div>
  </div>
  <MenuButton
    label="Importar"
    icon="import"
    items={importItems}
    primary
    wide
    title={"Importar arquivos, uma pasta ou texto colado do Analyzer.\nVocê também pode arrastar arquivos para a janela."}
  />
  <nav>
    {#each items.filter((i) => !i.atBottom) as item (item.key)}
      <button class="nav" class:active={item.key === current} onclick={() => onselect(item.key)}>
        <Icon name={item.icon} />
        {item.label}
      </button>
    {/each}
    <div class="spacer"></div>
    {#each items.filter((i) => i.atBottom) as item (item.key)}
      <button class="nav" class:active={item.key === current} onclick={() => onselect(item.key)}>
        <Icon name={item.icon} />
        {item.label}
      </button>
    {/each}
  </nav>
  <button class="footer" title="Sobre o aplicativo" onclick={onabout}>Versão {version}</button>
</aside>

<style>
  .sidebar {
    width: 210px;
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px 14px 14px;
    background: var(--sidebar);
    border-right: 1px solid var(--border);
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 6px;
  }

  .title {
    font-size: 16px;
    font-weight: 600;
  }

  .subtitle {
    color: var(--muted);
    font-size: 12px;
  }

  nav {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 10px;
  }

  .spacer {
    flex: 1;
  }

  .nav {
    border: none;
    background: transparent;
    padding: 9px 12px;
    border-radius: 8px;
    color: var(--text);
  }

  .nav :global(.icon) {
    color: var(--icon);
  }

  .nav:hover {
    background: var(--surface-hover);
  }

  .nav.active {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
  }

  .nav.active :global(.icon) {
    color: var(--accent);
  }

  .footer {
    border: none;
    background: transparent;
    color: var(--muted);
    font-size: 12px;
    padding: 4px 12px;
  }

  .footer:hover {
    color: var(--text);
  }

  /* Ícone branco no botão principal, como o white_icon do Python. */
  .sidebar :global(.anchor > button.primary .icon) {
    color: #ffffff;
  }
</style>
