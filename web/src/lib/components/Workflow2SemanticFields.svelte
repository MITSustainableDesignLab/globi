<script lang="ts">
  import { sampleFields, type GisField } from "$lib/data/sampleGis";

  let fields: GisField[] = sampleFields.map((field) => ({ ...field }));
  let derivedName = "";
  let derivedType: "numeric range mapping" | "categorical mapping" =
    "categorical mapping";
  let sourceColumn = "";
  let mapping: Record<string, string> = {};
  let ranges = [{ min: 0, max: 0, label: "range_1" }];

  $: enabledFields = fields.filter((field) => field.enabled);
  $: numericOptions = enabledFields.filter((field) => field.type === "numeric");
  $: categoricalOptions = enabledFields.filter(
    (field) => field.type === "categorical"
  );

  $: if (derivedType === "numeric range mapping") {
    if (!numericOptions.find((field) => field.name === sourceColumn)) {
      sourceColumn = numericOptions[0]?.name ?? "";
    }
  } else {
    if (!categoricalOptions.find((field) => field.name === sourceColumn)) {
      sourceColumn = categoricalOptions[0]?.name ?? "";
    }
  }

  $: if (derivedType === "categorical mapping" && sourceColumn) {
    const field = fields.find((f) => f.name === sourceColumn);
    if (field) {
      const nextMapping: Record<string, string> = {};
      field.values.forEach((value) => {
        nextMapping[value] = mapping[value] ?? value;
      });
      mapping = nextMapping;
    }
  }

  const addRange = () => {
    ranges = [...ranges, { min: 0, max: 0, label: `range_${ranges.length + 1}` }];
  };

  const onSubmit = () => {
    if (!derivedName.trim()) {
      alert("enter a derived field name");
      return;
    }
    if (!sourceColumn) {
      alert("select a source column");
      return;
    }
    alert("derived field saved (frontend only)");
  };
</script>

<section class="content">
  <h1>workflow 2: data-first</h1>
  <h2>step 2: semantic fields from gis data</h2>
  <p>review all gis fields and their types. select the fields to use for derived fields.</p>

  <table class="fields-table">
    <thead>
      <tr>
        <th>use</th>
        <th>field</th>
        <th>type</th>
        <th>unique values</th>
      </tr>
    </thead>
    <tbody>
      {#each fields as field}
        <tr>
          <td>
            <input type="checkbox" bind:checked={field.enabled} />
          </td>
          <td>{field.name}</td>
          <td>{field.type}</td>
          <td>{field.values.length}</td>
        </tr>
      {/each}
    </tbody>
  </table>

  <hr />

  <h2>create derived semantic field</h2>
  <div class="form-row">
    <label for="derived-name">derived field name</label>
    <input id="derived-name" type="text" bind:value={derivedName} />
  </div>
  <div class="form-row">
    <label for="derived-type">derived field type</label>
    <select id="derived-type" bind:value={derivedType}>
      <option value="numeric range mapping">numeric range mapping</option>
      <option value="categorical mapping">categorical mapping</option>
    </select>
  </div>
  <div class="form-row">
    <label for="source-column">
      {derivedType === "numeric range mapping"
        ? "source column (numeric)"
        : "source column (categorical)"}
    </label>
    <select id="source-column" bind:value={sourceColumn}>
      {#if derivedType === "numeric range mapping"}
        {#each numericOptions as field}
          <option value={field.name}>{field.name}</option>
        {/each}
      {:else}
        {#each categoricalOptions as field}
          <option value={field.name}>{field.name}</option>
        {/each}
      {/if}
    </select>
  </div>

  {#if derivedType === "numeric range mapping"}
    <div class="ranges">
      <h3>define ranges</h3>
      <table class="ranges-table">
        <thead>
          <tr>
            <th>min</th>
            <th>max</th>
            <th>label</th>
          </tr>
        </thead>
        <tbody>
          {#each ranges as range, idx}
            <tr>
              <td><input type="number" bind:value={ranges[idx].min} /></td>
              <td><input type="number" bind:value={ranges[idx].max} /></td>
              <td><input type="text" bind:value={ranges[idx].label} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <button type="button" on:click={addRange}>add range</button>
    </div>
  {:else}
    <div class="groups">
      <h3>define groups</h3>
      <p>set the new group name for each unique value.</p>
      <table class="groups-table">
        <thead>
          <tr>
            <th>source value</th>
            <th>group</th>
          </tr>
        </thead>
        <tbody>
          {#if sourceColumn}
            {#each Object.entries(mapping) as [value, group]}
              <tr>
                <td>{value}</td>
                <td>
                  <input
                    type="text"
                    bind:value={mapping[value]}
                    placeholder="group name"
                  />
                </td>
              </tr>
            {/each}
          {/if}
        </tbody>
      </table>
    </div>
  {/if}

  <button class="primary" type="button" on:click={onSubmit}>create derived field</button>
</section>

<style>
  .content {
    padding: 24px 32px;
  }

  h1 {
    margin: 0 0 8px;
  }

  h2 {
    margin: 16px 0 8px;
  }

  .fields-table,
  .ranges-table,
  .groups-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
  }

  th,
  td {
    border: 1px solid #e2e2e2;
    padding: 8px;
    text-align: left;
  }

  .form-row {
    display: grid;
    grid-template-columns: 220px 1fr;
    gap: 12px;
    margin-bottom: 12px;
    align-items: center;
  }

  input,
  select {
    padding: 6px 8px;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
  }

  hr {
    border: none;
    border-top: 1px solid #e2e2e2;
    margin: 24px 0;
  }

  button {
    padding: 8px 12px;
    border: 1px solid #d0d0d0;
    border-radius: 6px;
    background: white;
    cursor: pointer;
    margin-top: 12px;
  }

  button.primary {
    background: #0f62fe;
    border-color: #0f62fe;
    color: white;
  }
</style>
