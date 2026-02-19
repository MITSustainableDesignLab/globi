<script lang="ts">
  import { useNodes, type ConnectionLineComponentProps } from "@xyflow/svelte";
  import { getEdgeParams, createBezierPath } from "./floatingEdgeUtils";

  type $$Props = ConnectionLineComponentProps;

  export let fromX: $$Props["fromX"];
  export let fromY: $$Props["fromY"];
  export let toX: $$Props["toX"];
  export let toY: $$Props["toY"];
  export let fromNode: $$Props["fromNode"];
  export let connectionStatus: $$Props["connectionStatus"] = null;

  const nodes = useNodes();

  // Find target node if hovering over one
  $: targetNode = $nodes.find((n) => {
    if (!n.measured?.width || !n.measured?.height) return false;
    const inX = toX >= n.position.x && toX <= n.position.x + n.measured.width;
    const inY = toY >= n.position.y && toY <= n.position.y + n.measured.height;
    return inX && inY && n.id !== fromNode?.id;
  });

  $: edgeParams =
    fromNode && targetNode
      ? getEdgeParams(fromNode, targetNode)
      : null;

  $: path = edgeParams
    ? createBezierPath(edgeParams)
    : `M ${fromX},${fromY} L ${toX},${toY}`;

  $: strokeColor = connectionStatus === "valid" ? "#22c55e" : "#3b82f6";
</script>

<g class="connection-line">
  <path
    d={path}
    fill="none"
    stroke={strokeColor}
    stroke-width="2"
    stroke-dasharray="6 3"
    class:valid={connectionStatus === "valid"}
    class:invalid={connectionStatus === "invalid"}
  />
  <circle
    cx={toX}
    cy={toY}
    r="6"
    fill={strokeColor}
    class="connection-indicator"
    class:valid={connectionStatus === "valid"}
  />
</g>

<style>
  .connection-line path {
    animation: dash 0.5s linear infinite;
  }

  @keyframes dash {
    from {
      stroke-dashoffset: 18;
    }
    to {
      stroke-dashoffset: 0;
    }
  }

  .connection-indicator {
    opacity: 0.8;
  }

  .connection-indicator.valid {
    fill: #22c55e;
    animation: pulse 0.8s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% {
      r: 6;
      opacity: 0.8;
    }
    50% {
      r: 8;
      opacity: 1;
    }
  }

  path.invalid {
    stroke: #ef4444;
  }
</style>
