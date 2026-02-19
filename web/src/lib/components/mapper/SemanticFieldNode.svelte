<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";

  export let data: {
    fieldName: string;
    fieldType: "categorical" | "numeric";
    optionCount: number;
    color: string;
    isDerived: boolean;
    options?: string[];
    compoundDerived?: { sourceFieldIds: string[]; logic: "and" | "or" };
  };
  export let selected = false;

  let showOptions = false;
</script>

<div class:selected class="node" style="--field-color: {data.color}">
  <Handle type="source" position={Position.Bottom} id="bottom" />
  <div class="color-bar"></div>
  <div class="title">
    <span class="dot" style={`background:${data.color}`}></span>
    <span>{data.fieldName}</span>
    {#if data.compoundDerived}
      <span class="badge">compound ({data.compoundDerived.logic})</span>
    {:else if data.isDerived}
      <span class="badge">derived</span>
    {/if}
  </div>
  <div class="meta">
    {data.fieldType === "categorical" ? `${data.optionCount} options` : "numeric"}
  </div>
  {#if data.fieldType === "categorical" && data.optionCount > 0}
    <button
      type="button"
      class="link"
      on:click={() => showOptions = !showOptions}
    >
      {showOptions ? "hide options" : "show options"}
    </button>
    {#if showOptions && data.options}
      <div class="options-list">
        {#each data.options.slice(0, 6) as option}
          <span class="option-tag">{option}</span>
        {/each}
        {#if data.options.length > 6}
          <span class="option-more">+{data.options.length - 6} more</span>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  .node {
    min-width: 180px;
    border: 1px solid #e2e2e2;
    border-radius: 8px;
    background: #ffffff;
    padding: 10px 12px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
    position: relative;
    overflow: hidden;
  }

  .color-bar {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--field-color, #3b82f6);
  }

  .node.selected {
    border-color: #3b82f6;
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
  }

  .title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    color: #1c1c1c;
    font-size: 13px;
  }

  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
  }

  .badge {
    font-size: 10px;
    color: #1f2937;
    background: #e5e7eb;
    padding: 2px 6px;
    border-radius: 999px;
  }

  .meta {
    font-size: 12px;
    color: #6b7280;
    margin-top: 6px;
  }

  .link {
    margin-top: 8px;
    background: none;
    border: none;
    color: #2563eb;
    padding: 0;
    font-size: 12px;
    cursor: pointer;
  }

  .link:hover {
    color: #1d4ed8;
  }

  .options-list {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid #e5e7eb;
  }

  .option-tag {
    font-size: 10px;
    padding: 2px 6px;
    background: #f3f4f6;
    border-radius: 4px;
    color: #4b5563;
  }

  .option-more {
    font-size: 10px;
    color: #9ca3af;
    padding: 2px 6px;
  }

  :global(.svelte-flow__handle) {
    opacity: 0.6;
    transition: opacity 0.15s ease;
  }

  .node:hover :global(.svelte-flow__handle) {
    opacity: 1;
  }
</style>
