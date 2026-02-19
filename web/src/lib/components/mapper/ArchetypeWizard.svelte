<script lang="ts">
  import { mapperStore } from "$lib/stores/mapperStore";
  import {
    archetypeStore,
    addArchetype,
    setArchetypeComponentValues,
    setArchetypeLinkedConditions
  } from "$lib/stores/archetypeStore";
  import type {
    ComponentValueDefinition,
    SemanticFieldCondition
  } from "$lib/stores/archetypeStore";
  import ComponentValueForm from "$lib/components/mapper/ComponentValueForm.svelte";

  export let onClose: () => void;

  let step = 1;
  let archetypeName = "";
  let archetypeIcon: "building" | "tower" | "warehouse" = "building";
  let selectedFields: string[] = [];
  let fieldConditions: SemanticFieldCondition = {};
  let componentValues: ComponentValueDefinition[] = [];
  let editingComponent: string | null = null;
  let editingValue: Partial<ComponentValueDefinition> | null = null;

  $: allComponents = $mapperStore.componentLevels;
  $: allFields = $mapperStore.semanticFields;
  $: selectedComponent = editingComponent
    ? allComponents.find((c) => c.path === editingComponent)
    : null;

  const handleFieldToggle = (fieldId: string) => {
    if (selectedFields.includes(fieldId)) {
      selectedFields = selectedFields.filter((id) => id !== fieldId);
      const { [fieldId]: _, ...rest } = fieldConditions;
      fieldConditions = rest;
    } else {
      selectedFields = [...selectedFields, fieldId];
    }
  };

  const handleFieldConditionChange = (fieldId: string, value: string) => {
    if (value === "") {
      const { [fieldId]: _, ...rest } = fieldConditions;
      fieldConditions = rest;
    } else {
      fieldConditions = { ...fieldConditions, [fieldId]: value };
    }
    fieldConditions = { ...fieldConditions };
  };

  const startEditingComponent = (componentPath: string) => {
    editingComponent = componentPath;
    const existing = componentValues.find((v) => v.componentPath === componentPath);
    editingValue = existing
      ? {
          componentPath: existing.componentPath,
          parameterName: existing.parameterName ?? "",
          value: existing.value,
          distribution: existing.distribution,
          conditions: existing.conditions ?? {}
        }
      : {
          componentPath,
          parameterName: "",
          conditions: {}
        };
  };

  const cancelEditing = () => {
    editingComponent = null;
    editingValue = null;
  };

  const saveComponentValue = (update: {
    parameterName: string;
    value?: number;
    distribution?: any;
    conditions: SemanticFieldCondition;
  }) => {
    if (!editingComponent) return;

    const existingIndex = componentValues.findIndex(
      (v) => v.componentPath === editingComponent
    );

    const valueDef: ComponentValueDefinition = {
      componentPath: editingComponent,
      parameterName: update.parameterName,
      value: update.value,
      distribution: update.distribution,
      conditions: update.conditions
    };

    if (existingIndex >= 0) {
      componentValues[existingIndex] = valueDef;
    } else {
      componentValues = [...componentValues, valueDef];
    }

    componentValues = [...componentValues];
    cancelEditing();
  };

  const removeComponentValue = (componentPath: string) => {
    componentValues = componentValues.filter((v) => v.componentPath !== componentPath);
  };

  const handleNext = () => {
    if (step === 1 && selectedFields.length > 0) {
      step = 2;
    } else if (step === 2) {
      step = 3;
    }
  };

  const handleBack = () => {
    if (step > 1) {
      step = step - 1;
    }
  };

  const handleFinish = () => {
    if (!archetypeName.trim()) return;

    const archetypeId = addArchetype(archetypeName, archetypeIcon);
    if (!archetypeId) {
      // Archetype creation failed (duplicate name or empty)
      return;
    }

    setArchetypeLinkedConditions(archetypeId, fieldConditions);
    setArchetypeComponentValues(archetypeId, componentValues);

    // Also link fields to archetype
    selectedFields.forEach((fieldId) => {
      // This would need to be implemented in archetypeStore
    });

    onClose();
  };

  $: canProceedStep1 = selectedFields.length > 0;
  $: canFinish = archetypeName.trim().length > 0;
</script>

<div class="modal-overlay" on:click={onClose}>
  <div class="modal-content" on:click|stopPropagation>
    <div class="modal-header">
      <div>
        <div class="title">Create Archetype</div>
        <div class="subtitle">Step {step} of 3</div>
      </div>
      <button type="button" class="close-btn" on:click={onClose}>×</button>
    </div>

    <div class="modal-body">
      {#if step === 1}
        <div class="step-content">
          <div class="step-title">Link Semantic Fields</div>
          <div class="step-description">
            Select which semantic fields this archetype applies to, and optionally
            specify conditions.
          </div>

          <div class="form-group">
            <label>Archetype Name</label>
            <input type="text" bind:value={archetypeName} placeholder="e.g., Modern Office" />
          </div>

          <div class="form-group">
            <label>Icon</label>
            <select bind:value={archetypeIcon}>
              <option value="building">Building</option>
              <option value="tower">Tower</option>
              <option value="warehouse">Warehouse</option>
            </select>
          </div>

          <div class="form-group">
            <label>Semantic Fields</label>
            <div class="fields-list">
              {#each allFields as field}
                <label class="field-checkbox">
                  <input
                    type="checkbox"
                    checked={selectedFields.includes(field.id)}
                    on:change={() => handleFieldToggle(field.id)}
                  />
                  <span class="field-name">{field.name}</span>
                  {#if selectedFields.includes(field.id) && field.options}
                    <select
                      value={fieldConditions[field.id] ?? ""}
                      on:change={(e) =>
                        handleFieldConditionChange(field.id, e.currentTarget.value)}
                    >
                      <option value="">Any value</option>
                      {#each field.options as option}
                        <option value={option}>{option}</option>
                      {/each}
                    </select>
                  {/if}
                </label>
              {/each}
            </div>
          </div>
        </div>
      {:else if step === 2}
        <div class="step-content">
          <div class="step-title">Define Component Values</div>
          <div class="step-description">
            Define parameter values for each component. You can set fixed values or
            distributions.
          </div>

          {#if editingComponent && editingValue}
            <div class="editor-panel">
              <div class="editor-header">
                <div>
                  <div class="editor-title">Edit Component: {selectedComponent?.displayName}</div>
                  <div class="editor-path">{editingComponent}</div>
                </div>
                <button type="button" class="cancel-btn" on:click={cancelEditing}>
                  Cancel
                </button>
              </div>
              {#if editingValue}
                <ComponentValueForm
                  componentPath={editingComponent}
                  parameterName={editingValue.parameterName ?? ""}
                  value={editingValue.value}
                  distribution={editingValue.distribution}
                  conditions={editingValue.conditions ?? {}}
                  linkedFields={selectedFields}
                  availableFields={allFields.map(f => ({ id: f.id, name: f.name, options: f.options }))}
                  onUpdate={saveComponentValue}
                />
              {/if}
            </div>
          {:else}
            <div class="components-list">
              {#each allComponents as component}
                {@const value = componentValues.find((v) => v.componentPath === component.path)}
                <div class="component-item">
                  <div class="component-info">
                    <div class="component-name">{component.displayName}</div>
                    <div class="component-path">{component.path}</div>
                    {#if value}
                      <div class="component-value">
                        {value.parameterName}
                        {#if value.value !== undefined}
                          = {value.value}
                        {:else if value.distribution}
                          ({value.distribution.type} distribution)
                        {/if}
                      </div>
                    {/if}
                  </div>
                  <div class="component-actions">
                    <button
                      type="button"
                      class="edit-btn"
                      on:click={() => startEditingComponent(component.path)}
                    >
                      {value ? "Edit" : "Add"} Value
                    </button>
                    {#if value}
                      <button
                        type="button"
                        class="delete-btn"
                        on:click={() => removeComponentValue(component.path)}
                      >
                        Remove
                      </button>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {:else if step === 3}
        <div class="step-content">
          <div class="step-title">Review</div>
          <div class="step-description">Review your archetype configuration before saving.</div>

          <div class="review-section">
            <div class="review-item">
              <div class="review-label">Name:</div>
              <div class="review-value">{archetypeName}</div>
            </div>
            <div class="review-item">
              <div class="review-label">Icon:</div>
              <div class="review-value">{archetypeIcon}</div>
            </div>
            <div class="review-item">
              <div class="review-label">Linked Fields:</div>
              <div class="review-value">
                {selectedFields.length > 0
                  ? selectedFields
                      .map((id) => allFields.find((f) => f.id === id)?.name ?? id)
                      .join(", ")
                  : "None"}
              </div>
            </div>
            <div class="review-item">
              <div class="review-label">Component Values:</div>
              <div class="review-value">{componentValues.length} defined</div>
            </div>
          </div>
        </div>
      {/if}
    </div>

    <div class="modal-footer">
      {#if step > 1}
        <button type="button" class="back-btn" on:click={handleBack}>
          Back
        </button>
      {/if}
      <div class="spacer"></div>
      {#if step < 3}
        <button
          type="button"
          class="next-btn"
          on:click={handleNext}
          disabled={step === 1 && !canProceedStep1}
        >
          Next
        </button>
      {:else}
        <button type="button" class="finish-btn" on:click={handleFinish} disabled={!canFinish}>
          Create Archetype
        </button>
      {/if}
    </div>
  </div>
</div>

<style>
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: grid;
    place-items: center;
    z-index: 200;
  }

  .modal-content {
    background: #ffffff;
    border: 1px solid #e2e2e2;
    border-radius: 12px;
    width: min(900px, 90vw);
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.15);
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 24px;
    border-bottom: 1px solid #e2e2e2;
  }

  .title {
    font-weight: 600;
    font-size: 18px;
    color: #1c1c1c;
  }

  .subtitle {
    font-size: 13px;
    color: #6b7280;
    margin-top: 4px;
  }

  .close-btn {
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

  .close-btn:hover {
    background: #f3f3f3;
    color: #1c1c1c;
  }

  .modal-body {
    padding: 24px;
    overflow-y: auto;
    flex: 1;
  }

  .step-content {
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .step-title {
    font-weight: 600;
    font-size: 16px;
    color: #1c1c1c;
  }

  .step-description {
    font-size: 13px;
    color: #6b7280;
    line-height: 1.5;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  label {
    font-size: 13px;
    font-weight: 500;
    color: #4b5563;
  }

  input,
  select {
    padding: 10px 12px;
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

  .fields-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    background: #f9fafb;
    border: 1px solid #e2e2e2;
    border-radius: 6px;
    max-height: 300px;
    overflow-y: auto;
  }

  .field-checkbox {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px;
    border-radius: 4px;
    cursor: pointer;
  }

  .field-checkbox:hover {
    background: #f3f3f3;
  }

  .field-checkbox input[type="checkbox"] {
    width: 18px;
    height: 18px;
    cursor: pointer;
  }

  .field-name {
    flex: 1;
    font-size: 13px;
    color: #4b5563;
  }

  .field-checkbox select {
    width: 150px;
    padding: 6px 8px;
    font-size: 12px;
  }

  .components-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-height: 500px;
    overflow-y: auto;
  }

  .component-item {
    padding: 16px;
    background: #f9fafb;
    border: 1px solid #e2e2e2;
    border-radius: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .component-info {
    flex: 1;
  }

  .component-name {
    font-weight: 600;
    font-size: 14px;
    color: #1c1c1c;
  }

  .component-path {
    font-size: 11px;
    color: #9ca3af;
    margin-top: 4px;
    font-family: monospace;
  }

  .component-value {
    font-size: 12px;
    color: #2563eb;
    margin-top: 6px;
  }

  .component-actions {
    display: flex;
    gap: 8px;
  }

  .edit-btn,
  .delete-btn {
    padding: 6px 12px;
    border: 1px solid #d8d8d8;
    background: white;
    color: #4b5563;
    border-radius: 4px;
    font-size: 12px;
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

  .editor-panel {
    padding: 20px;
    background: #f9fafb;
    border: 1px solid #e2e2e2;
    border-radius: 8px;
  }

  .editor-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    padding-bottom: 16px;
    border-bottom: 1px solid #e2e2e2;
  }

  .editor-title {
    font-weight: 600;
    font-size: 14px;
    color: #1c1c1c;
  }

  .editor-path {
    font-size: 11px;
    color: #9ca3af;
    margin-top: 4px;
    font-family: monospace;
  }

  .review-section {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px;
    background: #f9fafb;
    border: 1px solid #e2e2e2;
    border-radius: 8px;
  }

  .review-item {
    display: flex;
    gap: 12px;
  }

  .review-label {
    font-weight: 500;
    font-size: 13px;
    color: #4b5563;
    min-width: 120px;
  }

  .review-value {
    font-size: 13px;
    color: #1c1c1c;
  }

  .modal-footer {
    display: flex;
    gap: 12px;
    padding: 20px 24px;
    border-top: 1px solid #e2e2e2;
  }

  .spacer {
    flex: 1;
  }

  .back-btn,
  .next-btn,
  .finish-btn {
    padding: 10px 20px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    border: none;
  }

  .back-btn {
    background: #f3f4f6;
    color: #4b5563;
    border: 1px solid #d8d8d8;
  }

  .back-btn:hover {
    background: #e5e7eb;
  }

  .next-btn,
  .finish-btn {
    background: #3b82f6;
    color: #ffffff;
  }

  .next-btn:hover:not(:disabled),
  .finish-btn:hover:not(:disabled) {
    background: #2563eb;
  }

  .next-btn:disabled,
  .finish-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
