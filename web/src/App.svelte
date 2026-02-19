<script>
  import Sidebar from "$lib/components/Sidebar.svelte";
  import WorkflowLanding from "$lib/components/WorkflowLanding.svelte";
  import Workflow1Placeholder from "$lib/components/Workflow1Placeholder.svelte";
  import Workflow2SemanticFields from "$lib/components/Workflow2SemanticFields.svelte";
  import MapperCanvas from "$lib/components/mapper/MapperCanvas.svelte";
  import MapperSidebar from "$lib/components/mapper/MapperSidebar.svelte";
  import { workflowMode } from "$lib/stores/workflow";
  import { onMount } from "svelte";

  let currentPath = "/";
  let currentWorkflow = null;

  onMount(() => {
    const unsubscribe = workflowMode.subscribe((value) => {
      currentWorkflow = value;
    });

    if (typeof window !== "undefined") {
      currentPath = window.location.pathname || "/";
      const handlePopState = () => {
        currentPath = window.location.pathname || "/";
      };
      window.addEventListener("popstate", handlePopState);

      return () => {
        unsubscribe();
        window.removeEventListener("popstate", handlePopState);
      };
    }

    return () => {
      unsubscribe();
    };
  });

  $: activeView =
    currentPath === "/mapper"
      ? "mapper"
      : currentWorkflow === "workflow1"
      ? "workflow1"
      : currentWorkflow === "workflow2"
      ? "workflow2"
      : "landing";
</script>

<main class="layout">
  <Sidebar />
  <section class="main">
    {#if activeView === "landing"}
      <WorkflowLanding />
    {:else if activeView === "workflow1"}
      <Workflow1Placeholder />
    {:else if activeView === "workflow2"}
      <Workflow2SemanticFields />
    {:else if activeView === "mapper"}
      <div class="mapper-layout">
        <div class="mapper-sidebar">
          <MapperSidebar />
        </div>
        <div class="mapper-canvas">
          <MapperCanvas />
        </div>
      </div>
    {/if}
  </section>
</main>

<style>
  .layout {
    display: flex;
    min-height: 100vh;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #ffffff;
    color: #111827;
  }

  .main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .mapper-layout {
    display: grid;
    grid-template-columns: 360px 1fr;
    gap: 0;
    height: 100vh;
    box-sizing: border-box;
  }

  .mapper-sidebar {
    border-right: 1px solid #e5e7eb;
    background: #f9fafb;
    overflow-y: auto;
  }

  .mapper-canvas {
    padding: 16px;
    box-sizing: border-box;
  }
</style>
