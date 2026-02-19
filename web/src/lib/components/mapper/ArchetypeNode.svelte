<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";

  export let data: {
    name: string;
    linkedFields: number;
    icon: "building" | "tower" | "warehouse";
  };
  export let selected = false;
</script>

<div class:selected class="node">
  <Handle type="target" position={Position.Top} />
  <div class="icon">
    {#if data.icon === "tower"}
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M10 3h4v3h2v15H8V6h2V3Zm1 5v2h2V8h-2Zm0 4v2h2v-2h-2Zm0 4v2h2v-2h-2Z"
        />
      </svg>
    {:else if data.icon === "warehouse"}
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M3 10 12 4l9 6v10h-6v-4H9v4H3V10Zm6 1v2h2v-2H9Zm4 0v2h2v-2h-2Z"
        />
      </svg>
    {:else}
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M4 21V5l8-3 8 3v16H4Zm3-8v3h3v-3H7Zm0-5v3h3V8H7Zm7 5v3h3v-3h-3Zm0-5v3h3V8h-3Z"
        />
      </svg>
    {/if}
  </div>
  <div class="title">{data.name}</div>
  <div class="meta">{data.linkedFields} linked fields</div>
</div>

<style>
  .node {
    min-width: 200px;
    padding: 12px;
    border-radius: 10px;
    border: 1px solid #e2e2e2;
    background: #ffffff;
    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.06);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    position: relative;
  }

  .node.selected {
    border-color: #3b82f6;
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
  }

  .icon {
    width: 48px;
    height: 48px;
    display: grid;
    place-items: center;
    color: #2563eb;
  }

  svg {
    width: 40px;
    height: 40px;
    fill: currentColor;
  }

  .title {
    font-weight: 600;
    font-size: 13px;
    color: #1c1c1c;
  }

  .meta {
    font-size: 11px;
    color: #6b7280;
  }
</style>
