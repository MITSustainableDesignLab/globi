<script lang="ts">
  import { workflowMode } from "$lib/stores/workflow";

  const setMode = (mode: "workflow1" | "workflow2") => {
    workflowMode.set(mode);
  };

  export let collapsed = false;
</script>

<aside class:collapsed class="sidebar">
  <button type="button" class="toggle" on:click={() => (collapsed = !collapsed)}>
    {collapsed ? "→" : "←"}
  </button>
  {#if !collapsed}
  <h1>globi workflow manager</h1>
  <hr />
  <h2>select workflow</h2>
  <div class="button-stack">
    <button on:click={() => setMode("workflow1")}>workflow 1: template-first</button>
    <button on:click={() => setMode("workflow2")}>workflow 2: data-first</button>
  </div>
  <div class="link-stack">
    <a href="/">workflow home</a>
    <a href="/mapper">visual component mapper</a>
  </div>
  <hr />
  <div class="about">
    <h3>about globi</h3>
    <p>geospatial building energy interface for large-scale urban energy modeling.</p>
    <p>built with energyplus, scythe, and streamlit.</p>
  </div>
  {/if}
</aside>

<style>
  .sidebar {
    width: 320px;
    padding: 24px;
    border-right: 1px solid #e2e2e2;
    background: #fafafa;
    min-height: 100vh;
    box-sizing: border-box;
    position: relative;
    transition: width 0.2s ease;
  }

  .sidebar.collapsed {
    width: 48px;
    padding: 24px 8px;
  }

  .toggle {
    position: absolute;
    top: 12px;
    right: 8px;
    width: 32px;
    height: 32px;
    border: 1px solid #d8d8d8;
    border-radius: 8px;
    background: white;
    color: #1c1c1c;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    padding: 0;
    transition: all 0.2s ease;
  }

  .toggle:hover {
    background: #f3f3f3;
    border-color: #cbd5e1;
  }

  h1 {
    font-size: 20px;
    margin: 0 0 12px;
    color: #1c1c1c;
    font-weight: 600;
  }

  h2 {
    font-size: 14px;
    margin: 0 0 12px;
    text-transform: lowercase;
    color: #4b5563;
    font-weight: 500;
  }

  .button-stack {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .link-stack {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 12px;
  }

  .link-stack a {
    color: #2563eb;
    font-size: 12px;
    text-decoration: none;
    transition: color 0.2s ease;
  }

  .link-stack a:hover {
    color: #1d4ed8;
    text-decoration: underline;
  }

  button {
    padding: 10px 12px;
    border: 1px solid #d8d8d8;
    border-radius: 8px;
    background: white;
    color: #1c1c1c;
    cursor: pointer;
    text-align: left;
    font-size: 13px;
    transition: all 0.2s ease;
  }

  button:hover {
    background: #f3f3f3;
    border-color: #cbd5e1;
  }

  .about {
    font-size: 12px;
    color: #6b7280;
    line-height: 1.5;
  }

  .about h3 {
    color: #374151;
    font-size: 13px;
    margin: 0 0 8px;
  }

  hr {
    border: none;
    border-top: 1px solid #e2e2e2;
    margin: 16px 0;
  }
</style>
