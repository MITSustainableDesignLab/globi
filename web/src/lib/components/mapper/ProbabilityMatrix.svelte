<script lang="ts">
  import type { SemanticFieldCondition } from "$lib/types/mapper";

  export let conditions: SemanticFieldCondition[];
  export let probabilities: Record<string, number>[];
  export let fieldOptions: string[];
  export let sourceFields: Array<{ id: string; name: string }> = [];
  export let onUpdate: (index: number, option: string, probability: number) => void;
  export let onNormalize: (index: number) => void;

  const getTotal = (index: number) => {
    if (!probabilities || !probabilities[index]) return 0;
    return Object.values(probabilities[index]).reduce((sum, p) => sum + (p || 0), 0);
  };

  const formatCondition = (condition: SemanticFieldCondition) => {
    return Object.entries(condition)
      .map(([fieldId, value]) => {
        const field = sourceFields.find((f) => f.id === fieldId);
        return `${field?.name ?? fieldId} = ${value}`;
      })
      .join(", ");
  };
</script>

<div class="matrix">
  <div class="header-row">
    <div class="condition-col">Condition</div>
    {#each fieldOptions as option}
      <div class="prob-col">{option}</div>
    {/each}
    <div class="total-col">Total</div>
    <div class="action-col">Action</div>
  </div>

  {#each conditions as condition, index}
    {@const total = getTotal(index)}
    {@const isValid = Math.abs(total - 1.0) < 0.001}
    <div class="data-row" class:invalid={!isValid}>
      <div class="condition-col">
        <div class="condition-text">
          {#if Object.keys(condition).length === 0}
            <em>Default</em>
          {:else}
            {formatCondition(condition)}
          {/if}
        </div>
      </div>
      {#each fieldOptions as option}
        <div class="prob-col">
          <input
            type="number"
            min="0"
            max="1"
            step="0.01"
            value={probabilities?.[index]?.[option] ?? 0}
            on:input={(e) => {
              const value = parseFloat(e.currentTarget.value) || 0;
              onUpdate(index, option, value);
            }}
            class:error={(probabilities?.[index]?.[option] ?? 0) < 0 || (probabilities?.[index]?.[option] ?? 0) > 1}
          />
        </div>
      {/each}
      <div class="total-col" class:error={!isValid}>
        {total.toFixed(3)}
      </div>
      <div class="action-col">
        <button type="button" class="normalize-btn" on:click={() => onNormalize(index)}>
          normalize
        </button>
      </div>
    </div>
  {/each}
</div>

<style>
  .matrix {
    display: flex;
    flex-direction: column;
    border: 1px solid #e2e2e2;
    border-radius: 8px;
    overflow: hidden;
  }

  .header-row,
  .data-row {
    display: grid;
    grid-template-columns: 2fr repeat(var(--option-count, 1), 1fr) 80px 100px;
    gap: 1px;
    background: #e2e2e2;
  }

  .data-row {
    background: #ffffff;
  }

  .data-row.invalid {
    background: #fef2f2;
  }

  .condition-col,
  .prob-col,
  .total-col,
  .action-col {
    padding: 10px 12px;
    background: #ffffff;
    display: flex;
    align-items: center;
  }

  .header-row .condition-col,
  .header-row .prob-col,
  .header-row .total-col,
  .header-row .action-col {
    background: #f9fafb;
    font-weight: 600;
    font-size: 12px;
    color: #1c1c1c;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .condition-text {
    font-size: 12px;
    color: #4b5563;
  }

  .condition-text em {
    color: #9ca3af;
    font-style: italic;
  }

  input {
    width: 100%;
    padding: 6px 8px;
    background: white;
    border: 1px solid #d8d8d8;
    border-radius: 4px;
    color: #1c1c1c;
    font-size: 12px;
  }

  input:focus {
    outline: none;
    border-color: #3b82f6;
  }

  input.error {
    border-color: #ef4444;
  }

  .total-col {
    font-weight: 500;
    font-size: 12px;
    color: #4b5563;
    justify-content: center;
  }

  .total-col.error {
    color: #dc2626;
  }

  .normalize-btn {
    padding: 4px 8px;
    background: #3b82f6;
    border: none;
    border-radius: 4px;
    color: #ffffff;
    font-size: 11px;
    cursor: pointer;
  }

  .normalize-btn:hover {
    background: #2563eb;
  }
</style>
