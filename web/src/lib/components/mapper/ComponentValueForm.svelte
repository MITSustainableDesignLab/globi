<script lang="ts">
  import type { Distribution, DistributionType, SemanticFieldCondition } from "$lib/types/mapper";

  export let componentPath: string;
  export let parameterName: string = "";
  export let value: number | undefined = undefined;
  export let distribution: Distribution | undefined = undefined;
  export let conditions: SemanticFieldCondition = {};
  export let linkedFields: string[] = [];
  export let availableFields: Array<{ id: string; name: string; options?: string[] }> = [];

  export let onUpdate: (update: {
    parameterName: string;
    value?: number;
    distribution?: Distribution;
    conditions: SemanticFieldCondition;
  }) => void;

  let useDistribution = false;
  let distributionType: DistributionType = "fixed";
  let localDistribution: Distribution | undefined = undefined;

  $: if (distribution) {
    useDistribution = true;
    distributionType = distribution.type;
    localDistribution = { ...distribution };
  } else if (value !== undefined) {
    useDistribution = false;
    localDistribution = undefined;
  } else {
    useDistribution = false;
    localDistribution = undefined;
  }

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

  const handleSave = () => {
    if (!parameterName) return;

    const update: {
      parameterName: string;
      value?: number;
      distribution?: Distribution;
      conditions: SemanticFieldCondition;
    } = {
      parameterName,
      conditions
    };

    if (useDistribution) {
      update.distribution = localDistribution ?? { type: distributionType };
    } else {
      update.value = value;
    }

    onUpdate(update);
  };

  const handleConditionChange = (fieldId: string, optionValue: string) => {
    if (optionValue === "") {
      const { [fieldId]: _, ...rest } = conditions;
      conditions = rest;
    } else {
      conditions = { ...conditions, [fieldId]: optionValue };
    }
    conditions = { ...conditions };
  };
</script>

  <div class="form">
  <div class="form-group">
    <label for="param-name">Parameter Name</label>
    <input id="param-name" type="text" bind:value={parameterName} placeholder="e.g., lighting_power_density" />
  </div>

  {#if linkedFields.length > 0}
    <div class="form-group">
      <label>Conditions (optional)</label>
      <div class="conditions-builder">
        {#each availableFields.filter((f) => linkedFields.includes(f.id)) as field}
          <div class="condition-row">
            <span class="field-label">{field.name}:</span>
            <select
              value={conditions[field.id] ?? ""}
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
    <label>Value Type</label>
    <div class="radio-group">
      <label class="radio-label">
        <input
          type="radio"
          name="valueType"
          checked={!useDistribution}
          on:change={() => {
            useDistribution = false;
            distribution = undefined;
          }}
        />
        <span>Fixed Value</span>
      </label>
      <label class="radio-label">
        <input
          type="radio"
          name="valueType"
          checked={useDistribution}
          on:change={() => {
            useDistribution = true;
            value = undefined;
            if (!localDistribution) {
              localDistribution = { type: "fixed", value: 0 };
            }
          }}
        />
        <span>Distribution</span>
      </label>
    </div>
  </div>

  {#if !useDistribution}
    <div class="form-group">
      <label for="fixed-value">Value</label>
      <input
        id="fixed-value"
        type="number"
        step="any"
        bind:value={value}
        placeholder="Enter fixed value"
      />
    </div>
  {:else}
    <div class="form-group">
      <label for="dist-type">Distribution Type</label>
      <select
        id="dist-type"
        value={distributionType}
        on:change={(e) => {
          distributionType = e.currentTarget.value as DistributionType;
          localDistribution = { type: distributionType } as Distribution;
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

    {#if localDistribution}
      {@const params = getDistributionParams(localDistribution.type)}
      {#if params.includes("value")}
        <div class="form-group">
          <label for="dist-value">Value</label>
          <input
            id="dist-value"
            type="number"
            step="any"
            value={localDistribution.value ?? ""}
            on:input={(e) => {
              localDistribution = { ...localDistribution, value: parseFloat(e.currentTarget.value) || undefined };
            }}
          />
        </div>
      {/if}
      {#if params.includes("min")}
        <div class="form-group">
          <label for="dist-min">Min</label>
          <input
            id="dist-min"
            type="number"
            step="any"
            value={localDistribution.min ?? ""}
            on:input={(e) => {
              localDistribution = { ...localDistribution, min: parseFloat(e.currentTarget.value) || undefined };
            }}
          />
        </div>
      {/if}
      {#if params.includes("max")}
        <div class="form-group">
          <label for="dist-max">Max</label>
          <input
            id="dist-max"
            type="number"
            step="any"
            value={localDistribution.max ?? ""}
            on:input={(e) => {
              localDistribution = { ...localDistribution, max: parseFloat(e.currentTarget.value) || undefined };
            }}
          />
        </div>
      {/if}
      {#if params.includes("mean")}
        <div class="form-group">
          <label for="dist-mean">Mean</label>
          <input
            id="dist-mean"
            type="number"
            step="any"
            value={localDistribution.mean ?? ""}
            on:input={(e) => {
              localDistribution = { ...localDistribution, mean: parseFloat(e.currentTarget.value) || undefined };
            }}
          />
        </div>
      {/if}
      {#if params.includes("std")}
        <div class="form-group">
          <label for="dist-std">Standard Deviation</label>
          <input
            id="dist-std"
            type="number"
            step="any"
            value={localDistribution.std ?? ""}
            on:input={(e) => {
              localDistribution = { ...localDistribution, std: parseFloat(e.currentTarget.value) || undefined };
            }}
          />
        </div>
      {/if}
      {#if params.includes("mode")}
        <div class="form-group">
          <label for="dist-mode">Mode</label>
          <input
            id="dist-mode"
            type="number"
            step="any"
            value={localDistribution.mode ?? ""}
            on:input={(e) => {
              localDistribution = { ...localDistribution, mode: parseFloat(e.currentTarget.value) || undefined };
            }}
          />
        </div>
      {/if}
      {#if params.includes("options")}
        <div class="form-group">
          <label for="dist-options">Options (comma-separated)</label>
          <input
            id="dist-options"
            type="text"
            placeholder="option1, option2, option3"
            value={localDistribution.options?.join(", ") ?? ""}
            on:input={(e) => {
              const options = e.currentTarget.value
                .split(",")
                .map((s) => s.trim())
                .filter((s) => s.length > 0);
              localDistribution = { ...localDistribution, options };
            }}
          />
        </div>
      {/if}
      {#if params.includes("weights")}
        <div class="form-group">
          <label for="dist-weights">Weights (comma-separated)</label>
          <input
            id="dist-weights"
            type="text"
            placeholder="0.3, 0.5, 0.2"
            value={localDistribution.weights?.join(", ") ?? ""}
            on:input={(e) => {
              const weights = e.currentTarget.value
                .split(",")
                .map((s) => parseFloat(s.trim()))
                .filter((n) => !isNaN(n));
              localDistribution = { ...localDistribution, weights };
            }}
          />
        </div>
      {/if}
    {/if}
  {/if}

  <div class="form-actions">
    <button type="button" class="save-btn" on:click={handleSave} disabled={!parameterName}>
      Save
    </button>
  </div>
</div>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
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
    color: #9ca3af;
  }

  .conditions-builder {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px;
    background: #f9fafb;
    border: 1px solid #e2e2e2;
    border-radius: 6px;
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

  .radio-label input[type="radio"] {
    width: 16px;
    height: 16px;
    cursor: pointer;
  }

  .form-actions {
    margin-top: 8px;
  }

  .save-btn {
    width: 100%;
    padding: 10px;
    background: #3b82f6;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
  }

  .save-btn:hover:not(:disabled) {
    background: #2563eb;
  }

  .save-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
