export type FieldType = "categorical" | "numeric";

export type DerivedFieldType = "numeric_range" | "categorical_mapping";

export type RangeMapping = {
  min: number;
  max: number;
  label: string;
};

export type CompoundDerivedLogic = "and" | "or";

export type SemanticField = {
  id: string;
  name: string;
  type: FieldType;
  options?: string[];
  color: string;
  isDerived: boolean;
  sourceFieldId?: string;
  derivedType?: DerivedFieldType;
  rangeMapping?: RangeMapping[];
  groupMapping?: Record<string, string[]>;
  compoundDerived?: {
    sourceFieldIds: string[];
    logic: CompoundDerivedLogic;
  };
};

export type ComponentLevel = {
  id: string;
  name: string;
  displayName: string;
  path: string;
  depth: number;
  description: string;
  color: string;
};

export type SemanticFieldNode = {
  id: string;
  type: "semantic_field";
  fieldName: string;
  fieldType: FieldType;
  optionCount: number;
  options?: string[];
  position: { x: number; y: number };
  color: string;
  isConnected: boolean;
  connectedComponents: string[];
};

export type ComponentCategory = "space_use" | "hvac" | "envelope";

export type ComponentTypeNode = {
  id: string;
  type: "component_type";
  componentType: string;
  category: ComponentCategory;
  sourceFields: string[];
  suffix?: string;
  combinationCount: number;
  definedCount: number;
  position: { x: number; y: number };
  isFullyDefined: boolean;
  hasErrors: boolean;
};

export type MappingEdge = {
  id: string;
  sourceId: string;
  targetId: string;
  sourceField: string;
  targetComponent: string;
  color: string;
  animated: boolean;
  isRequired: boolean;
};

export type DistributionType =
  | "fixed"
  | "uniform"
  | "normal"
  | "triangular"
  | "lognormal"
  | "categorical";

export type Distribution = {
  type: DistributionType;
  value?: number;
  min?: number;
  max?: number;
  mean?: number;
  std?: number;
  mode?: number;
  clipMin?: number;
  clipMax?: number;
  options?: string[];
  weights?: number[];
  source?: string;
};

export type SemanticFieldCondition = Record<string, string>; // fieldId -> option value

export type ComponentDistribution = {
  id: string;
  componentPath: string;
  parameterName: string;
  conditions: SemanticFieldCondition;
  distribution: Distribution;
};

export type FieldPrior = {
  id: string;
  targetFieldId: string;
  sourceFieldIds: string[];
  probabilities: Array<{
    condition: SemanticFieldCondition;
    probabilities: Record<string, number>; // option -> probability
  }>;
};

// Combination of semantic field values for matrix view
export type FieldCombination = {
  id: string;
  conditions: SemanticFieldCondition;
  label: string; // Human-readable label for this combination
};

// Parameter value assignment - can be single value or distribution
export type ParameterValue = {
  type: "single" | "distribution";
  singleValue?: number | boolean | string;
  distribution?: Distribution;
};

// Wizard state for hierarchical value entry
export type WizardStep = "select-fields" | "select-component" | "enter-values" | "review";

export type ComponentValueEntry = {
  combinationId: string;
  parameterName: string;
  value: ParameterValue;
};

// Batch entry configuration
export type BatchEntryConfig = {
  componentPath: string;
  linkedFieldIds: string[];
  parameterName: string;
  entries: Map<string, ParameterValue>; // combinationId -> value
};

// Component mapping configuration (for the mapping wizard)
export type ComponentMappingConfig = {
  componentPath: string;
  semanticFieldIds: string[];
  includeDescendants: boolean; // Whether to map all child components too
};

// Generate combinations from field conditions
export function generateCombinations(
  fields: SemanticField[],
  fieldIds: string[]
): FieldCombination[] {
  const selectedFields = fields.filter((f) => fieldIds.includes(f.id));
  if (selectedFields.length === 0) {
    return [{ id: "default", conditions: {}, label: "Default" }];
  }

  const combinations: FieldCombination[] = [];
  const generateRecursive = (
    index: number,
    currentConditions: SemanticFieldCondition,
    labelParts: string[]
  ) => {
    if (index >= selectedFields.length) {
      const id = Object.entries(currentConditions)
        .map(([k, v]) => `${k}:${v}`)
        .join("|") || "default";
      combinations.push({
        id,
        conditions: { ...currentConditions },
        label: labelParts.join(" / ") || "Default"
      });
      return;
    }

    const field = selectedFields[index];
    const options = field.options ?? [];

    if (options.length === 0) {
      // Skip fields with no options
      generateRecursive(index + 1, currentConditions, labelParts);
    } else {
      for (const option of options) {
        generateRecursive(
          index + 1,
          { ...currentConditions, [field.id]: option },
          [...labelParts, `${field.name}=${option}`]
        );
      }
    }
  };

  generateRecursive(0, {}, []);
  return combinations;
}
