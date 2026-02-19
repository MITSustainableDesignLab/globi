<script lang="ts">
  import { browser } from "$app/environment";
  import { mapperStore } from "$lib/stores/mapperStore";
  import {
    addComponentDistribution,
    removeComponentDistribution,
    setSelectedComponentPath,
    updateComponentDistribution,
    openComponentWizard
  } from "$lib/stores/mapperStore";
  import type {
    ComponentDistribution,
    Distribution,
    DistributionType,
    SemanticFieldCondition
  } from "$lib/types/mapper";
  import { generateCombinations } from "$lib/types/mapper";
  import { COMPONENT_PARAMETERS, getDescendantLeafComponents } from "$lib/data/componentParameters";

  $: selectedPath = $mapperStore.ui.selectedComponentPath;
  $: component = $mapperStore.componentLevels.find((c) => c.path === selectedPath);
  $: distributions = selectedPath
    ? $mapperStore.componentDistributions[selectedPath] ?? []
    : [];
  $: linkedFields = selectedPath
    ? $mapperStore.componentLinks[selectedPath] ?? []
    : [];
  $: availableFields = $mapperStore.semanticFields.filter((f) =>
    linkedFields.includes(f.id)
  );

  // Generate combinations based on linked fields
  $: combinations = generateCombinations($mapperStore.semanticFields, linkedFields);

  // Check if this component has configurable parameters
  $: leafComponents = selectedPath ? getDescendantLeafComponents(selectedPath) : [];
  $: hasParameters = leafComponents.length > 0;

  // Get missing combinations (combinations without distributions)
  $: coveredCombinations = new Set(
    distributions.flatMap((d) => {
      const condKeys = Object.keys(d.conditions);
      if (condKeys.length === 0) return combinations.map((c) => c.id);
      return combinations
        .filter((c) => condKeys.every((k) => c.conditions[k] === d.conditions[k]))
        .map((c) => c.id);
    })
  );
  $: missingCombinations = combinations.filter((c) => !coveredCombinations.has(c.id));

  let editingId: string | null = null;
  let newDistribution: Partial<ComponentDistribution> = {
    parameterName: "",
    conditions: {},
    distribution: { type: "fixed", value: 0 }
  };

  const getDistributionParams = (type: DistributionType) => {
    switch (type) {
      case "fixed":
        return ["value"];
      case "uniform":
        return ["min", "max"];
      case "normal":
        return ["mean", "std"];
      case "triangular":
        return ["min", "mode", "max"];
      case "lognormal":
        return ["mean", "std"];
      case "categorical":
        return ["options", "weights"];
      default:
        return [];
    }
  };

  const startEditing = (dist: ComponentDistribution) => {
    editingId = dist.id;
    newDistribution = { ...dist };
  };

  const cancelEditing = () => {
    editingId = null;
    newDistribution = {
      parameterName: "",
      conditions: {},
      distribution: { type: "fixed", value: 0 }
    };
  };

  const saveDistribution = () => {
    if (!selectedPath || !newDistribution.parameterName) return;

    const dist: Omit<ComponentDistribution, "id"> = {
      componentPath: selectedPath,
      parameterName: newDistribution.parameterName!,
      conditions: newDistribution.conditions ?? {},
      distribution: newDistribution.distribution!
    };

    if (editingId) {
      updateComponentDistribution(selectedPath, editingId, dist);
    } else {
      addComponentDistribution(selectedPath, dist);
    }
    cancelEditing();
  };

  const handleConditionChange = (fieldId: string, value: string) => {
    if (!newDistribution.conditions) {
      newDistribution.conditions = {};
    }
    if (value === "") {
      const { [fieldId]: _, ...rest } = newDistribution.conditions;
      newDistribution.conditions = rest;
    } else {
      newDistribution.conditions = {
        ...newDistribution.conditions,
        [fieldId]: value
      };
    }
  };

  const getFieldOptions = (fieldId: string) => {
    const field = $mapperStore.semanticFields.find((f) => f.id === fieldId);
    return field?.options ?? [];
  };

  const formatConditions = (conditions: SemanticFieldCondition) => {
    return Object.entries(conditions)
      .map(([fieldId, value]) => {
        const field = $mapperStore.semanticFields.find((f) => f.id === fieldId);
        return `${field?.name ?? fieldId} = ${value}`;
      })
      .join(", ");
  };
</script>

{#if browser && selectedPath && component}
  <div class="panel">
    <div class="header">
      <div>
        <div class="title">Component Distributions</div>
        <div class="subtitle">{component.displayName}</div>
      </div>
      <button type="button" class="close" on:click={() => setSelectedComponentPath(null)}>
        ×
      </button>
    </div>

    <div class="content">
      <!-- Combination Summary -->
      {#if linkedFields.length > 0}
        <div class="combination-summary">
          <div class="summary-header">
            <span class="summary-title">Field Combinations</span>
            <span class="summary-count">{combinations.length} total</span>
          </div>
          <div class="summary-fields">
            {#each availableFields as field}
              <span class="field-chip" style="background: {field.color}20; border-color: {field.color}">
                {field.name}
              </span>
            {/each}
          </div>
          {#if missingCombinations.length > 0}
            <div class="missing-warning">
              {missingCombinations.length} combination{missingCombinations.length !== 1 ? "s" : ""} without distributions
            </div>
          {:else if distributions.length > 0}
            <div class="complete-badge">All combinations covered</div>
          {/if}
        </div>
      {:else}
        <div class="no-fields-hint">
          Connect semantic fields to this component to define conditional distributions.
        </div>
      {/if}

      <!-- Wizard Button -->
      {#if hasParameters}
        <button
          type="button"
          class="wizard-btn"
          on:click={() => openComponentWizard(selectedPath)}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 15a3 3 0 100-6 3 3 0 000 6z"/>
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>
          </svg>
          Open Configuration Wizard
        </button>
      {/if}
      {#if distributions.length > 0}
        <div class="distributions-list">
          {#each distributions as dist (dist.id)}
            <div class="distribution-item">
              <div class="dist-header">
                <div>
                  <div class="param-name">{dist.parameterName}</div>
                  {#if Object.keys(dist.conditions).length > 0}
                    <div class="conditions">{formatConditions(dist.conditions)}</div>
                  {/if}
                </div>
                <div class="actions">
                  <button type="button" class="edit-btn" on:click={() => startEditing(dist)}>
                    edit
                  </button>
                  <button
                    type="button"
                    class="delete-btn"
                    on:click={() => removeComponentDistribution(selectedPath, dist.id)}
                  >
                    delete
                  </button>
                </div>
              </div>
              <div class="dist-type">
                {dist.distribution.type} distribution
                {#if dist.distribution.type === "normal"}
                  (μ={dist.distribution.mean}, σ={dist.distribution.std})
                {:else if dist.distribution.type === "uniform"}
                  (min={dist.distribution.min}, max={dist.distribution.max})
                {:else if dist.distribution.type === "fixed"}
                  (value={dist.distribution.value})
                {/if}
              </div>
            </div>
          {/each}
        </div>
      {/if}

      <div class="form-section">
        <div class="section-title">
          {editingId ? "Edit Distribution" : "Add Distribution"}
        </div>

        <div class="form-group">
          <label>Parameter Name</label>
          <input
            type="text"
            placeholder="e.g., lighting_power_density"
            bind:value={newDistribution.parameterName}
          />
        </div>

        {#if availableFields.length > 0}
          <div class="form-group">
            <label>Conditions (optional)</label>
            <div class="conditions-builder">
              {#each availableFields as field}
                <div class="condition-row">
                  <span class="field-label">{field.name}:</span>
                  <select
                    value={newDistribution.conditions?.[field.id] ?? ""}
                    on:change={(e) => handleConditionChange(field.id, e.currentTarget.value)}
                  >
                    <option value="">Any</option>
                    {#each (field.options ?? []) as option}
                      <option value={option}>{option}</option>
                    {/each}
                  </select>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        <div class="form-group">
          <label>Distribution Type</label>
          <select
            value={newDistribution.distribution?.type ?? "fixed"}
            on:change={(e) => {
              const type = e.currentTarget.value as DistributionType;
              newDistribution.distribution = { type } as Distribution;
            }}
          >
            <option value="fixed">Fixed</option>
            <option value="uniform">Uniform</option>
            <option value="normal">Normal</option>
            <option value="triangular">Triangular</option>
            <option value="lognormal">Lognormal</option>
            <option value="categorical">Categorical</option>
          </select>
        </div>

        {#if newDistribution.distribution}
          {@const params = getDistributionParams(newDistribution.distribution.type)}
          {#if params.includes("value")}
            <div class="form-group">
              <label>Value</label>
              <input
                type="number"
                step="any"
                bind:value={newDistribution.distribution.value}
              />
            </div>
          {/if}
          {#if params.includes("min")}
            <div class="form-group">
              <label>Min</label>
              <input
                type="number"
                step="any"
                bind:value={newDistribution.distribution.min}
              />
            </div>
          {/if}
          {#if params.includes("max")}
            <div class="form-group">
              <label>Max</label>
              <input
                type="number"
                step="any"
                bind:value={newDistribution.distribution.max}
              />
            </div>
          {/if}
          {#if params.includes("mean")}
            <div class="form-group">
              <label>Mean</label>
              <input
                type="number"
                step="any"
                bind:value={newDistribution.distribution.mean}
              />
            </div>
          {/if}
          {#if params.includes("std")}
            <div class="form-group">
              <label>Standard Deviation</label>
              <input
                type="number"
                step="any"
                bind:value={newDistribution.distribution.std}
              />
            </div>
          {/if}
          {#if params.includes("mode")}
            <div class="form-group">
              <label>Mode</label>
              <input
                type="number"
                step="any"
                bind:value={newDistribution.distribution.mode}
              />
            </div>
          {/if}
          {#if params.includes("options")}
            <div class="form-group">
              <label>Options (comma-separated)</label>
              <input
                type="text"
                placeholder="option1, option2, option3"
                value={newDistribution.distribution.options?.join(", ") ?? ""}
                on:input={(e) => {
                  const options = e.currentTarget.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter((s) => s.length > 0);
                  newDistribution.distribution!.options = options;
                }}
              />
            </div>
          {/if}
          {#if params.includes("weights")}
            <div class="form-group">
              <label>Weights (comma-separated)</label>
              <input
                type="text"
                placeholder="0.3, 0.5, 0.2"
                value={newDistribution.distribution.weights?.join(", ") ?? ""}
                on:input={(e) => {
                  const weights = e.currentTarget.value
                    .split(",")
                    .map((s) => parseFloat(s.trim()))
                    .filter((n) => !isNaN(n));
                  newDistribution.distribution!.weights = weights;
                }}
              />
            </div>
          {/if}
        {/if}

        <div class="form-actions">
          <button type="button" class="cancel-btn" on:click={cancelEditing}>
            Cancel
          </button>
          <button
            type="button"
            class="save-btn"
            on:click={saveDistribution}
            disabled={!newDistribution.parameterName}
          >
            {editingId ? "Update" : "Add"} Distribution
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}

<style>
  .panel {
    position: fixed;
    top: 80px;
    right: 24px;
    width: 420px;
    max-height: calc(100vh - 120px);
    background: #ffffff;
    border: 1px solid #e2e2e2;
    border-radius: 12px;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.15);
    display: flex;
    flex-direction: column;
    z-index: 100;
    overflow: hidden;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    border-bottom: 1px solid #e2e2e2;
  }

  .title {
    font-weight: 600;
    font-size: 16px;
    color: #1c1c1c;
  }

  .subtitle {
    font-size: 12px;
    color: #6b7280;
    margin-top: 4px;
  }

  .close {
    width: 32px;
    height: 32px;
    border: none;
    background: transparent;
    color: #6b7280;
    font-size: 24px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 6px;
  }

  .close:hover {
    background: #f3f3f3;
    color: #1c1c1c;
  }

  .content {
    padding: 20px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .distributions-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .distribution-item {
    padding: 12px;
    background: #f9fafb;
    border: 1px solid #e2e2e2;
    border-radius: 8px;
  }

  .dist-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
  }

  .param-name {
    font-weight: 600;
    font-size: 13px;
    color: #1c1c1c;
  }

  .conditions {
    font-size: 11px;
    color: #6b7280;
    margin-top: 4px;
  }

  .actions {
    display: flex;
    gap: 6px;
  }

  .edit-btn,
  .delete-btn {
    padding: 4px 8px;
    border: 1px solid #d8d8d8;
    background: white;
    color: #4b5563;
    border-radius: 4px;
    font-size: 11px;
    cursor: pointer;
  }

  .edit-btn:hover {
    background: #f3f3f3;
    border-color: #cbd5e1;
  }

  .delete-btn:hover {
    background: #fef2f2;
    border-color: #fca5a5;
    color: #dc2626;
  }

  .dist-type {
    font-size: 11px;
    color: #6b7280;
    margin-top: 8px;
  }

  .form-section {
    padding-top: 20px;
    border-top: 1px solid #e2e2e2;
  }

  .section-title {
    font-weight: 600;
    font-size: 14px;
    color: #1c1c1c;
    margin-bottom: 16px;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: 16px;
  }

  label {
    font-size: 12px;
    font-weight: 500;
    color: #4b5563;
  }

  input,
  select {
    padding: 8px 12px;
    background: white;
    border: 1px solid #d8d8d8;
    border-radius: 6px;
    color: #1c1c1c;
    font-size: 13px;
  }

  input:focus,
  select:focus {
    outline: none;
    border-color: #3b82f6;
  }

  input::placeholder {
    color: #64748b;
  }

  .conditions-builder {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .condition-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .field-label {
    font-size: 12px;
    color: #4b5563;
    min-width: 100px;
  }

  .form-actions {
    display: flex;
    gap: 8px;
    margin-top: 20px;
  }

  .cancel-btn,
  .save-btn {
    flex: 1;
    padding: 10px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    border: none;
  }

  .cancel-btn {
    background: #f3f4f6;
    color: #4b5563;
    border: 1px solid #d8d8d8;
  }

  .cancel-btn:hover {
    background: #e5e7eb;
  }

  .save-btn {
    background: #3b82f6;
    color: #ffffff;
  }

  .save-btn:hover:not(:disabled) {
    background: #2563eb;
  }

  .save-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .combination-summary {
    padding: 14px;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    margin-bottom: 16px;
  }

  .summary-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
  }

  .summary-title {
    font-weight: 600;
    font-size: 13px;
    color: #1c1c1c;
  }

  .summary-count {
    font-size: 12px;
    color: #6b7280;
    background: #e5e7eb;
    padding: 2px 8px;
    border-radius: 10px;
  }

  .summary-fields {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 10px;
  }

  .field-chip {
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid;
  }

  .missing-warning {
    font-size: 12px;
    color: #dc2626;
    background: #fef2f2;
    padding: 6px 10px;
    border-radius: 4px;
    border: 1px solid #fecaca;
  }

  .complete-badge {
    font-size: 12px;
    color: #16a34a;
    background: #f0fdf4;
    padding: 6px 10px;
    border-radius: 4px;
    border: 1px solid #bbf7d0;
  }

  .no-fields-hint {
    padding: 14px;
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 8px;
    font-size: 12px;
    color: #92400e;
    margin-bottom: 16px;
  }

  .wizard-btn {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 12px;
    background: #3b82f6;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    margin-bottom: 16px;
    transition: background 0.15s ease;
  }

  .wizard-btn:hover {
    background: #2563eb;
  }

  .wizard-btn svg {
    flex-shrink: 0;
  }
</style>
