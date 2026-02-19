import { Position, type Node } from "@xyflow/svelte";

// Get the center of a node
function getNodeCenter(node: Node) {
  return {
    x: node.position.x + (node.measured?.width ?? 0) / 2,
    y: node.position.y + (node.measured?.height ?? 0) / 2
  };
}

// Get handle position based on Position enum
function getHandleCoordsByPosition(
  node: Node,
  handlePosition: Position,
  handleId?: string
) {
  // Get handle bounds if available
  const handle = node.internals?.handleBounds?.source?.find(
    (h) => h.position === handlePosition && (!handleId || h.id === handleId)
  ) ?? node.internals?.handleBounds?.target?.find(
    (h) => h.position === handlePosition && (!handleId || h.id === handleId)
  );

  const width = node.measured?.width ?? 0;
  const height = node.measured?.height ?? 0;

  if (handle) {
    return {
      x: node.position.x + handle.x + handle.width / 2,
      y: node.position.y + handle.y + handle.height / 2
    };
  }

  // Fallback to node center/edge
  switch (handlePosition) {
    case Position.Top:
      return { x: node.position.x + width / 2, y: node.position.y };
    case Position.Right:
      return { x: node.position.x + width, y: node.position.y + height / 2 };
    case Position.Bottom:
      return { x: node.position.x + width / 2, y: node.position.y + height };
    case Position.Left:
      return { x: node.position.x, y: node.position.y + height / 2 };
    default:
      return getNodeCenter(node);
  }
}

// Get the best position for edge connection
function getEdgePosition(node: Node, intersectionPoint: { x: number; y: number }) {
  const width = node.measured?.width ?? 0;
  const height = node.measured?.height ?? 0;
  const n = { ...node.position, width, height };
  const nx = Math.abs(n.x - intersectionPoint.x);
  const ny = Math.abs(n.y - intersectionPoint.y);
  const px = Math.abs(n.x + n.width - intersectionPoint.x);
  const py = Math.abs(n.y + n.height - intersectionPoint.y);

  const min = Math.min(nx, ny, px, py);

  if (min === ny) return Position.Top;
  if (min === py) return Position.Bottom;
  if (min === nx) return Position.Left;
  return Position.Right;
}

// Get intersection point between node and line from source to target
function getNodeIntersection(
  intersectionNode: Node,
  targetPoint: { x: number; y: number }
) {
  const width = intersectionNode.measured?.width ?? 0;
  const height = intersectionNode.measured?.height ?? 0;

  const centerX = intersectionNode.position.x + width / 2;
  const centerY = intersectionNode.position.y + height / 2;

  const w = width / 2;
  const h = height / 2;

  const dx = targetPoint.x - centerX;
  const dy = targetPoint.y - centerY;

  // Slope from center to target
  if (dx === 0) {
    return { x: centerX, y: centerY + (dy > 0 ? h : -h) };
  }

  const slope = dy / dx;
  const absSlope = Math.abs(slope);

  let x: number;
  let y: number;

  // Check if line hits top/bottom or left/right edge
  if (absSlope * w <= h) {
    // Hits left or right edge
    x = dx > 0 ? centerX + w : centerX - w;
    y = centerY + slope * (dx > 0 ? w : -w);
  } else {
    // Hits top or bottom edge
    y = dy > 0 ? centerY + h : centerY - h;
    x = centerX + (dy > 0 ? h : -h) / slope;
  }

  return { x, y };
}

// Main function to get edge parameters
export function getEdgeParams(source: Node, target: Node) {
  const sourceCenter = getNodeCenter(source);
  const targetCenter = getNodeCenter(target);

  const sourceIntersectionPoint = getNodeIntersection(source, targetCenter);
  const targetIntersectionPoint = getNodeIntersection(target, sourceCenter);

  const sourcePos = getEdgePosition(source, sourceIntersectionPoint);
  const targetPos = getEdgePosition(target, targetIntersectionPoint);

  return {
    sx: sourceIntersectionPoint.x,
    sy: sourceIntersectionPoint.y,
    tx: targetIntersectionPoint.x,
    ty: targetIntersectionPoint.y,
    sourcePos,
    targetPos
  };
}

// Create path for straight edge
export function createStraightPath(params: {
  sx: number;
  sy: number;
  tx: number;
  ty: number;
}) {
  return `M ${params.sx},${params.sy} L ${params.tx},${params.ty}`;
}

// Create path for bezier edge
export function createBezierPath(params: {
  sx: number;
  sy: number;
  tx: number;
  ty: number;
  sourcePos: Position;
  targetPos: Position;
}) {
  const { sx, sy, tx, ty, sourcePos, targetPos } = params;
  const offset = 50;

  let c1x = sx;
  let c1y = sy;
  let c2x = tx;
  let c2y = ty;

  // Adjust control points based on positions
  switch (sourcePos) {
    case Position.Top:
      c1y -= offset;
      break;
    case Position.Bottom:
      c1y += offset;
      break;
    case Position.Left:
      c1x -= offset;
      break;
    case Position.Right:
      c1x += offset;
      break;
  }

  switch (targetPos) {
    case Position.Top:
      c2y -= offset;
      break;
    case Position.Bottom:
      c2y += offset;
      break;
    case Position.Left:
      c2x -= offset;
      break;
    case Position.Right:
      c2x += offset;
      break;
  }

  return `M ${sx},${sy} C ${c1x},${c1y} ${c2x},${c2y} ${tx},${ty}`;
}
