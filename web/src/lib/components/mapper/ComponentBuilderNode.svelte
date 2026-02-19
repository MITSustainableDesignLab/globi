<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";

  export let data: {
    path: string;
    displayName: string;
    description: string;
    color: string;
    linkedFields: string[];
    distributionCount?: number;
    isSelected?: boolean;
  };
  export let selected = false;
</script>

<div
  class="node component-node"
  class:selected={selected || data.isSelected}
  class:has-values={data.distributionCount && data.distributionCount > 0}
>
  <Handle type="target" position={Position.Left} />
  <Handle type="source" position={Position.Right} />
  <div class="header">
    <div class="color-bar" style={`background:${data.color}`}></div>
    <div class="header-content">
      <span class="title">{data.displayName}</span>
      <span class="path">{data.path}</span>
    </div>
  </div>
  <div class="content">
    <div class="description">{data.description}</div>
    <div class="stats">
      <div class="stat">
        <span class="stat-icon">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
          </svg>
        </span>
        {data.linkedFields.length} field{data.linkedFields.length !== 1 ? "s" : ""}
      </div>
      {#if data.distributionCount !== undefined && data.distributionCount > 0}
        <div class="stat values">
          <span class="stat-icon">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 20V10M18 20V4M6 20v-4" />
            </svg>
          </span>
          {data.distributionCount} value{data.distributionCount !== 1 ? "s" : ""}
        </div>
      {/if}
    </div>
  </div>
  <div class="click-hint">Click to configure</div>
</div>

<style>
  .node {
    min-width: 200px;
    border: 2px solid #e2e2e2;
    border-radius: 8px;
    background: #ffffff;
    padding: 0;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
    overflow: hidden;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .node:hover {
    border-color: #94a3b8;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  }

  .node.selected {
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
  }

  .node.has-values {
    border-color: #22c55e;
  }

  .node.has-values.selected {
    border-color: #3b82f6;
  }

  .header {
    display: flex;
    align-items: stretch;
  }

  .color-bar {
    width: 4px;
    flex-shrink: 0;
  }

  .header-content {
    padding: 10px 12px;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .title {
    font-weight: 600;
    font-size: 12px;
    color: #1c1c1c;
  }

  .path {
    font-size: 9px;
    color: #9ca3af;
    font-family: monospace;
  }

  .content {
    padding: 0 12px 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .description {
    font-size: 10px;
    color: #6b7280;
    line-height: 1.4;
  }

  .stats {
    display: flex;
    gap: 12px;
  }

  .stat {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 10px;
    color: #6b7280;
  }

  .stat.values {
    color: #16a34a;
  }

  .stat-icon {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .click-hint {
    padding: 6px 12px;
    background: #f9fafb;
    border-top: 1px solid #e5e7eb;
    font-size: 10px;
    color: #9ca3af;
    text-align: center;
    opacity: 0;
    transition: opacity 0.15s ease;
  }

  .node:hover .click-hint {
    opacity: 1;
  }
</style>
