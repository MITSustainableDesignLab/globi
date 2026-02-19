<script lang="ts">
  import {
    mapperStore,
    addComponentDistribution,
    removeComponentDistribution
  } from "$lib/stores/mapperStore";
  import {
    COMPONENT_PARAMETERS,
    getDescendantLeafComponents,
    type ParameterSchema
  } from "$lib/data/componentParameters";
  import {
    generateCombinations,
    type DistributionType,
    type Distribution
  } from "$lib/types/mapper";

  export let selectedComponentPath: string | null = null;

  $: component = selectedComponentPath
    ? $mapperStore.componentLevels.find((c) => c.path === selectedComponentPath)
    : null;

  $: linkedFieldIds = selectedComponentPath
    ? $mapperStore.componentLinks[selectedComponentPath] ?? []
    : [];

  $: linkedFields = $mapperStore.semanticFields.filter((f) =>
    linkedFieldIds.includes(f.id)
  );

  $: combinations = generateCombinations($mapperStore.semanticFields, linkedFieldIds);

  $: leafComponents = selectedComponentPath
    ? getDescendantLeafComponents(selectedComponentPath)
    : [];

  $: existingDistributions = selectedComponentPath
    ? $mapperStore.componentDistributions[selectedComponentPath] ?? []
    : [];

  // Form state
  let selectedCombinationId: string = "";
  let selectedParameterPath: string = "";
  let selectedParameterName: string = "";
  let valueType: "single" | "distribution" = "single";
  let singleValue: number = 0;
  let distributionType: DistributionType = "uniform";
  let distMin: number = 0;
  let distMax: number = 1;
  let distMean: number = 0;
  let distStd: number = 1;

  $: selectedCombination = combinations.find((c) => c.id === selectedCombinationId);

  $: availableParameters = leafComponents.flatMap((path) => {
    const schema = COMPONENT_PARAMETERS[path];
    if (!schema) return [];
    return schema.parameters.map((p) => ({
      path,
      componentName: path.split(".").pop() ?? path,
      ...p
    }));
  });

  function resetForm() {
    valueType = "single";
    singleValue = 0;
    distributionType = "uniform";
    distMin = 0;
    distMax = 1;
    distMean = 0;
    distStd = 1;
  }

  function addValue() {
    if (!selectedComponentPath || !selectedCombinationId || !selectedParameterPath || !selectedParameterName) {
      return;
    }

    const combo = combinations.find((c) => c.id === selectedCombinationId);
    if (!combo) return;

    let distribution: Distribution;
    if (valueType === "single") {
      distribution = { type: "fixed", value: singleValue };
    } else {
      switch (distributionType) {
        case "uniform":
          distribution = { type: "uniform", min: distMin, max: distMax };
          break;
        case "normal":
          distribution = { type: "normal", mean: distMean, std: distStd };
          break;
        case "triangular":
          distribution = { type: "triangular", min: distMin, max: distMax, mode: (distMin + distMax) / 2 };
          break;
        default:
          distribution = { type: "fixed", value: singleValue };
      }
    }

    addComponentDistribution(selectedParameterPath, {
      componentPath: selectedParameterPath,
      parameterName: selectedParameterName,
      conditions: combo.conditions,
      distribution
    });

    resetForm();
  }

  function formatConditions(conditions: Record<string, string>): string {
    if (Object.keys(conditions).length === 0) return "All buildings";
    return Object.entries(conditions)
      .map(([fieldId, value]) => {
        const field = $mapperStore.semanticFields.find((f) => f.id === fieldId);
        return `${field?.name ?? fieldId}=${value}`;
      })
      .join(", ");
  }

  function formatDistribution(dist: Distribution): string {
    switch (dist.type) {
      case "fixed":
        return `${dist.value}`;
      case "uniform":
        return `U(${dist.min}, ${dist.max})`;
      case "normal":
        return `N(${dist.mean}, ${dist.std})`;
      case "triangular":
        return `Tri(${dist.min}, ${dist.mode}, ${dist.max})`;
      default:
        return dist.type;
    }
  }

  const distributionTypes: DistributionType[] = ["uniform", "normal", "triangular", "lognormal"];
</script>

<div class="panel">
  {#if !selectedComponentPath}
    <div class="empty-state">
      <div class="empty-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M9 9h6M9 13h6M9 17h4" />
        </svg>
      </div>
      <h3>Select a Component</h3>
      <p>Click on a component in the canvas to configure its values based on semantic field combinations.</p>
    </div>
  {:else if !component}
    <div class="empty-state">
      <p>Component not found</p>
    </div>
  {:else}
    <div class="panel-header">
      <h3>{component.displayName}</h3>
      <span class="path-badge">{component.path}</span>
    </div>

    <!-- Linked Fields -->
    <div class="section">
      <h4>Linked Semantic Fields</h4>
      {#if linkedFields.length === 0}
        <p class="hint">Connect semantic fields to this component to define conditional values.</p>
      {:else}
        <div class="field-chips">
          {#each linkedFields as field}
            <span class="field-chip" style="background: {field.color}20; border-color: {field.color}">
              {field.name}
            </span>
          {/each}
        </div>
        <p class="combo-count">{combinations.length} possible combinations</p>
      {/if}
    </div>

    <!-- Existing Values -->
    {#if existingDistributions.length > 0}
      <div class="section">
        <h4>Configured Values</h4>
        <div class="values-list">
          {#each existingDistributions as dist}
            <div class="value-item">
              <div class="value-main">
                <span class="param-name">{dist.parameterName}</span>
                <span class="param-value">{formatDistribution(dist.distribution)}</span>
              </div>
              <div class="value-conditions">{formatConditions(dist.conditions)}</div>
              <button
                type="button"
                class="delete-btn"
                on:click={() => removeComponentDistribution(selectedComponentPath!, dist.id)}
              >
                ×
              </button>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Add New Value -->
    <div class="section">
      <h4>Add Value</h4>

      <div class="form-group">
        <label for="combination">For buildings where:</label>
        <select id="combination" bind:value={selectedCombinationId}>
          <option value="">Select combination...</option>
          {#each combinations as combo}
            <option value={combo.id}>{combo.label}</option>
          {/each}
        </select>
      </div>

      {#if availableParameters.length > 0}
        <div class="form-group">
          <label for="parameter">Parameter:</label>
          <select
            id="parameter"
            on:change={(e) => {
              const [path, name] = e.currentTarget.value.split("::");
              selectedParameterPath = path;
              selectedParameterName = name;
            }}
          >
            <option value="">Select parameter...</option>
            {#each availableParameters as param}
              <option value="{param.path}::{param.name}">
                {param.componentName}: {param.displayName}
                {param.unit ? `(${param.unit})` : ""}
              </option>
            {/each}
          </select>
        </div>
      {:else}
        <p class="hint">This component has no configurable parameters.</p>
      {/if}

      <div class="form-group">
        <label>Value Type:</label>
        <div class="radio-group">
          <label class="radio-label">
            <input type="radio" bind:group={valueType} value="single" />
            Fixed Value
          </label>
          <label class="radio-label">
            <input type="radio" bind:group={valueType} value="distribution" />
            Distribution
          </label>
        </div>
      </div>

      {#if valueType === "single"}
        <div class="form-group">
          <label for="single-value">Value:</label>
          <input
            id="single-value"
            type="number"
            step="any"
            bind:value={singleValue}
            placeholder="Enter value"
          />
        </div>
      {:else}
        <div class="form-group">
          <label for="dist-type">Distribution Type:</label>
          <select id="dist-type" bind:value={distributionType}>
            {#each distributionTypes as dt}
              <option value={dt}>{dt}</option>
            {/each}
          </select>
        </div>

        {#if distributionType === "uniform" || distributionType === "triangular"}
          <div class="form-row">
            <div class="form-group">
              <label for="dist-min">Min:</label>
              <input id="dist-min" type="number" step="any" bind:value={distMin} />
            </div>
            <div class="form-group">
              <label for="dist-max">Max:</label>
              <input id="dist-max" type="number" step="any" bind:value={distMax} />
            </div>
          </div>
        {:else if distributionType === "normal" || distributionType === "lognormal"}
          <div class="form-row">
            <div class="form-group">
              <label for="dist-mean">Mean:</label>
              <input id="dist-mean" type="number" step="any" bind:value={distMean} />
            </div>
            <div class="form-group">
              <label for="dist-std">Std Dev:</label>
              <input id="dist-std" type="number" step="any" bind:value={distStd} />
            </div>
          </div>
        {/if}
      {/if}

      <button
        type="button"
        class="add-btn"
        on:click={addValue}
        disabled={!selectedCombinationId || !selectedParameterName}
      >
        Add Value
      </button>
    </div>
  {/if}
</div>

<style>
  .panel {
    width: 380px;
    height: 100%;
    background: white;
    border-left: 1px solid #e2e2e2;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    padding: 40px;
    text-align: center;
    color: #6b7280;
  }

  .empty-icon {
    color: #d1d5db;
    margin-bottom: 16px;
  }

  .empty-state h3 {
    margin: 0 0 8px;
    font-size: 16px;
    color: #374151;
  }

  .empty-state p {
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
  }

  .panel-header {
    padding: 16px 20px;
    border-bottom: 1px solid #e2e2e2;
    background: #f9fafb;
  }

  .panel-header h3 {
    margin: 0 0 6px;
    font-size: 16px;
    font-weight: 600;
    color: #1c1c1c;
  }

  .path-badge {
    font-size: 11px;
    color: #6b7280;
    font-family: monospace;
    background: #e5e7eb;
    padding: 2px 8px;
    border-radius: 4px;
  }

  .section {
    padding: 16px 20px;
    border-bottom: 1px solid #e2e2e2;
  }

  .section h4 {
    margin: 0 0 12px;
    font-size: 13px;
    font-weight: 600;
    color: #374151;
  }

  .hint {
    margin: 0;
    font-size: 12px;
    color: #9ca3af;
    line-height: 1.5;
  }

  .field-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
  }

  .field-chip {
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 4px;
    border: 1px solid;
  }

  .combo-count {
    margin: 0;
    font-size: 12px;
    color: #6b7280;
  }

  .values-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .value-item {
    position: relative;
    padding: 10px 12px;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
  }

  .value-main {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
  }

  .param-name {
    font-size: 12px;
    font-weight: 600;
    color: #1c1c1c;
  }

  .param-value {
    font-size: 12px;
    font-family: monospace;
    color: #3b82f6;
    background: #dbeafe;
    padding: 2px 6px;
    border-radius: 4px;
  }

  .value-conditions {
    font-size: 11px;
    color: #6b7280;
  }

  .delete-btn {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 20px;
    height: 20px;
    border: none;
    background: transparent;
    color: #9ca3af;
    cursor: pointer;
    font-size: 16px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
  }

  .delete-btn:hover {
    background: #fee2e2;
    color: #dc2626;
  }

  .form-group {
    margin-bottom: 14px;
  }

  .form-group label {
    display: block;
    font-size: 12px;
    font-weight: 500;
    color: #4b5563;
    margin-bottom: 6px;
  }

  .form-group input,
  .form-group select {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-size: 13px;
    color: #1c1c1c;
  }

  .form-group input:focus,
  .form-group select:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
  }

  .form-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }

  .radio-group {
    display: flex;
    gap: 16px;
  }

  .radio-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: #4b5563;
    cursor: pointer;
  }

  .radio-label input {
    width: auto;
    margin: 0;
  }

  .add-btn {
    width: 100%;
    padding: 10px;
    background: #3b82f6;
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s ease;
  }

  .add-btn:hover:not(:disabled) {
    background: #2563eb;
  }

  .add-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
