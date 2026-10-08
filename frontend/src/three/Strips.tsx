import React, { useMemo, useRef, useEffect } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { stripAtlasTexture, readPalette } from './textures';
import { phase, mix, mixEased } from './useScrollTimeline';

interface StripsProps {
  progressRef: React.MutableRefObject<number>;
  darkMode?: boolean;
}

const STRIP_COUNT = 7;
const MATCH_INDICES = [1, 4]; // Strips that match the student query

export const Strips: React.FC<StripsProps> = ({ progressRef, darkMode = false }) => {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const scanLineRef = useRef<THREE.Mesh>(null);

  const palette = useMemo(() => readPalette(darkMode), [darkMode]);
  const atlas = useMemo(() => stripAtlasTexture(palette), [palette]);

  // Procedural single strip geometry (width 1.75, height 0.26)
  const geometry = useMemo(() => {
    const geo = new THREE.PlaneGeometry(1.75, 0.26, 1, 1);
    const stripIndices = new Float32Array(STRIP_COUNT);
    for (let i = 0; i < STRIP_COUNT; i++) {
      stripIndices[i] = i;
    }
    geo.setAttribute('aStripIndex', new THREE.InstancedBufferAttribute(stripIndices, 1));
    return geo;
  }, []);

  const material = useMemo(() => {
    const mat = new THREE.MeshStandardMaterial({
      map: atlas,
      transparent: true,
      roughness: 0.85,
      metalness: 0.05,
      side: THREE.DoubleSide,
      depthWrite: true,
    });

    mat.onBeforeCompile = (shader) => {
      shader.vertexShader = `
        attribute float aStripIndex;
        ${shader.vertexShader}
      `.replace(
        '#include <uv_vertex>',
        `
        #include <uv_vertex>
        #ifdef USE_MAP
          vMapUv.y = ((6.0 - aStripIndex) + uv.y) / 7.0;
        #endif
        `
      );
    };

    return mat;
  }, [atlas]);

  // Reusable dummy objects for matrix calculations
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const baseColor = useMemo(() => new THREE.Color(palette.paper), [palette.paper]);
  const highlightColor = useMemo(() => new THREE.Color(palette.surface), [palette.surface]);
  const dimmedColor = useMemo(() => new THREE.Color(palette.rule), [palette.rule]);

  useEffect(() => {
    if (!meshRef.current) return;
    for (let i = 0; i < STRIP_COUNT; i++) {
      meshRef.current.setColorAt(i, baseColor);
    }
    if (meshRef.current.instanceColor) {
      meshRef.current.instanceColor.needsUpdate = true;
    }
  }, [baseColor]);

  useFrame(() => {
    const p = progressRef.current;
    if (!meshRef.current) return;

    // Visibility range: from step 2 (split) to step 5 (answer handoff)
    if (p < 1.7 || p > 5.3) {
      meshRef.current.visible = false;
      if (scanLineRef.current) scanLineRef.current.visible = false;
      return;
    }
    meshRef.current.visible = true;

    // Step 2 to 3 (Split): p in [2, 3]
    // Starts stacked as a single sheet at (0.2, 0, 0)
    // Fanning out vertically along y = (3 - i) * 0.3
    const splitProgress = phase(p, 2.0, 3.0);
    const searchProgress = phase(p, 3.0, 4.0);
    const answerProgress = phase(p, 4.0, 5.0);

    // Scan line animation during Search step
    if (scanLineRef.current) {
      if (p >= 3.05 && p <= 3.8) {
        scanLineRef.current.visible = true;
        const scanT = (p - 3.05) / 0.75; // 0 to 1
        const scanY = mix(1.1, -1.1, scanT);
        scanLineRef.current.position.set(0.15, scanY, 0.12);
        scanLineRef.current.scale.set(1, 1, 1);
      } else {
        scanLineRef.current.visible = false;
      }
    }

    for (let i = 0; i < STRIP_COUNT; i++) {
      const isMatch = MATCH_INDICES.includes(i);
      const targetY = (3 - i) * 0.3; // Spread from +0.9 to -0.9

      // 1. Initial split from center sheet
      let x = mix(-0.3, 0.15, splitProgress);
      // y fans out from center
      let y = mix((3 - i) * 0.02, targetY, mixEased(splitProgress));
      let z = mix(0.1, 0, splitProgress);
      let rotX = mix(-0.15, 0, splitProgress);
      let rotY = mix(0.1, 0, splitProgress);
      let rotZ = 0;
      let scale = mix(0.6, 1.0, splitProgress);

      // 2. Search phase (lift matching strips forward)
      if (p >= 3.0) {
        if (isMatch) {
          // Strips 1 and 4 lift forward towards viewer
          const liftAmount = mixEased(searchProgress);
          z += liftAmount * 0.35;
          x += liftAmount * 0.08;
          rotY = liftAmount * -0.05;
        } else {
          // Other strips push back slightly and dim
          const dimAmount = searchProgress;
          z -= dimAmount * 0.12;
        }
      }

      // 3. Answer phase (matching strips slide into Answer card at x=0.9, y=0.25)
      if (p >= 4.0) {
        if (isMatch) {
          const slide = mixEased(answerProgress);
          // Slide towards AnswerCard position
          x = mix(x, 0.85, slide);
          y = mix(y, 0.25 + (i === 1 ? 0.06 : -0.06), slide);
          z = mix(z, 0.15, slide);
          scale = mix(1.0, 0.4, slide);
        } else {
          // Non-matching strips fade away
          const fade = answerProgress;
          x += fade * -0.6;
          scale = Math.max(0, 1.0 - fade * 1.4);
        }
      }

      dummy.position.set(x, y, z);
      dummy.rotation.set(rotX, rotY, rotZ);
      dummy.scale.set(scale, scale, scale);
      dummy.updateMatrix();

      meshRef.current.setMatrixAt(i, dummy.matrix);

      // Color tinting:
      if (isMatch && p >= 3.4) {
        meshRef.current.setColorAt(i, highlightColor);
      } else if (!isMatch && p >= 3.4) {
        meshRef.current.setColorAt(i, dimmedColor);
      } else {
        meshRef.current.setColorAt(i, baseColor);
      }
    }

    meshRef.current.instanceMatrix.needsUpdate = true;
    if (meshRef.current.instanceColor) {
      meshRef.current.instanceColor.needsUpdate = true;
    }
  });

  return (
    <group>
      <instancedMesh
        ref={meshRef}
        args={[geometry, material, STRIP_COUNT]}
        castShadow
        receiveShadow
      />

      {/* Sweep scan line indicator across strips during search */}
      <mesh ref={scanLineRef} visible={false}>
        <planeGeometry args={[1.9, 0.02]} />
        <meshBasicMaterial
          color={palette.marine}
          transparent
          opacity={0.85}
        />
      </mesh>
    </group>
  );
};
