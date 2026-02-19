<script lang="ts">
  import type { DerivedFieldType, RangeMapping } from "$lib/types/mapper";
  import {
    addDerivedField,
    addCompoundDerivedField,
    mapperStore,
    setComponentViewMode,
    setComponentCanvas
  } from "$lib/stores/mapperStore";
  import { calculateComponentStatus } from "$lib/utils/mapperStatus";
  import { COMPONENT_PARAMETERS } from "$lib/data/componentParameters";

  let derivedName = "";
  let derivedType: DerivedFieldType = "numeric_range";
  let sourceFieldId = "";
  let rangeRows: RangeMapping[] = [{ min: 0, max: 0, label: "range_1" }];
  let groupMap: Record<string, string> = {};
  let groupSourceId = "";

  let compoundName = "";
  let compoundLogic: "and" | "or" = "and";
  let compoundSourceIds: string[] = [];

  $: baseFields = $mapperStore.semanticFields.filter((field) => !field.isDerived);
  $: derivedFields = $mapperStore.semanticFields.filter((field) => field.isDerived);

  $: numericFields = baseFields.filter((field) => field.type === "numeric");
  $: categoricalFields = baseFields.filter((field) => field.type === "categorical");
  $: availableSourceFields =
    derivedType === "numeric_range" ? numericFields : categoricalFields;
  $: if (!sourceFieldId && availableSourceFields.length) {
    sourceFieldId = availableSourceFields[0].id;
  }
  $: if (
    sourceFieldId &&
    availableSourceFields.length &&
    !availableSourceFields.some((field) => field.id === sourceFieldId)
  ) {
    sourceFieldId = availableSourceFields[0].id;
  }

  $: if (derivedType === "categorical_mapping" && sourceFieldId) {
    const sourceField = baseFields.find((field) => field.id === sourceFieldId);
    if (sourceField?.options?.length && groupSourceId !== sourceFieldId) {
      groupSourceId = sourceFieldId;
      groupMap = Object.fromEntries(
        sourceField.options.map((option) => [option, option])
      );
    }
  }

  const updateRangeRow = (
    index: number,
    key: "min" | "max" | "label",
    value: string
  ) => {
    rangeRows = rangeRows.map((row, rowIndex) => {
      if (rowIndex !== index) {
        return row;
      }
      if (key === "label") {
        return { ...row, label: value };
      }
      const numericValue = Number(value);
      return { ...row, [key]: Number.isNaN(numericValue) ? 0 : numericValue };
    });
  };

  const addRangeRow = () => {
    rangeRows = [
      ...rangeRows,
      { min: 0, max: 0, label: `range_${rangeRows.length + 1}` }
    ];
  };

  const removeRangeRow = (index: number) => {
    rangeRows = rangeRows.filter((_, rowIndex) => rowIndex !== index);
  };

  const updateGroupMap = (value: string, group: string) => {
    groupMap = { ...groupMap, [value]: group };
  };

  const buildGroupMapping = () => {
    const mapping: Record<string, string[]> = {};
    Object.entries(groupMap).forEach(([value, group]) => {
      const trimmedGroup = group.trim();
      if (!trimmedGroup) {
        return;
      }
      mapping[trimmedGroup] = mapping[trimmedGroup] ?? [];
      mapping[trimmedGroup].push(value);
    });
    return mapping;
  };

  const submitDerivedField = () => {
    if (!sourceFieldId || !derivedName.trim()) {
      return;
    }
    const cleanRanges = rangeRows.filter(
      (row) => row.label.trim() && row.max >= row.min
    );
    addDerivedField({
      name: derivedName,
      sourceFieldId,
      derivedType,
      rangeMapping: derivedType === "numeric_range" ? cleanRanges : [],
      groupMapping: derivedType === "categorical_mapping" ? buildGroupMapping() : {}
    });
    derivedName = "";
  };

  const toggleCompoundSource = (fieldId: string) => {
    if (compoundSourceIds.includes(fieldId)) {
      compoundSourceIds = compoundSourceIds.filter((id) => id !== fieldId);
    } else {
      compoundSourceIds = [...compoundSourceIds, fieldId];
    }
  };

  const submitCompoundDerivedField = () => {
    if (!compoundName.trim() || compoundSourceIds.length < 2) {
      return;
    }
    addCompoundDerivedField({
      name: compoundName.trim(),
      sourceFieldIds: compoundSourceIds,
      logic: compoundLogic
    });
    compoundName = "";
    compoundSourceIds = [];
  };

  $: compoundCategoricalFields = $mapperStore.semanticFields.filter(
    (f) => f.type === "categorical" && (f.options?.length ?? 0) > 0
  );

  // components to show; flat mode = leaf only, filtered by canvas
  $: leafPathsSet = new Set(Object.keys(COMPONENT_PARAMETERS));
  $: canvasPrefix = {
    envelope: "Envelope",
    spaceuse: "Operations.SpaceUse",
    hvac: "Operations.HVAC",
    dhw: "Operations.DHW"
  }[$mapperStore.ui.componentCanvas] ?? "Envelope";
  $: componentsWithLinks =
    $mapperStore.ui.componentViewMode === "flat"
      ? $mapperStore.componentLevels.filter(
          (l) => leafPathsSet.has(l.path) && l.path.startsWith(canvasPrefix)
        )
      : $mapperStore.componentLevels;

  $: fieldIdToName = Object.fromEntries(
    $mapperStore.semanticFields.map((f) => [f.id, f.name])
  );

  const statusClass = (status: string) =>
    status === "complete" ? "status-complete" : status === "connected" ? "status-connected" : "status-unconnected";
</script>

<div class="panel">
  <h2>component mapper</h2>
  <p>connect gis semantic fields to prisma component levels.</p>

  <div class="section">
    <h3>view mode</h3>
    <div class="toggle-row">
      <button
        type="button"
        class="toggle-btn"
        class:active={$mapperStore.ui.componentViewMode === "hierarchical"}
        on:click={() => setComponentViewMode("hierarchical")}
      >
        hierarchical
      </button>
      <button
        type="button"
        class="toggle-btn"
        class:active={$mapperStore.ui.componentViewMode === "flat"}
        on:click={() => setComponentViewMode("flat")}
      >
        flat
      </button>
    </div>
    <p class="helper">
      {#if $mapperStore.ui.componentViewMode === "hierarchical"}
        top-level components with nested hierarchy; connect to parent or child
      {:else}
        leaf components only; connect directly to granular (Lighting, Equipment, FlatRoofAssembly, etc.)
      {/if}
    </p>

    {#if $mapperStore.ui.componentViewMode === "flat"}
      <h3 class="canvas-label">canvas</h3>
      <div class="canvas-tabs">
        <button
          type="button"
          class="canvas-tab"
          class:active={$mapperStore.ui.componentCanvas === "envelope"}
          on:click={() => setComponentCanvas("envelope")}
        >
          envelope
        </button>
        <button
          type="button"
          class="canvas-tab"
          class:active={$mapperStore.ui.componentCanvas === "spaceuse"}
          on:click={() => setComponentCanvas("spaceuse")}
        >
          space use
        </button>
        <button
          type="button"
          class="canvas-tab"
          class:active={$mapperStore.ui.componentCanvas === "hvac"}
          on:click={() => setComponentCanvas("hvac")}
        >
          hvac
        </button>
        <button
          type="button"
          class="canvas-tab"
          class:active={$mapperStore.ui.componentCanvas === "dhw"}
          on:click={() => setComponentCanvas("dhw")}
        >
          dhw
        </button>
      </div>
    {/if}
  </div>

  <div class="section">
    <h3>semantic fields</h3>
    <div class="field-list">
      {#each baseFields as field}
        <div class="field-row">
          <span class="dot" style={`background:${field.color}`}></span>
          <div>
            <div class="field-name">{field.name}</div>
            <div class="field-meta">
              {field.type}
              {field.options?.length ? ` · ${field.options.length} options` : ""}
            </div>
          </div>
        </div>
      {/each}
    </div>

    {#if derivedFields.length}
      <div class="divider"></div>
      <div class="field-subtitle">derived fields</div>
      <div class="field-list">
        {#each derivedFields as field}
          <div class="field-row">
            <span class="dot" style={`background:${field.color}`}></span>
            <div>
              <div class="field-name">{field.name}</div>
              <div class="field-meta">
                {#if field.compoundDerived}
                  compound ({field.compoundDerived.logic})
                {:else if field.derivedType === "numeric_range"}
                  numeric range
                {:else}
                  categorical mapping
                {/if}
              </div>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <div class="section">
    <h3>create derived field</h3>
    <label class="label" for="derived-name">derived field name</label>
    <input id="derived-name" type="text" bind:value={derivedName} />

    <label class="label" for="derived-type">derived field type</label>
    <select id="derived-type" bind:value={derivedType}>
      <option value="numeric_range">numeric range mapping</option>
      <option value="categorical_mapping">categorical mapping</option>
    </select>

    <label class="label" for="source-field">source field</label>
    <select id="source-field" bind:value={sourceFieldId}>
      {#each availableSourceFields as field}
        <option value={field.id}>
          {field.name} ({field.type})
        </option>
      {/each}
    </select>

    {#if !availableSourceFields.length}
      <div class="helper">no compatible source fields available</div>
    {/if}

    {#if derivedType === "numeric_range"}
      <div class="helper">define ranges (inclusive) and labels</div>
      <div class="range-list">
        {#each rangeRows as row, index}
          <div class="range-row">
            <input
              type="number"
              value={row.min}
              on:input={(event) =>
                updateRangeRow(index, "min", event.currentTarget.value)}
              placeholder="min"
            />
            <input
              type="number"
              value={row.max}
              on:input={(event) =>
                updateRangeRow(index, "max", event.currentTarget.value)}
              placeholder="max"
            />
            <input
              type="text"
              value={row.label}
              on:input={(event) =>
                updateRangeRow(index, "label", event.currentTarget.value)}
              placeholder="label"
            />
            <button type="button" class="icon" on:click={() => removeRangeRow(index)}>
              remove
            </button>
          </div>
        {/each}
      </div>
      <button type="button" class="secondary" on:click={addRangeRow}>add range</button>
    {:else}
      <div class="helper">map each value to a group name</div>
      <div class="group-list">
        {#each Object.entries(groupMap) as [value, group]}
          <div class="group-row">
            <span class="group-value">{value}</span>
            <input
              type="text"
              value={group}
              on:input={(event) =>
                updateGroupMap(value, event.currentTarget.value)}
            />
          </div>
        {/each}
      </div>
    {/if}

    <button
      type="button"
      disabled={!availableSourceFields.length}
      on:click={submitDerivedField}
    >
      create derived field
    </button>
  </div>

  <div class="section">
    <h3>create compound (and/or) derived field</h3>
    <p class="helper">combine multiple semantic fields: and = cartesian product, or = union of options</p>
    <label class="label" for="compound-name">derived field name</label>
    <input id="compound-name" type="text" bind:value={compoundName} placeholder="e.g. Typology_Age" />

    <label class="label" for="compound-logic">logic</label>
    <select id="compound-logic" bind:value={compoundLogic}>
      <option value="and">and (cartesian product)</option>
      <option value="or">or (union of options)</option>
    </select>

    <span class="label">source fields (select 2+)</span>
    <div class="checkbox-list">
      {#each compoundCategoricalFields as field}
        <label class="checkbox">
          <input
            type="checkbox"
            checked={compoundSourceIds.includes(field.id)}
            on:change={() => toggleCompoundSource(field.id)}
          />
          <span class="field-dot" style="background:{field.color}"></span>
          <span>{field.name} ({field.options?.length ?? 0})</span>
        </label>
      {/each}
    </div>
    {#if compoundSourceIds.length > 0}
      <div class="helper">{compoundSourceIds.length} selected</div>
    {/if}

    <button
      type="button"
      disabled={compoundSourceIds.length < 2 || !compoundName.trim()}
      on:click={submitCompoundDerivedField}
    >
      create compound field
    </button>
  </div>

  <div class="section">
    <h3>components & connections</h3>
    <p class="helper">which components exist, their linked fields, and status (unconnected / connected / complete)</p>
    <div class="component-list">
      {#each componentsWithLinks as level}
        {@const status = calculateComponentStatus(level.path, $mapperStore)}
        {@const linkedIds = $mapperStore.componentLinks[level.path] ?? []}
        <div class="component-row" style="padding-left: {8 + level.depth * 12}px">
          <span class="status-dot {statusClass(status)}" title={status}></span>
          <div class="component-info">
            <div class="component-name">{level.displayName}</div>
            <div class="component-path">{level.path}</div>
            {#if linkedIds.length > 0}
              <div class="linked-fields">
                {linkedIds.map((id) => fieldIdToName[id] ?? id).join(", ")}
              </div>
            {:else}
              <div class="linked-fields empty">no fields linked</div>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  </div>

  <div class="section hint">
    <h3>linking</h3>
    <p class="helper">drag from a semantic field node (top) to a component node (bottom) to connect. delete key removes selected edges.</p>
  </div>
</div>

<style>
  .panel {
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  h2 {
    margin: 0 0 4px;
  }

  p {
    margin: 0;
    color: #6b7280;
    font-size: 13px;
  }

  h3 {
    margin: 0 0 8px;
    font-size: 14px;
  }

  .section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .toggle-row {
    display: flex;
    gap: 8px;
  }

  .toggle-btn {
    flex: 1;
    padding: 8px 12px;
    border-radius: 6px;
    border: 1px solid #d1d5db;
    background: #ffffff;
    font-size: 12px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .toggle-btn:hover {
    background: #f9fafb;
  }

  .toggle-btn.active {
    background: #eff6ff;
    border-color: #3b82f6;
    font-weight: 600;
  }

  .canvas-label {
    margin: 12px 0 4px;
    font-size: 12px;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .canvas-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .canvas-tab {
    padding: 6px 12px;
    border-radius: 6px;
    border: 1px solid #d1d5db;
    background: #ffffff;
    font-size: 11px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .canvas-tab:hover {
    background: #f9fafb;
  }

  .canvas-tab.active {
    background: #f0fdf4;
    border-color: #22c55e;
    font-weight: 600;
  }

  .field-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .field-row {
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }

  .field-name {
    font-size: 13px;
    font-weight: 600;
  }

  .field-meta {
    font-size: 11px;
    color: #6b7280;
  }

  .field-subtitle {
    font-size: 12px;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
    margin-top: 4px;
  }

  .divider {
    height: 1px;
    background: #e5e7eb;
    margin: 4px 0;
  }

  .label {
    font-size: 12px;
    color: #6b7280;
  }

  input,
  select {
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 12px;
    width: 100%;
  }

  button {
    display: block;
    width: 100%;
    padding: 8px 10px;
    border-radius: 6px;
    border: 1px solid #d1d5db;
    background: #f9fafb;
    cursor: pointer;
    text-align: center;
    font-size: 12px;
  }

  .secondary {
    background: #ffffff;
  }

  .icon {
    width: auto;
    padding: 6px 8px;
    font-size: 11px;
  }

  .helper {
    font-size: 11px;
    color: #6b7280;
  }

  .range-list,
  .group-list,
  .checkbox-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .range-row,
  .group-row {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr auto;
    gap: 6px;
    align-items: center;
  }

  .group-row {
    grid-template-columns: 1.5fr 1fr;
  }

  .group-value {
    font-size: 12px;
    color: #111827;
  }

  .checkbox {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 12px;
    color: #374151;
  }

  .field-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
  }

  .component-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-height: 280px;
    overflow-y: auto;
  }

  .component-row {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    padding: 6px 8px;
    background: #f9fafb;
    border-radius: 6px;
    border: 1px solid #e5e7eb;
  }

  .status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
    margin-top: 4px;
  }

  .status-unconnected {
    background: #f97316;
  }

  .status-connected,
  .status-complete {
    background: #22c55e;
  }

  .component-info {
    flex: 1;
    min-width: 0;
  }

  .component-name {
    font-size: 13px;
    font-weight: 600;
  }

  .component-path {
    font-size: 10px;
    color: #9ca3af;
    font-family: monospace;
  }

  .linked-fields {
    font-size: 11px;
    color: #6b7280;
    margin-top: 2px;
  }

  .linked-fields.empty {
    font-style: italic;
  }
</style>
