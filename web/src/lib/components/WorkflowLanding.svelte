<script lang="ts">
  import { onMount } from "svelte";

  const diagram = `flowchart TB
    start([select workflow])

    subgraph wf1[workflow 1: template-first]
      w1a[define semantic fields and options]
      w1b[create component map at different levels]
      w1c[pre-build component names from combinations]
      w1d[fill component database values]
      w1e[upload gis data and validate coverage]
      w1a --> w1b --> w1c --> w1d --> w1e
    end

    subgraph wf2[workflow 2: data-first]
      w2a[upload gis data]
      w2b[extract semantic fields from gis columns]
      w2c[create derived fields]
      w2d[build component graph with and/or logic]
      w2e[define component distributions]
      w2f[ensure full envelope and operations coverage]
      w2a --> w2b --> w2c --> w2d --> w2e --> w2f
    end

    start --> w1a
    start --> w2a`;

  let container: HTMLDivElement | null = null;

  onMount(() => {
    if (!container) return;
    const mermaid = (window as any).mermaid;
    if (!mermaid) return;
    try {
      if (typeof mermaid.run === "function") {
        mermaid.run();
      } else if (typeof mermaid.init === "function") {
        mermaid.init(undefined, container);
      }
    } catch {
      // mermaid render failed; diagram may not display
    }
  });
</script>

<section class="content">
  <h1>welcome to globi workflow manager</h1>
  <p>choose a workflow to get started:</p>
  <div bind:this={container} class="mermaid">{diagram}</div>
</section>

<style>
  .content {
    padding: 24px 32px;
  }

  h1 {
    margin: 0 0 12px;
    font-size: 28px;
  }

  .mermaid {
    margin-top: 16px;
    background: transparent;
  }
</style>
