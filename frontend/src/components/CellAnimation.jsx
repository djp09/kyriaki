import { useEffect, useRef } from "react";

const CELL_COUNT = 18;
const COLORS = [
  "rgba(168, 85, 247, 0.25)",   // purple — T-cells
  "rgba(236, 72, 153, 0.2)",    // pink — NK cells
  "rgba(108, 92, 231, 0.22)",   // violet — antibodies
  "rgba(96, 165, 250, 0.2)",    // blue — B-cells
  "rgba(52, 211, 153, 0.18)",   // green — macrophages
];

function createCell(w, h) {
  const color = COLORS[Math.floor(Math.random() * COLORS.length)];
  const size = 8 + Math.random() * 28;
  return {
    x: Math.random() * w,
    y: Math.random() * h,
    vx: (Math.random() - 0.5) * 0.5,
    vy: (Math.random() - 0.5) * 0.4,
    size,
    color,
    // organic wobble
    wobblePhase: Math.random() * Math.PI * 2,
    wobbleSpeed: 0.008 + Math.random() * 0.012,
    wobbleAmp: 2 + Math.random() * 4,
    // nucleus
    nucleusRatio: 0.3 + Math.random() * 0.25,
    // membrane irregularity
    lobes: 5 + Math.floor(Math.random() * 4),
    lobeDepth: 0.08 + Math.random() * 0.12,
    rotation: Math.random() * Math.PI * 2,
    rotationSpeed: (Math.random() - 0.5) * 0.005,
    // opacity pulse
    pulsePhase: Math.random() * Math.PI * 2,
    pulseSpeed: 0.01 + Math.random() * 0.015,
  };
}

function drawCell(ctx, cell, time) {
  const { x, y, size, color, lobes, lobeDepth, rotation, nucleusRatio } = cell;
  const wobbleX = Math.sin(cell.wobblePhase + time * cell.wobbleSpeed) * cell.wobbleAmp;
  const wobbleY = Math.cos(cell.wobblePhase + time * cell.wobbleSpeed * 0.7) * cell.wobbleAmp;
  const cx = x + wobbleX;
  const cy = y + wobbleY;
  const pulse = 0.7 + 0.3 * Math.sin(cell.pulsePhase + time * cell.pulseSpeed);
  const rot = rotation + time * cell.rotationSpeed;

  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(rot);
  ctx.globalAlpha = pulse;

  // Irregular membrane shape
  ctx.beginPath();
  for (let i = 0; i <= 64; i++) {
    const angle = (i / 64) * Math.PI * 2;
    const lobeOffset = 1 + Math.sin(angle * lobes) * lobeDepth;
    const r = size * lobeOffset;
    if (i === 0) ctx.moveTo(r, 0);
    else ctx.lineTo(r * Math.cos(angle), r * Math.sin(angle));
  }
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();

  // Nucleus
  ctx.beginPath();
  ctx.arc(size * 0.05, size * 0.05, size * nucleusRatio, 0, Math.PI * 2);
  ctx.fillStyle = color.replace(/[\d.]+\)$/, (m) => `${parseFloat(m) + 0.12})`);
  ctx.fill();

  ctx.restore();
}

export default function CellAnimation() {
  const canvasRef = useRef(null);
  const cellsRef = useRef([]);
  const rafRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let w, h;

    function resize() {
      const rect = canvas.parentElement.getBoundingClientRect();
      w = rect.width;
      h = rect.height;
      canvas.width = w * devicePixelRatio;
      canvas.height = h * devicePixelRatio;
      ctx.scale(devicePixelRatio, devicePixelRatio);
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";

      if (cellsRef.current.length === 0) {
        cellsRef.current = Array.from({ length: CELL_COUNT }, () => createCell(w, h));
      }
    }

    resize();
    window.addEventListener("resize", resize);

    let frame = 0;
    function animate() {
      frame++;
      ctx.clearRect(0, 0, w, h);

      for (const cell of cellsRef.current) {
        cell.x += cell.vx;
        cell.y += cell.vy;

        // Wrap around edges
        if (cell.x < -cell.size * 2) cell.x = w + cell.size;
        if (cell.x > w + cell.size * 2) cell.x = -cell.size;
        if (cell.y < -cell.size * 2) cell.y = h + cell.size;
        if (cell.y > h + cell.size * 2) cell.y = -cell.size;

        drawCell(ctx, cell, frame);
      }

      // Draw faint connecting lines between nearby cells
      ctx.globalAlpha = 0.06;
      ctx.strokeStyle = "rgba(168, 85, 247, 0.5)";
      ctx.lineWidth = 0.8;
      for (let i = 0; i < cellsRef.current.length; i++) {
        for (let j = i + 1; j < cellsRef.current.length; j++) {
          const a = cellsRef.current[i];
          const b = cellsRef.current[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 140) {
            ctx.globalAlpha = 0.06 * (1 - dist / 140);
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }
      ctx.globalAlpha = 1;

      rafRef.current = requestAnimationFrame(animate);
    }

    animate();

    return () => {
      window.removeEventListener("resize", resize);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="cell-canvas"
      aria-hidden="true"
    />
  );
}
