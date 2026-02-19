<script lang="ts">
  export let data: {
    fieldName: string;
    fieldType: "categorical" | "numeric";
    options?: string[];
    color: string;
    isDerived: boolean;
  };
  export let selected = false;
</script>

<div class:selected class="node input-node">
  <div class="header">
    <span class="dot" style={`background:${data.color}`}></span>
    <span class="title">{data.fieldName}</span>
  </div>
  <div class="content">
    {#if data.fieldType === "categorical" && data.options}
      <div class="options">
        {#each data.options.slice(0, 3) as option}
          <span class="option">{option}</span>
        {/each}
        {#if data.options.length > 3}
          <span class="option-more">+{data.options.length - 3}</span>
        {/if}
      </div>
    {:else}
      <div class="type-label">numeric</div>
    {/if}
    {#if data.isDerived}
      <div class="derived-badge">derived</div>
    {/if}
  </div>
</div>

<style>
  .node {
    min-width: 180px;
    border: 2px solid #e5e7eb;
    border-radius: 8px;
    background: #ffffff;
    padding: 12px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
  }

  .node.selected {
    border-color: #2563eb;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
  }

  .header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }

  .title {
    font-weight: 600;
    font-size: 13px;
  }

  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
  }

  .content {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .options {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .option {
    font-size: 11px;
    color: #6b7280;
    background: #f3f4f6;
    padding: 2px 6px;
    border-radius: 4px;
  }

  .option-more {
    font-size: 11px;
    color: #9ca3af;
  }

  .type-label {
    font-size: 11px;
    color: #6b7280;
    font-style: italic;
  }

  .derived-badge {
    font-size: 10px;
    color: #059669;
    background: #d1fae5;
    padding: 2px 6px;
    border-radius: 4px;
    width: fit-content;
  }
</style>
