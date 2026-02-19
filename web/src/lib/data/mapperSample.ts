import type {
  ComponentTypeNode,
  MappingEdge,
  SemanticFieldNode
} from "$lib/types/mapper";

export const semanticFields: SemanticFieldNode[] = [
  {
    id: "field_typology",
    type: "semantic_field",
    fieldName: "Typology",
    fieldType: "categorical",
    optionCount: 12,
    options: [
      "office_small",
      "office_medium",
      "office_large",
      "retail_small",
      "retail_medium",
      "retail_large",
      "hotel_small",
      "hotel_medium",
      "hotel_large",
      "warehouse",
      "school",
      "hospital"
    ],
    position: { x: 100, y: 40 },
    color: "#4f46e5",
    isConnected: true,
    connectedComponents: ["component_lighting", "component_occupancy"]
  },
  {
    id: "field_age",
    type: "semantic_field",
    fieldName: "Age_bracket",
    fieldType: "categorical",
    optionCount: 5,
    options: ["pre_1980", "1980_1999", "2000_2009", "2010_2019", "2020_plus"],
    position: { x: 320, y: 40 },
    color: "#16a34a",
    isConnected: true,
    connectedComponents: ["component_heating"]
  },
  {
    id: "field_weather",
    type: "semantic_field",
    fieldName: "Weatherization",
    fieldType: "categorical",
    optionCount: 4,
    options: ["low", "medium", "high", "retrofit"],
    position: { x: 540, y: 40 },
    color: "#f97316",
    isConnected: false,
    connectedComponents: []
  },
  {
    id: "field_lighting",
    type: "semantic_field",
    fieldName: "Lighting",
    fieldType: "categorical",
    optionCount: 3,
    options: ["low", "standard", "high"],
    position: { x: 760, y: 40 },
    color: "#0ea5e9",
    isConnected: true,
    connectedComponents: ["component_lighting"]
  }
];

export const componentTypes: ComponentTypeNode[] = [
  {
    id: "component_occupancy",
    type: "component_type",
    componentType: "Occupancy",
    category: "space_use",
    sourceFields: ["Typology"],
    combinationCount: 12,
    definedCount: 8,
    position: { x: 140, y: 320 },
    isFullyDefined: false,
    hasErrors: false
  },
  {
    id: "component_lighting",
    type: "component_type",
    componentType: "Lighting",
    category: "space_use",
    sourceFields: ["Typology", "Lighting"],
    combinationCount: 36,
    definedCount: 28,
    position: { x: 380, y: 320 },
    isFullyDefined: false,
    hasErrors: true
  },
  {
    id: "component_heating",
    type: "component_type",
    componentType: "Heating",
    category: "hvac",
    sourceFields: ["Age_bracket"],
    combinationCount: 8,
    definedCount: 8,
    position: { x: 200, y: 520 },
    isFullyDefined: true,
    hasErrors: false
  },
  {
    id: "component_facade",
    type: "component_type",
    componentType: "Facade",
    category: "envelope",
    sourceFields: ["Typology", "Weatherization"],
    combinationCount: 240,
    definedCount: 120,
    position: { x: 420, y: 720 },
    isFullyDefined: false,
    hasErrors: false
  }
];

export const edges: MappingEdge[] = [
  {
    id: "edge_typology_lighting",
    sourceId: "field_typology",
    targetId: "component_lighting",
    sourceField: "Typology",
    targetComponent: "Lighting",
    color: "#4f46e5",
    animated: true,
    isRequired: true
  },
  {
    id: "edge_lighting_lighting",
    sourceId: "field_lighting",
    targetId: "component_lighting",
    sourceField: "Lighting",
    targetComponent: "Lighting",
    color: "#0ea5e9",
    animated: true,
    isRequired: true
  },
  {
    id: "edge_typology_occupancy",
    sourceId: "field_typology",
    targetId: "component_occupancy",
    sourceField: "Typology",
    targetComponent: "Occupancy",
    color: "#4f46e5",
    animated: false,
    isRequired: true
  },
  {
    id: "edge_age_heating",
    sourceId: "field_age",
    targetId: "component_heating",
    sourceField: "Age_bracket",
    targetComponent: "Heating",
    color: "#16a34a",
    animated: false,
    isRequired: true
  }
];
