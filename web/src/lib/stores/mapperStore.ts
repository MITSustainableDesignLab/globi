import { writable } from "svelte/store";
import type {
  ComponentDistribution,
  ComponentLevel,
  DerivedFieldType,
  FieldPrior,
  RangeMapping,
  SemanticField
} from "$lib/types/mapper";
import {
  buildComponentLevels,
  buildInitialFields,
  buildInitialLinks,
  createDerivedOptions
} from "$lib/data/mapperSeed";

export type AppState = {
  project: {
    name: string;
    workflow: "template-first" | "data-first";
    modified: boolean;
  };
  semanticFields: SemanticField[];
  componentLevels: ComponentLevel[];
  componentLinks: Record<string, string[]>;
  componentDistributions: Record<string, ComponentDistribution[]>; // componentPath -> distributions
  fieldPriors: FieldPrior[];
  collapsedComponents: Set<string>; // paths of components that are manually expanded (overrides auto-collapse)
  expandedComponents: Set<string>; // paths of components that are manually expanded when parent has links
  ui: {
    selectedNode: string | null;
    selectedEdge: string | null;
    openPanel: "none" | "field-editor" | "component-values" | "distribution";
    selectedComponentPath: string | null;
    canvasZoom: number;
    canvasPan: { x: number; y: number };
    componentViewMode: "hierarchical" | "flat";
    componentCanvas: "envelope" | "spaceuse" | "hvac" | "dhw";
  };
};

export const mapperStore = writable<AppState>({
  project: {
    name: "untitled",
    workflow: "data-first",
    modified: false
  },
  semanticFields: buildInitialFields(),
  componentLevels: buildComponentLevels(),
  componentLinks: buildInitialLinks(),
  componentDistributions: {},
  fieldPriors: [],
  collapsedComponents: new Set(),
  expandedComponents: new Set(),
  ui: {
    selectedNode: null,
    selectedEdge: null,
    openPanel: "none",
    selectedComponentPath: null,
    canvasZoom: 1,
    canvasPan: { x: 0, y: 0 },
    componentViewMode: "hierarchical",
    componentCanvas: "envelope"
  }
});

const toFieldId = (name: string) =>
  `field_${name.toLowerCase().replace(/[^a-z0-9]+/g, "_")}`;

const derivedColorPalette = [
  "#22c55e",
  "#f97316",
  "#0ea5e9",
  "#a855f7",
  "#f43f5e"
];

function computeCompoundOptions(
  fields: SemanticField[],
  sourceFieldIds: string[],
  logic: "and" | "or"
): string[] {
  const sources = sourceFieldIds
    .map((id) => fields.find((f) => f.id === id))
    .filter((f): f is SemanticField => !!f && (f.options?.length ?? 0) > 0);

  if (logic === "and") {
    if (sources.length === 0) return [];
    const cartesian = (arrs: string[][]): string[] => {
      if (arrs.length === 0) return [];
      if (arrs.length === 1) return arrs[0];
      const [first, ...rest] = arrs;
      const restCombos = cartesian(rest);
      return first.flatMap((v) => restCombos.map((r) => `${v}|${r}`));
    };
    return cartesian(sources.map((s) => s.options ?? []));
  }

  if (logic === "or") {
    const seen = new Set<string>();
    for (const s of sources) {
      for (const opt of s.options ?? []) {
        seen.add(opt);
      }
    }
    return Array.from(seen);
  }

  return [];
}

export const addDerivedField = (payload: {
  name: string;
  sourceFieldId: string;
  derivedType: DerivedFieldType;
  rangeMapping: RangeMapping[];
  groupMapping: Record<string, string[]>;
}) => {
  mapperStore.update((state) => {
    const trimmedName = payload.name.trim();
    if (!trimmedName) {
      return state;
    }
    const existing = state.semanticFields.some(
      (field) => field.name.toLowerCase() === trimmedName.toLowerCase()
    );
    if (existing) {
      return state;
    }
    const derivedCount = state.semanticFields.filter((field) => field.isDerived)
      .length;
    const color =
      derivedColorPalette[derivedCount % derivedColorPalette.length];
    const rangeMapping = payload.derivedType === "numeric_range"
      ? payload.rangeMapping
      : [];
    const groupMapping =
      payload.derivedType === "categorical_mapping" ? payload.groupMapping : {};
    const newField: SemanticField = {
      id: toFieldId(trimmedName),
      name: trimmedName,
      type: "categorical",
      options: createDerivedOptions(
        payload.derivedType,
        rangeMapping,
        groupMapping
      ),
      color,
      isDerived: true,
      sourceFieldId: payload.sourceFieldId,
      derivedType: payload.derivedType,
      rangeMapping,
      groupMapping
    };
    return {
      ...state,
      semanticFields: [...state.semanticFields, newField],
      project: { ...state.project, modified: true }
    };
  });
};

export const addCompoundDerivedField = (payload: {
  name: string;
  sourceFieldIds: string[];
  logic: "and" | "or";
}) => {
  mapperStore.update((state) => {
    const trimmedName = payload.name.trim();
    if (!trimmedName || payload.sourceFieldIds.length < 2) {
      return state;
    }
    const existing = state.semanticFields.some(
      (field) => field.name.toLowerCase() === trimmedName.toLowerCase()
    );
    if (existing) {
      return state;
    }
    const derivedCount = state.semanticFields.filter((field) => field.isDerived)
      .length;
    const color =
      derivedColorPalette[derivedCount % derivedColorPalette.length];
    const options = computeCompoundOptions(
      state.semanticFields,
      payload.sourceFieldIds,
      payload.logic
    );
    if (options.length === 0) {
      return state;
    }
    const newField: SemanticField = {
      id: toFieldId(trimmedName),
      name: trimmedName,
      type: "categorical",
      options,
      color,
      isDerived: true,
      compoundDerived: {
        sourceFieldIds: payload.sourceFieldIds,
        logic: payload.logic
      }
    };
    return {
      ...state,
      semanticFields: [...state.semanticFields, newField],
      project: { ...state.project, modified: true }
    };
  });
};

export const toggleComponentLink = (componentPath: string, fieldId: string) => {
  mapperStore.update((state) => {
    const current = state.componentLinks[componentPath] ?? [];
    const exists = current.includes(fieldId);
    const next = exists
      ? current.filter((id) => id !== fieldId)
      : [...current, fieldId];
    return {
      ...state,
      componentLinks: {
        ...state.componentLinks,
        [componentPath]: next
      },
      project: { ...state.project, modified: true }
    };
  });
};

export const addComponentLink = (componentPath: string, fieldId: string) => {
  mapperStore.update((state) => {
    const current = state.componentLinks[componentPath] ?? [];
    if (current.includes(fieldId)) {
      return state;
    }
    return {
      ...state,
      componentLinks: {
        ...state.componentLinks,
        [componentPath]: [...current, fieldId]
      },
      project: { ...state.project, modified: true }
    };
  });
};

export const removeComponentLink = (componentPath: string, fieldId: string) => {
  mapperStore.update((state) => {
    const current = state.componentLinks[componentPath] ?? [];
    if (!current.includes(fieldId)) {
      return state;
    }
    return {
      ...state,
      componentLinks: {
        ...state.componentLinks,
        [componentPath]: current.filter((id) => id !== fieldId)
      },
      project: { ...state.project, modified: true }
    };
  });
};

export const clearComponentLinks = (componentPath: string) => {
  mapperStore.update((state) => ({
    ...state,
    componentLinks: {
      ...state.componentLinks,
      [componentPath]: []
    },
    project: { ...state.project, modified: true }
  }));
};

const generateDistributionId = () => `dist_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

export const addComponentDistribution = (
  componentPath: string,
  distribution: Omit<ComponentDistribution, "id">
) => {
  mapperStore.update((state) => {
    const current = state.componentDistributions[componentPath] ?? [];
    const newDistribution: ComponentDistribution = {
      ...distribution,
      id: generateDistributionId()
    };
    return {
      ...state,
      componentDistributions: {
        ...state.componentDistributions,
        [componentPath]: [...current, newDistribution]
      },
      project: { ...state.project, modified: true }
    };
  });
};

export const updateComponentDistribution = (
  componentPath: string,
  distributionId: string,
  update: Partial<ComponentDistribution>
) => {
  mapperStore.update((state) => {
    const current = state.componentDistributions[componentPath] ?? [];
    const updated = current.map((dist) =>
      dist.id === distributionId ? { ...dist, ...update } : dist
    );
    return {
      ...state,
      componentDistributions: {
        ...state.componentDistributions,
        [componentPath]: updated
      },
      project: { ...state.project, modified: true }
    };
  });
};

export const removeComponentDistribution = (
  componentPath: string,
  distributionId: string
) => {
  mapperStore.update((state) => {
    const current = state.componentDistributions[componentPath] ?? [];
    const filtered = current.filter((dist) => dist.id !== distributionId);
    return {
      ...state,
      componentDistributions: {
        ...state.componentDistributions,
        [componentPath]: filtered
      },
      project: { ...state.project, modified: true }
    };
  });
};

const generatePriorId = () => `prior_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

export const addFieldPrior = (prior: Omit<FieldPrior, "id">) => {
  mapperStore.update((state) => {
    const newPrior: FieldPrior = {
      ...prior,
      id: generatePriorId()
    };
    return {
      ...state,
      fieldPriors: [...state.fieldPriors, newPrior],
      project: { ...state.project, modified: true }
    };
  });
};

export const updateFieldPrior = (priorId: string, update: Partial<FieldPrior>) => {
  mapperStore.update((state) => {
    const updated = state.fieldPriors.map((prior) =>
      prior.id === priorId ? { ...prior, ...update } : prior
    );
    return {
      ...state,
      fieldPriors: updated,
      project: { ...state.project, modified: true }
    };
  });
};

export const removeFieldPrior = (priorId: string) => {
  mapperStore.update((state) => ({
    ...state,
    fieldPriors: state.fieldPriors.filter((prior) => prior.id !== priorId),
    project: { ...state.project, modified: true }
  }));
};

export const setSelectedComponentPath = (componentPath: string | null) => {
  mapperStore.update((state) => ({
    ...state,
    ui: {
      ...state.ui,
      selectedComponentPath: componentPath,
      openPanel: componentPath ? "distribution" : state.ui.openPanel
    }
  }));
};

export const setComponentViewMode = (mode: "hierarchical" | "flat") => {
  mapperStore.update((state) => ({
    ...state,
    ui: {
      ...state.ui,
      componentViewMode: mode
    }
  }));
};

export const setComponentCanvas = (
  canvas: "envelope" | "spaceuse" | "hvac" | "dhw"
) => {
  mapperStore.update((state) => ({
    ...state,
    ui: {
      ...state.ui,
      componentCanvas: canvas
    }
  }));
};

// Batch operations for creating distributions across combinations
export const addBatchComponentDistributions = (
  componentPath: string,
  distributions: Array<Omit<ComponentDistribution, "id">>
) => {
  mapperStore.update((state) => {
    const current = state.componentDistributions[componentPath] ?? [];
    const newDistributions = distributions.map((dist) => ({
      ...dist,
      id: generateDistributionId()
    }));
    return {
      ...state,
      componentDistributions: {
        ...state.componentDistributions,
        [componentPath]: [...current, ...newDistributions]
      },
      project: { ...state.project, modified: true }
    };
  });
};

// Link multiple semantic fields to a component at once
export const setComponentLinks = (componentPath: string, fieldIds: string[]) => {
  mapperStore.update((state) => ({
    ...state,
    componentLinks: {
      ...state.componentLinks,
      [componentPath]: fieldIds
    },
    project: { ...state.project, modified: true }
  }));
};

// Propagate links from a parent component to all its descendants
export const propagateComponentLinks = (
  parentPath: string,
  fieldIds: string[]
) => {
  mapperStore.update((state) => {
    const updatedLinks = { ...state.componentLinks };

    // Find all components that start with the parent path
    state.componentLevels.forEach((level) => {
      if (level.path.startsWith(parentPath)) {
        const existingLinks = updatedLinks[level.path] ?? [];
        // Merge with existing links, avoiding duplicates
        const mergedLinks = Array.from(new Set([...existingLinks, ...fieldIds]));
        updatedLinks[level.path] = mergedLinks;
      }
    });

    return {
      ...state,
      componentLinks: updatedLinks,
      project: { ...state.project, modified: true }
    };
  });
};

// Clear all distributions for a component
export const clearComponentDistributions = (componentPath: string) => {
  mapperStore.update((state) => {
    const { [componentPath]: _, ...rest } = state.componentDistributions;
    return {
      ...state,
      componentDistributions: rest,
      project: { ...state.project, modified: true }
    };
  });
};

// Get all child component paths for a given parent
export const getChildComponentPaths = (parentPath: string): string[] => {
  let paths: string[] = [];
  mapperStore.subscribe((state) => {
    paths = state.componentLevels
      .filter((level) => level.path.startsWith(parentPath + "."))
      .map((level) => level.path);
  })();
  return paths;
};

// Open the wizard panel for a component
export const openComponentWizard = (componentPath: string) => {
  mapperStore.update((state) => ({
    ...state,
    ui: {
      ...state.ui,
      selectedComponentPath: componentPath,
      openPanel: "component-values"
    }
  }));
};

// Close all panels
export const closePanel = () => {
  mapperStore.update((state) => ({
    ...state,
    ui: {
      ...state.ui,
      openPanel: "none",
      selectedComponentPath: null
    }
  }));
};

// Toggle expanded state for a component (when parent has links)
export const toggleComponentExpanded = (componentPath: string) => {
  mapperStore.update((state) => {
    const newExpanded = new Set(state.expandedComponents);
    if (newExpanded.has(componentPath)) {
      newExpanded.delete(componentPath);
    } else {
      newExpanded.add(componentPath);
    }
    return {
      ...state,
      expandedComponents: newExpanded
    };
  });
};

// Expand a component to show children
export const expandComponent = (componentPath: string) => {
  mapperStore.update((state) => {
    const newExpanded = new Set(state.expandedComponents);
    newExpanded.add(componentPath);
    return {
      ...state,
      expandedComponents: newExpanded
    };
  });
};

// Collapse a component to hide children
export const collapseComponent = (componentPath: string) => {
  mapperStore.update((state) => {
    const newExpanded = new Set(state.expandedComponents);
    newExpanded.delete(componentPath);
    return {
      ...state,
      expandedComponents: newExpanded
    };
  });
};
