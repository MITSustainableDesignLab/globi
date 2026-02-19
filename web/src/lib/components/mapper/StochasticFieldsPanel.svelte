<script lang="ts">
  import { mapperStore } from "$lib/stores/mapperStore";
  import {
    addFieldPrior,
    removeFieldPrior,
    updateFieldPrior
  } from "$lib/stores/mapperStore";
  import type {
    FieldPrior,
    SemanticField,
    SemanticFieldCondition
  } from "$lib/types/mapper";
  import ProbabilityMatrix from "$lib/components/mapper/ProbabilityMatrix.svelte";

  $: allFields = $mapperStore.semanticFields;
  $: priors = $mapperStore.fieldPriors;

  let selectedPriorId: string | null = null;
  let editingPrior: Partial<FieldPrior> | null = null;

  // For now, assume all fields can be stochastic (in real app, would filter by GIS data presence)
  $: availableTargetFields = allFields.filter(
    (f) => !priors.some((p) => p.targetFieldId === f.id)
  );

  const generateCombinations = (
    sourceFields: SemanticField[]
  ): SemanticFieldCondition[] => {
    if (sourceFields.length === 0) {
      return [{}];
    }

    const [first, ...rest] = sourceFields;
    const restCombinations = generateCombinations(rest);
    const combinations: SemanticFieldCondition[] = [];

    for (const option of first.options ?? []) {
      for (const restComb of restCombinations) {
        combinations.push({
          ...restComb,
          [first.id]: option
        });
      }
    }

    return combinations;
  };

  const startEditing = (prior: FieldPrior) => {
    editingPrior = { ...prior };
    selectedPriorId = prior.id;
  };

  const startNew = () => {
    editingPrior = {
      targetFieldId: "",
      sourceFieldIds: [],
      probabilities: []
    };
    selectedPriorId = null;
  };

  const cancelEditing = () => {
    editingPrior = null;
    selectedPriorId = null;
  };

  const savePrior = () => {
    if (!editingPrior || !editingPrior.targetFieldId) return;

    const targetField = allFields.find((f) => f.id === editingPrior.targetFieldId);
    if (!targetField || !targetField.options) return;

    const sourceFields = allFields.filter((f) =>
      editingPrior.sourceFieldIds?.includes(f.id)
    );

    // Generate combinations if not already set
    let conditions: SemanticFieldCondition[] = editingPrior.probabilities?.map(
      (p) => p.condition
    ) ?? [];
    if (conditions.length === 0) {
      conditions = generateCombinations(sourceFields);
    }

    // Initialize probabilities if needed
    const probabilities = conditions.map((condition, index) => {
      const existing = editingPrior.probabilities?.[index];
      const probs: Record<string, number> = {};
      for (const option of targetField.options) {
        probs[option] = existing?.probabilities[option] ?? 0;
      }
      return { condition, probabilities: probs };
    });

    const prior: Omit<FieldPrior, "id"> = {
      targetFieldId: editingPrior.targetFieldId,
      sourceFieldIds: editingPrior.sourceFieldIds ?? [],
      probabilities
    };

    if (selectedPriorId) {
      updateFieldPrior(selectedPriorId, prior);
    } else {
      addFieldPrior(prior);
    }

    cancelEditing();
  };

  const updateProbability = (
    conditionIndex: number,
    option: string,
    probability: number
  ) => {
    if (!editingPrior) return;

    const clamped = Math.max(0, Math.min(1, probability));
    if (!editingPrior.probabilities) {
      editingPrior.probabilities = [];
    }

    if (!editingPrior.probabilities[conditionIndex]) {
      const targetField = allFields.find((f) => f.id === editingPrior.targetFieldId);
      if (!targetField) return;
      editingPrior.probabilities[conditionIndex] = {
        condition: {},
        probabilities: Object.fromEntries(
          (targetField.options ?? []).map((opt) => [opt, 0])
        )
      };
    }

    if (!editingPrior.probabilities[conditionIndex].probabilities) {
      const targetField = allFields.find((f) => f.id === editingPrior.targetFieldId);
      if (!targetField) return;
      editingPrior.probabilities[conditionIndex].probabilities = Object.fromEntries(
        (targetField.options ?? []).map((opt) => [opt, 0])
      );
    }

    editingPrior.probabilities[conditionIndex].probabilities[option] = clamped;
    editingPrior = { ...editingPrior };
  };

  const normalizeProbabilities = (conditionIndex: number) => {
    if (!editingPrior?.probabilities?.[conditionIndex]?.probabilities) return;

    const probs = editingPrior.probabilities[conditionIndex].probabilities;
    if (!probs) return;
    const total = Object.values(probs).reduce((sum, p) => sum + (p || 0), 0);

    if (total === 0) {
      // Distribute evenly
      const count = Object.keys(probs).length;
      const value = 1 / count;
      for (const key in probs) {
        probs[key] = value;
      }
    } else {
      // Normalize to sum to 1
      for (const key in probs) {
        probs[key] = probs[key] / total;
      }
    }

    editingPrior = { ...editingPrior };
  };

  $: selectedPrior = selectedPriorId ? priors.find((p) => p.id === selectedPriorId) : null;
  $: targetField = editingPrior?.targetFieldId
    ? allFields.find((f) => f.id === editingPrior.targetFieldId) ?? null
    : null;
  $: sourceFields = editingPrior?.sourceFieldIds
    ? allFields.filter((f) => editingPrior.sourceFieldIds?.includes(f.id))
    : [];
  $: conditions = editingPrior?.probabilities?.map((p) => p.condition) ?? [];
  $: probabilities = editingPrior?.probabilities?.map((p) => p.probabilities ?? {}) ?? [];
</script>

<div class="panel">
  <div class="header">
    <div>
      <div class="title">Stochastic Field Assignment</div>
      <div class="subtitle">
        Define conditional probabilities for assigning unknown semantic fields
      </div>
    </div>
    <button type="button" class="new-btn" on:click={startNew}>+ New Prior</button>
  </div>

  <div class="content">
    {#if priors.length > 0}
      <div class="priors-list">
        <div class="list-header">Existing Priors</div>
        {#each priors as prior (prior.id)}
          {@const target = allFields.find((f) => f.id === prior.targetFieldId)}
          <div class="prior-item" class:selected={selectedPriorId === prior.id}>
            <div class="prior-info">
              <div class="prior-name">
                {target?.name ?? prior.targetFieldId}
              </div>
              <div class="prior-meta">
                Based on: {prior.sourceFieldIds.length} source field{prior.sourceFieldIds.length !== 1 ? "s" : ""}
              </div>
            </div>
            <div class="prior-actions">
              <button type="button" class="edit-btn" on:click={() => startEditing(prior)}>
                Edit
              </button>
              <button
                type="button"
                class="delete-btn"
                on:click={() => removeFieldPrior(prior.id)}
              >
                Delete
              </button>
            </div>
          </div>
        {/each}
      </div>
    {/if}

    {#if editingPrior}
      <div class="editor-section">
        <div class="section-title">
          {selectedPriorId ? "Edit Prior" : "Create New Prior"}
        </div>

        <div class="form-group">
          <label>Target Field (field to assign stochastically)</label>
          <select
            value={editingPrior.targetFieldId ?? ""}
            on:change={(e) => {
              editingPrior = {
                ...editingPrior,
                targetFieldId: e.currentTarget.value,
                probabilities: []
              };
            }}
            disabled={!!selectedPriorId}
          >
            <option value="">Select target field...</option>
            {#each availableTargetFields as field}
              <option value={field.id}>{field.name}</option>
            {/each}
            {#if selectedPriorId}
              {@const selected = allFields.find((f) => f.id === editingPrior.targetFieldId)}
              {#if selected}
                <option value={selected.id} selected>{selected.name}</option>
              {/if}
            {/if}
          </select>
        </div>

        {#if targetField}
          <div class="form-group">
            <label>Source Fields (known fields from GIS data)</label>
            <div class="field-checkboxes">
              {#each allFields.filter((f) => f.id !== editingPrior.targetFieldId) as field}
                <label class="checkbox-label">
                  <input
                    type="checkbox"
                    checked={editingPrior.sourceFieldIds?.includes(field.id) ?? false}
                    on:change={(e) => {
                      const current = editingPrior.sourceFieldIds ?? [];
                      const updated = e.currentTarget.checked
                        ? [...current, field.id]
                        : current.filter((id) => id !== field.id);
                      editingPrior = {
                        ...editingPrior,
                        sourceFieldIds: updated,
                        probabilities: []
                      };
                    }}
                  />
                  <span>{field.name}</span>
                </label>
              {/each}
            </div>
          </div>

          {#if sourceFields.length > 0 && targetField.options}
            <div class="form-group">
              <label>Probability Matrix</label>
              <div class="matrix-container">
                <ProbabilityMatrix
                  conditions={conditions.length > 0 ? conditions : generateCombinations(sourceFields)}
                  probabilities={probabilities.length > 0 ? probabilities : generateCombinations(sourceFields).map(() => ({}))}
                  fieldOptions={targetField.options}
                  sourceFields={sourceFields}
                  onUpdate={updateProbability}
                  onNormalize={normalizeProbabilities}
                />
              </div>
              <div class="help-text">
                Define probabilities for each target field option given the source field
                conditions. Probabilities should sum to 1.0 for each condition.
              </div>
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
            on:click={savePrior}
            disabled={!editingPrior.targetFieldId || !editingPrior.sourceFieldIds?.length}
          >
            {selectedPriorId ? "Update" : "Create"} Prior
          </button>
        </div>
      </div>
    {:else if priors.length === 0}
      <div class="empty-state">
        <div class="empty-icon">📊</div>
        <div class="empty-title">No stochastic field priors defined</div>
        <div class="empty-text">
          Create a prior to assign unknown semantic fields probabilistically based on
          known GIS data fields.
        </div>
        <button type="button" class="empty-action" on:click={startNew}>
          Create First Prior
        </button>
      </div>
    {/if}
  </div>
</div>

<style>
  .panel {
    height: calc(100vh - 160px);
    background: #ffffff;
    border: 1px solid #e2e2e2;
    border-radius: 12px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .header {
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

  .new-btn {
    padding: 10px 16px;
    background: #3b82f6;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
  }

  .new-btn:hover {
    background: #2563eb;
  }

  .content {
    padding: 24px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .priors-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .list-header {
    font-weight: 600;
    font-size: 14px;
    color: #1c1c1c;
    margin-bottom: 8px;
  }

  .prior-item {
    padding: 16px;
    background: #f9fafb;
    border: 1px solid #e2e2e2;
    border-radius: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .prior-item.selected {
    border-color: #3b82f6;
    background: #eff6ff;
  }

  .prior-info {
    flex: 1;
  }

  .prior-name {
    font-weight: 600;
    font-size: 14px;
    color: #1c1c1c;
  }

  .prior-meta {
    font-size: 12px;
    color: #6b7280;
    margin-top: 4px;
  }

  .prior-actions {
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

  .editor-section {
    padding: 20px;
    background: #f9fafb;
    border: 1px solid #e2e2e2;
    border-radius: 8px;
  }

  .section-title {
    font-weight: 600;
    font-size: 16px;
    color: #1c1c1c;
    margin-bottom: 20px;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 20px;
  }

  label {
    font-size: 13px;
    font-weight: 500;
    color: #4b5563;
  }

  select {
    padding: 10px 12px;
    background: white;
    border: 1px solid #d8d8d8;
    border-radius: 6px;
    color: #1c1c1c;
    font-size: 13px;
  }

  select:focus {
    outline: none;
    border-color: #3b82f6;
  }

  select:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .field-checkboxes {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px;
    background: white;
    border: 1px solid #e2e2e2;
    border-radius: 6px;
  }

  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: #4b5563;
    cursor: pointer;
  }

  .checkbox-label input[type="checkbox"] {
    width: 16px;
    height: 16px;
    cursor: pointer;
  }

  .matrix-container {
    margin-top: 12px;
  }

  .help-text {
    font-size: 12px;
    color: #6b7280;
    margin-top: 8px;
    line-height: 1.5;
  }

  .form-actions {
    display: flex;
    gap: 12px;
    margin-top: 24px;
  }

  .cancel-btn,
  .save-btn {
    flex: 1;
    padding: 12px;
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

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 60px 40px;
    text-align: center;
  }

  .empty-icon {
    font-size: 48px;
    margin-bottom: 16px;
  }

  .empty-title {
    font-weight: 600;
    font-size: 18px;
    color: #1c1c1c;
    margin-bottom: 8px;
  }

  .empty-text {
    font-size: 14px;
    color: #6b7280;
    margin-bottom: 24px;
    max-width: 400px;
  }

  .empty-action {
    padding: 12px 24px;
    background: #3b82f6;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
  }

  .empty-action:hover {
    background: #2563eb;
  }
</style>
