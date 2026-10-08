import React, { useRef, useState, useEffect, useMemo } from 'react';
import * as THREE from 'three';
import { Canvas, useFrame } from '@react-three/fiber';
import { DocStack } from './DocStack';
import { Strips } from './Strips';
import { AnswerCard } from './AnswerCard';
import { SourceSlip } from './SourceSlip';
import { readPalette } from './textures';
import fallbackSvg from './fallback.svg';

interface SceneProps {
  progressRef: React.MutableRefObject<number>;
  darkMode?: boolean;
}

// Check WebGL availability
function checkWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(
      window.WebGLRenderingContext &&
        (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    );
  } catch {
    return false;
  }
}

// Inner 3D World with mouse parallax
const SceneWorld: React.FC<{
  progressRef: React.MutableRefObject<number>;
  darkMode: boolean;
}> = ({ progressRef, darkMode }) => {
  const worldGroupRef = useRef<THREE.Group>(null);
  const mouseRef = useRef({ x: 0, y: 0, targetX: 0, targetY: 0 });

  const palette = useMemo(() => readPalette(darkMode), [darkMode]);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      // Normalize to [-1, 1]
      const nx = (e.clientX / window.innerWidth) * 2 - 1;
      const ny = -(e.clientY / window.innerHeight) * 2 + 1;
      mouseRef.current.targetX = nx;
      mouseRef.current.targetY = ny;
    };

    window.addEventListener('mousemove', handleMouseMove, { passive: true });
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, []);

  useFrame(() => {
    // Smooth lerp mouse
    mouseRef.current.x += (mouseRef.current.targetX - mouseRef.current.x) * 0.05;
    mouseRef.current.y += (mouseRef.current.targetY - mouseRef.current.y) * 0.05;

    if (worldGroupRef.current) {
      // Subtle mouse move (max 6 degrees = ~0.1 rad)
      const maxRot = (6 * Math.PI) / 180;
      worldGroupRef.current.rotation.y = mouseRef.current.x * maxRot;
      worldGroupRef.current.rotation.x = -mouseRef.current.y * (maxRot * 0.6);
    }
  });

  return (
    <>
      {/* Lighting: Soft ambient + soft directional with subtle shadow */}
      <ambientLight intensity={darkMode ? 0.75 : 0.9} color={darkMode ? '#B8C4C2' : '#F8FAFA'} />
      <directionalLight
        position={[3.5, 5, 4.5]}
        intensity={darkMode ? 1.0 : 1.25}
        color="#FFFFFF"
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
        shadow-bias={-0.0001}
      />
      <directionalLight
        position={[-3, -2, 2]}
        intensity={0.25}
        color={palette.paper}
      />

      <group ref={worldGroupRef}>
        {/* 1. Document Stack (Steps 1 & 2) */}
        <DocStack progressRef={progressRef} darkMode={darkMode} />

        {/* 2. Instanced Strips with scan line (Steps 3 & 4) */}
        <Strips progressRef={progressRef} darkMode={darkMode} />

        {/* 3. Question cards, Answer card with highlight, Refusal card (Steps 4, 5, 6) */}
        <AnswerCard progressRef={progressRef} darkMode={darkMode} />

        {/* 4. Docking Source Slip & 3D Unanswered Tray (Steps 5 & 6) */}
        <SourceSlip progressRef={progressRef} darkMode={darkMode} />
      </group>
    </>
  );
};

export const Scene: React.FC<SceneProps> = ({ progressRef, darkMode = false }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isSupported, setIsSupported] = useState<boolean>(true);
  const [reducedMotion, setReducedMotion] = useState<boolean>(false);
  const [inView, setInView] = useState<boolean>(true);

  useEffect(() => {
    // 1. WebGL support check
    if (!checkWebGL()) {
      setIsSupported(false);
      return;
    }

    // 2. Reduced motion check
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReducedMotion(mediaQuery.matches);

    const handleMotionChange = (e: MediaQueryListEvent) => {
      setReducedMotion(e.matches);
    };

    mediaQuery.addEventListener('change', handleMotionChange);
    return () => mediaQuery.removeEventListener('change', handleMotionChange);
  }, []);

  useEffect(() => {
    // 3. Pause rendering when off screen via IntersectionObserver
    const el = containerRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        setInView(entry.isIntersecting);
      },
      { threshold: 0.05 }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Show static fallback SVG if WebGL not supported or reduced motion requested
  if (!isSupported || reducedMotion) {
    return (
      <div
        ref={containerRef}
        className="w-full h-full flex items-center justify-center pointer-events-none select-none p-6"
        aria-hidden="true"
      >
        <img
          src={fallbackSvg}
          alt=""
          className="w-full max-w-xl max-h-[80vh] object-contain opacity-90 transition-opacity"
        />
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="w-full h-full relative"
      aria-hidden="true"
    >
      <Canvas
        camera={{ position: [0, 0, 5.5], fov: 40 }}
        dpr={[1, 2]} // Cap devicePixelRatio at 2
        frameloop={inView ? 'always' : 'never'}
        gl={{
          antialias: true,
          alpha: true,
          powerPreference: 'high-performance',
        }}
        shadows
        className="w-full h-full"
      >
        <SceneWorld progressRef={progressRef} darkMode={darkMode} />
      </Canvas>
    </div>
  );
};

export default Scene;
