<script lang="ts">
  import { mapperStore, setComponentLinks, addBatchComponentDistributions, closePanel } from "$lib/stores/mapperStore";
  import { COMPONENT_PARAMETERS, getDescendantLeafComponents, type ParameterSchema } from "$lib/data/componentParameters";
  import { generateCombinations, type FieldCombination, type Distribution, type DistributionType, type SemanticFieldCondition } from "$lib/types/mapper";
  import { PRISMA_COMPONENTS } from "$lib/data/prismaComponents";

  $: selectedPath = $mapperStore.ui.selectedComponentPath;
  $: isOpen = $mapperStore.ui.openPanel === "component-values" && selectedPath;

  $: component = $mapperStore.componentLevels.find((c) => c.path === selectedPath);
  $: linkedFieldIds = selectedPath ? ($mapperStore.componentLinks[selectedPath] ?? []) : [];
  $: allFields = $mapperStore.semanticFields;

  // Wizard state
  type WizardStep = "select-fields" | "select-parameters" | "enter-values" | "review";
  let currentStep: WizardStep = "select-fields";
  let selectedFieldIds: string[] = [];
  let selectedParameters: string[] = [];
  let currentParameterIndex = 0;
  let currentCombinationIndex = 0;

  // Value entry state
  type ValueEntry = {
    combinationId: string;
    parameterName: string;
    valueType: "single" | "distribution";
    singleValue: number | string | boolean;
    distribution: Distribution;
  };
  let valueEntries: ValueEntry[] = [];

  // Get leaf components that have parameters
  $: leafComponentPaths = selectedPath ? getDescendantLeafComponents(selectedPath) : [];
  $: hasLeafComponents = leafComponentPaths.length > 0;

  // Get parameters for current component or its descendants
  $: availableParameters = selectedPath ? getAvailableParameters(selectedPath) : [];

  function getAvailableParameters(path: string): { path: string; params: ParameterSchema[] }[] {
    const result: { path: string; params: ParameterSchema[] }[] = [];
    const leafPaths = getDescendantLeafComponents(path);

    for (const leafPath of leafPaths) {
      const schema = COMPONENT_PARAMETERS[leafPath];
      if (schema) {
        result.push({ path: leafPath, params: schema.parameters });
      }
    }

    return result;
  }

  // Generate combinations based on selected fields
  $: combinations = generateCombinations(allFields, selectedFieldIds);

  // Initialize when opening
  $: if (isOpen && selectedPath) {
    currentStep = "select-fields";
    selectedFieldIds = [...linkedFieldIds];
    selectedParameters = [];
    valueEntries = [];
    currentParameterIndex = 0;
    currentCombinationIndex = 0;
  }

  function toggleField(fieldId: string) {
    if (selectedFieldIds.includes(fieldId)) {
      selectedFieldIds = selectedFieldIds.filter((id) => id !== fieldId);
    } else {
      selectedFieldIds = [...selectedFieldIds, fieldId];
    }
  }

  function toggleParameter(paramKey: string) {
    if (selectedParameters.includes(paramKey)) {
      selectedParameters = selectedParameters.filter((p) => p !== paramKey);
    } else {
      selectedParameters = [...selectedParameters, paramKey];
    }
  }

  function initializeValueEntries() {
    valueEntries = [];
    for (const combo of combinations) {
      for (const paramKey of selectedParameters) {
        const [componentPath, paramName] = paramKey.split("::");
        valueEntries.push({
          combinationId: combo.id,
          parameterName: paramKey,
          valueType: "single",
          singleValue: 0,
          distribution: { type: "fixed", value: 0 }
        });
      }
    }
  }

  function goToStep(step: WizardStep) {
    if (step === "enter-values") {
      initializeValueEntries();
    }
    currentStep = step;
  }

  function getEntry(combinationId: string, paramKey: string): ValueEntry | undefined {
    return valueEntries.find(
      (e) => e.combinationId === combinationId && e.parameterName === paramKey
    );
  }

  function updateEntry(
    combinationId: string,
    paramKey: string,
    updates: Partial<ValueEntry>
  ) {
    valueEntries = valueEntries.map((e) =>
      e.combinationId === combinationId && e.parameterName === paramKey
        ? { ...e, ...updates }
        : e
    );
  }

  function applyToAll(paramKey: string, entry: ValueEntry) {
    valueEntries = valueEntries.map((e) =>
      e.parameterName === paramKey
        ? { ...e, valueType: entry.valueType, singleValue: entry.singleValue, distribution: { ...entry.distribution } }
        : e
    );
  }

  function saveAndClose() {
    if (!selectedPath) return;

    // Update component links
    setComponentLinks(selectedPath, selectedFieldIds);

    // Create distributions for each entry
    const distributions = valueEntries.map((entry) => {
      const [componentPath, paramName] = entry.parameterName.split("::");
      const combo = combinations.find((c) => c.id === entry.combinationId);

      return {
        componentPath,
        parameterName: paramName,
        conditions: combo?.conditions ?? {},
        distribution: entry.valueType === "single"
          ? { type: "fixed" as const, value: entry.singleValue as number }
          : entry.distribution
      };
    });

    // Group by component path and add
    const byPath = new Map<string, typeof distributions>();
    for (const dist of distributions) {
      const existing = byPath.get(dist.componentPath) ?? [];
      existing.push(dist);
      byPath.set(dist.componentPath, existing);
    }

    for (const [path, dists] of byPath) {
      addBatchComponentDistributions(path, dists);
    }

    closePanel();
  }

  function getParamDisplayName(paramKey: string): string {
    const [componentPath, paramName] = paramKey.split("::");
    const schema = COMPONENT_PARAMETERS[componentPath];
    const param = schema?.parameters.find((p) => p.name === paramName);
    const componentName = componentPath.split(".").pop() ?? componentPath;
    return `${componentName}: ${param?.displayName ?? paramName}`;
  }

  const distributionTypes: DistributionType[] = ["fixed", "uniform", "normal", "triangular", "lognormal", "categorical"];
</script>

{#if isOpen && component}
  <div class="wizard-overlay" on:click={closePanel} on:keydown={(e) => e.key === "Escape" && closePanel()}>
    <div class="wizard-modal" on:click|stopPropagation>
      <div class="wizard-header">
        <div>
          <h2>Configure {component.displayName}</h2>
          <p class="subtitle">{component.path}</p>
        </div>
        <button type="button" class="close-btn" on:click={closePanel}>×</button>
      </div>

      <div class="wizard-progress">
        <div class="step" class:active={currentStep === "select-fields"} class:done={currentStep !== "select-fields"}>
          <span class="step-number">1</span>
          <span class="step-label">Select Fields</span>
        </div>
        <div class="step-line"></div>
        <div class="step" class:active={currentStep === "select-parameters"} class:done={["enter-values", "review"].includes(currentStep)}>
          <span class="step-number">2</span>
          <span class="step-label">Select Parameters</span>
        </div>
        <div class="step-line"></div>
        <div class="step" class:active={currentStep === "enter-values"} class:done={currentStep === "review"}>
          <span class="step-number">3</span>
          <span class="step-label">Enter Values</span>
        </div>
        <div class="step-line"></div>
        <div class="step" class:active={currentStep === "review"}>
          <span class="step-number">4</span>
          <span class="step-label">Review</span>
        </div>
      </div>

      <div class="wizard-content">
        {#if currentStep === "select-fields"}
          <div class="step-content">
            <h3>Which semantic fields determine {component.displayName}?</h3>
            <p class="help-text">
              Select the fields that this component depends on. Values will be configured for each combination of these fields.
            </p>

            <div class="field-grid">
              {#each allFields as field}
                <button
                  type="button"
                  class="field-card"
                  class:selected={selectedFieldIds.includes(field.id)}
                  on:click={() => toggleField(field.id)}
                >
                  <span class="field-dot" style="background: {field.color}"></span>
                  <span class="field-name">{field.name}</span>
                  <span class="field-options">
                    {field.type === "categorical" ? `${field.options?.length ?? 0} options` : "numeric"}
                  </span>
                  {#if field.isDerived}
                    <span class="derived-badge">derived</span>
                  {/if}
                </button>
              {/each}
            </div>

            {#if selectedFieldIds.length > 0}
              <div class="combination-preview">
                <strong>{combinations.length}</strong> combinations will be generated
              </div>
            {/if}
          </div>
        {:else if currentStep === "select-parameters"}
          <div class="step-content">
            <h3>Which parameters do you want to configure?</h3>
            <p class="help-text">
              Select the parameters you want to set values for. You can configure values for each field combination.
            </p>

            {#if !hasLeafComponents}
              <div class="no-params">
                This component has no configurable parameters. Select child components instead.
              </div>
            {:else}
              <div class="parameter-groups">
                {#each availableParameters as { path, params }}
                  {@const componentName = path.split(".").pop()}
                  <div class="param-group">
                    <div class="param-group-header">{componentName}</div>
                    <div class="param-list">
                      {#each params as param}
                        {@const paramKey = `${path}::${param.name}`}
                        <button
                          type="button"
                          class="param-card"
                          class:selected={selectedParameters.includes(paramKey)}
                          on:click={() => toggleParameter(paramKey)}
                        >
                          <span class="param-name">{param.displayName}</span>
                          <span class="param-type">{param.type}</span>
                          {#if param.unit}
                            <span class="param-unit">{param.unit}</span>
                          {/if}
                        </button>
                      {/each}
                    </div>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {:else if currentStep === "enter-values"}
          <div class="step-content values-step">
            <h3>Enter values for each combination</h3>

            <div class="value-matrix">
              <div class="matrix-header">
                <div class="combo-cell header">Combination</div>
                {#each selectedParameters as paramKey}
                  <div class="param-cell header">{getParamDisplayName(paramKey)}</div>
                {/each}
              </div>

              {#each combinations as combo}
                <div class="matrix-row">
                  <div class="combo-cell">
                    <span class="combo-label">{combo.label}</span>
                  </div>
                  {#each selectedParameters as paramKey}
                    {@const entry = getEntry(combo.id, paramKey)}
                    <div class="param-cell">
                      {#if entry}
                        <div class="value-input-group">
                          <select
                            class="value-type-select"
                            value={entry.valueType}
                            on:change={(e) => updateEntry(combo.id, paramKey, { valueType: e.currentTarget.value as "single" | "distribution" })}
                          >
                            <option value="single">Fixed</option>
                            <option value="distribution">Distribution</option>
                          </select>

                          {#if entry.valueType === "single"}
                            <input
                              type="number"
                              step="any"
                              class="value-input"
                              value={entry.singleValue}
                              on:input={(e) => updateEntry(combo.id, paramKey, { singleValue: parseFloat(e.currentTarget.value) || 0 })}
                            />
                          {:else}
                            <select
                              class="dist-type-select"
                              value={entry.distribution.type}
                              on:change={(e) => updateEntry(combo.id, paramKey, {
                                distribution: { ...entry.distribution, type: e.currentTarget.value as DistributionType }
                              })}
                            >
                              {#each distributionTypes as dt}
                                <option value={dt}>{dt}</option>
                              {/each}
                            </select>
                            {#if entry.distribution.type === "uniform"}
                              <input type="number" step="any" placeholder="min" class="dist-param"
                                value={entry.distribution.min ?? ""}
                                on:input={(e) => updateEntry(combo.id, paramKey, {
                                  distribution: { ...entry.distribution, min: parseFloat(e.currentTarget.value) }
                                })} />
                              <input type="number" step="any" placeholder="max" class="dist-param"
                                value={entry.distribution.max ?? ""}
                                on:input={(e) => updateEntry(combo.id, paramKey, {
                                  distribution: { ...entry.distribution, max: parseFloat(e.currentTarget.value) }
                                })} />
                            {:else if entry.distribution.type === "normal" || entry.distribution.type === "lognormal"}
                              <input type="number" step="any" placeholder="mean" class="dist-param"
                                value={entry.distribution.mean ?? ""}
                                on:input={(e) => updateEntry(combo.id, paramKey, {
                                  distribution: { ...entry.distribution, mean: parseFloat(e.currentTarget.value) }
                                })} />
                              <input type="number" step="any" placeholder="std" class="dist-param"
                                value={entry.distribution.std ?? ""}
                                on:input={(e) => updateEntry(combo.id, paramKey, {
                                  distribution: { ...entry.distribution, std: parseFloat(e.currentTarget.value) }
                                })} />
                            {:else if entry.distribution.type === "fixed"}
                              <input type="number" step="any" placeholder="value" class="dist-param"
                                value={entry.distribution.value ?? ""}
                                on:input={(e) => updateEntry(combo.id, paramKey, {
                                  distribution: { ...entry.distribution, value: parseFloat(e.currentTarget.value) }
                                })} />
                            {/if}
                          {/if}

                          <button
                            type="button"
                            class="apply-all-btn"
                            title="Apply to all combinations"
                            on:click={() => applyToAll(paramKey, entry)}
                          >
                            ⇅
                          </button>
                        </div>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/each}
            </div>
          </div>
        {:else if currentStep === "review"}
          <div class="step-content">
            <h3>Review your configuration</h3>

            <div class="review-summary">
              <div class="summary-item">
                <strong>Component:</strong> {component.displayName}
              </div>
              <div class="summary-item">
                <strong>Linked Fields:</strong> {selectedFieldIds.length > 0
                  ? allFields.filter((f) => selectedFieldIds.includes(f.id)).map((f) => f.name).join(", ")
                  : "None"}
              </div>
              <div class="summary-item">
                <strong>Combinations:</strong> {combinations.length}
              </div>
              <div class="summary-item">
                <strong>Parameters configured:</strong> {selectedParameters.length}
              </div>
              <div class="summary-item">
                <strong>Total value entries:</strong> {valueEntries.length}
              </div>
            </div>

            <div class="review-entries">
              <h4>Value Entries Preview</h4>
              <div class="entries-table">
                {#each valueEntries.slice(0, 10) as entry}
                  {@const combo = combinations.find((c) => c.id === entry.combinationId)}
                  <div class="entry-row">
                    <span class="entry-combo">{combo?.label}</span>
                    <span class="entry-param">{getParamDisplayName(entry.parameterName)}</span>
                    <span class="entry-value">
                      {entry.valueType === "single"
                        ? entry.singleValue
                        : `${entry.distribution.type}(...)`}
                    </span>
                  </div>
                {/each}
                {#if valueEntries.length > 10}
                  <div class="more-entries">
                    ... and {valueEntries.length - 10} more entries
                  </div>
                {/if}
              </div>
            </div>
          </div>
        {/if}
      </div>

      <div class="wizard-footer">
        {#if currentStep !== "select-fields"}
          <button
            type="button"
            class="btn secondary"
            on:click={() => {
              const steps: WizardStep[] = ["select-fields", "select-parameters", "enter-values", "review"];
              const idx = steps.indexOf(currentStep);
              if (idx > 0) goToStep(steps[idx - 1]);
            }}
          >
            Back
          </button>
        {:else}
          <div></div>
        {/if}

        {#if currentStep === "review"}
          <button type="button" class="btn primary" on:click={saveAndClose}>
            Save Configuration
          </button>
        {:else}
          <button
            type="button"
            class="btn primary"
            disabled={
              (currentStep === "select-fields" && selectedFieldIds.length === 0) ||
              (currentStep === "select-parameters" && selectedParameters.length === 0)
            }
            on:click={() => {
              const steps: WizardStep[] = ["select-fields", "select-parameters", "enter-values", "review"];
              const idx = steps.indexOf(currentStep);
              if (idx < steps.length - 1) goToStep(steps[idx + 1]);
            }}
          >
            Next
          </button>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .wizard-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .wizard-modal {
    background: white;
    border-radius: 16px;
    width: 90vw;
    max-width: 1000px;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 25px 50px rgba(0, 0, 0, 0.25);
  }

  .wizard-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding: 24px;
    border-bottom: 1px solid #e2e2e2;
  }

  .wizard-header h2 {
    margin: 0;
    font-size: 20px;
    font-weight: 600;
    color: #1c1c1c;
  }

  .subtitle {
    margin: 4px 0 0;
    font-size: 13px;
    color: #6b7280;
  }

  .close-btn {
    width: 36px;
    height: 36px;
    border: none;
    background: transparent;
    color: #6b7280;
    font-size: 28px;
    cursor: pointer;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .close-btn:hover {
    background: #f3f4f6;
    color: #1c1c1c;
  }

  .wizard-progress {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px 24px;
    background: #f9fafb;
    gap: 8px;
  }

  .step {
    display: flex;
    align-items: center;
    gap: 8px;
    opacity: 0.5;
  }

  .step.active {
    opacity: 1;
  }

  .step.done {
    opacity: 0.7;
  }

  .step-number {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: #e5e7eb;
    color: #6b7280;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    font-weight: 600;
  }

  .step.active .step-number {
    background: #3b82f6;
    color: white;
  }

  .step.done .step-number {
    background: #22c55e;
    color: white;
  }

  .step-label {
    font-size: 13px;
    color: #4b5563;
    font-weight: 500;
  }

  .step-line {
    width: 40px;
    height: 2px;
    background: #e5e7eb;
  }

  .wizard-content {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
  }

  .step-content h3 {
    margin: 0 0 8px;
    font-size: 16px;
    font-weight: 600;
    color: #1c1c1c;
  }

  .help-text {
    margin: 0 0 20px;
    font-size: 13px;
    color: #6b7280;
  }

  .field-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
  }

  .field-card {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    padding: 14px;
    background: white;
    border: 2px solid #e5e7eb;
    border-radius: 10px;
    cursor: pointer;
    text-align: left;
    transition: all 0.15s ease;
  }

  .field-card:hover {
    border-color: #3b82f6;
    background: #f0f7ff;
  }

  .field-card.selected {
    border-color: #3b82f6;
    background: #dbeafe;
  }

  .field-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
  }

  .field-name {
    font-weight: 600;
    font-size: 14px;
    color: #1c1c1c;
  }

  .field-options {
    font-size: 12px;
    color: #6b7280;
  }

  .derived-badge {
    font-size: 10px;
    padding: 2px 6px;
    background: #e5e7eb;
    color: #4b5563;
    border-radius: 4px;
  }

  .combination-preview {
    margin-top: 20px;
    padding: 12px 16px;
    background: #f0f9ff;
    border: 1px solid #bae6fd;
    border-radius: 8px;
    font-size: 14px;
    color: #0369a1;
  }

  .parameter-groups {
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .param-group-header {
    font-weight: 600;
    font-size: 14px;
    color: #1c1c1c;
    margin-bottom: 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid #e5e7eb;
  }

  .param-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 10px;
  }

  .param-card {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
    padding: 12px;
    background: white;
    border: 2px solid #e5e7eb;
    border-radius: 8px;
    cursor: pointer;
    text-align: left;
    transition: all 0.15s ease;
  }

  .param-card:hover {
    border-color: #3b82f6;
  }

  .param-card.selected {
    border-color: #3b82f6;
    background: #dbeafe;
  }

  .param-name {
    font-weight: 500;
    font-size: 13px;
    color: #1c1c1c;
  }

  .param-type {
    font-size: 11px;
    color: #6b7280;
  }

  .param-unit {
    font-size: 11px;
    color: #3b82f6;
  }

  .no-params {
    padding: 40px;
    text-align: center;
    color: #6b7280;
    background: #f9fafb;
    border-radius: 8px;
  }

  .values-step {
    overflow-x: auto;
  }

  .value-matrix {
    min-width: 600px;
  }

  .matrix-header, .matrix-row {
    display: flex;
    border-bottom: 1px solid #e5e7eb;
  }

  .matrix-header {
    background: #f9fafb;
    font-weight: 600;
    font-size: 12px;
    position: sticky;
    top: 0;
  }

  .combo-cell {
    width: 200px;
    min-width: 200px;
    padding: 12px;
    border-right: 1px solid #e5e7eb;
  }

  .combo-cell.header {
    font-weight: 600;
    color: #4b5563;
  }

  .combo-label {
    font-size: 12px;
    color: #1c1c1c;
  }

  .param-cell {
    flex: 1;
    min-width: 280px;
    padding: 8px 12px;
    border-right: 1px solid #e5e7eb;
  }

  .param-cell.header {
    font-size: 11px;
    color: #4b5563;
  }

  .value-input-group {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .value-type-select, .dist-type-select {
    padding: 6px 8px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-size: 12px;
    background: white;
  }

  .value-input, .dist-param {
    width: 80px;
    padding: 6px 8px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-size: 12px;
  }

  .dist-param {
    width: 60px;
  }

  .apply-all-btn {
    padding: 6px 8px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    background: white;
    cursor: pointer;
    font-size: 12px;
    color: #6b7280;
  }

  .apply-all-btn:hover {
    background: #f3f4f6;
    border-color: #3b82f6;
    color: #3b82f6;
  }

  .review-summary {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
    margin-bottom: 24px;
  }

  .summary-item {
    padding: 12px 16px;
    background: #f9fafb;
    border-radius: 8px;
    font-size: 14px;
  }

  .summary-item strong {
    color: #4b5563;
  }

  .review-entries h4 {
    margin: 0 0 12px;
    font-size: 14px;
    font-weight: 600;
    color: #1c1c1c;
  }

  .entries-table {
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    overflow: hidden;
  }

  .entry-row {
    display: grid;
    grid-template-columns: 1fr 1fr 150px;
    gap: 12px;
    padding: 10px 14px;
    border-bottom: 1px solid #e5e7eb;
    font-size: 13px;
  }

  .entry-row:last-child {
    border-bottom: none;
  }

  .entry-combo {
    color: #6b7280;
  }

  .entry-param {
    color: #1c1c1c;
    font-weight: 500;
  }

  .entry-value {
    color: #3b82f6;
    font-family: monospace;
  }

  .more-entries {
    padding: 12px 14px;
    text-align: center;
    color: #6b7280;
    font-size: 13px;
    background: #f9fafb;
  }

  .wizard-footer {
    display: flex;
    justify-content: space-between;
    padding: 20px 24px;
    border-top: 1px solid #e2e2e2;
    background: #f9fafb;
  }

  .btn {
    padding: 10px 20px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    border: none;
    transition: all 0.15s ease;
  }

  .btn.primary {
    background: #3b82f6;
    color: white;
  }

  .btn.primary:hover:not(:disabled) {
    background: #2563eb;
  }

  .btn.primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn.secondary {
    background: white;
    color: #4b5563;
    border: 1px solid #d1d5db;
  }

  .btn.secondary:hover {
    background: #f3f4f6;
  }
</style>
