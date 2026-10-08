import React, { useRef, useMemo, useState, useEffect } from 'react';
import * as THREE from 'three';
import { Canvas, useFrame } from '@react-three/fiber';
import { docTitleTexture, sourceSlipTexture, readPalette } from './textures';
import fallbackSvg from './fallback.svg';

interface LoginSceneProps {
  freeze?: boolean;
  success?: boolean;
  darkMode?: boolean;
}

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

const SheetCard: React.FC<{
  freeze: boolean;
  success: boolean;
  darkMode: boolean;
}> = ({ freeze, success, darkMode }) => {
  const groupRef = useRef<THREE.Group>(null);
  const angleRef = useRef(0);
  const successT = useRef(0);

  const palette = useMemo(() => readPalette(darkMode), [darkMode]);

  const frontTexture = useMemo(
    () =>
      docTitleTexture(
        palette,
        'Academic Regulations 2025–26',
        'Official College Policies & Procedures'
      ),
    [palette]
  );

  const backTexture = useMemo(
    () =>
      sourceSlipTexture(
        palette,
        'Academic Regulations §4.2',
        18,
        'S1'
      ),
    [palette]
  );

  const sheetGeo = useMemo(() => new THREE.PlaneGeometry(1.9, 2.5), []);
  const backGeo = useMemo(() => new THREE.PlaneGeometry(1.9, 2.5), []);

  useFrame((_, delta) => {
    if (!groupRef.current) return;

    if (success) {
      // On success, accelerate forward towards camera
      successT.current = Math.min(1.0, successT.current + delta * 2.2);
      const s = successT.current;
      groupRef.current.position.z = s * 2.8;
      groupRef.current.position.x = s * 0.15;
      groupRef.current.rotation.y = THREE.MathUtils.lerp(groupRef.current.rotation.y, 0, 0.1);
      groupRef.current.rotation.x = THREE.MathUtils.lerp(groupRef.current.rotation.x, -0.05, 0.1);
      return;
    }

    if (!freeze) {
      // Gentle turnover animation: completes a turnover every ~7 seconds
      angleRef.current += delta * 0.8;
    }

    // Floating and gentle turning over to reveal the highlighted source slip, then resting
    // Sine wave between 0 (front) and PI (back revealed)
    const cycle = (Math.sin(angleRef.current * 0.6) + 1) * 0.5; // 0 to 1
    const rotY = cycle * Math.PI + Math.sin(angleRef.current * 0.3) * 0.12;
    const rotX = Math.sin(angleRef.current * 0.4) * 0.08 - 0.04;
    const floatY = Math.sin(angleRef.current * 0.8) * 0.06;

    groupRef.current.rotation.y = rotY;
    groupRef.current.rotation.x = rotX;
    groupRef.current.position.y = floatY;
    groupRef.current.position.z = 0;
  });

  return (
    <group ref={groupRef}>
      {/* Front Face (Document Sheet) */}
      <mesh geometry={sheetGeo} castShadow receiveShadow>
        <meshStandardMaterial
          map={frontTexture}
          roughness={0.85}
          metalness={0.02}
          side={THREE.FrontSide}
        />
      </mesh>

      {/* Back Face (Revealing Source Slip) */}
      <mesh
        geometry={backGeo}
        rotation={[0, Math.PI, 0]}
        position={[0, 0, -0.002]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          map={backTexture}
          roughness={0.85}
          metalness={0.02}
          side={THREE.FrontSide}
        />
      </mesh>

      {/* Subtle Paper Edge Frame */}
      <mesh position={[0, 0, -0.001]}>
        <planeGeometry args={[1.91, 2.51]} />
        <meshBasicMaterial color={palette.rule} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
};

export const LoginScene: React.FC<LoginSceneProps> = ({
  freeze = false,
  success = false,
  darkMode = false,
}) => {
  const [isSupported, setIsSupported] = useState<boolean>(true);
  const [reducedMotion, setReducedMotion] = useState<boolean>(false);

  useEffect(() => {
    if (!checkWebGL()) {
      setIsSupported(false);
      return;
    }

    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReducedMotion(mediaQuery.matches);

    const handleMotionChange = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mediaQuery.addEventListener('change', handleMotionChange);
    return () => mediaQuery.removeEventListener('change', handleMotionChange);
  }, []);

  if (!isSupported || reducedMotion) {
    return (
      <div
        className="w-full h-full flex items-center justify-center pointer-events-none select-none p-6"
        aria-hidden="true"
      >
        <img
          src={fallbackSvg}
          alt=""
          className="w-full max-w-sm max-h-[60vh] object-contain opacity-90"
        />
      </div>
    );
  }

  return (
    <div className="w-full h-full relative" aria-hidden="true">
      <Canvas
        camera={{ position: [0, 0, 4.8], fov: 38 }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true }}
        shadows
        className="w-full h-full"
      >
        <ambientLight intensity={darkMode ? 0.75 : 0.9} color="#F1F3F2" />
        <directionalLight
          position={[3, 4.5, 4]}
          intensity={darkMode ? 1.0 : 1.25}
          castShadow
          shadow-mapSize-width={512}
          shadow-mapSize-height={512}
        />
        <directionalLight position={[-2, -2, 2]} intensity={0.2} color="#FFFFFF" />

        <SheetCard freeze={freeze} success={success} darkMode={darkMode} />
      </Canvas>
    </div>
  );
};

export default LoginScene;
