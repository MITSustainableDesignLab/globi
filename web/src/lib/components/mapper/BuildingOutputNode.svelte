<script lang="ts">
  import { mapperStore } from "$lib/stores/mapperStore";

  export let data: {
    componentLinks: Record<string, string[]>;
  };
  export let selected = false;

  $: allComponents = $mapperStore.componentLevels;
  $: linkedComponents = allComponents.filter(
    (comp) => (data.componentLinks[comp.path]?.length ?? 0) > 0
  );
  $: topLevelComponents = linkedComponents.filter((comp) => {
    const parts = comp.path.split(".");
    return parts.length === 1;
  });

  $: envelopeComponents = linkedComponents.filter((comp) =>
    comp.path.startsWith("Envelope")
  );
  $: operationsComponents = linkedComponents.filter((comp) =>
    comp.path.startsWith("Operations")
  );

  const getComponentStatus = (componentPath: string) => {
    const links = data.componentLinks[componentPath] ?? [];
    return {
      linked: links.length > 0,
      linkCount: links.length
    };
  };

  const getComponentColor = (componentPath: string) => {
    const component = allComponents.find((c) => c.path === componentPath);
    return component?.color ?? "#6b7280";
  };
</script>

<div class:selected class="node output-node">
  <div class="header">
    <div class="title">building archetype</div>
    <div class="subtitle">fully defined components</div>
  </div>
  <div class="content">
    {#if topLevelComponents.length === 0}
      <div class="empty-state">
        <div class="empty-icon">🏗️</div>
        <div class="empty-text">connect semantic fields to components to build archetype</div>
      </div>
    {:else}
      <div class="building-preview">
        <div class="building-structure">
          {#if envelopeComponents.length > 0}
            <div class="building-section envelope-section">
              <div class="section-header">
                <span class="section-title">envelope</span>
                <span class="section-count">{envelopeComponents.length} components</span>
              </div>
              <div class="component-list">
                {#each envelopeComponents.slice(0, 5) as comp}
                  <div class="component-item" style={`border-left-color:${getComponentColor(comp.path)}`}>
                    <span class="component-name">{comp.displayName}</span>
                    <span class="component-meta">
                      {getComponentStatus(comp.path).linkCount} field{getComponentStatus(comp.path).linkCount !== 1 ? "s" : ""}
                    </span>
                  </div>
                {/each}
                {#if envelopeComponents.length > 5}
                  <div class="component-more">+{envelopeComponents.length - 5} more</div>
                {/if}
              </div>
            </div>
          {/if}

          {#if operationsComponents.length > 0}
            <div class="building-section operations-section">
              <div class="section-header">
                <span class="section-title">operations</span>
                <span class="section-count">{operationsComponents.length} components</span>
              </div>
              <div class="component-list">
                {#each operationsComponents.slice(0, 5) as comp}
                  <div class="component-item" style={`border-left-color:${getComponentColor(comp.path)}`}>
                    <span class="component-name">{comp.displayName}</span>
                    <span class="component-meta">
                      {getComponentStatus(comp.path).linkCount} field{getComponentStatus(comp.path).linkCount !== 1 ? "s" : ""}
                    </span>
                  </div>
                {/each}
                {#if operationsComponents.length > 5}
                  <div class="component-more">+{operationsComponents.length - 5} more</div>
                {/if}
              </div>
            </div>
          {/if}
        </div>

        <div class="summary">
          <div class="summary-item">
            <span class="summary-label">total components:</span>
            <span class="summary-value">{linkedComponents.length}</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">total links:</span>
            <span class="summary-value">
              {Object.values(data.componentLinks).reduce((sum, links) => sum + links.length, 0)}
            </span>
          </div>
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .node {
    min-width: 320px;
    border: 2px solid #e5e7eb;
    border-radius: 8px;
    background: #ffffff;
    padding: 16px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
  }

  .node.selected {
    border-color: #2563eb;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
  }

  .header {
    margin-bottom: 12px;
  }

  .title {
    font-weight: 600;
    font-size: 16px;
    margin-bottom: 4px;
  }

  .subtitle {
    font-size: 12px;
    color: #6b7280;
  }

  .content {
    min-height: 200px;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 40px 20px;
    text-align: center;
  }

  .empty-icon {
    font-size: 48px;
    margin-bottom: 12px;
  }

  .empty-text {
    font-size: 13px;
    color: #6b7280;
    max-width: 240px;
  }

  .building-preview {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .building-structure {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .building-section {
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px;
    background: #f9fafb;
  }

  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }

  .section-title {
    font-weight: 600;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .section-count {
    font-size: 11px;
    color: #6b7280;
  }

  .component-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .component-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 8px;
    background: #ffffff;
    border-radius: 4px;
    border-left: 3px solid;
  }

  .component-name {
    font-size: 12px;
    color: #111827;
  }

  .component-meta {
    font-size: 11px;
    color: #6b7280;
  }

  .component-more {
    font-size: 11px;
    color: #9ca3af;
    text-align: center;
    padding: 4px;
  }

  .summary {
    display: flex;
    gap: 16px;
    padding-top: 12px;
    border-top: 1px solid #e5e7eb;
  }

  .summary-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .summary-label {
    font-size: 11px;
    color: #6b7280;
  }

  .summary-value {
    font-size: 18px;
    font-weight: 600;
    color: #111827;
  }
</style>
