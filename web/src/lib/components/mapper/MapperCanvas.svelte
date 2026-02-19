<script lang="ts">
  import "@xyflow/svelte/dist/style.css";
  import { browser } from "$app/environment";
  import {
    Background,
    Controls,
    MiniMap,
    Position,
    SvelteFlow,
    ConnectionLineType,
    MarkerType,
    type Connection,
    type Edge,
    type Node
  } from "@xyflow/svelte";
  import {
    addComponentLink,
    mapperStore,
    removeComponentLink,
    setSelectedComponentPath
  } from "$lib/stores/mapperStore";
  import type { AppState } from "$lib/stores/mapperStore";
  import SemanticFieldNode from "$lib/components/mapper/SemanticFieldNode.svelte";
  import ComponentLevelNode from "$lib/components/mapper/ComponentLevelNode.svelte";
  import ComponentDistributionPanel from "$lib/components/mapper/ComponentDistributionPanel.svelte";
  import ComponentValueWizard from "$lib/components/mapper/ComponentValueWizard.svelte";
  import { calculateComponentStatus } from "$lib/utils/mapperStatus";
  import { COMPONENT_PARAMETERS } from "$lib/data/componentParameters";

  const nodeTypes = {
    semanticField: SemanticFieldNode,
    componentLevel: ComponentLevelNode
  };

  const defaultEdgeOptions = {
    type: "smoothstep",
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 15,
      height: 15,
      color: "#94a3b8"
    }
  };

  const fieldRowY = 30;
  const fieldColumnGap = 200;
  const componentRowGap = 140;
  const componentColumnGap = 240;

  // semantic fields always at top; components below, grouped by top-level (Envelope vs Operations)
  const getTopLevelPath = (path: string) => path.split(".")[0] ?? path;

  const buildFieldNodes = (state: AppState): Node[] =>
    state.semanticFields.map((field, index) => ({
      id: field.id,
      type: "semanticField",
      position: { x: 80 + index * fieldColumnGap, y: fieldRowY },
      data: {
        fieldName: field.name,
        fieldType: field.type,
        optionCount: field.options?.length ?? 0,
        options: field.options,
        color: field.color,
        isDerived: field.isDerived,
        compoundDerived: field.compoundDerived
      },
      sourcePosition: Position.Bottom
    }));

  // Check if a component or any ancestor has links
  const hasLinksOrAncestorHasLinks = (
    path: string,
    componentLinks: Record<string, string[]>
  ): boolean => {
    const parts = path.split(".");
    for (let i = 1; i <= parts.length; i++) {
      const ancestorPath = parts.slice(0, i).join(".");
      const links = componentLinks[ancestorPath] ?? [];
      if (links.length > 0) return true;
    }
    return false;
  };

  // Get direct parent path
  const getParentPath = (path: string): string | null => {
    const parts = path.split(".");
    if (parts.length <= 1) return null;
    return parts.slice(0, -1).join(".");
  };

  // Check if component should be visible
  const isComponentVisible = (
    path: string,
    componentLinks: Record<string, string[]>,
    expandedComponents: Set<string>
  ): boolean => {
    const parentPath = getParentPath(path);
    if (!parentPath) return true; // Top-level components always visible

    const parentLinks = componentLinks[parentPath] ?? [];

    // If parent has links, children are hidden unless explicitly expanded
    if (parentLinks.length > 0) {
      return expandedComponents.has(parentPath);
    }

    // Recursively check grandparents
    return isComponentVisible(parentPath, componentLinks, expandedComponents);
  };

  // Check if component has children
  const hasChildren = (path: string, componentLevels: typeof $mapperStore.componentLevels): boolean => {
    return componentLevels.some(c => c.path.startsWith(path + "."));
  };

  // Count hidden children
  const countHiddenChildren = (
    path: string,
    componentLevels: typeof $mapperStore.componentLevels,
    componentLinks: Record<string, string[]>,
    expandedComponents: Set<string>
  ): number => {
    return componentLevels.filter(c =>
      c.path.startsWith(path + ".") &&
      !isComponentVisible(c.path, componentLinks, expandedComponents)
    ).length;
  };

  const leafPaths = new Set(Object.keys(COMPONENT_PARAMETERS));

  const canvasPathPrefix: Record<string, string> = {
    envelope: "Envelope",
    spaceuse: "Operations.SpaceUse",
    hvac: "Operations.HVAC",
    dhw: "Operations.DHW"
  };

  const buildComponentNodes = (state: AppState): Node[] => {
    const isFlat = state.ui.componentViewMode === "flat";

    let visibleLevels = isFlat
      ? state.componentLevels.filter((level) => leafPaths.has(level.path))
      : state.componentLevels.filter((level) =>
          isComponentVisible(level.path, state.componentLinks, state.expandedComponents)
        );

    if (isFlat) {
      const prefix = canvasPathPrefix[state.ui.componentCanvas] ?? "Envelope";
      visibleLevels = visibleLevels.filter((l) => l.path.startsWith(prefix));
    }

    const envelopeLevels = visibleLevels.filter((l) => getTopLevelPath(l.path) === "Envelope");
    const opsLevels = visibleLevels.filter((l) => getTopLevelPath(l.path) === "Operations");

    const envelopeStartX = 80;

    const placeNode = (
      level: (typeof state.componentLevels)[0],
      colIndex: number,
      rowIndex: number,
      startX: number
    ) => {
      const distributions = state.componentDistributions[level.path] ?? [];
      const status = calculateComponentStatus(level.path, state);
      const childCount = isFlat ? false : hasChildren(level.path, state.componentLevels);
      const hiddenCount = isFlat
        ? 0
        : countHiddenChildren(
            level.path,
            state.componentLevels,
            state.componentLinks,
            state.expandedComponents
          );
      const isExpanded = state.expandedComponents.has(level.path);
      const linkedFields = state.componentLinks[level.path] ?? [];

      return {
        id: level.id,
        type: "componentLevel",
        position: {
          x: startX + colIndex * componentColumnGap,
          y: fieldRowY + 180 + rowIndex * componentRowGap
        },
        data: {
          path: level.path,
          displayName: level.displayName,
          description: level.description,
          linkedFields,
          color: level.color,
          status,
          distributionCount: distributions.length,
          hasChildren: childCount,
          hiddenChildCount: hiddenCount,
          isExpanded,
          canExpand: !isFlat && linkedFields.length > 0 && childCount
        },
        targetPosition: Position.Top
      };
    };

    const result: Node[] = [];

    if (isFlat) {
      // flat: single canvas; one row of components
      const flatColGap = 180;
      const flatLevels = envelopeLevels.length > 0 ? envelopeLevels : opsLevels;
      flatLevels.forEach((l, i) =>
        result.push(placeNode(l, i, 0, envelopeStartX))
      );
    } else {
      const envByDepth = new Map<number, (typeof state.componentLevels)[0][]>();
      envelopeLevels.forEach((l) => {
        const list = envByDepth.get(l.depth) ?? [];
        list.push(l);
        envByDepth.set(l.depth, list);
      });
      const opsByDepth = new Map<number, (typeof state.componentLevels)[0][]>();
      opsLevels.forEach((l) => {
        const list = opsByDepth.get(l.depth) ?? [];
        list.push(l);
        opsByDepth.set(l.depth, list);
      });

      const maxEnvelopeCols = Math.max(
        ...Array.from(envByDepth.values()).map((arr) => arr.length),
        1
      );
      const opsStartX = envelopeStartX + maxEnvelopeCols * componentColumnGap + 100;

      let rowIdx = 0;
      const depths = Array.from(
        new Set([...envByDepth.keys(), ...opsByDepth.keys()])
      ).sort((a, b) => a - b);

      for (const d of depths) {
        const envRow = envByDepth.get(d) ?? [];
        const opsRow = opsByDepth.get(d) ?? [];
        envRow.forEach((l, i) =>
          result.push(placeNode(l, i, rowIdx, envelopeStartX))
        );
        opsRow.forEach((l, i) =>
          result.push(placeNode(l, i, rowIdx, opsStartX))
        );
        rowIdx += 1;
      }
    }

    return result;
  };

  const buildEdges = (state: AppState): Edge[] => {
    const isFlat = state.ui.componentViewMode === "flat";
    const prefix = canvasPathPrefix[state.ui.componentCanvas] ?? "Envelope";
    const visiblePaths = isFlat
      ? new Set(Array.from(leafPaths).filter((p) => p.startsWith(prefix)))
      : new Set(
          state.componentLevels
            .filter((level) =>
              isComponentVisible(level.path, state.componentLinks, state.expandedComponents)
            )
            .map((level) => level.path)
        );

    const componentIdByPath = new Map(
      state.componentLevels.map((level) => [level.path, level.id])
    );
    const fieldColorById = new Map(
      state.semanticFields.map((field) => [field.id, field.color])
    );

    return Object.entries(state.componentLinks).flatMap(
      ([componentPath, fieldIds]) => {
        // Skip edges to hidden components
        if (!visiblePaths.has(componentPath)) {
          return [];
        }

        const targetId = componentIdByPath.get(componentPath);
        if (!targetId) {
          return [];
        }
        return fieldIds.map((fieldId) => {
          const color = fieldColorById.get(fieldId) ?? "#94a3b8";
          return {
            id: `edge_${fieldId}_${targetId}`,
            source: fieldId,
            sourceHandle: "bottom",
            target: targetId,
            targetHandle: "top",
            type: "smoothstep",
            animated: false,
            style: `stroke: ${color}; stroke-width: 2px;`,
            markerEnd: {
              type: MarkerType.ArrowClosed,
              width: 12,
              height: 12,
              color
            }
          };
        });
      }
    );
  };

  let nodes: Node[] = [];
  let edges: Edge[] = [];
  $: nodes = [
    ...buildFieldNodes($mapperStore),
    ...buildComponentNodes($mapperStore)
  ];
  $: edges = buildEdges($mapperStore);

  const isFieldNode = (nodeId: string) => nodeId.startsWith("field_");
  const isComponentNode = (nodeId: string) => nodeId.startsWith("component_");

  const componentPathById = (state: AppState, componentId: string) =>
    state.componentLevels.find((level) => level.id === componentId)?.path ?? null;

  const handleConnect = (connection: Connection) => {
    if (!connection.source || !connection.target) {
      return;
    }
    const sourceIsField = isFieldNode(connection.source);
    const targetIsField = isFieldNode(connection.target);
    const sourceIsComponent = isComponentNode(connection.source);
    const targetIsComponent = isComponentNode(connection.target);
    if (sourceIsField && targetIsComponent) {
      const componentPath = componentPathById($mapperStore, connection.target);
      if (componentPath) {
        addComponentLink(componentPath, connection.source);
      }
      return;
    }
    if (targetIsField && sourceIsComponent) {
      const componentPath = componentPathById($mapperStore, connection.source);
      if (componentPath) {
        addComponentLink(componentPath, connection.target);
      }
    }
  };

  const handleDelete = ({
    nodes: _deletedNodes,
    edges: deletedEdges
  }: { nodes: Node[]; edges: Edge[] }) => {
    deletedEdges.forEach((edge) => {
      const sourceIsField = isFieldNode(edge.source);
      const targetIsComponent = isComponentNode(edge.target);
      const sourceIsComponent = isComponentNode(edge.source);
      const targetIsField = isFieldNode(edge.target);
      if (sourceIsField && targetIsComponent) {
        const componentPath = componentPathById($mapperStore, edge.target);
        if (componentPath) {
          removeComponentLink(componentPath, edge.source);
        }
      }
      if (targetIsField && sourceIsComponent) {
        const componentPath = componentPathById($mapperStore, edge.source);
        if (componentPath) {
          removeComponentLink(componentPath, edge.target);
        }
      }
    });
  };

  const handleNodeClick = ({ node }: { node: Node; event: MouseEvent }) => {
    if (node?.type === "componentLevel") {
      const componentPath = componentPathById($mapperStore, node.id);
      if (componentPath) {
        setSelectedComponentPath(componentPath);
      }
    } else {
      setSelectedComponentPath(null);
    }
  };

  // Check if connection is valid (field -> component or component -> field)
  const isValidConnection = (connection: Connection): boolean => {
    if (!connection.source || !connection.target) return false;
    const sourceIsField = isFieldNode(connection.source);
    const targetIsField = isFieldNode(connection.target);
    const sourceIsComponent = isComponentNode(connection.source);
    const targetIsComponent = isComponentNode(connection.target);
    return (sourceIsField && targetIsComponent) || (targetIsField && sourceIsComponent);
  };

</script>

<div class="canvas">
  {#if browser}
    <SvelteFlow
      {nodes}
      {edges}
      {nodeTypes}
      {defaultEdgeOptions}
      connectionLineType={ConnectionLineType.SmoothStep}
      {isValidConnection}
      fitView
      deleteKey={["Backspace", "Delete"]}
      onconnect={handleConnect}
      ondelete={handleDelete}
      onnodeclick={handleNodeClick}
    >
      <Background gap={24} />
      <Controls position="bottom-right" />
      <MiniMap position="bottom-left" />
    </SvelteFlow>
    <ComponentDistributionPanel />
    <ComponentValueWizard />
  {:else}
    <div class="loading">Loading canvas...</div>
  {/if}
</div>

<style>
  .canvas {
    height: calc(100vh - 120px);
    border: 1px solid #e2e2e2;
    border-radius: 12px;
    background: #ffffff;
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
