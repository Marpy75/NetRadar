/**
 * Traffic particle system on graph links
 */
const PROTOCOL_COLORS = {
  dns: 0x06b6d4,    // cyan
  https: 0x3b82f6,  // blue
  http: 0x60a5fa,   // light blue
  wireguard: 0x8b5cf6, // purple
  icmp: 0x10b981,   // green
  tcp: 0x3b82f6,    // blue
  udp: 0x06b6d4,    // cyan
  other: 0x9ca3af   // grey
};

export class ParticleSystem {
  constructor(container) {
    this.container = container;
    this.graphics = new PIXI.Graphics();
    this.container.addChild(this.graphics);
    this.particles = [];
    this.maxParticles = 300;
  }

  update(flows, nodePositions, routerPos, delta) {
    this.graphics.clear();

    if (!routerPos) {
      return;
    }

    // Spawn particles based on active flows
    if (flows && flows.length > 0) {
      for (const flow of flows) {
        const clientPos = nodePositions.get(flow.client_ip);
        if (!clientPos) continue;

        // Density determined by rate (spawn probability)
        const bytesPerSec = flow.bytes_per_sec || 0;
        const spawnProb = Math.min(0.4, 0.05 + bytesPerSec / 250000);

        if (Math.random() < spawnProb && this.particles.length < this.maxParticles) {
          const proto = (flow.protocol || "tcp").toLowerCase();
          const color = PROTOCOL_COLORS[proto] || PROTOCOL_COLORS.other;

          // Outbound/inbound direction alternating for visual liveliness
          const isInbound = Math.random() > 0.5;
          const start = isInbound ? routerPos : clientPos;
          const end = isInbound ? clientPos : routerPos;

          // Speed based on traffic volume
          const speed = 0.008 + Math.min(0.03, bytesPerSec / 5000000);

          this.particles.push({
            start,
            end,
            progress: 0,
            speed,
            color,
            size: 2.5 + Math.min(2.5, bytesPerSec / 1000000)
          });
        }
      }
    }

    // Update and draw particles
    const alive = [];
    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];
      p.progress += p.speed * (delta || 1);

      if (p.progress < 1) {
        const x = p.start.x + (p.end.x - p.start.x) * p.progress;
        const y = p.start.y + (p.end.y - p.start.y) * p.progress;

        // Glow
        this.graphics.beginFill(p.color, 0.35);
        this.graphics.drawCircle(x, y, p.size * 1.8);
        this.graphics.endFill();

        // Core
        this.graphics.beginFill(0xffffff, 0.9);
        this.graphics.drawCircle(x, y, p.size * 0.7);
        this.graphics.endFill();

        alive.push(p);
      }
    }
    this.particles = alive;
  }

  clear() {
    this.particles = [];
    this.graphics.clear();
  }
}
