import { Empty, Spin } from "antd";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { KlineShadowSegment } from "../../services/agent";

interface Props {
  segments: KlineShadowSegment[];
  loading?: boolean;
  height?: number;
}

function normalizeSegment(seg: KlineShadowSegment) {
  if (!seg.points.length) return [];
  const ys = seg.points.map((p) => Number(p.nav));
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanY = Math.max(1e-6, maxY - minY);
  const n = seg.points.length;
  return seg.points.map((p, i) => ({
    x: n <= 1 ? 0 : (i / (n - 1)) * 8 - 4,
    y: ((Number(p.nav) - minY) / spanY) * 2 - 1
  }));
}

export function TechnicalShadowScene({ segments, loading = false, height = 260 }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);

  const normalized = useMemo(() => segments.map(normalizeSegment).filter((x) => x.length >= 2), [segments]);

  useEffect(() => {
    const el = mountRef.current;
    if (!el || !normalized.length) return;
    const width = Math.max(200, el.clientWidth || 600);
    const h = Math.max(160, height);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf7f9fc);
    const camera = new THREE.PerspectiveCamera(45, width / h, 0.1, 100);
    camera.position.set(0, 0, 8.5);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, h);
    el.innerHTML = "";
    el.appendChild(renderer.domElement);

    const palette = [0x5b8ff9, 0x61ddaa, 0xf6bd16, 0xe8684a, 0x9270ca, 0x6dc8ec];
    normalized.forEach((line, idx) => {
      const curvePts = line.map((p) => new THREE.Vector3(p.x, p.y + idx * 0.12 - 0.3, -idx * 0.22));
      const g = new THREE.BufferGeometry().setFromPoints(curvePts);
      const m = new THREE.LineBasicMaterial({
        color: palette[idx % palette.length],
        transparent: true,
        opacity: 0.45 + (idx === 0 ? 0.3 : 0.0)
      });
      scene.add(new THREE.Line(g, m));
    });

    const grid = new THREE.GridHelper(10, 10, 0xd9d9d9, 0xefefef);
    grid.position.y = -1.5;
    scene.add(grid);

    let raf = 0;
    const animate = () => {
      raf = requestAnimationFrame(animate);
      scene.rotation.y += 0.0016;
      renderer.render(scene, camera);
    };
    animate();

    const onResize = () => {
      const w = Math.max(200, el.clientWidth || width);
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(raf);
      renderer.dispose();
      scene.clear();
      el.innerHTML = "";
    };
  }, [normalized, height]);

  if (!segments.length && !loading) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无影子线数据" />;
  }
  return (
    <Spin spinning={loading}>
      <div ref={mountRef} style={{ width: "100%", height }} />
    </Spin>
  );
}
