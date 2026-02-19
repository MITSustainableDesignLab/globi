<script lang="ts">
  import { createEventDispatcher } from "svelte";

  export let data: {
    componentType: string;
    sourceFields: string[];
    combinationCount: number;
    definedCount: number;
    isFullyDefined: boolean;
    hasErrors: boolean;
  };
  export let selected = false;

  const dispatch = createEventDispatcher();

  const progress = () =>
    data.combinationCount > 0
      ? Math.round((data.definedCount / data.combinationCount) * 100)
      : 0;

  const handleConfigureClick = () => {
    dispatch("configure", { componentType: data.componentType });
  };
</script>

<div class:selected class:warning={data.hasErrors} class="node">
  <div class="header">
    <span>{data.componentType}</span>
    {#if data.hasErrors}
      <span class="badge">needs attention</span>
    {/if}
  </div>
  <div class="meta">{data.sourceFields.join(" × ") || "no sources"}</div>
  <div class="meta">{data.combinationCount} combinations</div>
  <div class="progress">
    <div class="bar" style={`width:${progress()}%`}></div>
  </div>
  <div class="meta">{data.definedCount}/{data.combinationCount} defined</div>
  <button type="button" class="button" on:click={handleConfigureClick}>configure values</button>
</div>

<style>
  .node {
    min-width: 200px;
    border: 1px solid #d8d8d8;
    border-radius: 8px;
    background: #ffffff;
    padding: 12px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
  }

  .node.selected {
    border-color: #2563eb;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
  }

  .node.warning {
    border-color: #f59e0b;
  }

  .header {
    display: flex;
    justify-content: space-between;
    font-weight: 600;
  }

  .badge {
    font-size: 10px;
    color: #92400e;
    background: #fef3c7;
    padding: 2px 6px;
    border-radius: 999px;
  }

  .meta {
    font-size: 12px;
    color: #6b7280;
    margin-top: 6px;
  }

  .progress {
    height: 6px;
    background: #e5e7eb;
    border-radius: 999px;
    margin-top: 8px;
  }

  .bar {
    height: 6px;
    background: #2563eb;
    border-radius: 999px;
  }

  .button {
    margin-top: 10px;
    padding: 6px 8px;
    border: 1px solid #d1d5db;
    background: #f9fafb;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12px;
  }
</style>
