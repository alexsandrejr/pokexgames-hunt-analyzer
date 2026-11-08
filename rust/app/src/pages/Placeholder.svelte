<script lang="ts">
  // Seções que ainda vão ser portadas (fase 4 do plano em docs/migracao-rust.md).
  let { title }: { title: string } = $props();
</script>

<header>
  <h1>{title}</h1>
  <p class="muted">Esta página ainda vai ser portada para a versão em Rust.</p>
</header>

<style>
  h1 {
    margin: 0;
    font-size: 21px;
    font-weight: 600;
  }

  p {
    margin: 4px 0 0;
  }
</style>
