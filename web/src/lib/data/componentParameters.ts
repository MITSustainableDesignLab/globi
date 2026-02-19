/**
 * Component parameter schemas derived from the Prisma models.
 * These define what values need to be specified for each component type.
 */

export type ParameterType = "number" | "boolean" | "string" | "enum";

export type ParameterSchema = {
  name: string;
  displayName: string;
  type: ParameterType;
  required: boolean;
  defaultValue?: number | boolean | string;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  enumOptions?: string[];
  description?: string;
};

export type ComponentParameterSchema = {
  componentName: string;
  displayName: string;
  parameters: ParameterSchema[];
};

// Occupancy parameters
const OccupancyParams: ParameterSchema[] = [
  { name: "PeopleDensity", displayName: "People Density", type: "number", required: true, min: 0, step: 0.001, unit: "people/m²", description: "Occupant density per floor area" },
  { name: "IsOn", displayName: "Is On", type: "boolean", required: true, defaultValue: true },
  { name: "MetabolicRate", displayName: "Metabolic Rate", type: "number", required: true, min: 0, step: 1, unit: "W/person", description: "Metabolic heat generation rate" }
];

// Lighting parameters
const LightingParams: ParameterSchema[] = [
  { name: "PowerDensity", displayName: "Power Density", type: "number", required: true, min: 0, step: 0.1, unit: "W/m²", description: "Lighting power per floor area" },
  { name: "DimmingType", displayName: "Dimming Type", type: "enum", required: true, enumOptions: ["None", "Stepped", "Continuous"], description: "Type of lighting dimming control" },
  { name: "IsOn", displayName: "Is On", type: "boolean", required: true, defaultValue: true }
];

// Equipment parameters
const EquipmentParams: ParameterSchema[] = [
  { name: "PowerDensity", displayName: "Power Density", type: "number", required: true, min: 0, step: 0.1, unit: "W/m²", description: "Equipment power per floor area" },
  { name: "IsOn", displayName: "Is On", type: "boolean", required: true, defaultValue: true }
];

// Thermostat parameters
const ThermostatParams: ParameterSchema[] = [
  { name: "IsOn", displayName: "Is On", type: "boolean", required: true, defaultValue: true },
  { name: "HeatingSetpoint", displayName: "Heating Setpoint", type: "number", required: true, min: 10, max: 30, step: 0.5, unit: "°C", description: "Heating temperature setpoint" },
  { name: "CoolingSetpoint", displayName: "Cooling Setpoint", type: "number", required: true, min: 15, max: 35, step: 0.5, unit: "°C", description: "Cooling temperature setpoint" }
];

// WaterUse parameters
const WaterUseParams: ParameterSchema[] = [
  { name: "FlowRatePerPerson", displayName: "Flow Rate Per Person", type: "number", required: true, min: 0, step: 0.0001, unit: "m³/s/person", description: "Water flow rate per occupant" }
];

// ThermalSystem parameters (Heating/Cooling)
const ThermalSystemParams: ParameterSchema[] = [
  { name: "ConditioningType", displayName: "Conditioning Type", type: "enum", required: true, enumOptions: ["Heating", "Cooling"], description: "Whether this is heating or cooling system" },
  { name: "Fuel", displayName: "Fuel Type", type: "enum", required: true, enumOptions: ["Electricity", "NaturalGas", "DistrictHeating", "DistrictCooling", "Oil", "Propane", "Biomass"], description: "Energy source for the system" },
  { name: "SystemCOP", displayName: "System COP", type: "number", required: true, min: 0.1, max: 10, step: 0.1, description: "Coefficient of performance at the system" },
  { name: "DistributionCOP", displayName: "Distribution COP", type: "number", required: true, min: 0.1, max: 1, step: 0.01, defaultValue: 1, description: "Efficiency of the distribution system" }
];

// Ventilation parameters
const VentilationParams: ParameterSchema[] = [
  { name: "FreshAirPerFloorArea", displayName: "Fresh Air Per Floor Area", type: "number", required: true, min: 0, step: 0.0001, unit: "m³/s/m²", description: "Fresh air supply rate per floor area" },
  { name: "FreshAirPerPerson", displayName: "Fresh Air Per Person", type: "number", required: true, min: 0, step: 0.001, unit: "m³/s/person", description: "Fresh air supply rate per person" },
  { name: "Provider", displayName: "Provider", type: "enum", required: true, enumOptions: ["Natural", "Mechanical", "Hybrid"], description: "Ventilation delivery method" },
  { name: "HRV", displayName: "Heat Recovery", type: "enum", required: true, enumOptions: ["NoHRV", "Sensible", "Enthalpy"], description: "Heat recovery ventilation type" },
  { name: "Economizer", displayName: "Economizer", type: "enum", required: true, enumOptions: ["NoEconomizer", "DifferentialDryBulb", "DifferentialEnthalpy"], description: "Economizer control strategy" },
  { name: "DCV", displayName: "Demand Control", type: "enum", required: true, enumOptions: ["NoDCV", "OccupancySchedule", "CO2Setpoint"], description: "Demand-controlled ventilation type" }
];

// DHW parameters
const DHWParams: ParameterSchema[] = [
  { name: "SystemCOP", displayName: "System COP", type: "number", required: true, min: 0.1, max: 10, step: 0.1, description: "Coefficient of performance" },
  { name: "WaterTemperatureInlet", displayName: "Inlet Temperature", type: "number", required: true, min: 0, max: 30, step: 1, unit: "°C", description: "Cold water inlet temperature" },
  { name: "DistributionCOP", displayName: "Distribution COP", type: "number", required: true, min: 0.1, max: 1, step: 0.01, defaultValue: 1, description: "Efficiency of the distribution system" },
  { name: "WaterSupplyTemperature", displayName: "Supply Temperature", type: "number", required: true, min: 30, max: 80, step: 1, unit: "°C", description: "Hot water supply temperature" },
  { name: "IsOn", displayName: "Is On", type: "boolean", required: true, defaultValue: true },
  { name: "FuelType", displayName: "Fuel Type", type: "enum", required: true, enumOptions: ["Electricity", "NaturalGas", "DistrictHeating", "Oil", "Propane", "Biomass", "SolarThermal"], description: "Energy source for DHW" }
];

// Infiltration parameters
const InfiltrationParams: ParameterSchema[] = [
  { name: "IsOn", displayName: "Is On", type: "boolean", required: true, defaultValue: true },
  { name: "ConstantCoefficient", displayName: "Constant Coefficient", type: "number", required: true, min: 0, max: 1, step: 0.01, defaultValue: 0.606 },
  { name: "TemperatureCoefficient", displayName: "Temperature Coefficient", type: "number", required: true, min: 0, max: 1, step: 0.001, defaultValue: 0.03636 },
  { name: "WindVelocityCoefficient", displayName: "Wind Velocity Coefficient", type: "number", required: true, min: 0, max: 1, step: 0.001, defaultValue: 0.1177 },
  { name: "WindVelocitySquaredCoefficient", displayName: "Wind Velocity² Coefficient", type: "number", required: true, min: 0, step: 0.0001, defaultValue: 0 },
  { name: "AFNAirMassFlowCoefficientCrack", displayName: "AFN Air Mass Flow Coefficient", type: "number", required: true, min: 0, step: 0.0001, defaultValue: 0.01 },
  { name: "AirChangesPerHour", displayName: "Air Changes Per Hour", type: "number", required: true, min: 0, max: 20, step: 0.1, unit: "ACH", description: "Infiltration rate in air changes per hour" },
  { name: "FlowPerExteriorSurfaceArea", displayName: "Flow Per Exterior Area", type: "number", required: true, min: 0, step: 0.0001, unit: "m³/s/m²", defaultValue: 0 },
  { name: "CalculationMethod", displayName: "Calculation Method", type: "enum", required: true, enumOptions: ["AirChanges/Hour", "Flow/ExteriorSurfaceArea", "Flow/ExteriorWallArea", "EffectiveLeakageArea", "AIM-2"], description: "Infiltration calculation method" }
];

// Window/Glazing parameters
const WindowParams: ParameterSchema[] = [
  { name: "SHGF", displayName: "SHGC", type: "number", required: true, min: 0, max: 1, step: 0.01, description: "Solar Heat Gain Coefficient" },
  { name: "UValue", displayName: "U-Value", type: "number", required: true, min: 0.1, max: 10, step: 0.01, unit: "W/m²K", description: "Thermal transmittance" },
  { name: "TVis", displayName: "Visible Transmittance", type: "number", required: true, min: 0, max: 1, step: 0.01, description: "Visible light transmittance" },
  { name: "Type", displayName: "Glazing Type", type: "enum", required: true, enumOptions: ["Single", "Double", "Triple"], description: "Number of glass panes" }
];

// Construction Assembly parameters (simplified - references materials)
const ConstructionAssemblyParams: ParameterSchema[] = [
  { name: "Type", displayName: "Assembly Type", type: "enum", required: true, enumOptions: ["Wall", "Roof", "Floor", "Ceiling", "Partition", "GroundContact"], description: "Type of construction assembly" },
  { name: "RValue", displayName: "R-Value", type: "number", required: true, min: 0.1, max: 30, step: 0.1, unit: "m²K/W", description: "Total thermal resistance" },
  { name: "ThermalMass", displayName: "Thermal Mass", type: "number", required: false, min: 0, step: 1000, unit: "J/m²K", description: "Heat capacity per unit area" }
];

// Export all schemas by component path
export const COMPONENT_PARAMETERS: Record<string, ComponentParameterSchema> = {
  "Operations.SpaceUse.Occupancy": {
    componentName: "Occupancy",
    displayName: "Occupancy",
    parameters: OccupancyParams
  },
  "Operations.SpaceUse.Lighting": {
    componentName: "Lighting",
    displayName: "Lighting",
    parameters: LightingParams
  },
  "Operations.SpaceUse.Equipment": {
    componentName: "Equipment",
    displayName: "Equipment",
    parameters: EquipmentParams
  },
  "Operations.SpaceUse.Thermostat": {
    componentName: "Thermostat",
    displayName: "Thermostat",
    parameters: ThermostatParams
  },
  "Operations.SpaceUse.WaterUse": {
    componentName: "WaterUse",
    displayName: "Water Use",
    parameters: WaterUseParams
  },
  "Operations.HVAC.ConditioningSystems.Heating": {
    componentName: "Heating",
    displayName: "Heating System",
    parameters: ThermalSystemParams.filter(p => p.name !== "ConditioningType")
  },
  "Operations.HVAC.ConditioningSystems.Cooling": {
    componentName: "Cooling",
    displayName: "Cooling System",
    parameters: ThermalSystemParams.filter(p => p.name !== "ConditioningType")
  },
  "Operations.HVAC.Ventilation": {
    componentName: "Ventilation",
    displayName: "Ventilation",
    parameters: VentilationParams
  },
  "Operations.DHW": {
    componentName: "DHW",
    displayName: "Domestic Hot Water",
    parameters: DHWParams
  },
  "Envelope.Infiltration": {
    componentName: "Infiltration",
    displayName: "Infiltration",
    parameters: InfiltrationParams
  },
  "Envelope.AtticInfiltration": {
    componentName: "AtticInfiltration",
    displayName: "Attic Infiltration",
    parameters: InfiltrationParams
  },
  "Envelope.BasementInfiltration": {
    componentName: "BasementInfiltration",
    displayName: "Basement Infiltration",
    parameters: InfiltrationParams
  },
  "Envelope.Window": {
    componentName: "Window",
    displayName: "Window/Glazing",
    parameters: WindowParams
  },
  "Envelope.Assemblies.FlatRoofAssembly": {
    componentName: "FlatRoofAssembly",
    displayName: "Flat Roof Assembly",
    parameters: ConstructionAssemblyParams
  },
  "Envelope.Assemblies.AtticRoofAssembly": {
    componentName: "AtticRoofAssembly",
    displayName: "Attic Roof Assembly",
    parameters: ConstructionAssemblyParams
  },
  "Envelope.Assemblies.AtticFloorAssembly": {
    componentName: "AtticFloorAssembly",
    displayName: "Attic Floor Assembly",
    parameters: ConstructionAssemblyParams
  },
  "Envelope.Assemblies.FacadeAssembly": {
    componentName: "FacadeAssembly",
    displayName: "Facade Assembly",
    parameters: ConstructionAssemblyParams
  },
  "Envelope.Assemblies.FloorCeilingAssembly": {
    componentName: "FloorCeilingAssembly",
    displayName: "Floor/Ceiling Assembly",
    parameters: ConstructionAssemblyParams
  },
  "Envelope.Assemblies.PartitionAssembly": {
    componentName: "PartitionAssembly",
    displayName: "Partition Assembly",
    parameters: ConstructionAssemblyParams
  },
  "Envelope.Assemblies.ExternalFloorAssembly": {
    componentName: "ExternalFloorAssembly",
    displayName: "External Floor Assembly",
    parameters: ConstructionAssemblyParams
  },
  "Envelope.Assemblies.GroundSlabAssembly": {
    componentName: "GroundSlabAssembly",
    displayName: "Ground Slab Assembly",
    parameters: ConstructionAssemblyParams
  },
  "Envelope.Assemblies.GroundWallAssembly": {
    componentName: "GroundWallAssembly",
    displayName: "Ground Wall Assembly",
    parameters: ConstructionAssemblyParams
  },
  "Envelope.Assemblies.BasementCeilingAssembly": {
    componentName: "BasementCeilingAssembly",
    displayName: "Basement Ceiling Assembly",
    parameters: ConstructionAssemblyParams
  },
  "Envelope.Assemblies.InternalMassAssembly": {
    componentName: "InternalMassAssembly",
    displayName: "Internal Mass Assembly",
    parameters: ConstructionAssemblyParams
  }
};

// Get all leaf components (components that have parameters)
export const getLeafComponents = (parentPath: string): string[] => {
  return Object.keys(COMPONENT_PARAMETERS).filter((path) =>
    path.startsWith(parentPath)
  );
};

// Get parameters for a component path
export const getComponentParameters = (componentPath: string): ParameterSchema[] | null => {
  const schema = COMPONENT_PARAMETERS[componentPath];
  return schema?.parameters ?? null;
};

// Check if a component is a leaf (has parameters)
export const isLeafComponent = (componentPath: string): boolean => {
  return componentPath in COMPONENT_PARAMETERS;
};

// Get all descendants of a component path that have parameters
export const getDescendantLeafComponents = (componentPath: string): string[] => {
  return Object.keys(COMPONENT_PARAMETERS).filter(
    (path) => path.startsWith(componentPath + ".") || path === componentPath
  );
};
