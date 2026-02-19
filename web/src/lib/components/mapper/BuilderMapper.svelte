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
  import { mapperStore, addComponentLink, removeComponentLink } from "$lib/stores/mapperStore";
  import SemanticFieldInputNode from "$lib/components/mapper/SemanticFieldInputNode.svelte";
  import ComponentBuilderNode from "$lib/components/mapper/ComponentBuilderNode.svelte";
  import BuildingOutputNode from "$lib/components/mapper/BuildingOutputNode.svelte";
  import BuilderValuePanel from "$lib/components/mapper/BuilderValuePanel.svelte";

  const nodeTypes = {
    semanticFieldInput: SemanticFieldInputNode,
    componentBuilder: ComponentBuilderNode,
    buildingOutput: BuildingOutputNode
  };

  let selectedComponentPath: string | null = null;

  const fieldInputX = 100;
  const componentX = 500;
  const outputX = 900;
  const nodeSpacing = 100;

  $: fieldInputNodes = $mapperStore.semanticFields.map((field, index) => ({
    id: field.id,
    type: "semanticFieldInput",
    position: { x: fieldInputX, y: 80 + index * nodeSpacing },
    data: {
      fieldName: field.name,
      fieldType: field.type,
      options: field.options,
      color: field.color,
      isDerived: field.isDerived
    },
    sourcePosition: Position.Right
  }));

  $: componentNodes = $mapperStore.componentLevels.map((component, index) => {
    const distributions = $mapperStore.componentDistributions[component.path] ?? [];
    return {
      id: component.path,
      type: "componentBuilder",
      position: { x: componentX, y: 80 + index * nodeSpacing },
      data: {
        path: component.path,
        displayName: component.displayName,
        description: component.description,
        color: component.color,
        linkedFields: $mapperStore.componentLinks[component.path] ?? [],
        distributionCount: distributions.length,
        isSelected: component.path === selectedComponentPath
      },
      targetPosition: Position.Left,
      sourcePosition: Position.Right
    };
  });

  $: outputNode = {
    id: "building_output",
    type: "buildingOutput",
    position: { x: outputX, y: 200 },
    data: {
      componentLinks: $mapperStore.componentLinks
    },
    targetPosition: Position.Left
  };

  $: nodes = [
    ...fieldInputNodes,
    ...componentNodes,
    outputNode
  ];

  $: edges = Object.entries($mapperStore.componentLinks).flatMap(
    ([componentPath, fieldIds]) => {
      const component = $mapperStore.componentLevels.find((c) => c.path === componentPath);
      return fieldIds.map((fieldId) => {
        const field = $mapperStore.semanticFields.find((f) => f.id === fieldId);
        const color = field?.color ?? "#64748b";
        return {
          id: `edge_${fieldId}_${componentPath}`,
          source: fieldId,
          target: componentPath,
          animated: false,
          style: `stroke: ${color}; stroke-width: 2px;`
        };
      });
    }
  );

  const isFieldNode = (nodeId: string) => nodeId.startsWith("field_");
  const isComponentNode = (nodeId: string) =>
    $mapperStore.componentLevels.some((c) => c.path === nodeId);
  const isOutputNode = (nodeId: string) => nodeId === "building_output";

  const handleConnect = (connection: Connection) => {
    if (!connection.source || !connection.target) {
      return;
    }
    if (isFieldNode(connection.source) && isComponentNode(connection.target)) {
      addComponentLink(connection.target, connection.source);
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
      if (isFieldNode(edge.source) && isComponentNode(edge.target)) {
        removeComponentLink(edge.target, edge.source);
      }
    });
  };

  const handleNodeClick = (event: CustomEvent<{ node: Node }>) => {
    const node = event.detail.node;
    if (node && isComponentNode(node.id)) {
      selectedComponentPath = node.id;
    } else {
      selectedComponentPath = null;
    }
  };

  const handlePaneClick = () => {
    selectedComponentPath = null;
  };
</script>

<div class="builder-layout">
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
        on:paneClick={handlePaneClick}
      >
        <Background gap={24} />
        <Controls position="bottom-right" />
        <MiniMap position="bottom-left" />
      </SvelteFlow>
    {:else}
      <div class="loading">Loading canvas...</div>
    {/if}
  </div>
  <BuilderValuePanel {selectedComponentPath} />
</div>

<style>
  .builder-layout {
    display: flex;
    height: calc(100vh - 160px);
    gap: 0;
  }

  .canvas {
    flex: 1;
    border: 1px solid #e2e2e2;
    border-radius: 12px 0 0 12px;
    background: #ffffff;
    overflow: hidden;
  }

  :global(.svelte-flow__background) {
    background-color: #ffffff;
  }

  :global(.svelte-flow__controls) {
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(226, 232, 240, 0.8);
    border-radius: 12px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    padding: 4px;
  }

  :global(.svelte-flow__controls button) {
    background: transparent;
    border: none;
    color: #64748b;
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
    background: rgba(59, 130, 246, 0.1);
    color: #2563eb;
  }

  :global(.svelte-flow__controls button:active) {
    background: rgba(59, 130, 246, 0.2);
    transform: scale(0.95);
  }

  :global(.svelte-flow__controls svg) {
    width: 16px;
    height: 16px;
  }

  :global(.svelte-flow__minimap) {
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(226, 232, 240, 0.8);
    border-radius: 12px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    overflow: hidden;
  }

  :global(.svelte-flow__minimap-mask) {
    fill: rgba(59, 130, 246, 0.15);
    stroke: #3b82f6;
    stroke-width: 2;
  }

  :global(.svelte-flow__minimap-node) {
    fill: #e2e8f0;
    stroke: #cbd5e1;
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
