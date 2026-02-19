import type { AppState } from "$lib/stores/mapperStore";
import { generateCombinations } from "$lib/types/mapper";
import { getDescendantLeafComponents, COMPONENT_PARAMETERS } from "$lib/data/componentParameters";

const getParentPath = (path: string): string | null => {
  const parts = path.split(".");
  if (parts.length <= 1) return null;
  return parts.slice(0, -1).join(".");
};

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

export type ComponentStatus = "unconnected" | "connected" | "complete";

export function calculateComponentStatus(path: string, state: AppState): ComponentStatus {
  const linkedFieldIds = state.componentLinks[path] ?? [];
  const hasLinks = hasLinksOrAncestorHasLinks(path, state.componentLinks);

  if (!hasLinks) return "unconnected";

  const leafPaths = getDescendantLeafComponents(path);
  if (leafPaths.length === 0) {
    return linkedFieldIds.length > 0 ? "connected" : "unconnected";
  }

  const effectiveFieldIds =
    linkedFieldIds.length > 0
      ? linkedFieldIds
      : (() => {
          const parentPath = getParentPath(path);
          return parentPath ? state.componentLinks[parentPath] ?? [] : [];
        })();

  if (effectiveFieldIds.length === 0) return "unconnected";

  const combinations = generateCombinations(state.semanticFields, effectiveFieldIds);
  let allComplete = true;

  for (const leafPath of leafPaths) {
    const params = COMPONENT_PARAMETERS[leafPath];
    if (!params) continue;

    const distributions = state.componentDistributions[leafPath] ?? [];
    for (const param of params.parameters.filter((p) => p.required)) {
      const paramDists = distributions.filter((d) => d.parameterName === param.name);
      for (const combo of combinations) {
        const hasDistForCombo = paramDists.some((d) => {
          const condKeys = Object.keys(d.conditions);
          if (condKeys.length === 0) return true;
          return condKeys.every((k) => d.conditions[k] === combo.conditions[k]);
        });
        if (!hasDistForCombo) {
          allComplete = false;
          break;
        }
      }
      if (!allComplete) break;
    }
    if (!allComplete) break;
  }

  return allComplete ? "complete" : "connected";
}
