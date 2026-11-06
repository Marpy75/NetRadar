import { ParticleSystem } from "./particle-system.js";

/**
 * Interactive Force-Directed Network Graph using PixiJS and d3-force
 */
export class NetworkGraph {
  constructor(containerEl, onSelectDevice) {
    this.containerEl = containerEl;
    this.onSelectDevice = onSelectDevice;

    this.width = containerEl.clientWidth || 800;
    this.height = containerEl.clientHeight || 600;

    // PixiJS Application
    this.app = new PIXI.Application({
      width: this.width,
      height: this.height,
      backgroundColor: 0x181b22,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true
    });

    this.containerEl.appendChild(this.app.view);

    // Containers
    this.edgeLayer = new PIXI.Graphics();
    this.app.stage.addChild(this.edgeLayer);

    this.particleSystem = new ParticleSystem(this.app.stage);

    this.nodeLayer = new PIXI.Container();
    this.app.stage.addChild(this.nodeLayer);

    // Nodes & Simulation data
    this.nodes = [];       // array of node objects for d3
    this.nodeMap = new Map(); // ip -> node object
    this.links = [];       // array of link objects for d3
    this.flows = [];

    this.routerNode = {
      id: "router",
      ip: "router",
      hostname: "MikroTik",
      device_type: "router",
      isRouter: true,
      fx: this.width / 2,
      fy: this.height / 2,
      x: this.width / 2,
      y: this.height / 2
    };

    this.selectedIp = null;

    // Initialize d3-force simulation
    this._initSimulation();

    // Resize handling
    window.addEventListener("resize", () => this._onResize());

    // Animation ticker
    this.app.ticker.add((delta) => this._onTick(delta));
  }

  _initSimulation() {
    this.nodes = [this.routerNode];
    this.simulation = d3.forceSimulation(this.nodes)
      .force("link", d3.forceLink(this.links).id(d => d.id).distance(140).strength(0.3))
      .force("charge", d3.forceManyBody().strength(-280))
      .force("center", d3.forceCenter(this.width / 2, this.height / 2).strength(0.05))
      .force("collision", d3.forceCollide().radius(35))
      .alphaDecay(0.015)
      .velocityDecay(0.4);
  }

  _onResize() {
    this.width = this.containerEl.clientWidth || 800;
    this.height = this.containerEl.clientHeight || 600;
    this.app.renderer.resize(this.width, this.height);

    this.routerNode.fx = this.width / 2;
    this.routerNode.fy = this.height / 2;
    this.simulation.force("center", d3.forceCenter(this.width / 2, this.height / 2).strength(0.05));
    this.simulation.alpha(0.3).restart();
  }

  updateData(devices, flows) {
    this.flows = flows || [];
    const currentIps = new Set();

    // Update or add devices
    for (const dev of devices) {
      currentIps.add(dev.ip);
      let node = this.nodeMap.get(dev.ip);

      if (!node) {
        // New node: position near center with small random offset
        const angle = Math.random() * Math.PI * 2;
        const dist = 60 + Math.random() * 80;
        node = {
          id: dev.ip,
          ip: dev.ip,
          x: (this.width / 2) + Math.cos(angle) * dist,
          y: (this.height / 2) + Math.sin(angle) * dist,
          vx: 0,
          vy: 0,
          rawDevice: dev,
          displayOpacity: 0
        };

        this._createNodeView(node);
        this.nodeMap.set(dev.ip, node);
        this.nodes.push(node);
        this.links.push({ source: this.routerNode.id, target: node.id });
      }

      node.rawDevice = dev;
      this._updateNodeView(node);
    }

    // Handle offline or removed devices
    for (const [ip, node] of this.nodeMap.entries()) {
      if (!currentIps.has(ip)) {
        node.rawDevice.status = "offline";
        this._updateNodeView(node);
      }
    }

    // Restart simulation smoothly
    this.simulation.nodes(this.nodes);
    this.simulation.force("link").links(this.links);
    this.simulation.alpha(0.2).restart();
  }

  _createNodeView(node) {
    const view = new PIXI.Container();
    view.interactive = true;
    view.cursor = "pointer";

    // Glow background
    const glow = new PIXI.Graphics();
    view.addChild(glow);
    view.glow = glow;

    // Node body circle
    const circle = new PIXI.Graphics();
    view.addChild(circle);
    view.circle = circle;

    // Device Icon Sprite
    const iconType = node.isRouter ? "router" : (node.rawDevice?.device_type || "generic");
    const icon = PIXI.Sprite.from(`/icons/${iconType}.svg`);
    icon.anchor.set(0.5);
    const size = node.isRouter ? 28 : 22;
    icon.width = size;
    icon.height = size;
    view.addChild(icon);
    view.icon = icon;

    // IP label
    const label = new PIXI.Text(node.ip, {
      fontFamily: "Cascadia Code, Consolas, monospace",
      fontSize: 10,
      fill: 0x8b95a5,
      align: "center"
    });
    label.anchor.set(0.5, 0);
    label.position.set(0, node.isRouter ? 22 : 18);
    view.addChild(label);
    view.label = label;

    // Hostname label
    const nameLabel = new PIXI.Text(node.hostname || node.rawDevice?.hostname || "", {
      fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      fontSize: 10,
      fill: 0xdcdcdc,
      align: "center"
    });
    nameLabel.anchor.set(0.5, 1);
    nameLabel.position.set(0, node.isRouter ? -22 : -18);
    view.addChild(nameLabel);
    view.nameLabel = nameLabel;

    // Click handler
    view.on("pointerdown", () => {
      if (!node.isRouter && this.onSelectDevice) {
        this.selectedIp = node.ip;
        this.onSelectDevice(node.rawDevice);
      }
    });

    this.nodeLayer.addChild(view);
    node.view = view;
  }

  _updateNodeView(node) {
    if (!node.view) return;

    const dev = node.rawDevice;
    const isOffline = dev?.status === "offline";
    const isSelected = this.selectedIp === node.ip;

    // Circle style
    const c = node.view.circle;
    c.clear();
    const radius = node.isRouter ? 22 : 16;

    let fillColor = 0x212630;
    let strokeColor = 0x373f50;
    let strokeWidth = 1.5;

    if (node.isRouter) {
      fillColor = 0x1e293b;
      strokeColor = 0x3b82f6;
      strokeWidth = 2;
    } else if (isSelected) {
      strokeColor = 0x38bdf8;
      strokeWidth = 2.5;
    } else if (isOffline) {
      fillColor = 0x181b22;
      strokeColor = 0x475569;
    } else if ((dev?.rate_bytes_rx || 0) + (dev?.rate_bytes_tx || 0) > 100000) {
      strokeColor = 0x10b981;
    }

    c.lineStyle(strokeWidth, strokeColor);
    c.beginFill(fillColor, 1);
    c.drawCircle(0, 0, radius);
    c.endFill();

    // Pulse/Glow for active traffic
    const g = node.view.glow;
    g.clear();
    if (!isOffline && ((dev?.rate_bytes_rx || 0) + (dev?.rate_bytes_tx || 0) > 200000)) {
      g.beginFill(0x3b82f6, 0.15);
      g.drawCircle(0, 0, radius + 8);
      g.endFill();
    }

    // Hostname
    if (node.view.nameLabel) {
      const name = dev?.hostname || dev?.oui_vendor || "";
      node.view.nameLabel.text = name.length > 14 ? name.substring(0, 12) + "..." : name;
      node.view.nameLabel.style.fill = isOffline ? 0x64748b : 0xe0e4ec;
    }
  }

  _onTick(delta) {
    if (!this.routerNode.view) {
      this._createNodeView(this.routerNode);
      this._updateNodeView(this.routerNode);
    }

    // Update node positions and smooth fade
    const nodePositions = new Map();
    for (const node of this.nodes) {
      if (node.view) {
        node.view.position.set(node.x, node.y);

        // Smooth opacity transition
        const targetOpacity = node.rawDevice?.status === "offline" ? 0.35 : 1.0;
        if (node.displayOpacity === undefined) node.displayOpacity = 0;
        node.displayOpacity += (targetOpacity - node.displayOpacity) * 0.1;
        node.view.alpha = node.displayOpacity;

        nodePositions.set(node.ip, { x: node.x, y: node.y });
      }
    }

    // Draw links
    this.edgeLayer.clear();
    for (const link of this.links) {
      const src = link.source;
      const tgt = link.target;
      if (!src || !tgt) continue;

      const isOffline = tgt.rawDevice?.status === "offline";
      const edgeColor = isOffline ? 0x272e3b : 0x333d4d;
      const edgeAlpha = isOffline ? 0.3 : 0.6;

      this.edgeLayer.lineStyle(1, edgeColor, edgeAlpha);
      this.edgeLayer.moveTo(src.x, src.y);
      this.edgeLayer.lineTo(tgt.x, tgt.y);
    }

    // Update particles
    const routerPos = { x: this.routerNode.x, y: this.routerNode.y };
    this.particleSystem.update(this.flows, nodePositions, routerPos, delta);
  }
}
