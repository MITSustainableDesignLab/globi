<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import { openComponentWizard, toggleComponentExpanded } from "$lib/stores/mapperStore";

  export let data: {
    path: string;
    displayName: string;
    description: string;
    linkedFields: string[];
    color: string;
    status: "unconnected" | "connected" | "complete";
    distributionCount?: number;
    hasChildren?: boolean;
    hiddenChildCount?: number;
    isExpanded?: boolean;
    canExpand?: boolean;
  };
  export let selected = false;

  function handleDoubleClick() {
    openComponentWizard(data.path);
  }

  function handleConfigureClick(e: MouseEvent) {
    e.stopPropagation();
    openComponentWizard(data.path);
  }

  function handleExpandClick(e: MouseEvent) {
    e.stopPropagation();
    toggleComponentExpanded(data.path);
  }

  $: statusColor = data.status === "complete" || data.status === "connected" ? "#22c55e" : "#f97316";

  $: statusBg = data.status === "complete" || data.status === "connected" ? "#f0fdf4" : "#fff7ed";

  $: statusLabel = data.status === "complete" ? "Fully defined" :
                   data.status === "connected" ? "Connected" : "Unconnected";
</script>

<div
  class="node"
  class:selected
  class:status-complete={data.status === "complete"}
  class:status-connected={data.status === "connected"}
  class:status-unconnected={data.status === "unconnected"}
  style={`--component-color:${data.color}; --status-color:${statusColor}; --status-bg:${statusBg}`}
  on:dblclick={handleDoubleClick}
  role="button"
  tabindex="0"
  on:keydown={(e) => e.key === "Enter" && handleDoubleClick()}
>
  <Handle type="target" position={Position.Top} id="top" />
  <Handle type="source" position={Position.Bottom} id="bottom" />

  <div class="status-indicator" title={statusLabel}></div>

  <div class="header">
    <span class="title">{data.displayName}</span>
    <div class="header-actions">
      {#if data.canExpand}
        <button
          type="button"
          class="expand-btn"
          on:click={handleExpandClick}
          title={data.isExpanded ? "Collapse children" : `Expand (${data.hiddenChildCount} hidden)`}
        >
          {#if data.isExpanded}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 15l-6-6-6 6"/>
            </svg>
          {:else}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M6 9l6 6 6-6"/>
            </svg>
          {/if}
        </button>
      {/if}
      <button
        type="button"
        class="configure-btn"
        on:click={handleConfigureClick}
        title="Configure values"
        on:mousedown|stopPropagation
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 15a3 3 0 100-6 3 3 0 000 6z"/>
          <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>
        </svg>
      </button>
    </div>
  </div>

  <div class="path">{data.path}</div>
  <div class="description">{data.description}</div>

  <div class="stats">
    <div class="stat">
      <span class="stat-icon">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
        </svg>
      </span>
      {data.linkedFields.length} field{data.linkedFields.length !== 1 ? "s" : ""}
    </div>

    {#if data.distributionCount !== undefined && data.distributionCount > 0}
      <div class="stat values">
        <span class="stat-icon">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 20V10M18 20V4M6 20v-4" />
          </svg>
        </span>
        {data.distributionCount} value{data.distributionCount !== 1 ? "s" : ""}
      </div>
    {/if}

    {#if data.hiddenChildCount && data.hiddenChildCount > 0}
      <div class="stat hidden-children">
        <span class="stat-icon">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M17 8l4 4-4 4M7 8l-4 4 4 4M14 4l-4 16"/>
          </svg>
        </span>
        {data.hiddenChildCount} hidden
      </div>
    {/if}
  </div>

  <div class="status-badge" style="background: {statusColor}20; color: {statusColor}; border-color: {statusColor}40">
    {statusLabel}
  </div>
</div>

<style>
  .node {
    min-width: 240px;
    border: 2px solid var(--status-color, #e2e2e2);
    border-radius: 8px;
    background: var(--status-bg, #ffffff);
    padding: 10px 12px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
    position: relative;
    transition: all 0.15s ease;
  }

  .status-indicator {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 4px;
    background: var(--status-color, #e2e2e2);
    border-radius: 6px 6px 0 0;
  }

  .node.selected {
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.3);
  }

  .node:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 4px;
  }

  .title {
    font-weight: 600;
    font-size: 13px;
    color: #1c1c1c;
  }

  .header-actions {
    display: flex;
    gap: 4px;
  }

  .configure-btn,
  .expand-btn {
    width: 24px;
    height: 24px;
    border: none;
    background: transparent;
    color: #9ca3af;
    border-radius: 4px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
    padding: 0;
    position: relative;
    z-index: 10;
    pointer-events: auto;
  }

  .configure-btn:hover,
  .expand-btn:hover {
    background: #f3f4f6;
    color: #3b82f6;
  }

  .node:hover .configure-btn,
  .node:hover .expand-btn {
    color: #6b7280;
  }

  .expand-btn {
    color: #6b7280;
  }

  .path {
    font-size: 10px;
    color: #9ca3af;
    font-family: monospace;
    margin-top: 4px;
  }

  .description {
    font-size: 11px;
    color: #6b7280;
    margin-top: 4px;
    line-height: 1.4;
  }

  .stats {
    display: flex;
    gap: 12px;
    margin-top: 8px;
    flex-wrap: wrap;
  }

  .stat {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 10px;
    color: #6b7280;
  }

  .stat.values {
    color: #3b82f6;
  }

  .stat.hidden-children {
    color: #9ca3af;
  }

  .stat-icon {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .status-badge {
    margin-top: 8px;
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 4px;
    width: fit-content;
    font-weight: 500;
    border: 1px solid;
  }

  :global(.svelte-flow__handle) {
    opacity: 0.6;
    transition: opacity 0.15s ease;
  }

  .node:hover :global(.svelte-flow__handle) {
    opacity: 1;
  }
</style>
