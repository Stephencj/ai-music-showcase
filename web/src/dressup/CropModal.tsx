// Simple square photo cropper for the shirt print: pan (drag) + zoom (slider)
// an image inside a square frame, then render the framed region to a canvas
// → data URL. Pure client-side (canvas), works offline.
import { useEffect, useRef, useState } from "react";

const FRAME = 256;   // square viewport (px) and output size

export default function CropModal({ src, onDone, onCancel }: {
  src: string; onDone: (dataUrl: string) => void; onCancel: () => void;
}) {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [scale, setScale] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 });   // top-left of image within frame
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const [minScale, setMinScale] = useState(1);

  useEffect(() => {
    const i = new Image();
    i.onload = () => {
      const s = Math.max(FRAME / i.width, FRAME / i.height);   // cover the frame
      setImg(i); setMinScale(s); setScale(s);
      setPos({ x: (FRAME - i.width * s) / 2, y: (FRAME - i.height * s) / 2 });
    };
    i.src = src;
  }, [src]);

  // Keep the image covering the frame as it scales/moves.
  const clamp = (p: { x: number; y: number }, sc: number) => {
    if (!img) return p;
    const w = img.width * sc, h = img.height * sc;
    return { x: Math.min(0, Math.max(FRAME - w, p.x)), y: Math.min(0, Math.max(FRAME - h, p.y)) };
  };
  const onScale = (sc: number) => { setScale(sc); setPos((p) => clamp(p, sc)); };

  const down = (e: React.PointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, px: pos.x, py: pos.y };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };
  const move = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const nx = drag.current.px + (e.clientX - drag.current.x);
    const ny = drag.current.py + (e.clientY - drag.current.y);
    setPos(clamp({ x: nx, y: ny }, scale));
  };
  const up = () => { drag.current = null; };

  const apply = () => {
    if (!img) return;
    const c = document.createElement("canvas");
    c.width = FRAME; c.height = FRAME;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, FRAME, FRAME);
    ctx.drawImage(img, pos.x, pos.y, img.width * scale, img.height * scale);
    onDone(c.toDataURL("image/jpeg", 0.85));
  };

  return (
    <div className="cof-backdrop" onClick={onCancel}>
      <div className="du-crop" onClick={(e) => e.stopPropagation()}>
        <h3>Move &amp; zoom your photo</h3>
        <div className="du-crop-frame" style={{ width: FRAME, height: FRAME }}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
          {img && (
            <img src={src} draggable={false} style={{
              position: "absolute", left: pos.x, top: pos.y,
              width: img.width * scale, height: img.height * scale, userSelect: "none",
            }} />
          )}
        </div>
        <input type="range" min={minScale} max={minScale * 4} step={0.01} value={scale}
          onChange={(e) => onScale(Number(e.target.value))} className="du-crop-zoom" />
        <div className="du-crop-actions">
          <button className="btn ghost" style={{ width: "auto" }} onClick={onCancel}>Cancel</button>
          <button className="btn" style={{ width: "auto" }} onClick={apply}>✨ Use it!</button>
        </div>
      </div>
    </div>
  );
}
