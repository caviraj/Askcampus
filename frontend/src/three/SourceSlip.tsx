import React, { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { sourceSlipTexture, trayTexture, readPalette } from './textures';
import { phase, mix, mixEased } from './useScrollTimeline';

interface SourceSlipProps {
  progressRef: React.MutableRefObject<number>;
  darkMode?: boolean;
}

export const SourceSlip: React.FC<SourceSlipProps> = ({ progressRef, darkMode = false }) => {
  const palette = useMemo(() => readPalette(darkMode), [darkMode]);

  // Source Slip Texture (Step 5)
  const slipTexture = useMemo(
    () => sourceSlipTexture(palette, 'Academic Regulations 2025–26', 18, 'S1'),
    [palette]
  );

  // Tray Front Label Texture (Step 6)
  const trayLabelTexture = useMemo(
    () => trayTexture(palette, 'UNANSWERED QUERIES (STAFF QUEUE)'),
    [palette]
  );

  const slipGroupRef = useRef<THREE.Group>(null);
  const trayGroupRef = useRef<THREE.Group>(null);

  // Source slip geometry
  const slipGeo = useMemo(() => new THREE.PlaneGeometry(1.05, 0.48), []);

  useFrame(() => {
    const p = progressRef.current;

    // 1. Source Slip Animation (Step 5: attaches to Answer card at p in [4.2, 5.2])
    if (slipGroupRef.current) {
      if (p >= 4.1 && p <= 5.4) {
        slipGroupRef.current.visible = true;
        const enter = phase(p, 4.15, 4.65);
        const exit = phase(p, 5.05, 5.4);

        // Slides in from right (x=2.2 -> 1.45) and docks near the bottom right of the answer card
        const x = mix(2.2, 1.42, mixEased(enter));
        const y = mix(0.3, -0.28, mixEased(enter));
        const z = mix(0.1, 0.52, mixEased(enter));
        const rotZ = mix(0.15, -0.04, mixEased(enter));
        const scale = mix(0.7, 1.0, mixEased(enter)) * (1.0 - exit);

        slipGroupRef.current.position.set(x, y, z);
        slipGroupRef.current.rotation.set(-0.02, -0.04, rotZ);
        slipGroupRef.current.scale.set(scale, scale, scale);
      } else {
        slipGroupRef.current.visible = false;
      }
    }

    // 2. Unanswered Tray Animation (Step 6: p in [5.0, 6.0])
    if (trayGroupRef.current) {
      if (p >= 4.95) {
        trayGroupRef.current.visible = true;
        const enter = phase(p, 4.95, 5.4);

        const y = mix(-1.6, -0.85, mixEased(enter));
        const scale = mix(0.6, 1.0, mixEased(enter));

        trayGroupRef.current.position.set(0.72, y, 0.05);
        trayGroupRef.current.rotation.set(-0.35, 0.05, -0.02);
        trayGroupRef.current.scale.set(scale, scale, scale);
      } else {
        trayGroupRef.current.visible = false;
      }
    }
  });

  return (
    <group>
      {/* 1. Attaching Source Slip (Step 5) */}
      <group ref={slipGroupRef} visible={false}>
        <mesh geometry={slipGeo} castShadow receiveShadow>
          <meshStandardMaterial
            map={slipTexture}
            roughness={0.85}
            metalness={0.05}
            side={THREE.DoubleSide}
          />
        </mesh>
        {/* Subtle slip backing */}
        <mesh position={[0, 0, -0.004]}>
          <planeGeometry args={[1.06, 0.49]} />
          <meshBasicMaterial color={palette.marine} />
        </mesh>
      </group>

      {/* 2. Procedural 3D Unanswered Tray (Step 6) */}
      <group ref={trayGroupRef} visible={false}>
        {/* Tray Base Floor */}
        <mesh position={[0, 0, 0]} receiveShadow>
          <boxGeometry args={[1.8, 0.04, 1.1]} />
          <meshStandardMaterial
            color={palette.paper}
            roughness={0.92}
            metalness={0.05}
          />
        </mesh>

        {/* Back Wall */}
        <mesh position={[0, 0.12, -0.53]} castShadow>
          <boxGeometry args={[1.8, 0.24, 0.04]} />
          <meshStandardMaterial color={palette.rule} roughness={0.9} />
        </mesh>

        {/* Left Wall */}
        <mesh position={[-0.88, 0.1, 0]} castShadow>
          <boxGeometry args={[0.04, 0.2, 1.1]} />
          <meshStandardMaterial color={palette.rule} roughness={0.9} />
        </mesh>

        {/* Right Wall */}
        <mesh position={[0.88, 0.1, 0]} castShadow>
          <boxGeometry args={[0.04, 0.2, 1.1]} />
          <meshStandardMaterial color={palette.rule} roughness={0.9} />
        </mesh>

        {/* Front Lip with Canvas Label ("UNANSWERED QUERIES (STAFF QUEUE)") */}
        <group position={[0, 0.08, 0.54]}>
          <mesh castShadow>
            <boxGeometry args={[1.8, 0.16, 0.04]} />
            <meshStandardMaterial color={palette.rule} roughness={0.85} />
          </mesh>
          <mesh position={[0, 0, 0.022]}>
            <planeGeometry args={[1.76, 0.14]} />
            <meshBasicMaterial map={trayLabelTexture} />
          </mesh>
        </group>
      </group>
    </group>
  );
};
