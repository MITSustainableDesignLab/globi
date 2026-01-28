# GloBI Architecture - Simple Overview

This diagram provides a high-level overview of the GloBI (Global Building Intelligence) system workflow.

```mermaid
%%{init: {'theme':'base', 'themeVariables': { 'primaryColor':'#4a9eff','primaryTextColor':'#000','primaryBorderColor':'#2563eb','lineColor':'#64748b','secondaryColor':'#fbbf24','tertiaryColor':'#34d399','noteBkgColor':'#fef3c7','noteTextColor':'#000','noteBorderColor':'#f59e0b'}}}%%
flowchart TD
    %% Input Stage
    A[User Manifest File<br/>YAML Configuration] --> B{CLI Command<br/>submit manifest}

    %% Input Files
    C[GIS Building Data<br/>Shapefile/GeoJSON] --> D
    E[Component Database<br/>SQLite/Prisma] --> D
    F[Semantic Fields<br/>YAML Mappings] --> D
    G[Weather Data<br/>EPW Files] --> D

    %% Preprocessing Stage
    B --> D[1. GIS Preprocessing<br/>Validate & Enrich Data]

    %% Spec Generation
    D --> H[2. Building Spec Generation<br/>Create GloBIBuildingSpec]

    %% Allocation Stage
    H --> I[3. Job Allocation<br/>Calculate Branching<br/>& Submit to Hatchet]

    %% Distributed Execution
    I --> J[4. Distributed Simulation<br/>Workers Run EnergyPlus]

    %% Results Collection
    J --> K[5. Results Aggregation<br/>Store in S3/Cloud]

    %% Output Stage
    K --> L{CLI Command<br/>get experiment}
    L --> M[Local Results<br/>Parquet/CSV Files]
    L --> N[Visualization Dashboard<br/>Interactive HTML]

    %% Styling
    style A fill:#60a5fa,stroke:#2563eb,stroke-width:2px,color:#000
    style C fill:#60a5fa,stroke:#2563eb,stroke-width:2px,color:#000
    style E fill:#60a5fa,stroke:#2563eb,stroke-width:2px,color:#000
    style F fill:#60a5fa,stroke:#2563eb,stroke-width:2px,color:#000
    style G fill:#60a5fa,stroke:#2563eb,stroke-width:2px,color:#000
    style D fill:#fcd34d,stroke:#f59e0b,stroke-width:2px,color:#000
    style H fill:#fcd34d,stroke:#f59e0b,stroke-width:2px,color:#000
    style I fill:#fca5a5,stroke:#dc2626,stroke-width:2px,color:#000
    style J fill:#fca5a5,stroke:#dc2626,stroke-width:2px,color:#000
    style K fill:#4ade80,stroke:#16a34a,stroke-width:2px,color:#000
    style M fill:#4ade80,stroke:#16a34a,stroke-width:2px,color:#000
    style N fill:#4ade80,stroke:#16a34a,stroke-width:2px,color:#000
```

## Workflow Stages

### 1. **Input Configuration**

- **Manifest File**: YAML configuration defining the experiment, file paths, and preprocessing parameters
- **GIS Data**: Building footprints with properties (height, floors, typology)
- **Component Database**: Building components and materials specifications
- **Semantic Fields**: Mappings between building categories and properties
- **Weather Data**: EPW climate files for simulation

### 2. **GIS Preprocessing**

Validates and enriches building data:

- Filters buildings by area, height, and geometry validity
- Converts polygons to rotated rectangles
- Identifies neighboring buildings for shading analysis
- Assigns weather files based on location
- Injects semantic context (building typology, age, region)

### 3. **Building Spec Generation**

Creates structured specifications for each building:

- Extracts geometry (footprint dimensions, height, neighbors)
- Assigns building properties (WWR, basement, attic)
- Links semantic context and weather data
- Produces `GloBIBuildingSpec` objects ready for simulation

### 4. **Job Allocation**

Distributes work across compute infrastructure:

- Calculates optimal branching factor based on payload size
- Submits jobs to Hatchet workflow orchestrator
- Distributes building specs across Docker worker containers

### 5. **Distributed Simulation**

Workers execute energy simulations in parallel:

- Each worker processes assigned building specs
- Uses component database to construct EnergyPlus models
- Runs building energy simulations
- Extracts monthly energy and peak results
- Optionally captures hourly timeseries data

### 6. **Results Aggregation & Collection**

Consolidates simulation outputs:

- Aggregates results from all workers
- Stores in cloud storage (S3) as Parquet files
- Versions experiments for reproducibility
- Makes results available for retrieval

### 7. **Output & Visualization**

Delivers results to users:

- Downloads results to local filesystem
- Generates interactive D3-based dashboards
- Provides both Parquet and CSV formats
- Enables analysis of building stock energy performance

## Key Features

- **Scalability**: Processes thousands of buildings in parallel using distributed computing
- **Automation**: Minimal manual intervention from GIS data to simulation results
- **Reproducibility**: Version-controlled experiments with semantic versioning
- **Flexibility**: Configurable preprocessing, semantic mappings, and output options
- **Regional Analysis**: Designed for urban-scale building energy modeling
