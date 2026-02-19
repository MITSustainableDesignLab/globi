<script lang="ts">
  import { browser } from "$app/environment";
  import {
    Background,
    Controls,
    MiniMap,
    Position,
    SvelteFlow,
    type Connection,
    type Edge,
    type EdgeChange,
    type Node
  } from "@xyflow/svelte";
  import type {
    ArchetypeIcon,
    ArchetypeState
  } from "$lib/stores/archetypeStore";
  import {
    addArchetype,
    addArchetypeLink,
    archetypeStore,
    removeArchetypeLink,
    selectArchetype,
    updateArchetypeIcon,
    updateArchetypeDistribution
  } from "$lib/stores/archetypeStore";
  import SemanticFieldNode from "$lib/components/mapper/SemanticFieldNode.svelte";
  import ArchetypeNode from "$lib/components/mapper/ArchetypeNode.svelte";
  import ArchetypeWizard from "$lib/components/mapper/ArchetypeWizard.svelte";

  const nodeTypes = {
    semanticField: SemanticFieldNode,
    archetype: ArchetypeNode
  };

  let newArchetypeName = "";
  let newArchetypeIcon: ArchetypeIcon = "building";
  let showDetails = false;
  let showFloatingPanel = true;
  let showWizard = false;

  const fieldRowY = 40;
  const fieldColumnGap = 220;
  const archetypeRowY = 520;
  const archetypeColumnGap = 260;

  const buildFieldNodes = (state: ArchetypeState): Node[] =>
    state.semanticFields.map((field, index) => ({
      id: field.id,
      type: "semanticField",
      position: { x: 80 + index * fieldColumnGap, y: fieldRowY },
      data: {
        fieldName: field.name,
        fieldType: field.type,
        optionCount: field.options?.length ?? 0,
        color: field.color,
        isDerived: field.isDerived
      },
      sourcePosition: Position.Bottom
    }));

  const buildArchetypeNodes = (state: ArchetypeState): Node[] =>
    state.archetypes.map((archetype, index) => ({
      id: archetype.id,
      type: "archetype",
      position: { x: 120 + index * archetypeColumnGap, y: archetypeRowY },
      data: {
        name: archetype.name,
        icon: archetype.icon,
        linkedFields: state.links[archetype.id]?.length ?? 0
      },
      targetPosition: Position.Top
    }));

  const buildEdges = (state: ArchetypeState): Edge[] =>
    Object.entries(state.links).flatMap(([archetypeId, fieldIds]) =>
      fieldIds.map((fieldId) => ({
        id: `edge_${fieldId}_${archetypeId}`,
        source: fieldId,
        target: archetypeId,
        animated: false,
        style: { stroke: "#64748b", strokeWidth: 2 }
      }))
    );

  $: nodes = [...buildFieldNodes($archetypeStore), ...buildArchetypeNodes($archetypeStore)];
  $: edges = buildEdges($archetypeStore);

  const isFieldNode = (nodeId: string) => nodeId.startsWith("field_");
  const isArchetypeNode = (nodeId: string) => nodeId.startsWith("archetype_");

  const handleConnect = (connection: Connection) => {
    if (!connection.source || !connection.target) {
      return;
    }
    const sourceIsField = isFieldNode(connection.source);
    const targetIsField = isFieldNode(connection.target);
    const sourceIsArchetype = isArchetypeNode(connection.source);
    const targetIsArchetype = isArchetypeNode(connection.target);
    if (sourceIsField && targetIsArchetype) {
      addArchetypeLink(connection.target, connection.source);
      return;
    }
    if (targetIsField && sourceIsArchetype) {
      addArchetypeLink(connection.source, connection.target);
    }
  };

  const handleEdgesChange = (changes: EdgeChange[]) => {
    changes.forEach((change) => {
      if (change.type !== "remove") {
        return;
      }
      const edge = edges.find((existing) => existing.id === change.id);
      if (!edge) {
        return;
      }
      if (isFieldNode(edge.source) && isArchetypeNode(edge.target)) {
        removeArchetypeLink(edge.target, edge.source);
      }
      if (isFieldNode(edge.target) && isArchetypeNode(edge.source)) {
        removeArchetypeLink(edge.source, edge.target);
      }
    });
  };

  const handleNodeClick = (event: CustomEvent<{ node: Node }>) => {
    const node = event.detail.node;
    if (node?.type === "archetype") {
      selectArchetype(node.id);
    }
  };

  const selectedArchetype =
    $archetypeStore.archetypes.find(
      (archetype) => archetype.id === $archetypeStore.selectedArchetypeId
    ) ?? null;

  const addNewArchetype = () => {
    addArchetype(newArchetypeName, newArchetypeIcon);
    newArchetypeName = "";
  };
</script>

<div class="canvas">
  {#if browser}
    <SvelteFlow
      {nodes}
      {edges}
      {nodeTypes}
      fitView
      deleteKeyCode={["Backspace", "Delete"]}
      on:connect={(event) => handleConnect(event.detail)}
      on:edgesChange={(event) => handleEdgesChange(event.detail)}
      on:nodeClick={handleNodeClick}
    >
      <Background gap={24} />
      <Controls position="bottom-right" />
      <MiniMap position="bottom-left" />
    </SvelteFlow>
  {:else}
    <div class="loading">Loading canvas...</div>
  {/if}

  {#if !showFloatingPanel}
    <button type="button" class="show-panel-btn" on:click={() => (showFloatingPanel = true)}>
      show controls
    </button>
  {/if}

  {#if showFloatingPanel}
    <div class="floating">
      <div class="floating-header">
        <div>
          <div class="title">archetype mapper</div>
          <div class="subtitle">add archetypes and link fields</div>
        </div>
        <div class="header-actions">
          <button type="button" class="ghost" on:click={() => (showWizard = true)}>
            create archetype
          </button>
          <button type="button" class="ghost" on:click={() => (showDetails = true)}>
            edit distributions
          </button>
          <button type="button" class="ghost" on:click={() => (showFloatingPanel = false)}>
            hide
          </button>
        </div>
      </div>
    <div class="floating-body">
      <input
        type="text"
        placeholder="archetype name"
        bind:value={newArchetypeName}
      />
      <div class="row">
        <select bind:value={newArchetypeIcon}>
          <option value="building">building</option>
          <option value="tower">tower</option>
          <option value="warehouse">warehouse</option>
        </select>
        <button type="button" on:click={addNewArchetype}>add archetype</button>
      </div>
      <div class="row">
        <select bind:value={$archetypeStore.selectedArchetypeId}>
          {#each $archetypeStore.archetypes as archetype}
            <option value={archetype.id}>{archetype.name}</option>
          {/each}
        </select>
        <select
          value={selectedArchetype?.icon ?? "building"}
          on:change={(event) =>
            selectedArchetype &&
            updateArchetypeIcon(
              selectedArchetype.id,
              event.currentTarget.value as ArchetypeIcon
            )}
        >
          <option value="building">building</option>
          <option value="tower">tower</option>
          <option value="warehouse">warehouse</option>
        </select>
      </div>
    </div>
  </div>
  {/if}
</div>

{#if showDetails && selectedArchetype}
  <div class="modal">
    <div class="modal-card">
      <div class="modal-header">
        <div>
          <div class="title">component distributions</div>
          <div class="subtitle">{selectedArchetype.name}</div>
        </div>
        <button type="button" class="ghost" on:click={() => (showDetails = false)}>
          close
        </button>
      </div>
      <div class="distribution-list">
        {#each $archetypeStore.componentPaths as componentPath}
          <div class="distribution-row">
            <div class="component-label">{componentPath}</div>
            <div class="range-inputs">
              <input
                type="number"
                placeholder="min"
                value={selectedArchetype.distributions[componentPath]?.min ?? 0}
                on:input={(event) =>
                  updateArchetypeDistribution(
                    selectedArchetype.id,
                    componentPath,
                    { min: Number(event.currentTarget.value) }
                  )}
              />
              <input
                type="number"
                placeholder="max"
                value={selectedArchetype.distributions[componentPath]?.max ?? 0}
                on:input={(event) =>
                  updateArchetypeDistribution(
                    selectedArchetype.id,
                    componentPath,
                    { max: Number(event.currentTarget.value) }
                  )}
              />
            </div>
          </div>
        {/each}
      </div>
    </div>
  </div>
{/if}

{#if showWizard}
  <ArchetypeWizard onClose={() => (showWizard = false)} />
{/if}

<style>
  .canvas {
    height: calc(100vh - 160px);
    border: 1px solid #334155;
    border-radius: 12px;
    background: #0f172a;
    position: relative;
  }

  :global(.svelte-flow__background) {
    background-color: #0f172a;
  }

  :global(.svelte-flow__controls) {
    background: rgba(30, 41, 59, 0.95);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(51, 65, 85, 0.5);
    border-radius: 12px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    padding: 4px;
  }

  :global(.svelte-flow__controls button) {
    background: transparent;
    border: none;
    color: #cbd5e1;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s ease;
    margin: 2px;
  }

  :global(.svelte-flow__controls button:hover) {
    background: rgba(59, 130, 246, 0.15);
    color: #60a5fa;
  }

  :global(.svelte-flow__controls button:active) {
    background: rgba(59, 130, 246, 0.25);
    transform: scale(0.95);
  }

  :global(.svelte-flow__controls svg) {
    width: 16px;
    height: 16px;
  }

  :global(.svelte-flow__minimap) {
    background: rgba(30, 41, 59, 0.95);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(51, 65, 85, 0.5);
    border-radius: 12px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    overflow: hidden;
  }

  :global(.svelte-flow__minimap-mask) {
    fill: rgba(59, 130, 246, 0.2);
    stroke: #3b82f6;
    stroke-width: 2;
  }

  :global(.svelte-flow__minimap-node) {
    fill: #334155;
    stroke: #475569;
  }

  .floating {
    position: absolute;
    top: 16px;
    left: 16px;
    width: 320px;
    background: #ffffff;
    border: 1px solid #e2e2e2;
    border-radius: 12px;
    padding: 12px;
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.1);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .floating-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }

  .header-actions {
    display: flex;
    gap: 6px;
  }

  .show-panel-btn {
    position: absolute;
    top: 16px;
    left: 16px;
    padding: 8px 12px;
    border: 1px solid #d8d8d8;
    border-radius: 6px;
    background: white;
    color: #1c1c1c;
    cursor: pointer;
    font-size: 12px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  }

  .show-panel-btn:hover {
    background: #f3f3f3;
    border-color: #cbd5e1;
  }

  .floating-body {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .title {
    font-weight: 600;
    font-size: 13px;
    color: #1c1c1c;
  }

  .subtitle {
    font-size: 11px;
    color: #6b7280;
  }

  .row {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 6px;
    align-items: center;
  }

  input,
  select {
    border: 1px solid #d8d8d8;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 12px;
    width: 100%;
    background: white;
    color: #1c1c1c;
  }

  input:focus,
  select:focus {
    outline: none;
    border-color: #3b82f6;
  }

  button {
    display: block;
    width: 100%;
    padding: 8px 10px;
    border-radius: 6px;
    border: 1px solid #d8d8d8;
    background: white;
    color: #1c1c1c;
    cursor: pointer;
    text-align: center;
    font-size: 12px;
  }

  button:hover {
    background: #f3f3f3;
    border-color: #cbd5e1;
  }

  .ghost {
    background: transparent;
  }

  .distribution-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .distribution-row {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-bottom: 8px;
    border-bottom: 1px solid #f3f4f6;
  }

  .component-label {
    font-size: 11px;
    color: #4b5563;
  }

  .range-inputs {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }

  .modal {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: grid;
    place-items: center;
    z-index: 20;
  }

  .modal-card {
    background: #ffffff;
    border: 1px solid #e2e2e2;
    border-radius: 12px;
    padding: 16px;
    width: min(720px, 90vw);
    max-height: 80vh;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
  }

  .loading {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #64748b;
    font-size: 14px;
  }

  :global(.svelte-flow__edge-path) {
    stroke-width: 2;
    transition: stroke-width 0.2s ease;
  }

  :global(.svelte-flow__edge:hover .svelte-flow__edge-path) {
    stroke-width: 3;
  }

  :global(.svelte-flow__edge.selected .svelte-flow__edge-path) {
    stroke-width: 3;
    filter: drop-shadow(0 0 4px currentColor);
  }

  :global(.svelte-flow__connectionline) {
    stroke: #3b82f6;
    stroke-width: 2;
    stroke-dasharray: 5 5;
    opacity: 0.8;
  }

  :global(.svelte-flow__handle) {
    width: 8px;
    height: 8px;
    background: #3b82f6;
    border: 2px solid #ffffff;
    border-radius: 50%;
    transition: all 0.2s ease;
  }

  :global(.svelte-flow__handle:hover) {
    width: 12px;
    height: 12px;
    background: #2563eb;
    box-shadow: 0 0 8px rgba(59, 130, 246, 0.4);
  }

  :global(.svelte-flow__handle.connecting) {
    background: #22c55e;
    box-shadow: 0 0 12px rgba(34, 197, 94, 0.6);
  }
</style>
