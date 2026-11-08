<script lang="ts" module>
  // Os SVGs de resources/icons são desenhados com o traço #aeb6c4; ele vira `currentColor`,
  // para o ícone seguir a cor do texto do tema (como o icons.py faz no Qt).
  const sources = import.meta.glob("../assets/icons/*.svg", { query: "?raw", import: "default", eager: true }) as Record<
    string,
    string
  >;
  const icons: Record<string, string> = {};
  for (const [path, svg] of Object.entries(sources)) {
    const name = path.split("/").pop()!.replace(".svg", "");
    icons[name] = svg.replaceAll("#aeb6c4", "currentColor").replace(/width="\d+" height="\d+"/, 'width="100%" height="100%"');
  }
</script>

<script lang="ts">
  let { name, size = 16 }: { name: string; size?: number } = $props();
</script>

<span class="icon" style:width="{size}px" style:height="{size}px" aria-hidden="true">{@html icons[name] ?? ""}</span>

<style>
  .icon {
    display: inline-flex;
    flex: none;
  }
</style>
