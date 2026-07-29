<template>
  <div class="monitor-card">
    <div class="monitor-card__header">
      <span class="monitor-card__name">{{ service.name }}</span>
      <span class="monitor-card__badge" :class="service.statusClass">
        {{ service.statusLabel }}
      </span>
    </div>

    <div class="monitor-card__stats">
      <span>可用率 <span class="monitor-card__value">{{ service.uptime }}%</span></span>
      <span>请求 <span class="monitor-card__value">{{ service.total }}</span></span>
      <span>成功 <span class="monitor-card__value">{{ service.success }}</span></span>
    </div>

    <div class="monitor-card__beats">
      <div
        v-for="(beat, index) in service.beats"
        :key="index"
        class="monitor-beat"
        :class="beat.className"
      >
        <span v-if="beat.tooltip" class="monitor-beat__tooltip">{{ beat.tooltip }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  service: {
    name: string
    statusLabel: string
    statusClass: string
    uptime: number
    total: number
    success: number
    beats: Array<{ className: string; tooltip: string | null }>
  }
}>()
</script>

<style scoped>
.monitor-badge--up {
  background: var(--bauhaus-blue, #2d5da1);
  color: #ffffff;
}

.monitor-badge--warn {
  background: var(--bauhaus-yellow, #fff9c4);
  color: var(--bauhaus-ink, #2d2d2d);
}

.monitor-badge--down {
  background: var(--bauhaus-red, #ff4d4d);
  color: #ffffff;
}

.monitor-badge--unknown {
  background: hsl(var(--muted));
  color: var(--bauhaus-grey, #9e9e9e);
}

.monitor-card {
  position: relative;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  padding: 14px 14px 12px;
  background: hsl(var(--card));
  box-shadow: var(--shadow-card, 3px 3px 0 0 var(--bauhaus-ink));
  overflow: hidden;
}

html[data-theme='dark'] .monitor-card {
  border-color: hsl(var(--border));
  box-shadow: var(--shadow-card-soft, 0 4px 14px rgba(0, 0, 0, 0.45));
}

.monitor-card::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 5px;
  background: var(--bauhaus-blue, #2d5da1);
}

.monitor-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  margin-top: 4px;
}

.monitor-card__name {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: hsl(var(--foreground));
}

.monitor-card__badge {
  padding: 2px 8px;
  border-radius: var(--radius);
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.monitor-card__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
  margin-bottom: 12px;
}

.monitor-card__value {
  margin-left: 4px;
  color: hsl(var(--foreground));
  font-family: var(--font-display);
  font-weight: 700;
  font-variant-numeric: tabular-nums lining-nums;
  font-feature-settings: "tnum" 1, "lnum" 1;
  letter-spacing: -0.03em;
}

.monitor-card__beats {
  display: flex;
  gap: 2px;
  height: 24px;
  align-items: flex-end;
}

.monitor-beat {
  flex: 1;
  min-width: 4px;
  max-width: 8px;
  border-radius: 2px;
  transition: opacity 0.2s, transform 0.2s;
  position: relative;
}

.monitor-beat:hover {
  opacity: 0.8;
  transform: scaleY(1.1);
}

@media (prefers-reduced-motion: reduce) {
  .monitor-beat {
    transition: none;
  }

  .monitor-beat:hover {
    transform: none;
  }
}

.monitor-beat--up {
  background: var(--bauhaus-blue, #2d5da1);
  height: 100%;
}

.monitor-beat--warn,
.monitor-beat--slow {
  background: var(--bauhaus-yellow, #fff9c4);
  height: 100%;
}

.monitor-beat--down {
  background: var(--bauhaus-red, #ff4d4d);
  height: 100%;
}

.monitor-beat--empty {
  background: var(--bauhaus-line-soft, #c9c2b4);
  height: 40%;
}

.monitor-beat__tooltip {
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: #1d1d1f;
  color: #fff;
  padding: 6px 10px;
  border-radius: var(--radius);
  font-size: 11px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
  margin-bottom: 6px;
  z-index: 10;
}

.monitor-beat__tooltip::after {
  content: "";
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: #1d1d1f;
}

.monitor-beat:hover .monitor-beat__tooltip {
  opacity: 1;
}

@media (max-width: 768px) {
  .monitor-beat {
    min-width: 3px;
    max-width: 6px;
  }
}
</style>
